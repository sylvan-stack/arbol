"""The recompute tick of Subscriptions Vigor (SGM-1.14, SGM-D30), on a database of the check's own with stand-in Drivers.

Every three minutes while the backend runs: every Driver listed, every newer report recorded, every Subscription
recalculated and recorded, a passed reset taking effect at that tick and never earlier, no faster schedule, and a Root
without the tables left alone. Vigor stays advisory: nothing of the package writes a route, a binding or a request file.
"""

from __future__ import annotations

import ast
import asyncio
import re
import subprocess
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.model import Refused  # noqa: E402
from arbol_backend.process import Programs  # noqa: E402
from arbol_radar.cli import USAGE  # noqa: E402
from arbol_radar.drivers import LIST  # noqa: E402
from arbol_radar.model import FIRST_PROFILE, Profile, Rejected, Weight  # noqa: E402
from arbol_radar.tick import Tick, Ticker, tick  # noqa: E402
from radar.fixture import LAYOUT, LISTING, RecordFixture, drivers, record, usage  # noqa: E402
from radar.support import CLAUDE, CODEX, KIMI, MONDAY, ZAI, at, claude  # noqa: E402


def listing(**replies: dict[str, Any]) -> dict[str, Any]:
    """The stand-in Drivers' `list` replies: the worked examples' listing, with a Driver's reply replaced."""
    return {name: {"list": replies.get(name, config)} for name, config in LISTING.items()}


class Clock:
    """An injected clock: the moments the ticker reads, one per wake."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class TheTick(RecordFixture):
    """One tick: list, record what is newer, recalculate every Subscription (SGM-1.14)."""

    def programs(self, behavior: dict[str, Any]) -> Programs:
        drivers(self.frame, behavior)
        return Programs(self.selected)

    def commands(self) -> list[list[str]]:
        return [call["args"] for call in self.frame.calls()]

    async def test_a_tick_records_the_newer_reports_and_recalculates_every_subscription(self) -> None:
        """radar.tick-records"""
        programs = self.programs(listing())
        done = await tick(programs, self.records, FIRST_PROFILE, MONDAY)
        self.assertEqual(done.moment, MONDAY)
        self.assertEqual([report.subscription for report in done.reports], [CLAUDE, CODEX, KIMI])
        self.assertEqual([result.subscription for result in done.results], [CLAUDE, CODEX, KIMI, ZAI])
        self.assertEqual(dict(done.failures), {})
        self.assertEqual(self.commands(), [LIST] * 3)  # `list` and nothing else: no vendor
        self.assertEqual((await self.count("vigor_reports"), await self.count("vigor_results")), (3, 4))
        self.assertEqual(await self.records.last_result(ZAI), done.results[3])
        self.assertEqual((done.results[3].vigor, done.results[3].unknown), (None, "no report yet"))
        again = await tick(programs, self.records, FIRST_PROFILE, MONDAY + timedelta(minutes=3))
        self.assertEqual(again.reports, ())  # nothing newer arrived: no report recorded again
        self.assertEqual((await self.count("vigor_reports"), await self.count("vigor_results")), (3, 8))
        self.assertEqual([result.moment for result in again.results], [MONDAY + timedelta(minutes=3)] * 4)

    async def test_a_new_report_takes_effect_at_the_next_tick(self) -> None:
        """radar.tick-new-report"""
        programs = self.programs(listing())
        first = await tick(programs, self.records, FIRST_PROFILE, MONDAY)
        newer = usage(claude(60, 30), fetched=at(hours=1), extra={"isUsingOverage": False})  # a run moved the numbers
        drivers(self.frame, listing(**{"arbol-claude-driver": {"output": [record(CLAUDE, newer)]}}))
        second = await tick(programs, self.records, FIRST_PROFILE, MONDAY + timedelta(hours=1))
        self.assertEqual([report.subscription for report in second.reports], [CLAUDE])
        self.assertNotEqual(second.results[0].report, first.results[0].report)
        self.assertEqual(second.results[0].report, second.reports[0].id)
        self.assertEqual([entry.used_percent for entry in second.results[0].windows], [60.0, 30.0])
        self.assertEqual(await self.count("vigor_reports"), 4)

    async def test_a_passed_reset_takes_effect_at_the_next_tick_and_never_earlier(self) -> None:
        """radar.tick-passed-reset"""
        programs = self.programs(listing())
        await tick(programs, self.records, FIRST_PROFILE, MONDAY)
        before = await tick(programs, self.records, FIRST_PROFILE, MONDAY + timedelta(hours=3, minutes=19))
        self.assertFalse(before.results[0].predicted)  # 13:19: the five-hour window has a minute left
        self.assertEqual(before.results[0].windows[0].used_percent, 35.0)
        after = await tick(programs, self.records, FIRST_PROFILE, MONDAY + timedelta(hours=3, minutes=21))
        self.assertTrue(after.results[0].predicted and after.results[0].windows[0].predicted)  # 13:21: reset passed
        self.assertEqual(after.results[0].windows[0].used_percent, 0.0)
        self.assertEqual(after.results[0].windows[0].resets_at, MONDAY + timedelta(hours=8, minutes=20))
        assert after.results[0].vigor is not None
        self.assertEqual(round(after.results[0].vigor, 2), 0.39)  # the worked example's value at 13:20
        self.assertEqual(await self.records.last_result(CLAUDE), after.results[0])

    async def test_the_ticker_ticks_every_three_minutes_and_no_faster(self) -> None:
        """radar.tick-interval"""
        programs = self.programs(listing())
        clock = Clock(MONDAY)
        ticker = Ticker(programs, self.records, clock=clock)
        self.assertEqual(ticker.interval, timedelta(minutes=3))  # the profile's value (SGM-D30)
        self.assertEqual(FIRST_PROFILE.tick_minutes, 3.0)
        first = await ticker.wake()  # the first wake ticks at once
        assert first is not None
        self.assertEqual(first.moment, MONDAY)
        for seconds in (4, 60, 120, 179):
            clock.now = MONDAY + timedelta(seconds=seconds)
            self.assertIsNone(await ticker.wake())  # within the interval: nothing
        clock.now = MONDAY + timedelta(minutes=3)
        second = await ticker.wake()
        assert second is not None
        self.assertEqual(second.moment, MONDAY + timedelta(minutes=3))
        clock.now = MONDAY + timedelta(minutes=3, seconds=4)
        self.assertIsNone(await ticker.wake())
        self.assertEqual(await self.count("vigor_results"), 8)
        self.assertEqual(self.commands(), [LIST] * 6)  # two ticks, three Drivers each, nothing else
        slower = Profile(1, "proposed", "even", Weight(0.1), tick_minutes=5)
        self.assertEqual(Ticker(programs, self.records, slower).interval, timedelta(minutes=5))
        for bad in (0, -3, float("inf")):
            with self.assertRaises(Rejected) as caught:
                Profile(1, "proposed", "even", Weight(0.1), tick_minutes=bad)
            self.assertEqual(caught.exception.field, "tickMinutes")

    async def test_a_database_without_the_tables_refuses_and_is_tried_again_one_interval_later(self) -> None:
        """radar.tick-layout-incomplete"""
        programs = self.programs(listing())
        clock = Clock(MONDAY)
        ticker = Ticker(programs, self.records, clock=clock)
        await self.db.execute("DROP TABLE vigor_results")
        try:
            with self.assertRaises(Refused) as caught:
                await ticker.wake()
            self.assertEqual(caught.exception.code, "layout_incomplete")
            self.assertEqual(self.commands(), [])  # no Driver was run
            clock.now = MONDAY + timedelta(minutes=1)
            self.assertIsNone(await ticker.wake())  # not tried again sooner
        finally:
            await self.db.execute(LAYOUT.read_text(encoding="utf-8"))
        clock.now = MONDAY + timedelta(minutes=3)
        done = await ticker.wake()
        assert done is not None
        self.assertEqual(len(done.results), 4)

    async def test_a_failing_driver_or_report_is_named_and_the_others_go_on(self) -> None:
        """radar.tick-failure"""
        bad = {"outcome": "ok", "fetchedAt": at(), "windows": "x"}  # rejected by the Interface
        replies: dict[str, dict[str, Any]] = {
            "arbol-codex-driver": {"status": 1},
            "arbol-claude-driver": {"output": [record(CLAUDE, bad)]},
        }
        programs = self.programs(listing(**replies))
        done = await tick(programs, self.records, FIRST_PROFILE, MONDAY)
        self.assertEqual(set(done.failures), {"codex", "claude/anthropic"})
        self.assertTrue(done.failures["claude/anthropic"].startswith("invalid_report: "))
        self.assertEqual([result.subscription for result in done.results], [CLAUDE, KIMI, ZAI])
        self.assertEqual((done.results[0].vigor, done.results[0].unknown), (None, "no report yet"))
        self.assertEqual([report.subscription for report in done.reports], [KIMI])
        self.assertIsInstance(done, Tick)


class TheBackend(RecordFixture):
    """The backend's loop ticks while it runs: at its first wake, then every three minutes; without the tables it runs on."""

    def backend(self) -> subprocess.Popen[bytes]:
        child = self.frame.start(args=self.frame.options(self.cluster.address))
        self.assertTrue(self.frame.line(child)["ready"])
        return child

    @staticmethod
    def stop(child: subprocess.Popen[bytes]) -> None:
        assert child.stdin is not None
        child.stdin.close()  # the end of its standard input stops the backend, as the Swift App would
        child.communicate(timeout=10)

    async def test_the_running_backend_ticks_at_its_first_wake_and_not_again_within_the_interval(self) -> None:
        """radar.backend-ticks"""
        drivers(self.frame, listing())
        child = self.backend()
        try:
            for _ in range(60):  # the first wake comes four seconds after start
                if await self.count("vigor_results") >= 4:
                    break
                await asyncio.sleep(0.25)
            self.assertEqual(await self.count("vigor_results"), 4)  # one result per listed Subscription
            self.assertEqual(await self.count("vigor_reports"), 3)  # the listing's reports, recorded once
            self.assertEqual(await self.count("vigor_profiles"), 1)
            await asyncio.sleep(2)
            self.assertEqual(await self.count("vigor_results"), 4)  # no second tick within the interval
            # The backend's own account listing at startup asks `list` too (SYL-253): the tick adds `list` and nothing
            # else, and no `usage`, since a tick contacts no vendor.
            driver_calls = [call["args"] for call in self.frame.calls() if call["program"].endswith("-driver")]
            self.assertTrue(all(args == LIST for args in driver_calls))
            self.assertGreaterEqual(len(driver_calls), 3)
            self.assertIsNone(child.poll())
        finally:
            self.stop(child)
        self.assertEqual(child.returncode, 0)

    async def test_a_root_without_the_tables_leaves_the_backend_running_without_vigor(self) -> None:
        """radar.backend-layout-incomplete"""
        drivers(self.frame, listing())
        await self.db.execute("DROP TABLE vigor_results")
        try:
            child = self.backend()
            try:
                await asyncio.sleep(6)
                self.assertIsNone(child.poll())  # still running after its first wake
                self.assertEqual(await self.count("vigor_reports"), 0)  # the tick refused before listing anything
                self.assertEqual(await self.count("vigor_profiles"), 0)
            finally:
                self.stop(child)
            self.assertEqual(child.returncode, 0)
        finally:
            await self.db.execute(LAYOUT.read_text(encoding="utf-8"))


class Advisory(unittest.TestCase):
    """Nothing of `arbol_radar` writes a route, a binding or a request file, or runs anything but the two commands."""

    WRITERS = ("write_text", "write_bytes", "mkdir", "unlink", "rename", "os.open", "open(", "shutil", "tempfile")
    BACKEND_WRITERS = {
        "arbol_backend.requests",
        "arbol_backend.exchange_files",
        "arbol_backend.dispatch",
        "arbol_backend.chats",
        "arbol_backend.drafts",
        "arbol_backend.settling",
        "arbol_backend.controls",
        "arbol_backend.live",
        "arbol_backend.accounts",
    }

    def test_the_package_writes_nothing_but_its_own_tables_and_runs_nothing_but_the_two_commands(self) -> None:
        """radar.advisory-writes"""
        for path in sorted((ROOT / "src/arbol_radar").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for writer in self.WRITERS:
                self.assertNotIn(writer, text, f"{path.name} uses {writer}")
            tree = ast.parse(text, str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn(node.module, self.BACKEND_WRITERS, f"{path.name} imports {node.module}")
            for statement in re.findall(r'"(INSERT INTO|UPDATE|DELETE FROM|CREATE|ALTER|DROP)\s+(\w+)', text):
                self.assertEqual(statement[0], "INSERT INTO", f"{path.name}: {statement}")
                self.assertIn(statement[1], ("vigor_profiles", "vigor_reports", "vigor_results"))
        self.assertEqual((LIST, USAGE), (["subscriptions", "list"], ["subscriptions", "usage"]))
        for name in ("drivers.py", "cli.py", "tick.py"):
            text = (ROOT / "src/arbol_radar" / name).read_text(encoding="utf-8")
            for literal in re.findall(r'\["([a-z]+)", "([a-z]+)"', text):
                self.assertEqual(literal[0], "subscriptions")
                self.assertIn(literal[1], ("list", "usage"))
        self.assertLess(datetime(2026, 10, 27, tzinfo=UTC), datetime.now(UTC))

    def test_a_build_of_arbol_carries_the_radar_and_its_checks(self) -> None:
        """radar.packaged"""
        text = (ROOT / "scripts/package_backend.py").read_text(encoding="utf-8")
        for folder in ("src/arbol_radar", "tests/radar"):
            self.assertIn(f'root / "{folder}", folder / "{folder}"', text)  # copied into the Build as the backend is
        check = (ROOT / "scripts/check_backend.py").read_text(encoding="utf-8")
        self.assertIn('"-p", "test*.py"', check)  # the Build's unit check runs every packaged test, the radar's too


if __name__ == "__main__":
    unittest.main()
