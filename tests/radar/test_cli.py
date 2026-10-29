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
