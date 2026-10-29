# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Real Bridge requests and multiple windows against a disposable Root/database."""

from __future__ import annotations

import asyncio
import sys
import unittest
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Params, decode, encode  # noqa: E402
from arbol_backend.database import Database  # noqa: E402
from arbol_backend.model import identity, parse  # noqa: E402
from arbol_backend.server import Backend  # noqa: E402
from backend.support import Cluster, Frame  # noqa: E402


def chat(n: int) -> str:
    return str(UUID(int=n))


class WindowFixture(unittest.IsolatedAsyncioTestCase):
    """Socket/PG fixture shared by the chat and Draft/dispatch suites."""

    async def asyncSetUp(self) -> None:
        self.frame = Frame()
        self.cluster = await asyncio.to_thread(Cluster)
        self.frame.record["status"] = "working"
        self.frame.save_root()
        self.frame.behavior = {"arbol-roots": {"output": [{**self.frame.record, "current": True}]}}
        for driver in ("claude", "codex", "pi"):
            self.frame.behavior["arbol-" + driver + "-driver"] = {"output": [{"id": "private"}]}
        self.frame.configure()
        selected = identity(ROOT, parse(self.frame.options(self.cluster.address)), home=self.frame.home)
        self.db = Database(selected)
        await self.db.execute((ROOT / "tests/backend/own-layout.sql").read_text())
        await self.db.execute(
            "INSERT INTO chats SELECT lpad(to_hex(n),32,'0')::uuid,'chat '||n,"
            "'2026-10-27T00:00:00Z'::timestamptz+n*interval '1 microsecond' FROM generate_series(1,201) n"
        )
        self.backend = Backend(selected)
        self.running = asyncio.create_task(self.backend.run())
        self.writers: list[asyncio.StreamWriter] = []
        self.pending: dict[asyncio.StreamReader, list[Params]] = defaultdict(list)
        self.seq: dict[tuple[asyncio.StreamReader, str], int] = {}
        self.next_id = 0
        for _ in range(100):
            if (self.frame.root / "backend.sock").exists():
                break
            await asyncio.sleep(0.01)
        assert self.backend.chats.catalogues.task
        await self.backend.chats.catalogues.task
        if self.backend.measurements.task is not None:
            await asyncio.wait_for(asyncio.shield(self.backend.measurements.task), 3)

    async def asyncTearDown(self) -> None:
        for writer in self.writers:
            writer.close()
        self.backend.stopped.set()
        await asyncio.wait_for(self.running, 2)
        await self.db.close()
        await asyncio.to_thread(self.cluster.close)
        self.frame.close()

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
        reader, writer = await asyncio.open_unix_connection(str(self.frame.root / "backend.sock"), limit=16 * 1024 * 1024)
        self.writers.append(writer)
        self.assertEqual((await self.read(reader))["type"], "hello")
        return reader, writer

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


class Windows(WindowFixture):
    pass  # Shared fixture base; case bodies live in top/ and mid/.



# Archived complete imports; restore needed names in their original scope, not at this file tail.
