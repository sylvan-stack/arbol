"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_measurements as _support
from backend.test_measurements import (
    Any,
    Attention,
    Database,
    Health,
    LocalDisk,
    Measurements,
    Path,
    Programs,
    ROOT,
    Registry,
    Sequence,
    Session,
    Storage,
    WindowFixture,
    asyncio,
    json,
    mock,
    offline,
    os,
    replace,
    shlex,
    signal,
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
