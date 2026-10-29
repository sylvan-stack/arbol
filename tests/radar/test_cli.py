# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Subscriptions Vigor on the Radar and the read `arbol vigor`: the rollup, the verb, the latest records, the refresh.

The rollup checks need no database: they take results computed from the chapter's worked examples (SGM-1.12, SGM-D18).
"""

from __future__ import annotations
import json
from datetime import UTC, datetime, timedelta


import sys
import unittest
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.model import Refused, parse  # noqa: E402
from arbol_radar.cli import Options, options, read  # noqa: E402
from arbol_radar.rollup import Entry, Rollup, as_text, rollup, when  # noqa: E402
from radar.fixture import LAYOUT, LISTING, RecordFixture, drivers, usage  # noqa: E402

from arbol_radar.model import FIRST_PROFILE, Subscription  # noqa: E402
from arbol_radar.rollup import Entry  # noqa: E402
from arbol_radar.vigor import compute  # noqa: E402
from radar.fixture import LISTING, RecordFixture, usage  # noqa: E402
from radar.support import CLAUDE, CODEX, KIMI, MONDAY, ZAI, at, claude, codex, kimi, report, window  # noqa: E402

DEEPSEEK = Subscription("pi", "deepseek", "deepseek")


def examples(*, reached: bool = False) -> list[Entry]:
    """The worked examples' three Subscriptions, an unknown fourth and a fifth without a record, out of order."""
    zai = report(ZAI, [], outcome="unsupported", message="no allowance reading for zai", report_id="r4")
    return [
        Entry(DEEPSEEK, "DeepSeek", None),
        Entry(ZAI, "z.ai Coding Plan", compute(zai, FIRST_PROFILE, MONDAY)),
        Entry(CODEX, "ChatGPT", compute(report(CODEX, codex(), report_id="r2"), FIRST_PROFILE, MONDAY)),
        Entry(
            CLAUDE,
            "Anthropic",
            compute(report(CLAUDE, claude(reached=reached), extra={"isUsingOverage": False}), FIRST_PROFILE, MONDAY),
        ),
        Entry(KIMI, "Kimi Code", compute(report(KIMI, kimi(), report_id="r3"), FIRST_PROFILE, MONDAY)),
    ]


class TheRollup(unittest.TestCase):
    """Every Subscription sorted by Vigor, unknown ones kept visible below, the headline named, never a sum (SGM-1.12)."""


class TheVerb(unittest.TestCase):
    """`arbol [--root <root>] vigor [--refresh [<driver>/<subscription>]] [--text]` beside `backend` (SGM-D28)."""


class TheRead(RecordFixture):
    """A plain read shows the latest records, recomputes nothing and contacts no vendor (SGM-1.13, SGM-D30)."""

    async def seed(self) -> None:
        """Two calculations of the Claude account, one of Kimi, one of z.ai without a report; Codex never calculated."""
        await self.records.record_report(CLAUDE, usage(claude(), extra={"isUsingOverage": False}), now=MONDAY)
        await self.records.calculate(CLAUDE, FIRST_PROFILE, MONDAY)
        await self.records.calculate(CLAUDE, FIRST_PROFILE, MONDAY + timedelta(hours=1))
        await self.records.record_report(KIMI, usage(kimi()), now=MONDAY)
        await self.records.calculate(KIMI, FIRST_PROFILE, MONDAY)
        await self.records.calculate(ZAI, FIRST_PROFILE, MONDAY)


    def answer(self, *extra: str) -> tuple[int, str, str]:
        child = self.frame.start(args=self.vigor(*extra))
        out, err = child.communicate(timeout=20)
        return child.returncode, out.decode(), err.decode()


def unsupported(fetched: str) -> dict[str, Any]:
    return {
        "outcome": "unsupported",
        "fetchedAt": fetched,
        "windows": [],
        "message": "Account allowance is not supported for this family.",
    }


def kimi_fresh() -> list[dict[str, Any]]:
    """The Kimi account two hours later: a fresh five-hour window, the month's shares a little further along."""
    return [
        window("session", "Five hours", resource="calls", used=10, resets=at(hours=6), minutes=300),
        window("other", "Monthly, Kimi Code", resource="credits", used=41, resets=at(days=4), minutes=43200),
        window("other", "Monthly, all Kimi products", resource="credits", used=56, resets=at(days=4), minutes=43200),
    ]


def refreshed(**replies: dict[str, Any]) -> dict[str, Any]:
    """The stand-in Drivers' replies: the worked examples' listing, and a fresh `usage` reply per Subscription."""
    fresh = {
        "anthropic": {"output": usage(claude(10, 22), fetched=at(hours=2), extra={"isUsingOverage": False})},
        "chatgpt": {"output": usage(codex(), fetched=at(hours=2))},
        "kimi-coding": {"output": usage(kimi_fresh(), fetched=at(hours=2))},
        "zai": {"output": unsupported(at(hours=2))},
        **replies,
    }
    return {
        "arbol-claude-driver": {"list": LISTING["arbol-claude-driver"], "usage anthropic": fresh["anthropic"]},
        "arbol-codex-driver": {"list": LISTING["arbol-codex-driver"], "usage chatgpt": fresh["chatgpt"]},
        "arbol-pi-driver": {
            "list": LISTING["arbol-pi-driver"],
            "usage kimi-coding": fresh["kimi-coding"],
            "usage zai": fresh["zai"],
        },
    }


class TheRefresh(RecordFixture):
    """`--refresh` fetches through `subscriptions usage`, records the reports and recomputes (SGM-D20, SGM-D30)."""

    def commands(self) -> list[list[str]]:
        return [call["args"] for call in self.frame.calls()]


# Archived complete imports; restore needed names in their original scope, not at this file tail.

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/radar/test_cli.py::TheRollup.test_nothing_is_summed_across_subscriptions
# Reason: Searches serialized key names for sum/total and compares a copied upper bound; neither establishes aggregation semantics beyond the retained headline/order cases.
# Source: arbol@2ba18277c3ab444eaf0242fdf761e8912ce3909a:tests/radar/test_cli.py
# Retained evidence at review: test_the_headline_is_the_highest_vigor_named_with_its_subscription and rollup ordering.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_nothing_is_summed_across_subscriptions(self) -> None:
#         """radar.rollup-no-sum"""
#         value = rollup(MONDAY, examples())
#         document = as_json(value)
#         self.assertEqual(set(document), {"moment", "headline", "subscriptions", "failures"})
#         keys: set[str] = set()
#
#         def collect(value: object) -> None:
#             if isinstance(value, dict):
#                 keys.update(str(key).lower() for key in value)
#                 for item in value.values():
#                     collect(item)
#             elif isinstance(value, list):
#                 for item in value:
#                     collect(item)
#
#         collect(document)
#         self.assertFalse({key for key in keys if key.startswith(("sum", "total"))})  # no field adds them up
#         assert document["headline"] is not None
#         self.assertLess(document["headline"]["vigor"], 0.5)  # the maximum, not 0.47 + 0.37 + 0.16
#         self.assertNotIn("1.00", as_text(value, UTC))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/radar/test_cli.py::TheRollup.test_the_json_document_carries_every_field_of_the_result_record
# Reason: Large field-by-field copy of a direct JSON projection; most assertions repeat the result fixture and the serializer dictionary.
# Source: arbol@2ba18277c3ab444eaf0242fdf761e8912ce3909a:tests/radar/test_cli.py
# Retained evidence at review: Public read/refresh CLI cases plus calculation/unknown/prediction cases retain meaningful behavior.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_the_json_document_carries_every_field_of_the_result_record(self) -> None:
#         """radar.rollup-json"""
#         failures = {"codex": "no_answer: the launcher did not answer within its time limit"}
#         document = as_json(rollup(MONDAY, examples(), failures))
#         self.assertEqual(document["moment"], MONDAY.isoformat())
#         self.assertEqual(
#             document["headline"],
#             {
#                 "vigor": document["subscriptions"][0]["result"]["vigor"],
#                 "driver": "pi",
#                 "subscription": "kimi-coding",
#                 "label": "Kimi Code",
#             },
#         )
#         self.assertEqual(document["failures"], failures)
#         anthropic = document["subscriptions"][1]
#         self.assertEqual(
#             {key: anthropic[key] for key in ("driver", "subscription", "family", "label")},
#             {"driver": "claude", "subscription": "anthropic", "family": "anthropic", "label": "Anthropic"},
#         )
#         result = anthropic["result"]
#         self.assertEqual(
#             set(result),
#             {
#                 "moment",
#                 "report",
#                 "profile",
#                 "vigor",
#                 "exhausted",
#                 "predicted",
#                 "stale",
#                 "unknown",
#                 "nextChange",
#                 "notes",
#                 "windows",
#             },
#         )
#         self.assertEqual((result["moment"], result["report"], result["profile"]), (MONDAY.isoformat(), "r1", 1))
#         self.assertEqual(round(result["vigor"], 2), 0.37)
#         self.assertEqual(
#             (result["exhausted"], result["predicted"], result["stale"], result["unknown"]), (False, False, None, None)
#         )
#         self.assertEqual(result["nextChange"]["at"], (MONDAY + timedelta(hours=3, minutes=20)).isoformat())
#         self.assertEqual(round(result["nextChange"]["vigor"], 2), 0.39)
#         self.assertEqual([window["label"] for window in result["windows"]], ["Five hours", "Seven days"])
#         self.assertEqual(result["windows"][1]["role"], "store")
#         zai = document["subscriptions"][3]["result"]
#         self.assertEqual(
#             (zai["vigor"], zai["unknown"], zai["nextChange"], zai["windows"]),
#             (None, "allowance not supported for zai", None, []),
#         )
#         self.assertIsNone(document["subscriptions"][4]["result"])  # no record yet
#         json.dumps(document)  # one JSON document, nothing in it that JSON cannot carry
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/radar/test_cli.py::TheRollup.test_moments_are_printed_as_the_radar_reads_them
# Reason: Routine strftime branches and even the test helper output are checked against copied strings.
# Source: arbol@2ba18277c3ab444eaf0242fdf761e8912ce3909a:tests/radar/test_cli.py
# Retained evidence at review: Time-sensitive reset/staleness calculations and public text-rendering cases remain.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_moments_are_printed_as_the_radar_reads_them(self) -> None:
#         """radar.rollup-when"""
#         self.assertEqual(when(MONDAY + timedelta(hours=3, minutes=20), MONDAY, UTC), "13:20")
#         self.assertEqual(when(MONDAY + timedelta(days=3), MONDAY, UTC), "Thu 10:00")
#         self.assertEqual(when(MONDAY + timedelta(days=30), MONDAY, UTC), "2026-11-25 10:00")
#         self.assertEqual(when(MONDAY, MONDAY + timedelta(days=1), UTC), "Mon 10:00")
#         self.assertEqual(at(hours=3, minutes=20), "2026-10-26T13:20:00Z")  # the worked examples' 13:20
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/radar/test_cli.py::TheVerb.test_the_verb_and_its_options_are_parsed
# Reason: Copies valid parser dictionaries and Options defaults for ordinary flags.
# Source: arbol@2ba18277c3ab444eaf0242fdf761e8912ce3909a:tests/radar/test_cli.py
# Retained evidence at review: Refusal combinations and actual read/refresh/learn/approve commands remain.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_the_verb_and_its_options_are_parsed(self) -> None:
#         """radar.verb-parse"""
#         self.assertEqual(parse(["vigor"]), {"verb": "vigor"})
#         self.assertEqual(
#             parse(["--root", "sapling", "vigor", "--text"]), {"--root": "sapling", "--text": "", "verb": "vigor"}
#         )
#         self.assertEqual(parse(["vigor", "--refresh"]), {"--refresh": "", "verb": "vigor"})
#         self.assertEqual(parse(["vigor", "--refresh", "--text"]), {"--refresh": "", "--text": "", "verb": "vigor"})
#         self.assertEqual(
#             parse(["vigor", "--text", "--refresh", "claude/anthropic"]),
#             {"--refresh": "claude/anthropic", "--text": "", "verb": "vigor"},
#         )
#         self.assertEqual(parse(["backend"]), {"verb": "backend"})  # the backend's command line as it was
#         # The profile commands of SYL-299 (SGM-1.11).
#         self.assertEqual(parse(["vigor", "learn"]), {"verb": "vigor", "action": "learn"})
#         self.assertEqual(parse(["vigor", "profiles", "--text"]), {"verb": "vigor", "action": "profiles", "--text": ""})
#         self.assertEqual(
#             parse(["--root", "jensen", "vigor", "approve", "2"]),
#             {"--root": "jensen", "verb": "vigor", "action": "approve", "version": "2"},
#         )
#         self.assertEqual(options(parse(["vigor"])), Options())
#         self.assertEqual(options(parse(["vigor", "--refresh", "--text"])), Options(refresh=True, text=True))
#         self.assertEqual(
#             options(parse(["vigor", "--refresh", "pi/kimi-coding"])),
#             Options(refresh=True, target=("pi", "kimi-coding")),
#         )
# LOW-TIER-SOURCE-END
# LOW-TIER-END
