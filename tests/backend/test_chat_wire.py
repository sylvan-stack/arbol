# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Real Bridge requests and multiple windows against private sockets and databases."""

from __future__ import annotations

__all__ = [
    "Any", "Backend", "Callable", "Cluster", "Database", "Frame", "Params", "Path", "ROOT", "Sequence", "Session", "UUID",
    "WindowFixture", "Windows", "asyncio", "chat", "decode", "defaultdict", "encode", "identity", "json", "mock",
    "parse", "replace", "stat", "sys", "time", "unittest",
]
import asyncio
import json
import stat
import sys
import time
import unittest
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))

from arbol_backend.bridge import Params, decode, encode  # noqa: E402
from arbol_backend.database import Database, Session  # noqa: E402
from arbol_backend.model import Identity, identity, parse  # noqa: E402
from arbol_backend.server import Backend  # noqa: E402
from backend.support import BASELINE, Cluster, Frame, SingleInstallation  # noqa: E402


def chat(n: int) -> str:
    return str(UUID(int=n))


class BridgeWindows(unittest.IsolatedAsyncioTestCase):
    async def start_wire(self, selected: Identity) -> None:
        self.endpoint = selected.folder / "backend.sock"
        self.backend = Backend(selected)
        self.running = asyncio.create_task(self.backend.run())
        self.addAsyncCleanup(self.close_wire)
        self.writers: list[asyncio.StreamWriter] = []
        self.pending: dict[asyncio.StreamReader, list[Params]] = defaultdict(list)
        self.seq: dict[tuple[asyncio.StreamReader, str], int] = {}
        self.next_id = 0
        async with asyncio.timeout(3):
            while not self.endpoint.exists():
                if self.running.done():
                    await self.running
                    raise RuntimeError("The fixture backend exited before listening.")
                await asyncio.sleep(0.01)
        assert self.backend.chats.catalogues.task
        await self.backend.chats.catalogues.task
        if self.backend.measurements.task is not None:
            await asyncio.wait_for(asyncio.shield(self.backend.measurements.task), 3)

    async def close_wire(self) -> None:
        for writer in self.writers:
            writer.close()
        self.backend.stopped.set()
        await asyncio.wait_for(self.running, 2)

    async def read(self, reader: asyncio.StreamReader, seconds: float = 3) -> Params:
        async with asyncio.timeout(seconds):
            message = decode(await reader.readuntil(b"\n"))
        if message["type"] == "event":
            key = (reader, message["id"])
            self.assertEqual(message["seq"], self.seq.get(key, 0) + 1)
            self.seq[key] = message["seq"]
        return message

    async def until(self, reader: asyncio.StreamReader, match: Callable[[Params], bool]) -> Params:
        for index, message in enumerate(self.pending[reader]):
            if match(message):
                return self.pending[reader].pop(index)
        async with asyncio.timeout(3):
            while True:
                message = await self.read(reader)
                if match(message):
                    return message
                self.pending[reader].append(message)

    async def open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_unix_connection(str(self.endpoint), limit=16 * 1024 * 1024)
        self.writers.append(writer)
        self.check_hello(await self.read(reader))
        return reader, writer

    def check_hello(self, value: Params) -> None:
        self.assertEqual(value["type"], "hello")

    async def send(self, writer: asyncio.StreamWriter, message: Params) -> None:
        writer.write(encode(message))
        await writer.drain()

    async def call(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, method: str,
                   params: Params | None = None) -> Params:
        self.next_id += 1
        id = "call-" + str(self.next_id)
        await self.send(writer, {"type": "call", "id": id, "method": method, "params": params or {}})
        return await self.until(reader, lambda value: value["type"] == "reply" and value["id"] == id)

    async def subscribe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, id: str,
                        topic: str, params: Params | None = None) -> Params:
        await self.send(writer, {"type": "subscribe", "id": id, "topic": topic, "params": params or {}})
        result = await self.until(reader, lambda value: value.get("id") == id)
        self.assertEqual((result["type"], result["seq"], result["event"]["kind"]), ("event", 1, "snapshot"))
        event = result["event"]
        assert isinstance(event, dict)
        return event

    async def event(self, reader: asyncio.StreamReader, id: str, kind: str) -> Params:
        result = await self.until(reader, lambda value: value["type"] == "event" and value["id"] == id
                                  and value["event"]["kind"] == kind)
        event = result["event"]
        assert isinstance(event, dict)
        return event


class WindowFixture(BridgeWindows):
    """Historical fixture retained for the separate mid-tier sources."""

    async def asyncSetUp(self) -> None:
        self.frame = Frame()
        self.addCleanup(self.frame.close)
        self.cluster = await asyncio.to_thread(Cluster)
        self.addAsyncCleanup(asyncio.to_thread, self.cluster.close)
        self.frame.record["status"] = "working"
        self.frame.save_root()
        self.frame.behavior = {"arbol-roots": {"output": [{**self.frame.record, "current": True}]}}
        for driver in ("claude", "codex", "pi"):
            self.frame.behavior["arbol-" + driver + "-driver"] = {"output": [{"id": "private"}]}
        self.frame.configure()
        selected = identity(ROOT, parse(self.frame.options(self.cluster.address)), home=self.frame.home)
        self.db = Database(selected)
        self.addAsyncCleanup(self.db.close)
        await self.db.execute((ROOT / "tests/backend/own-layout.sql").read_text())
        await self.db.execute(
            "INSERT INTO chats SELECT lpad(to_hex(n),32,'0')::uuid,'chat '||n,"
            "'2026-10-27T00:00:00Z'::timestamptz+n*interval '1 microsecond' FROM generate_series(1,201) n"
        )
        await self.start_wire(selected)


class Windows(WindowFixture):
    pass  # Shared fixtures; case bodies live in top/ and mid/.


class InstallationWindows(BridgeWindows):
    async def asyncSetUp(self) -> None:
        self.fixture = await asyncio.to_thread(SingleInstallation)
        self.addAsyncCleanup(asyncio.to_thread, self.fixture.close)
        await asyncio.to_thread(self.fixture.open_admission)
        driver = self.fixture.bin / "arbol-claude-driver"
        driver.write_text("#!/bin/sh\nif [ \"$*\" = 'subscriptions list' ]; then\n"
                          "  printf '%s\\n' '[{\"id\":\"private\"}]'\nelse\n  exit 1\nfi\n")
        driver.chmod(0o700)
        selected = identity(ROOT, parse(["backend", *self.fixture.options()]), home=self.fixture.home)
        self.db = Database(selected)
        self.addAsyncCleanup(self.db.close)
        await self.db.execute("INSERT INTO chats(id, title, created_at) VALUES (%s, 'chat 1', clock_timestamp())", [chat(1)])
        await self.start_wire(selected)

    def check_hello(self, value: Params) -> None:
        super().check_hello(value)
        self.assertEqual(value["bridge"], 2)
        self.assertEqual(value["build"], self.backend.identity.build)
        self.assertEqual(value["installation"], {"database": "ready", "schema": BASELINE, "maintenance": "normal"})


# Archived complete imports; restore needed names in their original scope, not at this file tail.
