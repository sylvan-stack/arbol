"""Subscriptions Vigor on the Radar and the read `arbol vigor`: the rollup, the verb, the latest records, the refresh.

The rollup checks need no database: they take results computed from the chapter's worked examples (SGM-1.12, SGM-D18).
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.model import Refused, parse  # noqa: E402
from arbol_radar.cli import Options, options, read  # noqa: E402
from arbol_radar.model import FIRST_PROFILE, Subscription  # noqa: E402
from arbol_radar.rollup import Entry, Rollup, as_json, as_text, rollup, when  # noqa: E402
from arbol_radar.vigor import compute  # noqa: E402
from radar.fixture import LAYOUT, LISTING, RecordFixture, drivers, usage  # noqa: E402
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


class TheVerb(unittest.TestCase):
    """`arbol [--root <root>] vigor [--refresh [<driver>/<subscription>]] [--text]` beside `backend` (SGM-D28)."""

    def test_the_verb_and_its_options_are_parsed(self) -> None:
        """radar.verb-parse"""
        self.assertEqual(parse(["vigor"]), {"verb": "vigor"})
        self.assertEqual(
            parse(["--root", "sapling", "vigor", "--text"]), {"--root": "sapling", "--text": "", "verb": "vigor"}
        )
        self.assertEqual(parse(["vigor", "--refresh"]), {"--refresh": "", "verb": "vigor"})
        self.assertEqual(parse(["vigor", "--refresh", "--text"]), {"--refresh": "", "--text": "", "verb": "vigor"})
        self.assertEqual(
            parse(["vigor", "--text", "--refresh", "claude/anthropic"]),
            {"--refresh": "claude/anthropic", "--text": "", "verb": "vigor"},
        )
        self.assertEqual(parse(["backend"]), {"verb": "backend"})  # the backend's command line as it was
        self.assertEqual(options(parse(["vigor"])), Options())
        self.assertEqual(options(parse(["vigor", "--refresh", "--text"])), Options(refresh=True, text=True))
        self.assertEqual(
            options(parse(["vigor", "--refresh", "pi/kimi-coding"])),
            Options(refresh=True, target=("pi", "kimi-coding")),
        )

    def test_what_the_verb_refuses(self) -> None:
        """radar.verb-refusals"""
        for args in (
            [],
            ["vigor", "backend"],
            ["radar"],
            ["backend", "--text"],
            ["backend", "--refresh"],
            ["vigor", "--text", "--text"],
            ["vigor", "--refresh", "--refresh"],
            ["vigor", "--bogus"],
            ["vigor", "--root-dir", "/tmp/x"],
            ["vigor", "--root"],
        ):
            with self.subTest(args=args), self.assertRaises(Refused) as caught:
                parse(args)
            self.assertEqual(caught.exception.code, "invalid_input")
        for value in ("anthropic", "/anthropic", "claude/", "claude"):
            with self.subTest(value=value), self.assertRaises(Refused) as caught:
                options(parse(["vigor", "--refresh", value]))
            self.assertEqual(caught.exception.code, "invalid_input")


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

    def vigor(self, *extra: str) -> list[str]:
        """The command line of `arbol vigor` against the check's Root, launchers and database."""
        words = self.frame.options(self.cluster.address)
        words[words.index("backend")] = "vigor"
        return words + list(extra)

    async def test_the_latest_record_of_every_subscription_is_shown_without_recomputing(self) -> None:
        """radar.read-latest"""
        await self.seed()
        drivers(self.frame, {name: {"list": config} for name, config in LISTING.items()})
        before = await self.count("vigor_results")
        value = await read(self.selected, Options(), now=MONDAY + timedelta(hours=2))
        self.assertEqual(value.moment, MONDAY + timedelta(hours=2))
        self.assertEqual(
            [entry.name for entry in value.entries], ["pi/kimi-coding", "claude/anthropic", "pi/zai", "codex/chatgpt"]
        )
        self.assertEqual([entry.label for entry in value.entries], ["Kimi-Coding", "Anthropic", "Zai", "Chatgpt"])
        latest = value.entries[1].result
        assert latest is not None
        self.assertEqual(latest.moment, MONDAY + timedelta(hours=1))  # the latest record, not a fresh calculation
        self.assertEqual(latest, await self.records.last_result(CLAUDE))
        zai = value.entries[2].result
        assert zai is not None
        self.assertEqual((zai.vigor, zai.unknown), (None, "no report yet"))  # a Subscription whose Driver has no report
        self.assertIsNone(value.entries[3].result)  # listed, never calculated: no record yet
        self.assertEqual(dict(value.failures), {})
        self.assertEqual(await self.count("vigor_results"), before)  # nothing recomputed (SGM-D30)
        calls = self.frame.calls()
        self.assertEqual([call["args"] for call in calls], [["subscriptions", "list"]] * 3)  # no vendor was contacted
        headline = value.headline
        assert headline is not None and headline.vigor is not None
        self.assertEqual((headline.subscription, round(headline.vigor, 2)), (KIMI, 0.47))

    async def test_a_failing_driver_is_shown_beside_the_others(self) -> None:
        """radar.read-failure"""
        await self.seed()
        drivers(
            self.frame,
            {
                "arbol-claude-driver": {"list": LISTING["arbol-claude-driver"]},
                "arbol-codex-driver": {"list": {"status": 1}},
                "arbol-pi-driver": {"list": LISTING["arbol-pi-driver"]},
            },
        )
        value = await read(self.selected, Options(), now=MONDAY)
        self.assertEqual([entry.name for entry in value.entries], ["pi/kimi-coding", "claude/anthropic", "pi/zai"])
        self.assertEqual(set(value.failures), {"codex"})
        self.assertTrue(value.failures["codex"].startswith("no_answer: "))
        self.assertIn("Failed: codex · no_answer: ", as_text(value, UTC))

    async def test_a_root_without_the_tables_refuses_before_any_driver_runs(self) -> None:
        """radar.read-layout-incomplete"""
        drivers(self.frame, {name: {"list": config} for name, config in LISTING.items()})
        await self.db.execute("DROP TABLE vigor_results")
        try:
            with self.assertRaises(Refused) as caught:
                await read(self.selected, Options(), now=MONDAY)
            self.assertEqual(caught.exception.code, "layout_incomplete")
            self.assertEqual(self.frame.calls(), [])
        finally:
            await self.db.execute(LAYOUT.read_text(encoding="utf-8"))

    def answer(self, *extra: str) -> tuple[int, str, str]:
        child = self.frame.start(args=self.vigor(*extra))
        out, err = child.communicate(timeout=20)
        return child.returncode, out.decode(), err.decode()

    async def test_the_program_prints_one_json_document_or_the_radars_lines(self) -> None:
        """radar.read-program"""
        await self.seed()
        drivers(self.frame, {name: {"list": config} for name, config in LISTING.items()})
        status, out, err = self.answer()
        self.assertEqual((status, err), (0, ""))
        document: dict[str, Any] = json.loads(out)
        self.assertEqual(out.count("\n"), 1)  # one JSON document, one line
        self.assertEqual(set(document), {"moment", "headline", "subscriptions", "failures"})
        self.assertEqual(
            [item["subscription"] for item in document["subscriptions"]], ["kimi-coding", "anthropic", "zai", "chatgpt"]
        )
        self.assertEqual(document["headline"]["subscription"], "kimi-coding")
        self.assertEqual(await self.count("vigor_results"), 4)  # the program recomputed nothing
        status, out, err = self.answer("--text")
        self.assertEqual((status, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[0], "Subscriptions Vigor: 0.47, Kimi-Coding")
        self.assertTrue(lines[1].startswith("pi/kimi-coding 0.47 · next change "))
        # The latest record as it was computed at Monday 11:00, with its moment: nothing is computed afresh today.
        self.assertTrue(lines[2].startswith("claude/anthropic 0.40 · next change "))
        self.assertTrue(lines[2].endswith(" · recorded " + when(MONDAY + timedelta(hours=1), datetime.now(UTC))))
        self.assertNotIn("predicted", lines[2])
        self.assertTrue(lines[3].startswith("pi/zai · unknown: no report yet · recorded "))
        self.assertEqual(lines[4], "codex/chatgpt · no record yet")
        status, out, err = self.answer("--bogus")
        self.assertEqual((status, json.loads(out)["error"]["code"]), (1, "invalid_input"))
        status, out, err = self.answer("--refresh", "nobody")
        self.assertEqual((status, json.loads(out)["error"]["code"]), (1, "invalid_input"))
        self.assertEqual(await self.count("vigor_results"), 4)


if __name__ == "__main__":
    unittest.main()
