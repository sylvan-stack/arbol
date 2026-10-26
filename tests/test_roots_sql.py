"""Runtime SQL selection and application use only private records and stand-ins."""

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_roots  # noqa: E402

from arbol_builds.launcher import open_use_guard  # noqa: E402
from arbol_roots.model import Places, Refused, save_record  # noqa: E402
from arbol_roots.sql import databases, selected_sql  # noqa: E402


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
