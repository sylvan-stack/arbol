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
