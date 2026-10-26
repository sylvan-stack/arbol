"""The global Root catalogue: private homes and stand-ins, with a separate real-server example (SYL-160)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arbol_builds.roots import current_root, read_roots  # noqa: E402
from arbol_roots.database import Database, DatabaseError, environment  # noqa: E402
from arbol_roots.model import Places, Refused, catalogue, places, save_record  # noqa: E402
from arbol_roots.operations import Creation, catalogue_lock, default_database_name  # noqa: E402

ENTRY = ROOT / "bin/roots_entry.py"
ENV = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}

DATABASE_STAND_IN = f"""#!{sys.executable} -I
import json, os, sys, time
from pathlib import Path
home = Path(os.environ['HOME'])
kind = Path(__file__).name
config = json.loads((home / (kind + '.json')).read_text())
with (home / 'calls.jsonl').open('a') as stream:
    stream.write(json.dumps({{'kind': kind, 'args': sys.argv[1:], 'env': dict(os.environ)}}) + '\\n')
time.sleep(config.get('delay', 0))
print(config.get('password', '') if kind == 'security' else config.get('stdout', '1'))
sys.stderr.write(config.get('stderr', ''))
sys.exit(config.get('status', 0))
"""


def record(name: str = "sapling", state: str = "preparing", created: str = "2026-10-26T09:00:00.000Z",
           version: int = 1) -> dict[str, Any]:
    value: dict[str, Any] = {"root": name, "name": name.title(), "status": state, "createdAt": created,
                             "database": "arbol_" + name, "app": "0", "rootContract": version}
    if state == "failed":
        value["failed"] = {"at": created, "reason": "private failure"}
    return value


class DatabaseAccess(unittest.TestCase):
    def fixture(self) -> Places:
        home = Path(tempfile.mkdtemp(prefix="Arbol's database access "))
        self.addCleanup(shutil.rmtree, home, True)
        config = home / "database.json"
        config.write_text(json.dumps({"address": "postgresql://arbol@127.0.0.1:5433"}))
        for kind, values in (("security", {"password": "private-test-password"}), ("psql", {})):
            program = home / kind
            program.write_text(DATABASE_STAND_IN)
            program.chmod(0o755)
            (home / (kind + ".json")).write_text(json.dumps(values))
        return replace(places({"--database-config": str(config), "--security": str(home / "security"),
                               "--psql": str(home / "psql"), "--roots-dir": str(home / "roots"),
                               "--settings-dir": str(home / "settings")}), home=home)

    def test_roots_database_commands_quote_names_use_a_pristine_template_and_never_force_drop(self) -> None:
        """roots.database-ddl: one quoted identifier, template0 and UTF-8; DROP does not end other connections."""
        paths = self.fixture()
        database = Database(paths)
        name = 'private;name"quoted'
        database.create(name)
        database.drop(name)
        calls = [json.loads(line) for line in (paths.home / "calls.jsonl").read_text().splitlines()]
        sql = [row["args"][-1] for row in calls if row["kind"] == "psql"]
        self.assertEqual(sql, ['CREATE DATABASE "private;name""quoted" TEMPLATE template0 ENCODING \'UTF8\'',
                               'DROP DATABASE IF EXISTS "private;name""quoted"'])
        self.assertEqual(default_database_name("sapling"), "arbol_sapling")
        first = default_database_name("a" * 100)
        self.assertEqual(len(first), 63)
        self.assertEqual(first, default_database_name("a" * 100))
        self.assertNotEqual(first, default_database_name("a" * 99 + "b"))
        before = (paths.home / "calls.jsonl").read_bytes()
        for name in ("postgres", "template0", "template1", "", "x" * 64, "has\0nul"):
            with self.subTest(name=name), self.assertRaises(Refused):
                database.drop(name)
        self.assertEqual((paths.home / "calls.jsonl").read_bytes(), before)

    def test_roots_creation_compensation_removes_only_confirmed_new_work(self) -> None:
        """roots.creation-rollback: a later local failure drops the confirmed database and both new folders."""
        paths = self.fixture()
        database = Database(paths)
        with self.assertRaisesRegex(RuntimeError, "private local failure"):
            with Creation(paths, record()) as attempt:
                attempt.make_database(database)
                raise RuntimeError("private local failure")
        self.assertFalse((paths.roots / "sapling").exists())
        self.assertFalse((paths.settings / "sapling").exists())
        calls = [json.loads(line) for line in (paths.home / "calls.jsonl").read_text().splitlines()]
        self.assertEqual([row["args"][-1].split()[0] for row in calls if row["kind"] == "psql"], ["CREATE", "DROP"])
        (paths.roots / "sapling").mkdir()
        (paths.roots / "sapling/untouched").write_text("keep")
        with self.assertRaisesRegex(Refused, "already exists"):
            with Creation(paths, record()):
                self.fail("An existing target was accepted.")
        self.assertEqual((paths.roots / "sapling/untouched").read_text(), "keep")
        self.assertEqual((paths.home / "calls.jsonl").read_text().count('"kind": "psql"'), 2)
        # An ordinary SQL refusal (including an already existing database) authorizes no DROP.
        refused_paths = self.fixture()
        refused_database = Database(refused_paths)
        (refused_paths.home / "psql.json").write_text(json.dumps({"status": 3, "stderr": "database already exists"}))
        with self.assertRaisesRegex(DatabaseError, "already exists"):
            with Creation(refused_paths, record()) as attempt:
                attempt.make_database(refused_database)
        self.assertFalse((refused_paths.roots / "sapling").exists())
        calls = [json.loads(line) for line in (refused_paths.home / "calls.jsonl").read_text().splitlines()]
        self.assertEqual([row["args"][-1].split()[0] for row in calls if row["kind"] == "psql"], ["CREATE"])

    def test_roots_creation_retains_a_recovery_receipt_for_uncertain_outcomes_or_failed_rollback(self) -> None:
        """roots.creation-recovery: never drop a database after an uncertain CREATE or claim rollback succeeded."""
        for uncertain in (False, True):
            with self.subTest(uncertain=uncertain):
                paths = self.fixture()
                database = Database(paths)
                if uncertain:
                    (paths.home / "psql.json").write_text(json.dumps({"status": 2, "stderr": "lost connection"}))
                with self.assertRaisesRegex(DatabaseError, "recovery files are kept"):
                    with Creation(paths, record()) as attempt:
                        attempt.make_database(database)
                        (paths.home / "psql.json").write_text(json.dumps({"status": 3, "stderr": "drop refused"}))
                        raise RuntimeError("private local failure")
                self.assertTrue((paths.roots / "sapling/.creating.json").is_file())
                self.assertFalse((paths.roots / "sapling/root.json").exists())
                self.assertEqual(catalogue(paths), [])
                calls = [json.loads(line) for line in (paths.home / "calls.jsonl").read_text().splitlines()]
                self.assertEqual(len([row for row in calls if row["kind"] == "psql"]), 1 if uncertain else 2)

    def test_roots_catalogue_mutations_exclude_another_process_and_release_the_lock(self) -> None:
        """roots.catalogue-lock: another process is busy while held, then acquires after release."""
        paths = self.fixture()
        script = ("import json,sys\n" + f"sys.path.insert(0,{str(ROOT / 'src')!r})\n"
                  "from arbol_roots.model import places,Refused\n"
                  "from arbol_roots.operations import catalogue_lock\n"
                  "try:\n"
                  f" with catalogue_lock(places({{'--roots-dir': {str(paths.roots)!r}}})):\n"
                  "  print('acquired')\n"
                  "except Refused as e:\n"
                  " print(e.code);sys.exit(1)\n")
        with catalogue_lock(paths):
            result = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, timeout=20, check=False)
            self.assertEqual((result.returncode, result.stdout), (1, b"busy\n"))
        result = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, timeout=20, check=False)
        self.assertEqual((result.returncode, result.stdout), (0, b"acquired\n"))

    def test_roots_database_uses_maintenance_psql_keychain_account_and_only_the_declared_environment(self) -> None:
        """roots.database-access: no caller PG variables, Root database or password argument reaches psql."""
        paths = self.fixture()
        with mock.patch.dict(os.environ, {"PGHOST": "hostile", "PGSERVICE": "hostile", "UNRELATED": "private"}):
            with mock.patch("arbol_roots.database.subprocess.run", wraps=subprocess.run) as called:
                self.assertEqual(Database(paths).run("SELECT 1"), "1")
            self.assertEqual(set(called.call_args_list[0].kwargs["env"]), {"HOME", "PATH", "LANG"})
            self.assertEqual(set(called.call_args_list[1].kwargs["env"]), {"HOME", "PATH", "LANG", "PGPASSWORD"})
            self.assertEqual(called.call_args_list[0].kwargs["timeout"], 2)
            self.assertEqual(called.call_args_list[1].kwargs["timeout"], 30)
        calls = [json.loads(line) for line in (paths.home / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(calls[0]["args"], ["find-generic-password", "-s", "com.sylvan-stack.arbol.database",
                                          "-a", "arbol", "-w"])
        arguments = calls[1]["args"]
        self.assertIn("postgresql://arbol@127.0.0.1:5433/postgres", arguments)
        self.assertIn("--no-psqlrc", arguments)
        self.assertIn("--no-password", arguments)
        self.assertIn("ON_ERROR_STOP=1", arguments)
        self.assertNotIn("private-test-password", arguments)
        self.assertEqual(calls[1]["env"]["PGPASSWORD"], "private-test-password")
        self.assertFalse(any(name in calls[1]["env"] for name in ("PGHOST", "PGSERVICE", "UNRELATED")))

    def test_roots_database_keychain_missing_failure_and_timeout_are_distinct_without_secret_output(self) -> None:
        """roots.keychain: status 44 means no password; other failures and the two-second limit name Keychain."""
        paths = self.fixture()
        control = paths.home / "security.json"
        control.write_text(json.dumps({"status": 44}))
        self.assertIsNone(Database(paths).password)
        self.assertNotIn("PGPASSWORD", environment(paths))
        control.write_text(json.dumps({"status": 1, "password": "DO-NOT-PRINT", "stderr": "DO-NOT-PRINT"}))
        with self.assertRaisesRegex(DatabaseError, "Keychain.*status 1") as failed:
            Database(paths)
        self.assertNotIn("DO-NOT-PRINT", str(failed.exception))
        control.write_text(json.dumps({"delay": 3, "password": "DO-NOT-PRINT"}))
        started = time.monotonic()
        with self.assertRaisesRegex(DatabaseError, "Keychain.*2 seconds"):
            Database(paths)
        self.assertLess(time.monotonic() - started, 4)

    def test_roots_database_refuses_credential_or_database_addresses_and_redacts_psql_failures(self) -> None:
        """roots.database-refusal: invalid configuration stays private; psql diagnostics cannot echo a password."""
        paths = self.fixture()
        for address in ("postgresql://arbol:DO-NOT-PRINT@127.0.0.1:5433", "postgresql://arbol@127.0.0.1:5433/root",
                        "postgresql://arbol@127.0.0.1:bad", "not an address"):
            paths.database_config.write_text(json.dumps({"address": address}))
            with self.assertRaises(DatabaseError) as failed:
                Database(paths)
            self.assertNotIn("DO-NOT-PRINT", str(failed.exception))
            self.assertFalse((paths.home / "calls.jsonl").exists())
        paths.database_config.write_text(json.dumps({"address": "postgresql://arbol@127.0.0.1:5433"}))
        (paths.home / "psql.json").write_text(json.dumps({"status": 3, "stderr": "private-test-password failed"}))
        with self.assertRaises(DatabaseError) as failed:
            Database(paths).run("SELECT 1")
        self.assertNotIn("private-test-password", str(failed.exception))
        self.assertIn("[password removed]", str(failed.exception))


class Catalogue(unittest.TestCase):
    def test_roots_catalogue_agrees_with_launcher_headers_and_rereads_current_selection(self) -> None:
        """roots.catalogue: creation order, ties and state changes use the launchers' current-Root rule."""
        with tempfile.TemporaryDirectory() as home:
            roots = Path(home, "selected-roots")

            def put(value: dict[str, Any]) -> None:
                path = roots / value["root"]
                path.mkdir(parents=True, exist_ok=True)
                (path / "root.json").write_text(json.dumps(value))

            def call(*args: str, code: int = 0) -> Any:
                result = subprocess.run([sys.executable, "-I", "-B", str(ENTRY), *args,
                                         "--roots-dir", str(roots)], env={**ENV, "HOME": home},
                                        capture_output=True, timeout=20, check=False)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertEqual(result.stderr, b"")
                return json.loads(result.stdout)

            put(record("sapling", "working"))
            put(record("second", "preparing", "2026-10-26T11:00:00.000Z"))
            put(record("third", "failed", "2026-10-26T12:00:00.000Z"))
            put(record("alpha", "working", "2026-10-26T10:00:00.000Z"))
            put(record("zulu", "working", "2026-10-26T10:00:00.000Z"))
            listed = call("list")
            self.assertEqual([row["root"] for row in listed], ["third", "second", "zulu", "alpha", "sapling"])
            self.assertEqual([row["root"] for row in listed if row["current"]], ["zulu"])
            self.assertEqual(call("show")["root"], "zulu")
            self.assertEqual(call("show", "second")["status"], "preparing")
            # The shared header, rather than an independent catalogue schema, selects current.
            minimal = {"root": "minimal", "status": "working", "createdAt": "2026-10-26T13:00:00.000Z",
                       "rootContract": 2, "future": "preserved"}
            put(minimal)
            self.assertEqual(call("show"), minimal)
            shared = current_root(read_roots(str(roots)))
            self.assertIsNotNone(shared)
            assert shared is not None
            self.assertEqual(call("show")["root"], shared["root"])
            (roots / "minimal/root.json").write_text("{")
            self.assertEqual(call("show")["root"], "zulu")
            (roots / "zulu/root.json").unlink()
            self.assertEqual(call("show")["root"], "alpha")
            self.assertEqual(call("show", "minimal", code=1)["error"]["code"], "unknown_root")
            self.assertFalse(Path(home, "Library").exists())
            self.assertFalse(Path(home, ".arbol").exists())

    def test_roots_catalogue_isolates_damaged_missing_and_nonregular_records_and_reports_listing_failure(self) -> None:
        """roots.catalogue-damaged: a bad record affects one Root; an unavailable catalogue is not an empty list."""
        with tempfile.TemporaryDirectory() as home:
            roots = Path(home, "roots")

            def call(*args: str, code: int = 0) -> Any:
                result = subprocess.run([sys.executable, "-I", "-B", str(ENTRY), *args,
                                         "--roots-dir", str(roots)], cwd=home, env={**ENV, "HOME": home},
                                        capture_output=True, timeout=20, check=False)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                return json.loads(result.stdout)

            self.assertEqual(call("list"), [])
            self.assertEqual(call("show", code=1)["error"]["code"], "unknown_root")
            roots.write_text("not a directory")
            self.assertEqual(call("list", code=1)["error"]["code"], "operation_failed")
            roots.unlink()
            roots.mkdir()
            for name in ("damaged", "missing", "pipe", "directory", "good"):
                (roots / name).mkdir()
            (roots / "damaged/root.json").write_text("{")
            os.mkfifo(roots / "pipe/root.json")
            (roots / "directory/root.json").mkdir()
            (roots / "good/root.json").write_text(json.dumps(record("good")))
            self.assertEqual([row["root"] for row in call("list")], ["good"])

    def test_roots_frame_has_json_help_and_refuses_bad_command_lines_without_side_effects(self) -> None:
        """roots.cli: command counts, identifiers and inapplicable options fail as JSON before any work."""
        with tempfile.TemporaryDirectory() as home:
            for arguments in ([], ["unknown"], ["list", "extra"], ["ready", "../bad"],
                              ["list", "--name", "no"], ["create", "sapling", "--unknown", "x"],
                              ["show", "--roots-dir"]):
                result = subprocess.run([sys.executable, "-I", "-B", str(ENTRY), *arguments],
                                        env={**ENV, "HOME": home}, capture_output=True, timeout=20, check=False)
                self.assertEqual(result.returncode, 1, arguments)
                self.assertEqual(json.loads(result.stdout)["error"]["code"], "invalid_input", arguments)
                self.assertEqual(result.stderr, b"", arguments)
                self.assertEqual(os.listdir(home), [], arguments)
            result = subprocess.run([sys.executable, "-I", "-B", str(ENTRY), "--help"],
                                    env={**ENV, "HOME": home}, capture_output=True, timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("arbol-roots create", json.loads(result.stdout)["usage"])

    def test_roots_atomic_record_writes_validate_fields_preserve_extras_and_leave_no_temporary_file(self) -> None:
        """roots.record: complete records, compatible metadata and invalid writes use the shared header format."""
        with tempfile.TemporaryDirectory() as home:
            paths = places({"--roots-dir": str(Path(home, "roots"))})
            (paths.roots / "sapling").mkdir(parents=True)
            value = {**record(), "future": {"retained": True}}
            save_record(paths, value, complete=True)
            self.assertEqual(catalogue(paths), [value])
            self.assertEqual(list((paths.roots / "sapling").iterdir()), [paths.roots / "sapling/root.json"])
            before = (paths.roots / "sapling/root.json").read_bytes()
            for patch in ({"root": "../other"}, {"name": " "}, {"database": "postgres"}, {"database": "x" * 64},
                          {"app": "01"}, {"rootContract": 0}, {"grewFrom": "sapling"},
                          {"status": "failed", "failed": {"at": "invalid", "reason": "x"}}):
                with self.subTest(patch=patch), self.assertRaises(Refused):
                    save_record(paths, {**value, **patch}, complete=True)
                self.assertEqual((paths.roots / "sapling/root.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
