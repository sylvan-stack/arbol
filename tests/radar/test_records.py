"""Subscriptions Vigor: the Drivers' reports and the records in the Root's database, on a database of the check's own.

The database is made as `tests/backend/support.py` makes one, with the contract's chat tables, and gets the Vigor
tables from `tests/radar/layout.sql`, a copy of what both Roots' own layouts carry (SGM-1.10, SGM-D22, SGM-D29).
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from backend.support import PG, Cluster, Frame  # noqa: E402

from arbol_backend.database import Database  # noqa: E402
from arbol_backend.model import identity, parse  # noqa: E402
from arbol_backend.process import Programs  # noqa: E402
from arbol_radar.drivers import LIST, Listed, Listing, drivers_of, list_subscriptions, records_of  # noqa: E402
from arbol_radar.model import Subscription  # noqa: E402
from radar.support import CLAUDE, CODEX, FETCHED, KIMI, ZAI, claude, codex, kimi  # noqa: E402

LAYOUT = ROOT / "tests/radar/layout.sql"
MERGED = Path.home() / "repos/sylvan-stack/readonly/arbol-root"
TABLES = ("vigor_profiles", "vigor_reports", "vigor_results")


def usage(
    windows: list[dict[str, Any]], *, fetched: str = FETCHED, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A `UsageReport` as a Driver stores it with the Subscription (DRV-1.18)."""
    value: dict[str, Any] = {"outcome": "ok", "fetchedAt": fetched, "windows": windows}
    if extra is not None:
        value["extra"] = extra
    return value


def record(subscription: Subscription, last_usage: dict[str, Any] | None = None, **more: Any) -> dict[str, Any]:
    """A Subscription record as `subscriptions list` delivers it (DRV-1, `Subscription`), never a secret."""
    value: dict[str, Any] = {
        "id": subscription.id,
        "family": subscription.family,
        "label": subscription.id.title(),
        "auth": "vendor_login",
        "state": "signed_in",
        "settings": {},
        "createdAt": "2026-10-01T00:00:00Z",
        "updatedAt": "2026-10-26T09:55:00Z",
        **more,
    }
    if last_usage is not None:
        value["lastUsage"] = last_usage
    return value


LISTING = {
    "arbol-claude-driver": {"output": [record(CLAUDE, usage(claude(), extra={"isUsingOverage": False}))]},
    "arbol-codex-driver": {"output": [record(CODEX, usage(codex()))]},
    "arbol-pi-driver": {"output": [record(KIMI, usage(kimi())), record(ZAI)]},
}


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


class TheDrivers(RecordFixture):
    """Every Subscription of every Driver among the launchers through `subscriptions list`, and nothing else (BKD-0.25)."""

    def listing(self, behavior: dict[str, Any]) -> Programs:
        self.frame.behavior = behavior
        self.frame.configure()
        return Programs(self.selected)

    async def test_every_driver_among_the_launchers_lists_its_subscriptions_with_their_last_usage(self) -> None:
        """radar.drivers-list"""
        programs = self.listing(LISTING)
        self.assertEqual(drivers_of(programs), ("claude", "codex", "pi"))
        listing = await list_subscriptions(programs)
        self.assertEqual(listing.drivers, ("claude", "codex", "pi"))
        self.assertEqual(dict(listing.failures), {})
        self.assertEqual([item.subscription for item in listing.subscriptions], [CLAUDE, CODEX, KIMI, ZAI])
        by_id = {item.subscription.id: item for item in listing.subscriptions}
        self.assertEqual(by_id["anthropic"].last_usage, usage(claude(), extra={"isUsingOverage": False}))
        self.assertEqual(by_id["kimi-coding"].last_usage, usage(kimi()))
        self.assertIsNone(by_id["zai"].last_usage)  # no report yet
        self.assertEqual(by_id["zai"].record["state"], "signed_in")  # the record as delivered
        calls = self.frame.calls()
        self.assertEqual([call["program"] for call in calls], [f"arbol-{d}-driver" for d in ("claude", "codex", "pi")])
        self.assertTrue(all(call["args"] == LIST for call in calls))  # `list` and nothing else was run
        self.assertTrue(all(call["home"] == str(self.frame.home) and call["pgOverrides"] == [] for call in calls))

    async def test_a_failing_driver_is_reported_beside_the_others(self) -> None:
        """radar.drivers-failure"""
        behavior = {
            **LISTING,
            "arbol-codex-driver": {"status": 1},  # the launcher ends without a reply
            "arbol-pi-driver": {"raw": "not json"},  # no JSON reply
        }
        listing = await list_subscriptions(self.listing(behavior))
        self.assertEqual([item.subscription for item in listing.subscriptions], [CLAUDE])
        self.assertEqual(set(listing.failures), {"codex", "pi"})
        self.assertTrue(listing.failures["codex"].startswith("no_answer: "))
        self.assertTrue(listing.failures["pi"].startswith("no_answer: "))
        shapes = {
            "arbol-claude-driver": {"output": {"id": "anthropic"}},  # not a list
            "arbol-codex-driver": {"output": [record(CODEX), {"family": "chatgpt"}]},  # a record without id
            "arbol-pi-driver": {"output": [{"id": "zai", "family": ""}]},  # an empty family
        }
        listing = await list_subscriptions(self.listing(shapes))
        self.assertEqual(listing.subscriptions, ())
        self.assertEqual(
            dict(listing.failures),
            dict.fromkeys(
                ("claude", "codex", "pi"),
                "invalid_reply: the Driver did not answer with a list of Subscription records",
            ),
        )
        self.assertEqual(len(self.frame.calls()), 6)
        self.assertIsNone(records_of("claude", "nonsense"))
        self.assertEqual(records_of("claude", []), [])
        self.assertEqual(records_of("pi", [record(ZAI)]), [Listed(ZAI, record(ZAI))])

    async def test_only_drivers_with_a_launcher_are_asked(self) -> None:
        """radar.drivers-launchers"""
        (self.frame.bin / "arbol-pi-driver").unlink()
        (self.frame.bin / "arbol-other-driver.bak").write_text("#!/bin/sh\n")  # not a launcher's name
        programs = self.listing(LISTING)
        self.assertEqual(drivers_of(programs), ("claude", "codex"))
        listing = await list_subscriptions(programs)
        self.assertEqual(listing, Listing(("claude", "codex"), listing.subscriptions, {}))
        self.assertEqual([item.subscription for item in listing.subscriptions], [CLAUDE, CODEX])
        self.assertEqual(
            {call["program"] for call in self.frame.calls()}, {"arbol-claude-driver", "arbol-codex-driver"}
        )


if __name__ == "__main__":
    unittest.main()
