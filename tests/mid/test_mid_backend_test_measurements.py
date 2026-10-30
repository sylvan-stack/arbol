"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_measurements as _support
from backend.test_measurements import (
    Attention,
    Database,
    Health,
    LocalDisk,
    Measurements,
    Programs,
    Registry,
    asyncio,
    replace,
    shlex,
    sys,
    time,
)


class Storage(_support.Storage):

# TEST-TIER-BEGIN tests/backend/test_measurements.py::Storage.test_size_permission_failure_is_partial_without_escalation_or_an_outage
    async def test_size_permission_failure_is_partial_without_escalation_or_an_outage(self) -> None:
        """measurement.permission-partial; measurement.no-escalation; measurement.data-directory-permission"""
        await self.db.execute("CREATE DATABASE private_denied")
        await self.db.execute("CREATE DATABASE private_allowed")
        await self.db.execute("REVOKE CONNECT ON DATABASE private_denied FROM PUBLIC")
        await self.db.execute("CREATE ROLE measurement_user LOGIN")
        self.catalogue(("denied", "private_denied"), ("allowed", "private_allowed"))
        selected = replace(self.backend.identity, database=self.cluster.address.replace("bkd@", "measurement_user@"))
        database = Database(selected)
        health = Health(database, Attention())
        measure = Measurements(health, self.backend.roots, Registry())
        try:
            report = await measure.measure({})
            rows = {row["root"]: row for row in report["roots"]}
            self.assertTrue(report["server"]["ok"])
            self.assertIn("problem", rows["denied"])
            self.assertNotIn("bytes", rows["denied"])
            self.assertGreater(rows["allowed"]["bytes"], 0)
            self.assertGreater(rows[self.backend.identity.root]["bytes"], 0)
            self.assertIn("diskProblem", report)
            self.assertNotIn("freeBytes", report)
            self.assertFalse(database.away)
            self.assertNotIn("database_unreachable", health.attention.items)
            self.assertEqual(await self.db.execute("SELECT rolsuper,rolcreaterole FROM pg_roles WHERE rolname='measurement_user'"), [(False, False)])
        finally:
            await measure.close()
            await health.close()
            await database.close()
# TEST-TIER-END tests/backend/test_measurements.py::Storage.test_size_permission_failure_is_partial_without_escalation_or_an_outage


# TEST-TIER-BEGIN tests/backend/test_measurements.py::Storage.test_utility_split_output_is_complete_and_overflow_is_bounded
    async def test_utility_split_output_is_complete_and_overflow_is_bounded(self) -> None:
        """measurement.utility-whole-reply; measurement.utility-output-bound"""
        program = self.frame.bin / "private-du-output"
        code = "import os,time;os.write(1,b'12');time.sleep(0.03);os.write(1,b'34\\tignored\\n')"
        program.write_text("#!/bin/sh\nexec "+shlex.quote(sys.executable)+" -I -c "+shlex.quote(code)+"\n")
        program.chmod(0o700)
        disk = LocalDisk(program=str(program), seconds=1)
        self.assertEqual(await disk.size(self.cluster.data), 1234*1024)
        code = "import os,time;os.write(1,b'1'*5000);time.sleep(30)"
        program.write_text("#!/bin/sh\nexec "+shlex.quote(sys.executable)+" -I -c "+shlex.quote(code)+"\n")
        before = time.monotonic()
        report = await disk.get(str(self.cluster.data), "/private/socket", None)
        self.assertLess(time.monotonic()-before, 0.5)
        self.assertIn("freeBytes", report)
        self.assertIn("diskProblem", report)
        self.assertNotIn("dataFolderBytes", report)
# TEST-TIER-END tests/backend/test_measurements.py::Storage.test_utility_split_output_is_complete_and_overflow_is_bounded

# TEST-TIER-BEGIN tests/backend/test_measurements.py::Storage.test_a_root_named_catalogue_cannot_collide_with_the_global_catalogue_command
    async def test_a_root_named_catalogue_cannot_collide_with_the_global_catalogue_command(self) -> None:
        """measurement.catalogue-namespace; measurement.valid-root-name"""
        self.frame.behavior["arbol-roots"] = {"sleep": 0.1, "output": [{"root": "catalogue", "current": True}]}
        self.frame.behavior["arbol-root"] = {"sleep": 0.1, "output": {"root": "catalogue", "exchanges": [], "unreadable": []}}
        self.frame.configure()
        programs = Programs(replace(self.backend.identity, root="catalogue"))
        try:
            current, listed = await asyncio.gather(programs.current_root(), programs.call("arbol-root", ["list"], kind="list"))
            self.assertEqual(current, {"root": "catalogue", "current": True})
            self.assertEqual(listed["root"], "catalogue")
        finally:
            programs.close()
# TEST-TIER-END tests/backend/test_measurements.py::Storage.test_a_root_named_catalogue_cannot_collide_with_the_global_catalogue_command

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_measurements.py::Storage.test_actual_sizes_and_data_folder_use_only_the_own_connection_and_global_catalogue
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: measurement.own-connection; measurement.actual-sizes; measurement.local-disk; measurement.no-foreign-files
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_measurements.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_actual_sizes_and_data_folder_use_only_the_own_connection_and_global_catalogue(self) -> None:
#         """measurement.own-connection; measurement.actual-sizes; measurement.local-disk; measurement.no-foreign-files"""
#         await self.db.execute('CREATE DATABASE "private other; literal"')
#         self.catalogue(("t2", "private other; literal"), ("missing", "private_missing"), ("invalid", "postgres"))
#         observed: list[tuple[str, str, Sequence[Any] | None]] = []
#         original = Session.execute
#         async def recorded(session: Session, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
#             observed.append((session.connection.info.dbname, sql, params))
#             return await original(session, sql, params)
#         with mock.patch.object(Session, "execute", recorded):
#             r, w = await self.open()
#             reply = await self.call(r, w, "health.measure")
#         report = reply["result"]
#         self.assertTrue(report["server"]["ok"])
#         rows = {row["root"]: row for row in report["roots"]}
#         self.assertGreater(rows[self.backend.identity.root]["bytes"], 0)
#         self.assertGreater(rows["t2"]["bytes"], 0)
#         self.assertEqual(rows["t2"]["database"], "private other; literal")
#         for root in ("missing", "invalid"):
#             self.assertIn("problem", rows[root])
#             self.assertNotIn("bytes", rows[root])
#         self.assertEqual(rows["invalid"]["database"], "")
#         sizes = [entry for entry in observed if entry[1].startswith("SELECT pg_database_size")]
#         self.assertEqual([row[2] for row in sizes], [["arbol_test"], ["private other; literal"], ["private_missing"]])
#         self.assertTrue(all(row[0] == "arbol_test" for row in sizes))
#         self.assertGreater(report["dataFolderBytes"], 0)
#         self.assertEqual(report["dataFolderBytes"] % 1024, 0)
#         self.assertGreater(report["freeBytes"], 0)
#         self.assertNotIn("diskProblem", report)
#         self.assertFalse((self.frame.root.parent / "t2").exists())
#         self.assertNotIn("database", (await self.backend.roots.refresh()).event["root"])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_measurements.py::Storage.test_catalogue_failure_does_not_hide_confirmed_server_and_disk
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: measurement.catalogue-partial; measurement.safe-problems
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_measurements.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_catalogue_failure_does_not_hide_confirmed_server_and_disk(self) -> None:
#         """measurement.catalogue-partial; measurement.safe-problems"""
#         self.frame.behavior["arbol-roots"] = {"status": 2, "raw": "fictional-private-diagnostic"}
#         self.frame.configure()
#         report = await self.backend.measurements.measure({})
#         self.assertTrue(report["server"]["ok"])
#         self.assertEqual(report["roots"], [])
#         self.assertIn("catalogueProblem", report)
#         self.assertGreater(report["freeBytes"], 0)
#         self.assertNotIn("fictional-private-diagnostic", json.dumps(report))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_measurements.py::Storage.test_actual_away_report_has_no_invented_sizes_and_keeps_attention
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: measurement.database-away; measurement.no-zero-facts
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_measurements.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_actual_away_report_has_no_invented_sizes_and_keeps_attention(self) -> None:
#         """measurement.database-away; measurement.no-zero-facts"""
#         await offline(self.cluster)
#         report = await self.backend.measurements.measure({})
#         self.assertFalse(report["server"]["ok"])
#         self.assertIn("database_unreachable", self.backend.chats.attention.items)
#         self.assertIn("diskProblem", report)
#         self.assertNotIn("freeBytes", report)
#         self.assertNotIn("dataFolderBytes", report)
#         self.assertTrue(all("bytes" not in row and "problem" in row for row in report["roots"]))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_measurements.py::Storage.test_three_windows_share_one_fresh_measurement_and_health_probe
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: measurement.shared; measurement.fresh; measurement.shared-health-probe
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_measurements.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_three_windows_share_one_fresh_measurement_and_health_probe(self) -> None:
#         """measurement.shared; measurement.fresh; measurement.shared-health-probe"""
#         clients = [await self.open() for _ in range(3)]
#         queries: list[str] = []
#         original = Session.execute
#         async def delayed(session: Session, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
#             queries.append(sql)
#             if sql == "SELECT 1":
#                 await asyncio.sleep(0.08)
#             return await original(session, sql, params)
#         with mock.patch.object(Session, "execute", delayed):
#             probes = asyncio.create_task(self.backend.health.probe())
#             replies = await asyncio.gather(*(self.call(r, w, "health.measure") for r, w in clients))
#             await probes
#             self.assertTrue(all(reply["result"] == replies[0]["result"] for reply in replies))
#             self.assertEqual(queries.count("SELECT 1"), 1)
#             self.assertEqual(queries.count("SELECT pg_database_size(%s::name)"), 1)
#             await self.call(*clients[0], "health.measure")
#             self.assertEqual(queries.count("SELECT pg_database_size(%s::name)"), 2)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_measurements.py::Storage.test_whole_measurement_deadline_preserves_completed_disk_and_unfinished_root_metadata
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: measurement.total-bound; measurement.partial-deadline; measurement.disk-independent-of-size
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_measurements.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_whole_measurement_deadline_preserves_completed_disk_and_unfinished_root_metadata(self) -> None:
#         """measurement.total-bound; measurement.partial-deadline; measurement.disk-independent-of-size"""
#         self.backend.measurements.total = 0.15
#         original = Session.execute
#         async def delayed(session: Session, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
#             if sql.startswith("SELECT pg_database_size"):
#                 await asyncio.sleep(1)
#             return await original(session, sql, params)
#         with mock.patch.object(Session, "execute", delayed):
#             before = time.monotonic()
#             report = await self.backend.measurements.measure({})
#         self.assertLess(time.monotonic()-before, 0.4)
#         self.assertTrue(report["server"]["ok"])
#         self.assertGreater(report["freeBytes"], 0)
#         self.assertNotIn("diskProblem", report)
#         self.assertEqual(report["roots"][0]["database"], "arbol_test")
#         self.assertNotIn("bytes", report["roots"][0])
#         self.assertIn("problem", report["roots"][0])
#         self.assertFalse(self.backend.database.away)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_measurements.py::Storage.test_remote_relative_and_failed_utility_never_guess_a_local_disk_or_expose_diagnostics
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: measurement.remote-refused; measurement.disk-path; measurement.utility-failure; measurement.utility-bound
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_measurements.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_remote_relative_and_failed_utility_never_guess_a_local_disk_or_expose_diagnostics(self) -> None:
#         """measurement.remote-refused; measurement.disk-path; measurement.utility-failure; measurement.utility-bound"""
#         disk = LocalDisk()
#         address = (await self.db.execute("SELECT inet '127.0.0.1'::text"))[0][0]
#         self.assertTrue(disk.local("127.0.0.1", address))
#         self.assertTrue(disk.local("::1", "::1/128"))
#         self.assertIn("freeBytes", await disk.get(str(self.cluster.data), "127.0.0.1", address))
#         for host, server in (("203.0.113.10", "127.0.0.1"), ("127.0.0.1", "203.0.113.10")):
#             self.assertEqual(set(await disk.get(str(self.cluster.data), host, server)), {"diskProblem"})
#         self.assertEqual(set(await disk.get("relative", "/private/socket", None)), {"diskProblem"})
#         self.assertEqual(set(await disk.get(str(self.frame.base / "missing"), "/private/socket", None)), {"diskProblem"})
#         program = self.frame.bin / "private-du"
#         pidfile = self.frame.base / "du.pid"
#         program.write_text("#!/bin/sh\nprintf '%s' $$ > "+shlex.quote(str(pidfile))+"\nexec /bin/sleep 30\n")
#         program.chmod(0o700)
#         disk = LocalDisk(program=str(program), seconds=0.08)
#         children: list[asyncio.subprocess.Process] = []
#         create = asyncio.create_subprocess_exec
#         async def captured(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
#             child = await create(*args, **kwargs)
#             if args[0] == str(program):
#                 children.append(child)
#             return child
#         before = time.monotonic()
#         with mock.patch("arbol_backend.storage.asyncio.create_subprocess_exec", side_effect=captured):
#             report = await disk.get(str(self.cluster.data), "/private/socket", None)
#         self.assertLess(time.monotonic()-before, 0.4)
#         self.assertIn("freeBytes", report)
#         self.assertIn("diskProblem", report)
#         self.assertNotIn("dataFolderBytes", report)
#         self.assertEqual(len(children), 1)
#         self.assertEqual(children[0].returncode, -signal.SIGKILL)
#         with self.assertRaises(ProcessLookupError):
#             os.kill(children[0].pid, 0)
# LOW-TIER-SOURCE-END
# LOW-TIER-END
