"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import ui.test_relay as _support
from ui.test_relay import (
    Path,
    RelayChecks,
    TOOL,
    argparse,
    asyncio,
    base64,
    contextlib,
    importlib,
    json,
    parse_qs,
    read_frame,
    relay,
    secrets,
    send_frame,
    spec,
    struct,
    sys,
    tempfile,
    unittest,
    urlsplit,
)


class RelayChecks(_support.RelayChecks):
# TEST-TIER-BEGIN tests/ui/test_relay.py::RelayChecks.test_cookie_host_origin_and_safe_assets
    async def test_cookie_host_origin_and_safe_assets(self) -> None:
        self.assertEqual(len(base64.urlsafe_b64decode(self.host.token + "==")), 16)
        first = await self.http("/?token=" + self.host.token + "&open=fictional&reloadedFor=2")
        self.assertTrue(first.startswith(b"HTTP/1.1 303"))
        self.assertIn(b"HttpOnly; SameSite=Strict", first)
        self.assertIn(b"Location: /?open=fictional&reloadedFor=2\r\n", first)
        self.assertNotIn(b"token=", first)
        for target, headers in [
            ("/", {}),
            ("/", {"Cookie": self.cookie + "wrong"}),
            ("/", {"Cookie": self.cookie, "Host": "localhost:" + str(self.host.port)}),
            ("/?token=wrong", {}),
            ("/?token=" + self.host.token + "&token=" + self.host.token, {}),
            ("/", {"Cookie": self.cookie + "; " + self.cookie}),
        ]:
            self.assertIn(b"403 Forbidden", await self.http(target, headers))
        valid = await self.http("/local.js", {"Cookie": self.cookie})
        self.assertIn(b"200 OK", valid)
        self.assertIn(b"Cache-Control: no-store", valid)
        self.assertIn(b"connect-src 'self' ws://" + self.host.host.encode(), valid)
        for path in ["/../private.txt", "/%2e%2e/private.txt", "/escape", "/.private"]:
            self.assertIn(b"404 Not Found", await self.http(path, {"Cookie": self.cookie}))
        for extra in [
            {"Cookie": "wrong"},
            {"Origin": "https://evil.example"},
            {"Host": "evil.example"},
            {"Origin": ""},
        ]:
            _, _, header = await self.ws(extra)
            self.assertIn(b"403 Forbidden", header)
        self.assertEqual(self.count, 0, "Rejected handshakes must not reach backend")
# TEST-TIER-END tests/ui/test_relay.py::RelayChecks.test_cookie_host_origin_and_safe_assets

# TEST-TIER-BEGIN tests/ui/test_relay.py::RelayChecks.test_independent_windows_unchanged_fragments_ping_and_reconnect
    async def test_independent_windows_unchanged_fragments_ping_and_reconnect(self) -> None:
        r, w, h = await self.ws()
        self.assertIn(b"101 Switching Protocols", h)
        r2, w2, _ = await self.ws()
        self.assertEqual(json.loads((await read_frame(r))[1])["type"], "hello")
        await read_frame(r2)
        text = '{"type":"call", "id":"unicode", "method":"fictional", "params":{"text":"你好 ☃"}}'
        a, b = text[:25], text[25:]
        await send_frame(w, a, final=False)
        await send_frame(w, b"ping", opcode=9)
        self.assertEqual(await read_frame(r), (10, b"ping"))
        await send_frame(w, b, opcode=0)
        self.assertEqual((await read_frame(r))[1], text.encode())
        await send_frame(w2, '{"type":"call","id":"other","method":"root.get","params":{}}')
        self.assertIn(b'"other"', (await read_frame(r2))[1])
        self.assertEqual(self.records[0], text.encode() + b"\n")
        self.assertEqual(self.count, 2)
        for item in self.backend_writers:
            item.close()
        self.assertEqual(json.loads((await read_frame(r))[1]), {"type": "lost"})
        self.assertEqual(json.loads((await read_frame(r2))[1]), {"type": "lost"})
        async with asyncio.timeout(2):
            self.assertEqual(json.loads((await read_frame(r))[1])["type"], "hello")
            self.assertEqual(json.loads((await read_frame(r2))[1])["type"], "hello")
        self.assertEqual(self.count, 4)
        await send_frame(w, b"", opcode=8)
        self.assertEqual((await read_frame(r))[0], 8)
        await send_frame(w2, b"", opcode=8)
        await read_frame(r2)
# TEST-TIER-END tests/ui/test_relay.py::RelayChecks.test_independent_windows_unchanged_fragments_ping_and_reconnect

# TEST-TIER-BEGIN tests/ui/test_relay.py::RelayChecks.test_exact_line_boundary_and_invalid_frames_close
    async def test_exact_line_boundary_and_invalid_frames_close(self) -> None:
        r, w, _ = await self.ws()
        await read_frame(r)
        prefix = b'{"type":"reply","text":"'
        suffix = b'"}'
        payload = prefix + b"x" * (relay.LIMIT - 1 - len(prefix) - len(suffix)) + suffix
        self.backend_writers[-1].write(payload + b"\n")
        await self.backend_writers[-1].drain()
        async with asyncio.timeout(3):
            self.assertEqual((await read_frame(r))[1], payload)
        await send_frame(w, payload)
        async with asyncio.timeout(4):
            self.assertEqual((await read_frame(r))[1], payload)
        self.assertEqual(self.records[-1], payload + b"\n")
        # Header alone proves an over-limit message is refused before allocation/read.
        w.write(b"\x81\xff" + struct.pack("!Q", relay.LIMIT))
        await w.drain()
        async with asyncio.timeout(2):
            self.assertEqual(await r.read(), b"")
        for value, opcode, masked in [
            ("{}", 2, True),
            ("{}", 1, False),
            ('{"text":"raw\nline"}', 1, True),
            ("[]", 1, True),
        ]:
            reader, writer, _ = await self.ws()
            await read_frame(reader)
            await send_frame(writer, value, opcode=opcode, masked=masked)
            async with asyncio.timeout(2):
                self.assertEqual(await reader.read(), b"")
# TEST-TIER-END tests/ui/test_relay.py::RelayChecks.test_exact_line_boundary_and_invalid_frames_close

# TEST-TIER-BEGIN tests/ui/test_relay.py::RelayChecks.test_process_prints_only_bootstrap_and_quiet_shutdown
    async def test_process_prints_only_bootstrap_and_quiet_shutdown(self) -> None:
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-B",
            str(TOOL),
            "--root",
            "t1",
            "--bundle",
            str(self.bundle),
            "--socket",
            str(self.path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert child.stdout is not None and child.stderr is not None
        async with asyncio.timeout(3):
            line = await child.stdout.readline()
        self.assertTrue(line.startswith(b"http://127.0.0.1:"))
        self.assertIn(b"/?token=", line)
        url = urlsplit(line.decode().strip())
        reader, writer = await asyncio.open_connection("127.0.0.1", url.port)
        self.writers.append(writer)
        token = parse_qs(url.query)["token"][0]
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        writer.write((f"GET /bridge HTTP/1.1\r\nHost: {url.netloc}\r\n"
                      f"Cookie: arbol_relay_{url.port}={token}\r\nOrigin: http://{url.netloc}\r\n"
                      f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        await writer.drain()
        try:
            async with asyncio.timeout(2):
                self.assertIn(b"101 Switching Protocols", await reader.readuntil(b"\r\n\r\n"))
                self.assertEqual(json.loads((await read_frame(reader))[1])["type"], "hello")
            child.terminate()
            async with asyncio.timeout(2):
                out, err = await child.communicate()
                self.assertEqual(await reader.read(), b"")
            self.assertEqual((child.returncode, out, err), (0, b"", b""))
        finally:
            writer.close()
            await writer.wait_closed()
            if child.returncode is None:
                child.kill()
                await child.wait()
# TEST-TIER-END tests/ui/test_relay.py::RelayChecks.test_process_prints_only_bootstrap_and_quiet_shutdown

# TEST-TIER-BEGIN tests/ui/test_relay.py::RelayChecks.test_document_refresh_keeps_only_old_assets_not_old_documents
    async def test_document_refresh_keeps_only_old_assets_not_old_documents(self) -> None:
        newer = self.root / "newer"
        (newer / "assets").mkdir(parents=True)
        (self.bundle / "assets").mkdir()
        (self.bundle / "assets/old-hash.js").write_text("OLD ASSET")
        (newer / "assets/new-hash.js").write_text("NEW ASSET")
        (newer / "index.html").write_text("NEW BUILD DOCUMENT")
        (self.bundle / "old-private.txt").write_text("OLD PRIVATE")
        selected = self.bundle
        self.host.refresh = lambda: selected
        self.assertIn(b"Fixture", await self.http("/", {"Cookie": self.cookie}))
        selected = newer
        self.assertIn(b"NEW BUILD DOCUMENT", await self.http("/?reloadedFor=2", {"Cookie": self.cookie}))
        self.assertIn(b"NEW ASSET", await self.http("/assets/new-hash.js", {"Cookie": self.cookie}))
        self.assertIn(b"OLD ASSET", await self.http("/assets/old-hash.js", {"Cookie": self.cookie}))
        self.assertIn(b"404 Not Found", await self.http("/old-private.txt", {"Cookie": self.cookie}))
        (newer / "index.html").unlink()
        self.assertIn(b"503 Service Unavailable", await self.http("/", {"Cookie": self.cookie}))
# TEST-TIER-END tests/ui/test_relay.py::RelayChecks.test_document_refresh_keeps_only_old_assets_not_old_documents

# TEST-TIER-BEGIN tests/ui/test_relay.py::RelayChecks.test_running_process_reselects_numbered_root_build
    async def test_running_process_reselects_numbered_root_build(self) -> None:
        registry = self.root / "rotation-registry"

        def build(number: str) -> None:
            folder = registry / "arbol" / number
            (folder / "bin").mkdir(parents=True)
            (folder / "bin/arbol").write_text("#!/bin/sh\n")
            (folder / "bin/arbol").chmod(0o700)
            (folder / "ui/elma").mkdir(parents=True)
            (folder / "ui/elma/index.html").write_text("PRIVATE BUILD " + number)
            (folder / "build.json").write_text(json.dumps({"component": "arbol", "root": "t1",
                "build": number, "status": "working", "entry": "bin/arbol"}))

        build("1")
        child = await asyncio.create_subprocess_exec(sys.executable, "-I", "-B", str(TOOL),
            "--root", "t1", "--registry-dir", str(registry), "--root-dir", str(self.root / "root"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        assert child.stdout is not None
        try:
            async with asyncio.timeout(3):
                url = urlsplit((await child.stdout.readline()).decode().strip())

            async def document() -> bytes:
                reader, writer = await asyncio.open_connection("127.0.0.1", url.port)
                try:
                    token = parse_qs(url.query)["token"][0]
                    writer.write((f"GET / HTTP/1.1\r\nHost: {url.netloc}\r\n"
                                  f"Cookie: arbol_relay_{url.port}={token}\r\n\r\n").encode())
                    await writer.drain()
                    return await reader.read()
                finally:
                    writer.close()
                    await writer.wait_closed()

            self.assertTrue((await document()).endswith(b"PRIVATE BUILD 1"))
            build("2")
            self.assertTrue((await document()).endswith(b"PRIVATE BUILD 2"))
            self.assertEqual(self.count, 0, "Reading Build metadata must start no backend")
        finally:
            child.terminate()
            async with asyncio.timeout(3):
                out, err = await child.communicate()
            self.assertEqual((child.returncode, out, err), (0, b"", b""))
# TEST-TIER-END tests/ui/test_relay.py::RelayChecks.test_running_process_reselects_numbered_root_build

# TEST-TIER-BEGIN tests/ui/test_relay.py::RelayChecks.test_newest_working_root_build_selection
    def test_newest_working_root_build_selection(self) -> None:
        reg = self.root / "registry"
        a = reg / "arbol"
        a.mkdir(parents=True)
        for build, root, status in [
            ("1", "t1", "working"),
            ("2", "t1", "withdrawn"),
            ("3", "other", "working"),
            ("4", "t1", "working"),
            ("5", "t1", "working"),
            ("6", "t1", "working"),
        ]:
            folder = a / build
            (folder / "bin").mkdir(parents=True)
            exe = folder / "bin/arbol"
            exe.write_text("#!/bin/sh\n")
            exe.chmod(0o700)
            (folder / "build.json").write_text(
                json.dumps({"component": "arbol", "root": root, "status": status, "build": build,
                            "entry": "bin/other" if build == "6" else "bin/arbol",
                            **({"prunedAt": "2026-10-27T00:00:00Z"} if build == "5" else {})})
            )
        args = argparse.Namespace(
            root="t1", bundle=None, socket=None, registry_dir=str(reg), root_dir=str(self.root / "root")
        )
        self.assertEqual(relay.paths(args), (a / "4/ui/elma", self.root / "root/backend.sock"))
        args.root = "../bad"
        with self.assertRaises(ValueError):
            relay.paths(args)
# TEST-TIER-END tests/ui/test_relay.py::RelayChecks.test_newest_working_root_build_selection
