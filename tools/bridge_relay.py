#!/usr/bin/env python3
"""BKD-1 development host. Loopback, per-start token/cookie, no content logs.

Serves the selected Root's newest working Build; starts no backend or other program.
The browser app-channel adapter stays in the renderer and never reaches this socket.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import signal
import struct
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

LIMIT = 16 * 1024 * 1024  # Complete backend line including LF.
HEADER_LIMIT = 65536


class Closed(Exception):
    pass


class TextFrame:
    """Keep asyncio debug task diagnostics from reflecting message content."""

    def __init__(self, text: str):
        self.text = text

    def __repr__(self) -> str:
        return "<WebSocket text frame>"


class WebSocket:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer
        self.lock = asyncio.Lock()

    async def send(self, data: bytes, opcode: int = 1) -> None:
        if len(data) >= LIMIT:
            raise Closed()
        size = len(data)
        header = (
            bytes([128 | opcode, size])
            if size < 126
            else bytes([128 | opcode, 126]) + struct.pack("!H", size)
            if size < 65536
            else bytes([128 | opcode, 127]) + struct.pack("!Q", size)
        )
        async with self.lock:
            self.writer.write(header + data)
            async with asyncio.timeout(5):
                await self.writer.drain()

    async def receive(self) -> TextFrame | None:
        # Keep fragment ownership here, including ping/pong interleaving.
        message = bytearray()
        fragmented = False
        while True:
            first, second = await self.reader.readexactly(2)
            final, opcode, size = bool(first & 128), first & 15, second & 127
            if first & 112 or not second & 128:
                raise Closed()
            if size == 126:
                size = struct.unpack("!H", await self.reader.readexactly(2))[0]
                if size < 126:
                    raise Closed()
            elif size == 127:
                size = struct.unpack("!Q", await self.reader.readexactly(8))[0]
                if size < 65536 or size & (1 << 63):
                    raise Closed()
            if (
                size >= LIMIT
                or (opcode < 8 and len(message) + size >= LIMIT)
                or (opcode >= 8 and (not final or size > 125))
            ):
                raise Closed()
            mask = await self.reader.readexactly(4)
            data = await self.reader.readexactly(size)
            data = bytes(v ^ mask[i % 4] for i, v in enumerate(data))
            if opcode == 8:
                if len(data) == 1:
                    raise Closed()
                await self.send(data, 8)
                return None
            if opcode == 9:
                await self.send(data, 10)
                continue
            if opcode == 10:
                continue
            if opcode == 1 and not fragmented or opcode == 0 and fragmented:
                message.extend(data)
                fragmented = not final
            else:
                raise Closed()
            if final:
                text = message.decode("utf-8", errors="strict")
                # A JSON string carries embedded newlines as escapes, never framing bytes.
                if "\n" in text or "\r" in text:
                    raise Closed()
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise Closed()
                return TextFrame(text)


class Relay:
    def __init__(self, bundle: Path, socket: Path):
        self.bundle, self.socket = bundle.resolve(strict=True), socket
        if not (self.bundle / "index.html").is_file():
            raise ValueError("The Build has no Elma renderer bundle.")
        self.token = secrets.token_urlsafe(16)
        self.port = 0
        self.server: asyncio.Server | None = None
        self.clients: set[asyncio.Task[None]] = set()
        self.writers: set[asyncio.StreamWriter] = set()

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.port}"

    @property
    def cookie(self) -> str:
        return f"arbol_relay_{self.port}"

    async def start(self, port: int = 0) -> None:
        self.server = await asyncio.start_server(self.client, "127.0.0.1", port, limit=LIMIT)
        self.port = self.server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in tuple(self.writers):
            writer.close()
        for task in tuple(self.clients):
            task.cancel()
        await asyncio.gather(*tuple(self.clients), return_exceptions=True)

    def authorized(self, headers: dict[str, str]) -> bool:
        pairs = [part.strip().split("=", 1) for part in headers.get("cookie", "").split(";")]
        values = [p[1] for p in pairs if len(p) == 2 and p[0] == self.cookie]
        return len(values) == 1 and hmac.compare_digest(values[0].encode(), self.token.encode())

    async def response(
        self, writer: asyncio.StreamWriter, status: str, body: bytes = b"", extra: dict[str, str] | None = None
    ) -> None:
        headers = {
            "Content-Length": str(len(body)),
            "Connection": "close",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": f"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self' ws://{self.host}; img-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'; frame-ancestors 'none'",
            **(extra or {}),
        }
        writer.write(
            (
                "HTTP/1.1 " + status + "\r\n" + "".join(k + ": " + v + "\r\n" for k, v in headers.items()) + "\r\n"
            ).encode("ascii")
            + body
        )
        async with asyncio.timeout(5):
            await writer.drain()

    async def client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.clients.add(task)
        self.writers.add(writer)
        try:
            if len(self.clients) > 128:
                return
            async with asyncio.timeout(5):
                request = await reader.readuntil(b"\r\n\r\n")
            if len(request) > HEADER_LIMIT:
                return
            lines = request.decode("ascii").split("\r\n")
            words = lines[0].split(" ")
            if (
                len(words) != 3
                or words[0] != "GET"
                or words[2] != "HTTP/1.1"
                or not words[1].startswith("/")
                or words[1].startswith("//")
            ):
                await self.response(writer, "400 Bad Request")
                return
            headers: dict[str, str] = {}
            for line in lines[1:-2]:
                key, value = line.split(":", 1)
                if (
                    not re.fullmatch(r"[A-Za-z0-9-]+", key)
                    or key.lower() in headers
                    or any(ord(v) < 32 for v in value.strip())
                ):
                    await self.response(writer, "400 Bad Request")
                    return
                headers[key.lower()] = value.strip()
            if headers.get("host") != self.host:
                await self.response(writer, "403 Forbidden")
                return
            if "transfer-encoding" in headers or headers.get("content-length", "0") != "0":
                await self.response(writer, "400 Bad Request")
                return
            target = urlsplit(words[1])
            query = parse_qsl(target.query, keep_blank_values=True)
            tokens = [v for k, v in query if k == "token"]
            if tokens:
                if (
                    target.path != "/"
                    or len(tokens) != 1
                    or not hmac.compare_digest(tokens[0].encode(), self.token.encode())
                ):
                    await self.response(writer, "403 Forbidden")
                    return
                rest = urlencode([(k, v) for k, v in query if k != "token"])
                await self.response(
                    writer,
                    "303 See Other",
                    extra={
                        "Set-Cookie": f"{self.cookie}={self.token}; Path=/; HttpOnly; SameSite=Strict",
                        "Location": "/" + ("?" + rest if rest else ""),
                    },
                )
                return
            if not self.authorized(headers):
                await self.response(writer, "403 Forbidden")
                return
            if target.path == "/bridge":
                if headers.get("origin") != f"http://{self.host}":
                    await self.response(writer, "403 Forbidden")
                    return
                key = headers.get("sec-websocket-key", "")
                try:
                    valid_key = len(base64.b64decode(key, validate=True)) == 16
                except ValueError:
                    valid_key = False
                if (
                    headers.get("upgrade", "").lower() != "websocket"
                    or "upgrade" not in [v.strip().lower() for v in headers.get("connection", "").split(",")]
                    or headers.get("sec-websocket-version") != "13"
                    or not valid_key
                ):
                    await self.response(writer, "400 Bad Request")
                    return
                accept = base64.b64encode(
                    hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
                ).decode()
                writer.write(
                    f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode()
                )
                await writer.drain()
                await self.bridge(WebSocket(reader, writer))
                return
            path = (self.bundle / unquote(target.path, errors="strict").lstrip("/")).resolve()
            if path == self.bundle:
                path = path / "index.html"
            if (
                self.bundle not in path.parents
                or not path.is_file()
                or any(part.startswith(".") for part in path.relative_to(self.bundle).parts)
            ):
                await self.response(writer, "404 Not Found")
                return
            if path.stat().st_size > 32 * 1024 * 1024:
                await self.response(writer, "404 Not Found")
                return
            content = path.read_bytes()
            await self.response(
                writer,
                "200 OK",
                content,
                {"Content-Type": mimetypes.guess_type(path.name)[0] or "application/octet-stream"},
            )
        except (
            OSError,
            ValueError,
            UnicodeError,
            TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            Closed,
        ):
            pass
        finally:
            self.writers.discard(writer)
            writer.close()
            with contextlib.suppress(OSError, TimeoutError):
                async with asyncio.timeout(1):
                    await writer.wait_closed()
            self.clients.discard(task)

    async def bridge(self, ws: WebSocket) -> None:
        backend: asyncio.StreamWriter | None = None

        async def follow() -> None:
            nonlocal backend
            while True:
                connection: asyncio.StreamWriter | None = None
                try:
                    async with asyncio.timeout(5):
                        source, connection = await asyncio.open_unix_connection(str(self.socket), limit=LIMIT)
                    backend = connection
                    while True:
                        line = await source.readuntil(b"\n")
                        if len(line) > LIMIT:
                            raise Closed()
                        line[:-1].decode("utf-8", errors="strict")
                        await ws.send(line[:-1])
                except (OSError, asyncio.IncompleteReadError):
                    await ws.send(b'{"type":"lost"}')
                finally:
                    backend = None
                    if connection:
                        connection.close()
                        with contextlib.suppress(OSError):
                            await connection.wait_closed()
                await asyncio.sleep(0.5)

        follower = asyncio.create_task(follow())
        incoming: asyncio.Task[TextFrame | None] | None = None
        try:
            while True:
                incoming = asyncio.create_task(ws.receive())
                done, _ = await asyncio.wait((incoming, follower), return_when=asyncio.FIRST_COMPLETED)
                if follower in done:
                    incoming.cancel()
                    await asyncio.gather(incoming, return_exceptions=True)
                    await follower
                    return
                text = incoming.result()
                if text is None:
                    return
                if backend:
                    backend.write(text.text.encode() + b"\n")
                    async with asyncio.timeout(5):
                        await backend.drain()
        finally:
            if incoming:
                incoming.cancel()
            follower.cancel()
            await asyncio.gather(*([incoming] if incoming else []), follower, return_exceptions=True)


def paths(args: argparse.Namespace) -> tuple[Path, Path]:
    if not re.fullmatch("[a-z0-9]+", args.root):
        raise ValueError("A Root identifier contains only lower-case letters and digits.")
    if args.bundle or args.socket:
        if not (args.bundle and args.socket):
            raise ValueError("Private --bundle and --socket overrides must be used together.")
        return Path(args.bundle), Path(args.socket)
    registry = (
        Path(args.registry_dir) if args.registry_dir else Path.home() / "Library/Application Support/Arbol/builds"
    )
    root_dir = (
        Path(args.root_dir) if args.root_dir else Path.home() / "Library/Application Support/Arbol/roots" / args.root
    )
    # Read only build metadata. Never import/invoke another component or start a backend.
    candidates = []
    for file in (registry / "arbol").glob("*/build.json"):
        try:
            record = json.loads(file.read_text())
            if not isinstance(record, dict):
                continue
            if (
                record.get("component") == "arbol"
                and record.get("root") == args.root
                and record.get("status") == "working"
                and re.fullmatch("[1-9a-f][0-9a-f]*", record.get("build", ""))
                and file.parent.name == record["build"]
                and os.access(file.parent / "bin/arbol", os.X_OK)
            ):
                candidates.append((int(record["build"], 16), file.parent))
        except (OSError, ValueError, TypeError):
            continue
    if not candidates:
        raise ValueError("The Root has no working Arbol Build.")
    return max(candidates)[1] / "ui/elma", root_dir / "backend.sock"


async def main(args: argparse.Namespace) -> None:
    bundle, socket = paths(args)
    relay = Relay(bundle, socket)
    await relay.start(args.port)
    print(f"http://{relay.host}/?token={relay.token}", flush=True)
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await relay.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--registry-dir")
    parser.add_argument("--root-dir")
    parser.add_argument("--bundle")
    parser.add_argument("--socket")
    try:
        asyncio.run(main(parser.parse_args()))
    except (OSError, ValueError):
        raise SystemExit("The development relay could not start; check the Root Build and socket paths.") from None
