# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Private socket and PostgreSQL qualification of BKD-1; never use owner credentials."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import (  # noqa: E402
    MAX_LINE,
    Connection,
    Params,
    Registry,
    decode,
    encode,
)
from arbol_backend.model import identity, parse  # noqa: E402
from arbol_backend.server import Backend  # noqa: E402
from backend.support import TEST_BUILD, TEST_ROOT  # noqa: E402
from backend.support import Frame as PrivateRoot  # noqa: E402


class Wire(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = PrivateRoot()
        self.registry = Registry()
        self.connections: list[Connection] = []
        self.work: list[asyncio.Task[None]] = []
        self.writers: list[asyncio.StreamWriter] = []
        self.header = {"type": "hello", "bridge": 1, "root": {"root": TEST_ROOT, "name": "Test Root",
                       "status": "working", "current": True}, "build": TEST_BUILD}
        async def hello() -> Params:
            return self.header
        def connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            connection = Connection(reader, writer, self.registry)
            self.connections.append(connection)
            self.work.append(asyncio.create_task(connection.run(hello)))
        self.server = await asyncio.start_unix_server(
            connected, path=str(self.fixture.root / "wire.sock"), limit=MAX_LINE - 1
        )

    async def asyncTearDown(self) -> None:
        for writer in self.writers:
            writer.close()
        self.server.close()
        self.server.close_clients()
        for task in self.work:
            task.cancel()
        await asyncio.gather(*self.work, return_exceptions=True)
        await self.server.wait_closed()
        self.fixture.close()

    async def open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_unix_connection(
            str(self.fixture.root / "wire.sock"), limit=MAX_LINE - 1
        )
        self.writers.append(writer)
        self.assertEqual(await self.read(reader), self.header)
        return reader, writer

    async def read(self, reader: asyncio.StreamReader, seconds: float = 2) -> Params:
        async with asyncio.timeout(seconds):
            return decode(await reader.readuntil(b"\n"))

    async def send(self, writer: asyncio.StreamWriter, message: Params) -> None:
        writer.write(encode(message))
        await writer.drain()


class RootWire(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = PrivateRoot()
        self.fixture.behavior = {"arbol-roots": {"output": [{**self.fixture.record, "current": True,
                                                          "password": "private-secret"}]}}
        self.fixture.configure()
        self.selected = identity(ROOT, parse(self.fixture.options()), home=self.fixture.home)
        self.backend = Backend(self.selected)
        self.work = asyncio.create_task(self.backend.run())
        for _ in range(100):
            if (self.fixture.root / "backend.sock").exists():
                break
            await asyncio.sleep(0.01)
        self.writers: list[asyncio.StreamWriter] = []

    async def asyncTearDown(self) -> None:
        for writer in self.writers:
            writer.close()
        self.backend.stopped.set()
        await asyncio.wait_for(self.work, 2)
        self.fixture.close()

    async def open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_unix_connection(str(self.fixture.root / "backend.sock"))
        self.writers.append(writer)
        hello = await self.read(reader)
        self.assertEqual((hello["type"], hello["bridge"], hello["build"]), ("hello", 1, TEST_BUILD))
        self.assertTrue(hello["root"]["current"])
        self.assertNotIn("private-secret", str(hello))
        return reader, writer

    async def read(self, reader: asyncio.StreamReader) -> Params:
        return decode(await asyncio.wait_for(reader.readuntil(b"\n"), 5))

    async def send(self, writer: asyncio.StreamWriter, message: Params) -> None:
        writer.write(encode(message))
        await writer.drain()


class Diagnostics(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.



# Archived complete imports; restore needed names in their original scope, not at this file tail.
