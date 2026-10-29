# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Subscriptions Vigor: the loss of a window and the Vigor of a Subscription, with fixed reports, clock and profile (SGM-1)."""

from __future__ import annotations
import ast
from datetime import timedelta


import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_radar.model import FIRST_PROFILE, Profile, Rejected, Report, Subscription, Weight, Window  # noqa: E402
from arbol_radar.vigor import compute, loss  # noqa: E402
from radar.support import (  # noqa: E402
    CLAUDE,
    CODEX,
    KIMI,
    MONDAY,
    ZAI,
    at,
    by_label,
    claude,
    codex,
    kimi,
    report,
    window,
)

from arbol_radar.model import Rejected  # noqa: E402


class Records(unittest.TestCase):
    """The records of the Interface, the used-share rules and what the Interface rejects."""

    def rejected(self, field: str, call: Any, *args: Any, **kwargs: Any) -> None:
        with self.assertRaises(Rejected) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.field, field)


class WindowsThatTakePart(unittest.TestCase):
    """Which windows take part in the sum, the store and the gates (SGM-1.2, SGM-D24, SGM-D25)."""


class LossOfAWindow(unittest.TestCase):
    """The loss of one window at its even pace (SGM-1.3)."""


class WorkedExamples(unittest.TestCase):
    """The chapter's worked examples: Claude 0.37, Codex 0.16, Kimi Code 0.47, and 0.39 at 13:20 (SGM-1.1, SGM-1.4)."""


class Weights(unittest.TestCase):
    """The weights and the capped sum (SGM-1.4, SGM-D15)."""


class ExhaustedSubscriptions(unittest.TestCase):
    """The exhausted state (SGM-1.5, SGM-D27); the recovery is computed on predicted windows and is not here."""


class Advisory(unittest.TestCase):
    """Vigor is advisory: the package runs no program, reads no Driver and writes no file (SGM-1.15)."""

    ALLOWED_IMPORTS = {
        "__future__",
        "collections.abc",
        "dataclasses",
        "datetime",
        "math",
        "typing",
        "arbol_radar.model",
    }
    FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "print"}

    # The two modules that reach outside the calculation, each pinned to its one reach (SYL-297): the Drivers through
    # the backend's launcher calls, and the records through the backend's bounded database connection.
    REACHES = {
        "drivers.py": {"arbol_backend.model", "arbol_backend.process"},
        "records.py": {
            "arbol_backend.database",
            "arbol_backend.model",
            "psycopg.types.json",
            "arbol_radar.vigor",
            "uuid",
        },
        # The rollup (SYL-298) reaches the records only for the shape of a loss row in the JSON answer; the command
        # line `arbol vigor` reaches the launchers, the database and standard output, and nothing else.
        "rollup.py": {"arbol_radar.records"},
        "cli.py": {
            "json",
            "arbol_backend.database",
            "arbol_backend.model",
            "arbol_backend.process",
            "arbol_radar.drivers",
            "arbol_radar.learning",
            "arbol_radar.records",
            "arbol_radar.rollup",
            "arbol_radar.tick",
            "arbol_radar.vigor",
        },
        # The tick reaches the Drivers' listing and the records, and nothing else.
        "tick.py": {"arbol_backend.process", "arbol_radar.drivers", "arbol_radar.records"},
        # The learner (SYL-299) reaches the records and the Root's chat tables through the bounded connection.
        "learning.py": {
            "arbol_backend.database",
            "arbol_radar.records",
            "arbol_radar.vigor",
            "itertools",
            "statistics",
        },
    }
    PRINTS = {"cli.py"}  # the one module that answers on standard output


# Archived complete imports; restore needed names in their original scope, not at this file tail.

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/radar/test_vigor.py::Records.test_the_records_are_frozen
# Reason: Tests standard dataclass frozen assignment behavior with no product-specific edge.
# Source: arbol@2ba18277c3ab444eaf0242fdf761e8912ce3909a:tests/radar/test_vigor.py
# Retained evidence at review: Record validation and computed window/profile behavior remain.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_the_records_are_frozen(self) -> None:
#         """radar.records-frozen"""
#         r = report(CLAUDE, claude())
#         with self.assertRaises(FrozenInstanceError):
#             r.windows[0].used_percent = 1.0  # type: ignore[misc]
#         with self.assertRaises(FrozenInstanceError):
#             FIRST_PROFILE.placeholder = Weight(0.2)  # type: ignore[misc]
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/radar/test_vigor.py::Advisory.test_the_same_inputs_give_the_same_result_and_change_nothing
# Reason: The before value aliases the inputs, so input mutation passes; the earlier controlled review demonstrated this. The remaining checks just repeat a pure calculation and dataclass freezing.
# Source: arbol@2ba18277c3ab444eaf0242fdf761e8912ce3909a:tests/radar/test_vigor.py
# Retained evidence at review: Independent expected vigor/weight/boundary calculations remain; this removal does not claim input immutability is proven.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_the_same_inputs_give_the_same_result_and_change_nothing(self) -> None:
#         """radar.advisory-pure"""
#         r = report(CLAUDE, claude(), extra={"isUsingOverage": False})
#         before = (r, FIRST_PROFILE)
#         first = compute(r, FIRST_PROFILE, MONDAY)
#         second = compute(r, FIRST_PROFILE, MONDAY)
#         self.assertEqual(first, second)
#         self.assertEqual(before, (r, FIRST_PROFILE))
#         with self.assertRaises(FrozenInstanceError):
#             first.vigor = 1.0  # type: ignore[misc]
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/radar/test_vigor.py::Records.test_the_first_profile
# Reason: Copies every field of the FIRST_PROFILE constant and its default lookup.
# Source: arbol@2ba18277c3ab444eaf0242fdf761e8912ce3909a:tests/radar/test_vigor.py
# Retained evidence at review: Worked examples and learned-profile tests exercise the profile through actual calculations.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_the_first_profile(self) -> None:
#         """radar.first-profile"""
#         self.assertEqual(FIRST_PROFILE.version, 1)
#         self.assertEqual(FIRST_PROFILE.approval, "proposed")
#         self.assertEqual(FIRST_PROFILE.pace, "even")
#         self.assertEqual(FIRST_PROFILE.placeholder, Weight(0.1, "placeholder"))
#         self.assertEqual(dict(FIRST_PROFILE.gates), {})
#         self.assertEqual(FIRST_PROFILE.stale_rule, "shortest-window")
#         self.assertEqual(FIRST_PROFILE.store_weight, 1.0)
#         self.assertEqual(FIRST_PROFILE.gate_weight("chatgpt", "5-hour window"), Weight(0.1, "placeholder"))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/radar/test_vigor.py::Records.test_a_report_is_read_as_delivered
# Reason: Long ordinary field projection from a fixed delivered report into dataclasses; substantive clamping, missing fields, invalid dates and resource interpretation have dedicated cases.
# Source: arbol@2ba18277c3ab444eaf0242fdf761e8912ce3909a:tests/radar/test_vigor.py
# Retained evidence at review: Records boundary cases and WindowsThatTakePart/WorkedExamples remain.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_a_report_is_read_as_delivered(self) -> None:
#         """radar.report-as-delivered"""
#         r = Report.from_contract(
#             CLAUDE,
#             {
#                 "outcome": "ok",
#                 "fetchedAt": "2026-10-26T09:55:00Z",
#                 "windows": claude(),
#                 "extra": {"isUsingOverage": False},
#             },
#             report_id="r7",
#             arrived_at=MONDAY,
#             run="run-1",
#         )
#         self.assertEqual(
#             (r.id, r.subscription, r.outcome, r.arrived_at, r.run, r.message),
#             ("r7", CLAUDE, "ok", MONDAY, "run-1", None),
#         )
#         self.assertEqual(r.fetched_at, datetime(2026, 10, 26, 9, 55, tzinfo=UTC))
#         self.assertEqual(r.delivered, tuple(claude()))
#         self.assertEqual(r.extra, {"isUsingOverage": False})
#         self.assertFalse(r.overage)
#         five = r.windows[0]
#         self.assertEqual(
#             (five.kind, five.label, five.resource, five.used_percent), ("session", "Five hours", "tokens", 35.0)
#         )
#         self.assertEqual(
#             (five.resets_at, five.window_minutes, five.limit_reached),
#             (MONDAY + timedelta(hours=3, minutes=20), 300.0, False),
#         )
#         self.assertEqual(
#             (five.scope, five.predicted, five.report, five.raw_used_percent, five.unknown),
#             ("subscription", False, "r7", None, None),
#         )
#         self.assertTrue(five.known)
#         kimi_report = report(KIMI, kimi())
#         self.assertEqual([w.scope for w in kimi_report.windows], ["subscription", "product", "subscription"])
#         absent = report(CODEX, codex()).windows[0]
#         self.assertEqual((absent.resource, absent.used_percent, absent.limit_reached), (None, 50.0, False))
#         unsupported = report(ZAI, [], outcome="unsupported", message="no allowance reading")
#         self.assertEqual((unsupported.windows, unsupported.message), ((), "no allowance reading"))
# LOW-TIER-SOURCE-END
# LOW-TIER-END
