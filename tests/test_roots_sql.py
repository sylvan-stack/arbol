"""Runtime SQL selection and application use only private records and stand-ins."""

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_roots  # noqa: E402

from arbol_builds.launcher import open_use_guard  # noqa: E402
from arbol_roots.database import Database, DatabaseError  # noqa: E402
from arbol_roots.model import Places, Refused, save_record  # noqa: E402
from arbol_roots.sql import databases, layout, selected_sql  # noqa: E402


def image(paths: Places, number: str = "1", root: str = "sapling", older: str | None = None,
          **changes: Any) -> Path:
    test_roots.build_record(paths, "arbol-root", number, root=root, **changes)
    folder = paths.registry / "arbol-root" / number
    (folder / "layout").mkdir()
    for name in ["chat-tables.sql", "root-tables.sql", *(["migrate.sql"] if older else [])]:
        (folder / "layout" / name).write_text("-- private SQL fixture\n")
    manifest = {"component":"arbol-root", "root":root, "build":number,
                "layout":{"root":root,"rootContract":1,"grewFrom":older},
                "files":{str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (folder / "layout").iterdir()}}
    (folder / "package-manifest.json").write_text(json.dumps(manifest))
    return folder


class Selection(unittest.TestCase):
    def setUp(self) -> None:
        self.paths = test_roots.database_fixture(self)
        self.record = test_roots.record()
        (self.paths.roots / "sapling").mkdir(parents=True)
        save_record(self.paths, self.record)

    def test_newest_working_same_root_with_sql_is_selected_and_guarded(self) -> None:
        """roots.sql-selection"""
        image(self.paths)
        image(self.paths, "2")
        image(self.paths, "3", status="withdrawn")
        image(self.paths, "4", root="other")
        image(self.paths, "5", prunedAt="2026-10-26T20:00:00.000Z")
        image(self.paths, "6").joinpath("layout").rename(self.paths.home / "absent-sql")
        with selected_sql(self.paths, self.record, migration=False) as build:
            self.assertEqual(build.number, "2")
            self.assertEqual(list(build.files), ["chat-tables.sql", "root-tables.sql"])
            with self.assertRaises(BlockingIOError):
                open_use_guard(str(self.paths.registry), "arbol-root", "2", exclusive=True)

    def test_damaged_selected_files_or_manifest_fail_without_older_fallback(self) -> None:
        """roots.sql-preflight"""
        image(self.paths)
        folder = image(self.paths, "2")
        file = folder / "layout/root-tables.sql"
        original = file.read_bytes()
        for kind in ["changed", "missing", "symlink"]:
            file.unlink(missing_ok=True)
            if kind == "changed":
                file.write_text("changed")
            elif kind == "symlink":
                file.symlink_to(folder / "layout/chat-tables.sql")
            with self.assertRaises(Refused) as caught, selected_sql(self.paths, self.record, migration=False):
                self.fail("A damaged selected file was accepted.")
            self.assertEqual(caught.exception.code, "build_unavailable")
        file.unlink()
        file.write_bytes(original)
        manifest = json.loads((folder / "package-manifest.json").read_text())
        for version in [2, True]:
            manifest["layout"]["rootContract"] = version
            (folder / "package-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(Refused), selected_sql(self.paths, self.record, migration=False):
                self.fail("Wrong contract was accepted.")

    def test_pruner_lock_refuses_and_migration_requires_its_extra_file(self) -> None:
        """roots.sql-pruning"""
        folder = image(self.paths, older="older")
        self.record["grewFrom"] = "older"
        guard = open_use_guard(str(self.paths.registry), "arbol-root", "1", exclusive=True)
        try:
            with self.assertRaises(Refused) as caught, selected_sql(self.paths, self.record, migration=True):
                self.fail("An exclusively held Build was accepted.")
            self.assertEqual(caught.exception.code, "busy")
        finally:
            os.close(guard)
        (folder / "layout/migrate.sql").unlink()
        with self.assertRaises(Refused), selected_sql(self.paths, self.record, migration=True):
            self.fail("A missing migration script was accepted.")
        with selected_sql(self.paths, self.record, migration=False):
            pass

    def test_database_aliases_and_connection_string_forms_are_refused(self) -> None:
        """roots.sql-databases"""
        other = test_roots.record("other")
        other["database"] = self.record["database"]
        (self.paths.roots / "other").mkdir()
        save_record(self.paths, other)
        with self.assertRaises(Refused):
            databases(self.paths, self.record)
        (self.paths.roots / "other/root.json").unlink()
        for name in ["dbname=elsewhere", "postgresql://elsewhere/db", "postgres://elsewhere/db", "-"]:
            with self.subTest(name=name), self.assertRaises(Refused):
                databases(self.paths, {**self.record,"database":name})
        self.assertEqual(databases(self.paths, {**self.record,"database":"私の 'database'"}),
                         ("私の 'database'", None))


class Layout(unittest.TestCase):
    def setUp(self) -> None:
        self.paths = test_roots.database_fixture(self)
        self.record = test_roots.record(state="working")
        (self.paths.roots / "sapling").mkdir(parents=True)
        save_record(self.paths, self.record)
        self.folder = image(self.paths)

    def test_layout_runs_two_transactions_minimal_environment_and_keeps_metadata(self) -> None:
        """roots.layout"""
        header = self.paths.roots / "sapling/root.json"
        before = header.read_bytes()
        with mock.patch.dict(os.environ, {"PGHOST":"outside", "PGSERVICE":"outside", "UNRELATED":"private"}):
            with mock.patch("arbol_roots.database.subprocess.run", wraps=subprocess.run) as calls:
                reply = layout(self.paths, "sapling")
        self.assertEqual(reply, {"root":"sapling", "rootBuild":"1", "files":["chat-tables.sql","root-tables.sql"]})
        self.assertEqual(header.read_bytes(), before)
        self.assertEqual(len(calls.call_args_list), 3)
        for called, name in zip(calls.call_args_list[1:], reply["files"], strict=True):
            args = called.args[0]
            self.assertEqual(args[args.index("--file")+1], str((self.folder / "layout" / name).resolve()))
            self.assertEqual(args[-1], "postgresql://arbol@127.0.0.1:5433/arbol_sapling")
            for arg in ["--no-psqlrc", "--no-password", "ON_ERROR_STOP=1", "--single-transaction"]:
                self.assertIn(arg, args)
            self.assertEqual(set(called.kwargs["env"]), {"HOME","PATH","LANG","PGPASSWORD"})
            self.assertEqual(called.kwargs["timeout"], 60)
            self.assertNotIn("private-test-password", str(args))

    def test_sql_error_statuses_name_failure_redact_password_and_stop_immediately(self) -> None:
        """roots.sql-failure"""
        for status in [1, 2, 3]:
            with self.subTest(status=status):
                (self.paths.home / "calls.jsonl").unlink(missing_ok=True)
                (self.paths.home / "psql.json").write_text(json.dumps({
                    "status":status, "stderr":"psql:root-tables.sql:35: ERROR: private-test-password broken SQL"}))
                with self.assertRaises(DatabaseError) as error:
                    layout(self.paths, "sapling")
                self.assertIn(f"status {status}", str(error.exception))
                self.assertIn("root-tables.sql:35", str(error.exception))
                self.assertIn("[password removed]", str(error.exception))
                self.assertNotIn("private-test-password", str(error.exception))
                self.assertEqual((self.paths.home / "calls.jsonl").read_text().count('"kind": "psql"'), 1)

    def test_preparing_missing_tool_or_damaged_sql_runs_no_psql(self) -> None:
        """roots.layout-refusal"""
        before = (self.paths.roots / "sapling/root.json").read_bytes()
        for state in ["preparing", "working"]:
            save_record(self.paths, {**self.record,"status":state})
            with mock.patch("arbol_roots.sql.shutil.which", return_value=None):
                with self.assertRaises(Refused):
                    layout(self.paths, "sapling")
        (self.folder / "layout/root-tables.sql").unlink()
        with self.assertRaises(Refused):
            layout(self.paths, "sapling")
        self.assertFalse((self.paths.home / "calls.jsonl").exists())
        self.assertEqual((self.paths.roots / "sapling/root.json").read_bytes(), before)

    def test_layout_cli_is_json_and_needs_no_older_root_or_database(self) -> None:
        """roots.layout-cli"""
        self.record["grewFrom"] = "gone"
        save_record(self.paths, self.record)
        p = self.folder / "package-manifest.json"
        value = json.loads(p.read_text())
        value["layout"]["grewFrom"] = "gone"
        p.write_text(json.dumps(value))
        result = test_roots.roots_command(self.paths, "layout", "sapling")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["rootBuild"], "1")

    def test_file_timeout_is_a_bounded_uncertain_database_failure(self) -> None:
        """roots.sql-timeout"""
        database = Database(self.paths)
        with mock.patch("arbol_roots.database.subprocess.run", side_effect=subprocess.TimeoutExpired("psql", 60)):
            with self.assertRaisesRegex(DatabaseError, "60 seconds") as error:
                database.file("arbol_sapling", self.folder / "layout/chat-tables.sql")
        self.assertTrue(error.exception.uncertain)
