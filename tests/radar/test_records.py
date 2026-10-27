"""Subscriptions Vigor: the Drivers' reports and the records in the Root's database, on a database of the check's own.

The database is made as `tests/backend/support.py` makes one, with the contract's chat tables, and gets the Vigor
tables from `tests/radar/layout.sql`, a copy of what both Roots' own layouts carry (SGM-1.10, SGM-D22, SGM-D29).
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from backend.support import PG, Cluster, Frame  # noqa: E402

from arbol_backend.database import Database  # noqa: E402
from arbol_backend.model import identity, parse  # noqa: E402

LAYOUT = ROOT / "tests/radar/layout.sql"
MERGED = Path.home() / "repos/sylvan-stack/readonly/arbol-root"
TABLES = ("vigor_profiles", "vigor_reports", "vigor_results")


class LayoutCopy(unittest.TestCase):
    """The check's copy of the Vigor tables' SQL is what both Roots' own layouts carry, appended after the backend's."""

    def test_the_copy_is_the_tail_of_both_root_layouts(self) -> None:
        """radar.layout-copy"""
        text = LAYOUT.read_text(encoding="utf-8")
        for table in TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table} (", text)
            self.assertIn(f"COMMENT ON TABLE {table} IS", text)
        self.assertIn("not copied when the Root changes (SGM-D29)", text)
        layouts = {root: MERGED / "roots" / root / "layout.sql" for root in ("sapling", "jensen")}
        if not all(path.is_file() and "vigor_reports" in path.read_text(encoding="utf-8") for path in layouts.values()):
            self.skipTest("the merged Root layouts in readonly/arbol-root do not carry the Vigor tables yet")
        for root, path in layouts.items():
            with self.subTest(root=root):
                layout = path.read_text(encoding="utf-8")
                self.assertTrue(layout.endswith("\n" + text), f"the {root} layout does not end with the copy")
                self.assertLess(layout.index("exchange_notes"), layout.index("vigor_profiles"))


class RecordFixture(unittest.IsolatedAsyncioTestCase):
    """A private cluster with the chat tables and the Vigor tables, a private Root folder and stand-in launchers."""

    cluster: Cluster

    @classmethod
    def setUpClass(cls) -> None:
        cls.cluster = Cluster()
        try:
            subprocess.run(
                [
                    str(PG / "psql"),
                    "-X",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-h",
                    str(cls.cluster.socket),
                    "-p",
                    "5432",
                    "-U",
                    "bkd",
                    "-d",
                    "arbol_test",
                ],
                input=LAYOUT.read_bytes(),
                capture_output=True,
                check=True,
                timeout=10,
            )
        except BaseException:
            cls.cluster.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.cluster.close()

    async def asyncSetUp(self) -> None:
        self.frame = Frame()
        self.selected = identity(ROOT, parse(self.frame.options(self.cluster.address)), home=self.frame.home)
        self.db = Database(self.selected)
        await self.db.execute("TRUNCATE vigor_results, vigor_reports, vigor_profiles")

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.frame.close()

    async def count(self, table: str) -> int:
        rows = await self.db.execute(f"SELECT count(*) FROM {table}")
        return int(rows[0][0])


class TheDatabase(RecordFixture):
    async def test_the_check_database_has_the_three_tables_empty(self) -> None:
        """radar.layout-database"""
        for table in TABLES:
            self.assertEqual(await self.count(table), 0)


if __name__ == "__main__":
    unittest.main()
