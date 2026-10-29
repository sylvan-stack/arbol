"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_backend as _support
from test_backend import (
    Any,
    AsyncFoundation,
    Backend,
    Cluster,
    Frame,
    LIMITS,
    Lifetime,
    Path,
    Process,
    Programs,
    ROOT,
    Refused,
    SQL,
    TEST_BUILD,
    TEST_ROOT,
    asyncio,
    database,
    identity,
    json,
    mock,
    os,
    parse,
    replace,
    settings,
    shlex,
    signal,
    socket,
    stat,
    subprocess,
    sys,
    time,
    unittest,
)


class Process(_support.Process):
# TEST-TIER-BEGIN tests/test_backend.py::Process.test_ready_modes_duplicate_and_stale_socket
    def test_ready_modes_duplicate_and_stale_socket(self) -> None:
        """backend.process-lock"""
        f = self.frame
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(f.root / "backend.sock"))
        stale.close()
        first = f.start()
        ready = f.line(first)
        self.assertEqual(
            {k: ready[k] for k in ("ready", "root", "build", "pid")},
            {"ready": True, "root": TEST_ROOT, "build": TEST_BUILD, "pid": first.pid},
        )
        self.assertEqual(stat.S_IMODE((f.root / "backend.sock").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((f.root / "backend.lock").stat().st_mode), 0o600)
        second = f.start()
        refusal = f.line(second)
        self.assertEqual(refusal["error"]["code"], "already_running")
        self.assertIn(str(first.pid), refusal["error"]["message"])
        self.assertEqual(second.wait(timeout=2), 1)
        first.send_signal(signal.SIGTERM)
        out, err = first.communicate(timeout=2)
        self.assertEqual((first.returncode, out, err), (0, b"", b""))
        self.assertFalse((f.root / "backend.sock").exists())
        third = f.start()
        self.assertTrue(f.line(third)["ready"])
# TEST-TIER-END tests/test_backend.py::Process.test_ready_modes_duplicate_and_stale_socket

# TEST-TIER-BEGIN tests/test_backend.py::Process.test_three_shutdown_paths_close_clients_without_exchange_change
    def test_three_shutdown_paths_close_clients_without_exchange_change(self) -> None:
        """backend.shutdown"""
        f = self.frame
        exchanges = f.root / "exchanges"
        exchanges.mkdir()
        sentinel = exchanges / "untouched"
        sentinel.write_text("exact")
        for stop in ("term", "int", "eof"):
            child = f.start()
            f.line(child)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(2)
            client.connect(str(f.root / "backend.sock"))
            started = time.monotonic()
            if stop == "eof":
                assert child.stdin is not None
                child.stdin.close()
                child.stdin = None
            else:
                child.send_signal(signal.SIGTERM if stop == "term" else signal.SIGINT)
            out, err = child.communicate(timeout=2)
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual((child.returncode, out, err), (0, b"", b""))
            self.assertTrue(all(json.loads(line)["type"] == "hello" for line in client.makefile("rb").read().splitlines()))
            client.close()
            self.assertFalse((f.root / "backend.sock").exists())
            self.assertEqual(sentinel.read_text(), "exact")
# TEST-TIER-END tests/test_backend.py::Process.test_three_shutdown_paths_close_clients_without_exchange_change

# TEST-TIER-BEGIN tests/test_backend.py::Process.test_root_states_identity_and_isolation_refusals
    def test_root_states_identity_and_isolation_refusals(self) -> None:
        """backend.identity-isolation"""
        f = self.frame
        for state in ("preparing", "working", "failed"):
            f.record["status"] = state
            f.save_root()
            self.assertEqual(self.selected().root, TEST_ROOT)
            child = f.start()
            self.assertTrue(f.line(child)["ready"])
            child.send_signal(signal.SIGTERM)
            out, err = child.communicate(timeout=2)
            self.assertEqual((child.returncode, out, err), (0, b"", b""))
        for args in (
            ["--root", "T1", "backend"],
            ["--root", "t1", "backend", "--root-dir", str(f.root)],
            ["--root", "t1", "backend", "--root", "t1"],
            ["--root", "t1", "backend", "--unknown", "secret"],
        ):
            child = f.start(args=args)
            result = f.line(child)
            self.assertEqual(result["error"]["code"], "invalid_input")
            self.assertEqual(child.wait(timeout=2), 1)
        development = f.base / "development"
        development.mkdir()
        options = parse(f.options())
        options.pop("--root")
        with self.assertRaises(Refused):
            identity(development, options, home=f.home)
        (f.root / "root.json").write_text("{}")
        child = f.start()
        self.assertEqual(f.line(child)["error"]["code"], "unknown_root")
# TEST-TIER-END tests/test_backend.py::Process.test_root_states_identity_and_isolation_refusals

# TEST-TIER-BEGIN tests/test_backend.py::Process.test_path_limit_and_non_socket_preserved
    def test_path_limit_and_non_socket_preserved(self) -> None:
        """backend.socket-path"""
        f = self.frame
        long = f.base / ("x" * 90)
        long.mkdir()
        (long / "root.json").write_text(json.dumps(f.record))
        args = f.options()
        args[args.index("--root-dir") + 1] = str(long)
        child = f.start(args=args)
        self.assertEqual(f.line(child)["error"]["code"], "invalid_input")
        length = 103 - len(os.fsencode(f.base)) - 1 - len("/backend.sock")
        boundary = f.base / ("b" * length)
        boundary.mkdir()
        (boundary / "root.json").write_text(json.dumps(f.record))
        args = f.options()
        args[args.index("--root-dir") + 1] = str(boundary)
        child = f.start(args=args)
        ready = f.line(child)
        self.assertTrue(ready["ready"])
        self.assertEqual(len(os.fsencode(ready["socket"])), 103)
        child.send_signal(signal.SIGTERM)
        self.assertEqual(child.communicate(timeout=2), (b"", b""))
        path = f.root / "backend.sock"
        path.write_text("keep")
        child = f.start()
        self.assertEqual(f.line(child)["error"]["code"], "invalid_input")
        self.assertEqual(path.read_text(), "keep")
        path.unlink()
        path.symlink_to(f.root / "root.json")
        child = f.start()
        self.assertEqual(f.line(child)["error"]["code"], "invalid_input")
        self.assertTrue(path.is_symlink())
# TEST-TIER-END tests/test_backend.py::Process.test_path_limit_and_non_socket_preserved

# TEST-TIER-BEGIN tests/test_backend.py::Process.test_build_root_is_adjacent_and_must_match
    def test_build_root_is_adjacent_and_must_match(self) -> None:
        """backend.build-identity"""
        f = self.frame
        package = f.base / "package"
        package.mkdir()
        (package / "package.json").write_text('{"version":"2.0.0"}')
        record = {
            "component": "arbol",
            "entry": "bin/arbol",
            "root": TEST_ROOT,
            "build": "a",
            "packageVersion": "2.0.0",
        }
        (package / "build.json").write_text(json.dumps(record))
        options = parse(f.options())
        options.pop("--root")
        self.assertEqual(identity(package, options, home=f.home).build, "a")
        options["--root"] = "other"
        with self.assertRaises(Refused):
            identity(package, options, home=f.home)
        options.pop("--root")
        record["component"] = "arbol-root"
        (package / "build.json").write_text(json.dumps(record))
        with self.assertRaises(Refused):
            identity(package, options, home=f.home)
# TEST-TIER-END tests/test_backend.py::Process.test_build_root_is_adjacent_and_must_match

# TEST-TIER-BEGIN tests/test_backend.py::Process.test_close_on_exec_and_cleanup_owns_only_its_socket
    def test_close_on_exec_and_cleanup_owns_only_its_socket(self) -> None:
        """backend.descriptor-ownership"""
        f = self.frame
        lifetime = Lifetime(f.root)
        sock = lifetime.acquire()
        self.assertFalse(os.get_inheritable(lifetime.lock))
        self.assertFalse(sock.get_inheritable())
        held = os.fstat(lifetime.lock)
        code = 'import os,json;print(json.dumps([os.fstat(i).st_ino for i in range(3,256) if os.path.exists("/dev/fd/"+str(i))]))'
        result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
        self.assertNotIn(held.st_ino, json.loads(result.stdout))
        lifetime.path.unlink()
        lifetime.path.write_text("replacement")
        lifetime.close()
        self.assertEqual(lifetime.path.read_text(), "replacement")
# TEST-TIER-END tests/test_backend.py::Process.test_close_on_exec_and_cleanup_owns_only_its_socket

# TEST-TIER-BEGIN tests/test_backend.py::Process.test_optional_settings_and_routes
    def test_optional_settings_and_routes(self) -> None:
        """backend.settings"""
        f = self.frame
        self.assertEqual(settings(f.settings).for_repository("shop"), {})
        value = {
            "route": {"driver": "claude", "model": "m"},
            "repositories": {"shop": {"route": {"driver": "codex"}}, "none": {}},
            "smallCallRoute": {"driver": "pi"},
            "future": True,
        }
        (f.settings / "arbol.json").write_text(json.dumps(value))
        loaded = settings(f.settings)
        self.assertEqual(loaded.for_repository("shop"), {"driver": "codex"})
        self.assertEqual(loaded.for_repository("other"), {"driver": "claude", "model": "m"})
        self.assertEqual(loaded.small_call_route, {"driver": "pi"})
        for raw in ("{", '{"route":null}', '{"route":{"driver":false}}', '{"repositories":[]}'):
            (f.settings / "arbol.json").write_text(raw)
            with self.assertRaises(Refused):
                settings(f.settings)
# TEST-TIER-END tests/test_backend.py::Process.test_optional_settings_and_routes



class AsyncFoundation(_support.AsyncFoundation):
# TEST-TIER-BEGIN tests/test_backend.py::AsyncFoundation.test_launcher_path_groups_and_no_inference
    async def test_launcher_path_groups_and_no_inference(self) -> None:
        """backend.launcher-boundaries"""
        p = Programs(self.selected)
        self.addCleanup(p.close)
        for program, args, kind in [
            ("arbol-root", ["list"], "list"),
            ("arbol-roots", ["list"], "list"),
            ("arbol-pi-driver", ["subscriptions", "list"], "account"),
        ]:
            with mock.patch.dict(os.environ, {"PGPASSWORD": "fictional", "PGSERVICE": "fictional"}):
                await p.call(program, args, kind=kind)
        for row in self.frame.calls():
            self.assertEqual(row["pid"], row["pgid"])
            self.assertNotEqual(row["pgid"], os.getpgrp())
            self.assertEqual(row["path"].split(os.pathsep)[0], str(self.frame.bin))
            self.assertEqual(row["pgOverrides"], [])
            if row["program"] == "arbol-root":
                self.assertEqual(row["args"], ["--root", TEST_ROOT, "list"])
        with self.assertRaises(Refused):
            await p.call("arbol-pi-driver", ["run"], kind="account")
        with self.assertRaises(Refused):
            await p.call("arbol-pi-driver", ["subscriptions", "sign-in", "secret"], kind="account")
        self.assertEqual(LIMITS, {"start": 25, "stop": 90, "settle": 120, "list": 10, "account": 10, "migrate-check": 90, "reimport": 90})
# TEST-TIER-END tests/test_backend.py::AsyncFoundation.test_launcher_path_groups_and_no_inference

# TEST-TIER-BEGIN tests/test_backend.py::AsyncFoundation.test_listing_group_killed_and_mutation_tracked
    async def test_listing_group_killed_and_mutation_tracked(self) -> None:
        """backend.child-deadlines"""
        f = self.frame
        f.behavior = {"arbol-root": {"sleep": 30, "ignoreTerm": True, "fork": True}}
        f.configure()
        p = Programs(self.selected, limits={key: 0.2 for key in LIMITS})
        self.addCleanup(p.close)
        with self.assertRaises(Refused) as caught:
            await p.call("arbol-root", ["list"], kind="list")
        self.assertEqual(caught.exception.code, "no_answer")
        await asyncio.sleep(0.05)
        p.reap()
        self.assertFalse(p.running)
        descendant = int((f.bin / "descendant.pid").read_text())
        # Killed descendants can briefly be zombies before their adopted parent reaps them.
        state = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(descendant)], capture_output=True, text=True
        ).stdout.strip()
        self.assertTrue(not state or state.startswith("Z"), state)
        f.behavior = {"arbol-root": {"sleep": 1}}
        f.configure()
        mutations: list[subprocess.Popen[bytes]] = []
        for kind in ("start", "stop", "settle"):
            with self.assertRaises(Refused):
                await p.call("arbol-root", [kind], kind=kind, key=kind)
            child = p.running[(kind, self.selected.root if kind == "settle" else kind)].process
            mutations.append(child)
            self.assertIsNone(child.poll())
            with self.assertRaises(Refused) as repeated:
                await p.call("arbol-root", [kind], kind=kind, key=kind)
            self.assertEqual(repeated.exception.code, "in_progress")
        p.close()
        for child in mutations:
            self.assertEqual(await asyncio.to_thread(child.wait, timeout=2), 0)
# TEST-TIER-END tests/test_backend.py::AsyncFoundation.test_listing_group_killed_and_mutation_tracked

# TEST-TIER-BEGIN tests/test_backend.py::AsyncFoundation.test_current_root_is_read_each_time_and_metadata_refreshes
    async def test_current_root_is_read_each_time_and_metadata_refreshes(self) -> None:
        """backend.root-observation"""
        f = self.frame
        p = Programs(self.selected)
        self.addCleanup(p.close)
        for root in ("first", "second"):
            f.behavior = {"arbol-roots": {"output": [{"root": root, "current": True}]}}
            f.configure()
            current = await p.current_root()
            assert current is not None
            self.assertEqual(current["root"], root)
        f.behavior = {"arbol-roots": {"output": [{**f.record, "current": True}]}}
        f.configure()
        backend = Backend(self.selected)
        task = asyncio.create_task(backend.run())
        await asyncio.sleep(0.1)
        reader, writer = await asyncio.open_unix_connection(str(f.root / "backend.sock"))
        f.record.update(name="Changed Root", status="failed")
        f.save_root()
        self.assertEqual(backend.record["name"], "Test Root")
        await asyncio.sleep(5)
        self.assertEqual(backend.record["name"], "Changed Root")
        self.assertEqual(backend.record["status"], "failed")
        writer.close()
        await writer.wait_closed()
        backend.stopped.set()
        self.assertEqual(await task, 0)
# TEST-TIER-END tests/test_backend.py::AsyncFoundation.test_current_root_is_read_each_time_and_metadata_refreshes

# TEST-TIER-BEGIN tests/test_backend.py::AsyncFoundation.test_security_exit44_fail_timeout_and_masking
    async def test_security_exit44_fail_timeout_and_masking(self) -> None:
        """backend.keychain"""
        f = self.frame
        program = f.bin / "security"

        def script(body: str) -> None:
            program.write_text(
                "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -I -c " + shlex.quote(body) + ' "$@"\n'
            )
            program.chmod(0o700)

        script("import sys;sys.exit(44)")
        self.assertEqual(await database.password("bkd", program=str(program)), "")
        script('print("fictional-private-password")')
        self.assertEqual(await database.password("bkd", program=str(program)), "fictional-private-password")
        script('import sys;print("fictional-private-password",file=sys.stderr);sys.exit(3)')
        with self.assertRaises(Refused) as caught:
            await database.password("bkd", program=str(program))
        self.assertNotIn("fictional-private-password", str(caught.exception))
        script("import time;time.sleep(30)")
        with self.assertRaises(Refused) as caught:
            await database.password("bkd", program=str(program), seconds=0.1)
        self.assertEqual(caught.exception.code, "timeout")
        with mock.patch.object(database, "password", side_effect=AssertionError("Owner Keychain reached")):
            info = await database.credentials(self.selected)
        self.assertEqual(info["dbname"], "arbol_test")
# TEST-TIER-END tests/test_backend.py::AsyncFoundation.test_security_exit44_fail_timeout_and_masking

# TEST-TIER-BEGIN tests/test_backend.py::AsyncFoundation.test_normal_database_config_uses_only_own_database_and_role
    async def test_normal_database_config_uses_only_own_database_and_role(self) -> None:
        """backend.database-identity"""
        selected = replace(self.selected, database=None)
        folder = selected.home / ".arbol"
        folder.mkdir()
        config = folder / "database.json"
        config.write_text('{"address":"postgresql://testrole@127.0.0.1:5433"}')
        with mock.patch.object(database, "password", new_callable=mock.AsyncMock, return_value="fictional") as lookup:
            value = await database.credentials(selected)
        lookup.assert_awaited_once_with("testrole")
        self.assertEqual(value["dbname"], self.frame.record["database"])
        self.assertEqual(value["password"], "fictional")
        config.write_text('{"address":"postgresql://testrole:fictional@127.0.0.1:5433"}')
        with self.assertRaises(Refused) as caught:
            await database.credentials(selected)
        self.assertNotIn("fictional", str(caught.exception))
# TEST-TIER-END tests/test_backend.py::AsyncFoundation.test_normal_database_config_uses_only_own_database_and_role



class SQL(_support.SQL):
# TEST-TIER-BEGIN tests/test_backend.py::SQL.test_contract_tables_autocommit_and_repeatable_read_only
    async def test_contract_tables_autocommit_and_repeatable_read_only(self) -> None:
        """backend.database-transactions"""
        self.assertEqual((await self.db.execute("SELECT count(*) FROM chats"))[0][0], 0)
        await self.db.execute("CREATE TABLE IF NOT EXISTS backend_probe(value integer)")
        await self.db.execute("TRUNCATE backend_probe")
        await self.db.execute("INSERT INTO backend_probe VALUES (1)")
        async with self.db.session(snapshot=True) as session:
            self.assertEqual(await session.execute("SHOW transaction_isolation"), [("repeatable read",)])
            self.assertEqual(await session.execute("SHOW transaction_read_only"), [("on",)])
            self.assertEqual(await session.execute("SELECT value FROM backend_probe"), [(1,)])
            await self.db.execute("UPDATE backend_probe SET value=2")
            self.assertEqual(await session.execute("SELECT value FROM backend_probe"), [(1,)])
        self.assertEqual(await self.db.execute("SELECT value FROM backend_probe"), [(2,)])
        with self.assertRaises(Refused):
            async with self.db.session(snapshot=True) as session:
                await session.execute("UPDATE backend_probe SET value=3")
# TEST-TIER-END tests/test_backend.py::SQL.test_contract_tables_autocommit_and_repeatable_read_only

# TEST-TIER-BEGIN tests/test_backend.py::SQL.test_statement_timeout_and_concurrent_call
    async def test_statement_timeout_and_concurrent_call(self) -> None:
        """backend.database-deadlines"""
        started = time.monotonic()
        slow = asyncio.create_task(self.db.execute("SELECT pg_sleep(10)"))
        await asyncio.sleep(0.1)
        self.assertEqual(await self.db.execute("SELECT 42"), [(42,)])
        self.assertLess(time.monotonic() - started, 1)
        with self.assertRaises(Refused) as caught:
            await slow
        self.assertEqual(caught.exception.code, "timeout")
        self.assertLess(time.monotonic() - started, 6)
        self.assertEqual(await self.db.execute("SELECT 43"), [(43,)])
# TEST-TIER-END tests/test_backend.py::SQL.test_statement_timeout_and_concurrent_call

# TEST-TIER-BEGIN tests/test_backend.py::SQL.test_unreachable_startup_remains_ready_and_shutdown_is_bounded
    async def test_unreachable_startup_remains_ready_and_shutdown_is_bounded(self) -> None:
        """backend.database-away-start"""
        f = self.frame
        child = f.start()
        self.assertTrue(f.line(child)["ready"])
        await asyncio.sleep(0.2)
        self.assertIsNone(child.poll())
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(f.root / "backend.sock"))
        child.send_signal(signal.SIGTERM)
        out, err = await asyncio.to_thread(child.communicate, timeout=2)
        self.assertEqual((child.returncode, out, err), (0, b"", b""))
        client.close()
# TEST-TIER-END tests/test_backend.py::SQL.test_unreachable_startup_remains_ready_and_shutdown_is_bounded

# TEST-TIER-BEGIN tests/test_backend.py::SQL.test_connect_deadline_and_shutdown_during_handshake
    async def test_connect_deadline_and_shutdown_during_handshake(self) -> None:
        """backend.connect-timeout"""
        writers: list[asyncio.StreamWriter] = []

        def stalled(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writers.append(writer)

        server = await asyncio.start_server(stalled, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        address = f"postgresql://bkd@127.0.0.1:{port}/arbol_test"
        db = database.Database(replace(self.selected, database=address))
        try:
            started = time.monotonic()
            with self.assertRaises(Refused) as caught:
                await db.execute("SELECT 1")
            self.assertEqual(caught.exception.code, "database_unavailable")
            self.assertLess(time.monotonic() - started, 6)
            f = self.frame
            child = f.start(args=f.options(address))
            self.assertTrue(f.line(child)["ready"])
            await asyncio.sleep(0.1)
            started = time.monotonic()
            child.send_signal(signal.SIGTERM)
            out, err = await asyncio.to_thread(child.communicate, timeout=2)
            self.assertEqual((child.returncode, out, err), (0, b"", b""))
            self.assertLess(time.monotonic() - started, 2)
        finally:
            await db.close()
            server.close()
            for writer in writers:
                writer.close()
            server.close_clients()
            await server.wait_closed()
# TEST-TIER-END tests/test_backend.py::SQL.test_connect_deadline_and_shutdown_during_handshake
