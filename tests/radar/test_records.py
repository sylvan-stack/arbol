# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Subscriptions Vigor: the Drivers' reports and the records in the Root's database, on a database of the check's own.

The database is made as `tests/backend/support.py` makes one, with the contract's chat tables, and gets the Vigor
tables from `tests/radar/layout.sql`, a copy of what both Roots' own layouts carry (SGM-1.10, SGM-D22, SGM-D29).
"""

from __future__ import annotations

__all__ = [
    "Any", "CLAUDE", "CODEX", "FETCHED", "FIRST_PROFILE", "KIMI", "LAYOUT", "LIST", "LISTING", "LayoutCopy",
    "Listed", "Listing", "MERGED", "MONDAY", "Path", "Profile", "Programs", "ROOT", "RecordFixture", "Refused",
    "Rejected", "TABLES", "TheDrivers", "TheRecords", "TheReplay", "Weight", "ZAI", "at", "claude", "codex",
    "drivers_of", "json", "kimi", "list_subscriptions", "loss_row", "record", "records_of", "sys", "timedelta",
    "unittest", "usage", "window",
]
import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.model import Refused  # noqa: E402
from arbol_backend.process import Programs  # noqa: E402
from arbol_radar.drivers import LIST, Listed, Listing, drivers_of, list_subscriptions, records_of  # noqa: E402
from arbol_radar.model import FIRST_PROFILE, Profile, Rejected, Weight  # noqa: E402
from arbol_radar.records import loss_row  # noqa: E402
from radar.fixture import LAYOUT, LISTING, TABLES, RecordFixture, record, usage  # noqa: E402
from radar.support import CLAUDE, CODEX, FETCHED, KIMI, MONDAY, ZAI, at, claude, codex, kimi, window  # noqa: E402

MERGED = Path.home() / "repos/sylvan-stack/readonly/arbol-root"


class LayoutCopy(unittest.TestCase):
    """The check's copy of the Vigor tables' SQL is what both Roots' own layouts carry, appended after the backend's."""


class TheDrivers(RecordFixture):
    """Every Subscription of every Driver among the launchers through `subscriptions list`, and nothing else (BKD-0.25)."""

    def listing(self, behavior: dict[str, Any]) -> Programs:
        self.frame.behavior = behavior
        self.frame.configure()
        return Programs(self.selected)


class TheRecords(RecordFixture):
    """Every report as it arrives and every calculation, recorded in the Vigor tables (SGM-1.10, SGM-D22)."""

    async def rows(self, table: str) -> list[dict[str, Any]]:
        rows = await self.db.execute(f"SELECT row_to_json(t) FROM {table} t ORDER BY row_to_json(t)::text")
        return [dict(row[0]) for row in rows]


class TheReplay(RecordFixture):
    """A named profile replayed over every recorded report of a Subscription gives the recorded results (SGM-1.14)."""


# Archived complete imports; restore needed names in their original scope, not at this file tail.

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/radar/test_records.py::TheDatabase.test_the_check_database_has_the_three_tables_empty
# Reason: Asserts only the state created by this test class fixture; adds no application action or failure case.
# Source: arbol@4c5489dac9c73d28a2fdf232403fdcfd3a2dbbd5:tests/radar/test_records.py
# Retained evidence at review: TheRecords tests exercise actual profile/report/result writes and quiet repeats.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_the_check_database_has_the_three_tables_empty(self) -> None:
#         """radar.layout-database"""
#         for table in TABLES:
#             self.assertEqual(await self.count(table), 0)
# LOW-TIER-SOURCE-END
# LOW-TIER-END
