# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Subscriptions Vigor: the Drivers' reports and the records in the Root's database, on a database of the check's own.

The database is made as `tests/backend/support.py` makes one, with the contract's chat tables, and gets the Vigor
tables from `tests/radar/layout.sql`, a copy of what both Roots' own layouts carry (SGM-1.10, SGM-D22, SGM-D29).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.process import Programs  # noqa: E402
from radar.fixture import RecordFixture  # noqa: E402

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
