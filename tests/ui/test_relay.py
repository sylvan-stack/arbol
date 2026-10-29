# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Private protocol/HTTP checks. No owner services, secrets or browser profile."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib.util
import json
import secrets
import struct
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / "tools/bridge_relay.py"
spec = importlib.util.spec_from_file_location("relay_under_test", TOOL)
assert spec and spec.loader
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


async def send_frame(
    writer: asyncio.StreamWriter, text: str | bytes, opcode: int = 1, final: bool = True, masked: bool = True
) -> None:
    data = text.encode() if isinstance(text, str) else text
    n = len(data)
    header = bytes(
        [(128 if final else 0) | opcode, (128 if masked else 0) | (n if n < 126 else 126 if n < 65536 else 127)]
    )
    if n >= 126:
        header += struct.pack("!H" if n < 65536 else "!Q", n)
    if masked:
        mask = secrets.token_bytes(4)
        header += mask
        data = bytes(v ^ mask[i % 4] for i, v in enumerate(data))
    writer.write(header + data)
    await writer.drain()


async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    first, second = await reader.readexactly(2)
    assert not second & 128
    n = second & 127
    if n == 126:
        n = struct.unpack("!H", await reader.readexactly(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", await reader.readexactly(8))[0]
    return first & 15, await reader.readexactly(n)


class RelayChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="er-", dir="/tmp")
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        (self.bundle / "index.html").write_text("<!doctype html><title>Fixture</title>")
        (self.bundle / "local.js").write_text("/* private fixture */")
        (self.root / "private.txt").write_text("PRIVATE OUTSIDE BUNDLE")
        (self.bundle / "escape").symlink_to(self.root / "private.txt")
        self.path = self.root / "backend.sock"
        self.records: list[bytes] = []
        self.backend_writers: list[asyncio.StreamWriter] = []
        self.count = 0
        self.backend = await asyncio.start_unix_server(self.back, path=self.path, limit=relay.LIMIT)
        self.host = relay.Relay(self.bundle, self.path)
        await self.host.start()
        self.writers: list[asyncio.StreamWriter] = []
        self.cookie = f"{self.host.cookie}={self.host.token}"

    async def back(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.count += 1
        self.backend_writers.append(writer)
        writer.write(
            (
                json.dumps(
                    {
                        "type": "hello",
                        "bridge": 1,
                        "root": {"root": "t1", "name": "Fixture Root", "status": "working", "current": True},
                        "build": "1",
                    }
                )
                + "\n"
            ).encode()
        )
        await writer.drain()
        try:
            while line := await reader.readline():
                self.records.append(line)
                writer.write(line)
                await writer.drain()
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def asyncTearDown(self) -> None:
        await self.host.close()
        self.backend.close()
        await self.backend.wait_closed()
        for writer in self.writers + self.backend_writers:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
        await asyncio.sleep(0)
        self.temp.cleanup()

    async def http(self, target: str = "/", headers: dict[str, str] | None = None) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.host.port)
        self.writers.append(writer)
        values = {"Host": self.host.host, **(headers or {})}
        writer.write(
            (
                "GET " + target + " HTTP/1.1\r\n" + "".join(k + ": " + v + "\r\n" for k, v in values.items()) + "\r\n"
            ).encode()
        )
        await writer.drain()
        data = await reader.read()
        return data

    async def ws(self, extra: dict[str, str] | None = None) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, bytes]:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.host.port, limit=relay.LIMIT)
        self.writers.append(writer)
        values = {
            "Host": self.host.host,
            "Cookie": self.cookie,
            "Origin": "http://" + self.host.host,
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": base64.b64encode(secrets.token_bytes(16)).decode(),
            "Sec-WebSocket-Version": "13",
            **(extra or {}),
        }
        writer.write(
            ("GET /bridge HTTP/1.1\r\n" + "".join(k + ": " + v + "\r\n" for k, v in values.items()) + "\r\n").encode()
        )
        await writer.drain()
        header = await reader.readuntil(b"\r\n\r\n")
        return reader, writer, header



# Archived complete imports; restore needed names in their original scope, not at this file tail.
