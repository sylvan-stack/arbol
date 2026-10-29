# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""The recompute tick of Subscriptions Vigor (SGM-1.14, SGM-D30), on a database of the check's own with stand-in Drivers.

Every three minutes while the backend runs: every Driver listed, every newer report recorded, every Subscription
recalculated and recorded, a passed reset taking effect at that tick and never earlier, no faster schedule, and a Root
without the tables left alone. Vigor stays advisory: nothing of the package writes a route, a binding or a request file.
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timedelta


import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.model import Refused  # noqa: E402
from arbol_radar.drivers import LIST  # noqa: E402
from arbol_radar.model import FIRST_PROFILE, Profile, Rejected, Weight  # noqa: E402
from arbol_radar.tick import Tick, Ticker, tick  # noqa: E402
from radar.fixture import LAYOUT, LISTING, RecordFixture, drivers, record, usage  # noqa: E402
from radar.support import CLAUDE, CODEX, KIMI, MONDAY, ZAI, at, claude  # noqa: E402

from arbol_backend.process import Programs  # noqa: E402
from radar.fixture import LISTING, RecordFixture, drivers  # noqa: E402


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


# Archived complete imports; restore needed names in their original scope, not at this file tail.

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/radar/test_tick.py::Advisory.test_a_build_of_arbol_carries_the_radar_and_its_checks
# Reason: Matches source quote style and packaging call spelling; the earlier behavior-preserving quote change failed it.
# Source: arbol@4c5489dac9c73d28a2fdf232403fdcfd3a2dbbd5:tests/radar/test_tick.py
# Retained evidence at review: Package manifests, package construction and remaining actual Radar behavior checks remain; no packaging success is inferred here.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_a_build_of_arbol_carries_the_radar_and_its_checks(self) -> None:
#         """radar.packaged"""
#         script = ROOT / "scripts/package_backend.py"
#         if script.is_file():  # a checkout: the packaging copies both folders into the Build as it copies the backend
#             text = script.read_text(encoding="utf-8")
#             for folder in ("src/arbol_radar", "tests/radar"):
#                 self.assertIn(f'root / "{folder}", folder / "{folder}"', text)
#         else:  # a packaged Build: its manifest lists every payload file, the radar's and its checks' among them
#             manifest = json.loads((ROOT / "package-manifest.json").read_text(encoding="utf-8"))
#             files = set(manifest["files"])
#             self.assertIn("src/arbol_radar/tick.py", files)
#             self.assertIn("tests/radar/test_tick.py", files)
#             self.assertIn("tests/radar/layout.sql", files)
#         check = (ROOT / "scripts/check_backend.py").read_text(encoding="utf-8")
#         self.assertIn('"-p", "test*.py"', check)  # the Build's unit check runs every packaged test, the radar's too
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/radar/test_tick.py::Advisory.test_the_package_writes_nothing_but_its_own_tables_and_runs_nothing_but_the_two_commands
# Reason: Source substrings and a SQL regex do not observe writes/calls; includes an unrelated current-date assertion. Its import constraints overlap the retained explicit dependency audit.
# Source: arbol@4c5489dac9c73d28a2fdf232403fdcfd3a2dbbd5:tests/radar/test_tick.py
# Retained evidence at review: test_vigor.Advisory import boundary plus actual Tick/driver/records tests remain; no new runtime absence claim is made.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_the_package_writes_nothing_but_its_own_tables_and_runs_nothing_but_the_two_commands(self) -> None:
#         """radar.advisory-writes"""
#         for path in sorted((ROOT / "src/arbol_radar").glob("*.py")):
#             text = path.read_text(encoding="utf-8")
#             for writer in self.WRITERS:
#                 self.assertNotIn(writer, text, f"{path.name} uses {writer}")
#             tree = ast.parse(text, str(path))
#             for node in ast.walk(tree):
#                 if isinstance(node, ast.ImportFrom):
#                     self.assertNotIn(node.module, self.BACKEND_WRITERS, f"{path.name} imports {node.module}")
#             for statement in re.findall(r'"(INSERT INTO|UPDATE|DELETE FROM|CREATE|ALTER|DROP)\s+(\w+)', text):
#                 if statement[0] == "UPDATE":  # the owner's approval of a profile, in its row (SGM-1.11), alone
#                     self.assertEqual((path.name, statement[1]), ("records.py", "vigor_profiles"))
#                     continue
#                 self.assertEqual(statement[0], "INSERT INTO", f"{path.name}: {statement}")
#                 self.assertIn(statement[1], ("vigor_profiles", "vigor_reports", "vigor_results"))
#         self.assertEqual((LIST, USAGE), (["subscriptions", "list"], ["subscriptions", "usage"]))
#         for name in ("drivers.py", "cli.py", "tick.py"):
#             text = (ROOT / "src/arbol_radar" / name).read_text(encoding="utf-8")
#             for literal in re.findall(r'\["([a-z]+)", "([a-z]+)"', text):
#                 self.assertEqual(literal[0], "subscriptions")
#                 self.assertIn(literal[1], ("list", "usage"))
#         self.assertLess(datetime(2026, 10, 27, tzinfo=UTC), datetime.now(UTC))
# LOW-TIER-SOURCE-END
# LOW-TIER-END
