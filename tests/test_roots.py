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
from arbol_roots.operations import Creation, catalogue_lock, create, default_database_name, remove  # noqa: E402

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


def database_fixture(test: unittest.TestCase) -> Places:
    home = Path(tempfile.mkdtemp(prefix="Arbol's database access "))
    test.addCleanup(shutil.rmtree, home, True)
    config = home / "database.json"
    config.write_text(json.dumps({"address": "postgresql://arbol@127.0.0.1:5433"}))
    for kind, values in (("security", {"password": "private-test-password"}), ("psql", {})):
        program = home / kind
        program.write_text(DATABASE_STAND_IN)
        program.chmod(0o755)
        (home / (kind + ".json")).write_text(json.dumps(values))
    return replace(places({"--database-config": str(config), "--security": str(home / "security"),
                           "--psql": str(home / "psql"), "--roots-dir": str(home / "roots"),
                           "--settings-dir": str(home / "settings"), "--registry-dir": str(home / "registry")}), home=home)


def roots_command(paths: Places, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([sys.executable, "-I", "-B", str(ENTRY), *args,
                           "--roots-dir", str(paths.roots), "--settings-dir", str(paths.settings),
                           "--registry-dir", str(paths.registry), "--database-config", str(paths.database_config),
                           "--psql", paths.psql, "--security", paths.security],
                          cwd=paths.home, env={**ENV, "HOME": str(paths.home)}, capture_output=True, timeout=20, check=False)


def build_record(paths: Places, component: str, number: str, **extra: Any) -> dict[str, Any]:
    folder = paths.registry / component / number
    folder.mkdir(parents=True)
    value: dict[str, Any] = {"component": component, "build": number, "packageVersion": "1.0.0", "status": "working",
                             "startedAt": "2026-10-26T09:00:00.000Z", "finishedAt": "2026-10-26T09:00:01.000Z",
                             "source": {"repository": "/private", "branch": "main", "commit": "fixture",
                                        "uncommittedChanges": False}, "entry": "program", "checks": [
                                 {"name": "private", "passed": True}], **extra}
    (folder / "build.json").write_text(json.dumps(value))
    (folder / "program").write_text("#!/bin/sh\nexit 0\n")
    (folder / "program").chmod(0o755)
    return value


class Commands(unittest.TestCase):
    def test_roots_app_minimum_requires_an_available_working_build_and_never_moves_backwards(self) -> None:
        """roots.app: bootstrap is replaced by an available minimum, with idempotence and monotonic hexadecimal order."""
        paths = database_fixture(self)
        made = roots_command(paths, "create", "sapling", "--name", "First")
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
        for number in ("9", "a"):
            build_record(paths, "arbol-app", number)
        build_record(paths, "arbol-app", "b", status="withdrawn",
                     withdrawn={"at": "2026-10-26T10:00:00.000Z", "reason": "private"})
        build_record(paths, "arbol-app", "c", status="failed")
        build_record(paths, "arbol-app", "d")
        (paths.registry / "arbol-app/d/program").unlink()
        result = roots_command(paths, "app", "sapling", "a")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["app"], "a")
        self.assertEqual(json.loads(roots_command(paths, "app", "sapling", "a").stdout), json.loads(result.stdout))
        before = (paths.roots / "sapling/root.json").read_bytes()
        for number, code in (("9", "invalid_input"), ("b", "build_unavailable"), ("c", "build_unavailable"),
                             ("d", "build_unavailable"), ("e", "build_unavailable"), ("0", "invalid_input")):
            refused = roots_command(paths, "app", "sapling", number)
            self.assertEqual(refused.returncode, 1)
            self.assertEqual(json.loads(refused.stdout)["error"]["code"], code)
            self.assertEqual((paths.roots / "sapling/root.json").read_bytes(), before)

    def test_roots_remove_never_removes_current_and_deletes_only_the_named_noncurrent_root(self) -> None:
        """roots.remove: current is refused before SQL, while a noncurrent Root's own database/settings/state go."""
        paths = database_fixture(self)
        build_record(paths, "arbol-trunk/trivial", "1", rootContracts=[1])
        for name in ("sapling", "second"):
            result = roots_command(paths, "create", name, "--name", name.title())
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(roots_command(paths, "ready", "sapling").returncode, 0)
        source_record = (paths.roots / "sapling/root.json").read_bytes()
        (paths.settings / "sapling/arbol.json").write_text("keep source settings")
        refused = roots_command(paths, "remove", "sapling")
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(json.loads(refused.stdout)["error"]["code"], "current_root")
        self.assertEqual((paths.home / "calls.jsonl").read_text().count('"kind": "psql"'), 2)
        removed = roots_command(paths, "remove", "second")
        self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
        self.assertEqual(json.loads(removed.stdout)["root"], "second")
        self.assertFalse((paths.roots / "second").exists())
        self.assertFalse((paths.settings / "second").exists())
        self.assertEqual((paths.roots / "sapling/root.json").read_bytes(), source_record)
        self.assertEqual((paths.settings / "sapling/arbol.json").read_text(), "keep source settings")
        calls = [json.loads(line) for line in (paths.home / "calls.jsonl").read_text().splitlines()]
        self.assertEqual([row["args"][-1] for row in calls if row["kind"] == "psql"][-1],
                         'DROP DATABASE IF EXISTS "arbol_second"')

    def test_roots_remove_database_failure_or_duplicate_claim_preserves_all_files(self) -> None:
        """roots.remove-refusal: DROP failure, a shared database claim and symlink targets authorize no deletion."""
        paths = database_fixture(self)
        self.assertEqual(roots_command(paths, "create", "sapling", "--name", "First").returncode, 0)
        (paths.settings / "sapling/arbol.json").write_text("private settings")
        before = (paths.roots / "sapling/root.json").read_bytes()
        (paths.home / "psql.json").write_text(json.dumps({"status": 3, "stderr": "database has open connections"}))
        refused = roots_command(paths, "remove", "sapling")
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(json.loads(refused.stdout)["error"]["code"], "database_unavailable")
        self.assertEqual((paths.roots / "sapling/root.json").read_bytes(), before)
        self.assertEqual((paths.settings / "sapling/arbol.json").read_text(), "private settings")
        (paths.roots / "second").mkdir()
        save_record(paths, {**record("second"), "database": "arbol_sapling"}, complete=True)
        calls_before = (paths.home / "calls.jsonl").read_bytes()
        refused = roots_command(paths, "remove", "sapling")
        self.assertEqual(json.loads(refused.stdout)["error"]["code"], "invalid_input")
        self.assertEqual((paths.home / "calls.jsonl").read_bytes(), calls_before)
        (paths.roots / "second/root.json").unlink()
        target = paths.home / "elsewhere"
        (paths.settings / "sapling").rename(target)
        (paths.settings / "sapling").symlink_to(target, target_is_directory=True)
        refused = roots_command(paths, "remove", "sapling")
        self.assertEqual(json.loads(refused.stdout)["error"]["code"], "invalid_input")
        self.assertEqual((paths.home / "calls.jsonl").read_bytes(), calls_before)
        self.assertEqual((target / "arbol.json").read_text(), "private settings")

    def test_roots_remove_reports_partial_filesystem_cleanup_and_can_be_retried(self) -> None:
        """roots.remove-retry: a completed DROP with failed folder cleanup retains its record for a truthful retry."""
        paths = database_fixture(self)
        self.assertEqual(roots_command(paths, "create", "sapling", "--name", "First").returncode, 0)
        with mock.patch("arbol_roots.operations.shutil.rmtree", side_effect=PermissionError("private cleanup failure")):
            with self.assertRaisesRegex(Refused, "database was removed.*cleanup.*incomplete"):
                remove(paths, "sapling")
        self.assertTrue((paths.roots / "sapling/root.json").exists())
        retried = roots_command(paths, "remove", "sapling")
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertFalse((paths.roots / "sapling").exists())

    def test_roots_ready_requires_a_runnable_working_compatible_trivial_build(self) -> None:
        """roots.ready: only a working runnable Trivial Build of the Root's contract permits readiness."""
        paths = database_fixture(self)
        made = roots_command(paths, "create", "sapling", "--name", "First", "--root-contract", "2")
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
        before = (paths.roots / "sapling/root.json").read_bytes()

        def refused() -> None:
            result = roots_command(paths, "ready", "sapling")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["error"]["code"], "no_fit")
            self.assertIn("Root Contract 2", json.loads(result.stdout)["error"]["message"])
            self.assertEqual((paths.roots / "sapling/root.json").read_bytes(), before)

        refused()
        build_record(paths, "arbol-trunk/other", "1", rootContracts=[2])
        build_record(paths, "arbol-trunk/trivial", "1", rootContracts=[1])
        refused()
        build_record(paths, "arbol-trunk/trivial", "2", rootContracts=[2])
        (paths.registry / "arbol-trunk/trivial/2/program").unlink()
        build_record(paths, "arbol-trunk/trivial", "3", rootContracts=[2], status="building")
        build_record(paths, "arbol-trunk/trivial", "4", rootContracts=[2], status="withdrawn",
                     withdrawn={"at": "2026-10-26T10:00:00.000Z", "reason": "private"})
        build_record(paths, "arbol-trunk/trivial", "5", rootContracts=[2], status="failed")
        refused()
        build_record(paths, "arbol-trunk/trivial", "6", rootContracts=[2])
        result = roots_command(paths, "ready", "sapling")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "working")
        self.assertEqual(json.loads(result.stdout)["rootContract"], 2)

    def test_roots_ready_and_fail_reread_current_preserve_identity_and_clear_an_old_failure(self) -> None:
        """roots.states: preparing/failed Roots are never current, and readiness restores the same identity."""
        paths = database_fixture(self)
        build_record(paths, "arbol-trunk/trivial", "1", rootContracts=[1])
        first = roots_command(paths, "create", "sapling", "--name", "First")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(roots_command(paths, "ready", "sapling").returncode, 0)
        second = roots_command(paths, "create", "second", "--name", "Second", "--from", "sapling")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        original = json.loads(second.stdout)
        self.assertEqual(json.loads(roots_command(paths, "show").stdout)["root"], "sapling")
        invalid = roots_command(paths, "fail", "second", "--reason", "not working yet")
        self.assertEqual(invalid.returncode, 1)
        self.assertEqual(json.loads(invalid.stdout)["error"]["code"], "invalid_input")
        self.assertEqual(roots_command(paths, "ready", "second").returncode, 0)
        self.assertEqual(json.loads(roots_command(paths, "show").stdout)["root"], "second")
        failed = roots_command(paths, "fail", "second", "--reason", "private failure")
        self.assertEqual(failed.returncode, 0, failed.stdout + failed.stderr)
        self.assertEqual(json.loads(failed.stdout)["failed"]["reason"], "private failure")
        self.assertEqual(json.loads(roots_command(paths, "show").stdout)["root"], "sapling")
        for key in ("root", "database", "app", "grewFrom", "rootContract", "createdAt"):
            self.assertEqual(json.loads(failed.stdout)[key], original[key])
        restored = roots_command(paths, "ready", "second")
        self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
        self.assertNotIn("failed", json.loads(restored.stdout))
        self.assertEqual(json.loads(restored.stdout)["createdAt"], original["createdAt"])
        self.assertEqual(json.loads(roots_command(paths, "show").stdout)["root"], "second")
        again = roots_command(paths, "ready", "second")
        self.assertEqual(json.loads(again.stdout), json.loads(restored.stdout))
        self.assertEqual(roots_command(paths, "fail", "second", "--reason", " ").returncode, 1)

    def test_roots_state_command_uses_the_catalogue_lock_and_changes_nothing_while_busy(self) -> None:
        """roots.state-busy: the CLI mutation shares the same lock as create/remove and current selection."""
        paths = database_fixture(self)
        made = roots_command(paths, "create", "sapling", "--name", "First")
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
        before = (paths.roots / "sapling/root.json").read_bytes()
        with catalogue_lock(paths):
            result = roots_command(paths, "ready", "sapling")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "busy")
        self.assertEqual((paths.roots / "sapling/root.json").read_bytes(), before)

    def test_roots_create_from_records_lineage_inherits_or_overrides_contract_and_copies_settings_once(self) -> None:
        """roots.create-from: source settings stay independent, opaque and unchanged, and no migration runs."""
        paths = database_fixture(self)
        first = roots_command(paths, "create", "sapling", "--name", "First", "--root-contract", "2")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = paths.settings / "sapling"
        (source / "arbol.json").write_text('{"brain":"private recipe"}\n')
        (source / "nested").mkdir()
        (source / "nested/opaque").write_bytes(b"opaque\x00settings")
        (source / "linked").symlink_to("arbol.json")
        before = (paths.roots / "sapling/root.json").read_bytes()
        second = roots_command(paths, "create", "second", "--name", "Second", "--from", "sapling")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        value = json.loads(second.stdout)
        self.assertEqual((value["grewFrom"], value["rootContract"], value["status"]), ("sapling", 2, "preparing"))
        target = paths.settings / "second"
        self.assertEqual((target / "arbol.json").read_bytes(), (source / "arbol.json").read_bytes())
        self.assertEqual((target / "nested/opaque").read_bytes(), b"opaque\x00settings")
        self.assertTrue((target / "linked").is_symlink())
        (source / "arbol.json").write_text("source changed later")
        self.assertEqual((target / "arbol.json").read_text(), '{"brain":"private recipe"}\n')
        self.assertEqual((paths.roots / "sapling/root.json").read_bytes(), before)
        third = roots_command(paths, "create", "third", "--name", "Third", "--from", "sapling",
                              "--root-contract", "1")
        self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
        self.assertEqual(json.loads(third.stdout)["rootContract"], 1)
        calls = [json.loads(line) for line in (paths.home / "calls.jsonl").read_text().splitlines()]
        self.assertTrue(all(row["args"][-1].startswith("CREATE DATABASE ") for row in calls if row["kind"] == "psql"))

    def test_roots_create_from_refuses_an_unknown_source_and_rolls_back_a_failed_settings_copy(self) -> None:
        """roots.create-from-failure: missing sources and copying failures cannot damage the source or target."""
        paths = database_fixture(self)
        missing = roots_command(paths, "create", "second", "--name", "Second", "--from", "missing")
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)["error"]["code"], "unknown_root")
        self.assertFalse((paths.roots / "second").exists())
        self.assertFalse((paths.home / "calls.jsonl").exists())
        first = roots_command(paths, "create", "sapling", "--name", "First")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        source = paths.settings / "sapling/arbol.json"
        source.write_text("source settings")
        with mock.patch("arbol_roots.operations.shutil.copytree", side_effect=PermissionError("private copy failure")):
            with self.assertRaisesRegex(PermissionError, "private copy failure"):
                create(paths, "second", {"--name": "Second", "--from": "sapling"})
        self.assertEqual(source.read_text(), "source settings")
        self.assertFalse((paths.roots / "second").exists())
        self.assertFalse((paths.settings / "second").exists())
        self.assertEqual((paths.home / "calls.jsonl").read_text().count('"kind": "psql"'), 1)

    def test_roots_create_writes_a_complete_preparing_record_settings_and_only_an_empty_database_command(self) -> None:
        """roots.create: private paths, App bootstrap, explicit version and App selection, with no Root script."""
        paths = database_fixture(self)
        first = roots_command(paths, "create", "sapling", "--name", "First Sapling")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        value = json.loads(first.stdout)
        expected = {**record(), "name": "First Sapling"}
        expected.pop("createdAt")
        self.assertEqual({key: item for key, item in value.items() if key != "createdAt"}, expected)
        self.assertEqual(value["name"], "First Sapling")
        self.assertTrue((paths.settings / "sapling").is_dir())
        self.assertEqual(set(p.name for p in (paths.roots / "sapling").iterdir()), {"root.json"})
        self.assertEqual(json.loads((paths.roots / "sapling/root.json").read_text()), value)
        build_record(paths, "arbol-app", "a")
        build_record(paths, "arbol-app", "b")
        (paths.registry / "arbol-app/b/program").unlink()
        second = roots_command(paths, "create", "second", "--name", "Second", "--root-contract", "2",
                               "--database-name", 'private"database')
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        value = json.loads(second.stdout)
        self.assertEqual((value["rootContract"], value["app"], value["database"]), (2, "a", 'private"database'))
        calls = [json.loads(line) for line in (paths.home / "calls.jsonl").read_text().splitlines()]
        commands = [row["args"][-1] for row in calls if row["kind"] == "psql"]
        self.assertEqual(len(commands), 2)
        self.assertTrue(all(command.startswith("CREATE DATABASE ") for command in commands))
        self.assertFalse(Path(paths.home, "Library").exists())
        self.assertFalse(Path(paths.home, ".arbol").exists())

    def test_roots_create_refuses_invalid_existing_or_claimed_targets_and_preserves_previous_state(self) -> None:
        """roots.create-refusal: input and target failures make no Root or database and overwrite nothing."""
        paths = database_fixture(self)
        for args in (("create", "sapling"), ("create", "sapling", "--name", " "),
                     ("create", "../sapling", "--name", "x"),
                     ("create", "sapling", "--name", "x", "--root-contract", "0"),
                     ("create", "sapling", "--name", "x", "--root-contract", "1.5"),
                     ("create", "sapling", "--name", "x", "--database-name", "postgres")):
            result = roots_command(paths, *args)
            self.assertEqual(result.returncode, 1, args)
            self.assertEqual(json.loads(result.stdout)["error"]["code"], "invalid_input", args)
            self.assertFalse((paths.roots / "sapling").exists())
            self.assertFalse((paths.home / "calls.jsonl").exists())
        first = roots_command(paths, "create", "sapling", "--name", "First")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        before = (paths.roots / "sapling/root.json").read_bytes()
        for args in (("create", "sapling", "--name", "replacement"),
                     ("create", "second", "--name", "x", "--database-name", "arbol_sapling")):
            result = roots_command(paths, *args)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["error"]["code"], "already_exists")
        self.assertEqual((paths.roots / "sapling/root.json").read_bytes(), before)
        self.assertFalse((paths.roots / "second").exists())
        self.assertEqual((paths.home / "calls.jsonl").read_text().count('"kind": "psql"'), 1)

    def test_roots_create_database_failure_leaves_no_published_or_half_created_root(self) -> None:
        """roots.create-failure: a confirmed SQL refusal removes only this attempt's unpublished folders."""
        paths = database_fixture(self)
        (paths.home / "psql.json").write_text(json.dumps({"status": 3, "stderr": "private database refusal"}))
        result = roots_command(paths, "create", "sapling", "--name", "First")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "database_unavailable")
        self.assertFalse((paths.roots / "sapling").exists())
        self.assertFalse((paths.settings / "sapling").exists())


class DatabaseAccess(unittest.TestCase):
    def fixture(self) -> Places:
        return database_fixture(self)

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
