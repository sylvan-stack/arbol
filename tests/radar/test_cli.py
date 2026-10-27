"""Subscriptions Vigor on the Radar and the read `arbol vigor`: the rollup, the verb, the latest records, the refresh.

The rollup checks need no database: they take results computed from the chapter's worked examples (SGM-1.12, SGM-D18).
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_radar.model import FIRST_PROFILE, Subscription  # noqa: E402
from arbol_radar.rollup import Entry, Rollup, as_json, as_text, rollup, when  # noqa: E402
from arbol_radar.vigor import compute  # noqa: E402
from radar.support import CLAUDE, CODEX, KIMI, MONDAY, ZAI, at, claude, codex, kimi, report  # noqa: E402

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

    def test_the_subscriptions_are_sorted_by_vigor_with_unknown_ones_below(self) -> None:
        """radar.rollup-order"""
        value = rollup(MONDAY, examples())
        self.assertEqual(
            [entry.name for entry in value.entries],
            [
                "pi/kimi-coding",
                "claude/anthropic",
                "codex/chatgpt",
                "pi/zai",
                "pi/deepseek",
            ],
        )
        self.assertEqual(
            [round(entry.vigor, 2) if entry.vigor is not None else None for entry in value.entries],
            [0.47, 0.37, 0.16, None, None],
        )
        self.assertEqual(value.moment, MONDAY)
        with_reached = rollup(MONDAY, examples(reached=True))  # the exhausted Claude account sorts last of the known
        self.assertEqual(
            [entry.name for entry in with_reached.entries][:3], ["pi/kimi-coding", "codex/chatgpt", "claude/anthropic"]
        )
        self.assertEqual(with_reached.entries[2].vigor, 0.0)
        self.assertEqual(rollup(MONDAY, []), Rollup(MONDAY, (), {}))

    def test_the_headline_is_the_highest_vigor_named_with_its_subscription(self) -> None:
        """radar.rollup-headline"""
        headline = rollup(MONDAY, examples()).headline
        assert headline is not None and headline.vigor is not None
        self.assertEqual((headline.subscription, headline.label, round(headline.vigor, 2)), (KIMI, "Kimi Code", 0.47))
        unknown_only = rollup(MONDAY, [entry for entry in examples() if entry.vigor is None])
        self.assertIsNone(unknown_only.headline)  # unknown is never promoted to a value
        self.assertEqual(len(unknown_only.entries), 2)

    def test_nothing_is_summed_across_subscriptions(self) -> None:
        """radar.rollup-no-sum"""
        value = rollup(MONDAY, examples())
        document = as_json(value)
        self.assertEqual(set(document), {"moment", "headline", "subscriptions", "failures"})
        keys: set[str] = set()

        def collect(value: object) -> None:
            if isinstance(value, dict):
                keys.update(str(key).lower() for key in value)
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(document)
        self.assertFalse({key for key in keys if key.startswith(("sum", "total"))})  # no field adds them up
        assert document["headline"] is not None
        self.assertLess(document["headline"]["vigor"], 0.5)  # the maximum, not 0.47 + 0.37 + 0.16
        self.assertNotIn("1.00", as_text(value, UTC))

    def test_the_json_document_carries_every_field_of_the_result_record(self) -> None:
        """radar.rollup-json"""
        failures = {"codex": "no_answer: the launcher did not answer within its time limit"}
        document = as_json(rollup(MONDAY, examples(), failures))
        self.assertEqual(document["moment"], MONDAY.isoformat())
        self.assertEqual(
            document["headline"],
            {
                "vigor": document["subscriptions"][0]["result"]["vigor"],
                "driver": "pi",
                "subscription": "kimi-coding",
                "label": "Kimi Code",
            },
        )
        self.assertEqual(document["failures"], failures)
        anthropic = document["subscriptions"][1]
        self.assertEqual(
            {key: anthropic[key] for key in ("driver", "subscription", "family", "label")},
            {"driver": "claude", "subscription": "anthropic", "family": "anthropic", "label": "Anthropic"},
        )
        result = anthropic["result"]
        self.assertEqual(
            set(result),
            {
                "moment",
                "report",
                "profile",
                "vigor",
                "exhausted",
                "predicted",
                "stale",
                "unknown",
                "nextChange",
                "notes",
                "windows",
            },
        )
        self.assertEqual((result["moment"], result["report"], result["profile"]), (MONDAY.isoformat(), "r1", 1))
        self.assertEqual(round(result["vigor"], 2), 0.37)
        self.assertEqual(
            (result["exhausted"], result["predicted"], result["stale"], result["unknown"]), (False, False, None, None)
        )
        self.assertEqual(result["nextChange"]["at"], (MONDAY + timedelta(hours=3, minutes=20)).isoformat())
        self.assertEqual(round(result["nextChange"]["vigor"], 2), 0.39)
        self.assertEqual([window["label"] for window in result["windows"]], ["Five hours", "Seven days"])
        self.assertEqual(result["windows"][1]["role"], "store")
        zai = document["subscriptions"][3]["result"]
        self.assertEqual(
            (zai["vigor"], zai["unknown"], zai["nextChange"], zai["windows"]),
            (None, "allowance not supported for zai", None, []),
        )
        self.assertIsNone(document["subscriptions"][4]["result"])  # no record yet
        json.dumps(document)  # one JSON document, nothing in it that JSON cannot carry

    def test_the_text_form_is_the_radars_lines(self) -> None:
        """radar.rollup-text"""
        text = as_text(rollup(MONDAY, examples(), {"codex": "no_answer: no reply"}), UTC)
        self.assertEqual(
            text.splitlines(),
            [
                "Subscriptions Vigor: 0.47, Kimi Code",
                "pi/kimi-coding 0.47 · next change 11:00, 0.47 · recorded 10:00",
                "claude/anthropic 0.37 · next change 13:20, 0.39 · recorded 10:00",
                "codex/chatgpt 0.16 · next change 12:30, 0.17 · recorded 10:00",
                "pi/zai · unknown: allowance not supported for zai · recorded 10:00",
                "pi/deepseek · no record yet",
                "Failed: codex · no_answer: no reply",
            ],
        )
        reached = as_text(rollup(MONDAY, examples(reached=True)), UTC).splitlines()
        self.assertEqual(reached[3], "claude/anthropic 0 · exhausted, recovers 13:20, 0.39 · recorded 10:00")
        later = MONDAY + timedelta(hours=5, minutes=10)  # the five-hour window reset without a report: predicted, stale
        aged = compute(report(CLAUDE, claude(), extra={"isUsingOverage": False}), FIRST_PROFILE, later)
        lines = as_text(rollup(later, [Entry(CLAUDE, "Anthropic", aged)]), UTC).splitlines()
        self.assertTrue(lines[1].startswith("claude/anthropic 0."))
        self.assertIn(" · predicted · stale, report 5 h 15 min old · recorded 15:10", lines[1])
        self.assertEqual(
            as_text(rollup(MONDAY, [Entry(DEEPSEEK, "DeepSeek", None)]), UTC).splitlines(),
            ["Subscriptions Vigor: unknown", "pi/deepseek · no record yet"],
        )

    def test_moments_are_printed_as_the_radar_reads_them(self) -> None:
        """radar.rollup-when"""
        self.assertEqual(when(MONDAY + timedelta(hours=3, minutes=20), MONDAY, UTC), "13:20")
        self.assertEqual(when(MONDAY + timedelta(days=3), MONDAY, UTC), "Thu 10:00")
        self.assertEqual(when(MONDAY + timedelta(days=30), MONDAY, UTC), "2026-11-25 10:00")
        self.assertEqual(when(MONDAY, MONDAY + timedelta(days=1), UTC), "Mon 10:00")
        self.assertEqual(at(hours=3, minutes=20), "2026-10-26T13:20:00Z")  # the worked examples' 13:20


if __name__ == "__main__":
    unittest.main()
