# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Learning the gate weights of Subscriptions Vigor as a versioned profile (SGM-1.11, SGM-D15, SGM-D17), with fixed reports.

Pairs of consecutive reports and their trust are pure; the runs between two fetch times come from the chat tables of a
database of the check's own, as `tests/radar/fixture.py` makes it.
"""

from __future__ import annotations

__all__ = [
    "Any", "CLAUDE", "CODEX", "ChatRecords", "FIRST_PROFILE", "KIMI", "LEARNING", "Learning", "Listed", "Listing",
    "MONDAY", "Observation", "Path", "ProfileRecords", "RATIOS", "ROOT", "RecordFixture", "Refused", "Report",
    "Series", "Subscription", "TheCommands", "TheEstimate", "ThePairs", "TheProfiles", "TheRuns", "Weight", "at",
    "claude_report", "claude_windows", "codex", "datetime", "estimate", "json", "kimi", "learn", "observation",
    "observations", "observe", "one", "pairs", "recompute", "record", "report", "runs_between", "sys", "timedelta",
    "unittest", "usage", "uuid", "window",
]


import json
import sys
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.model import Refused  # noqa: E402
from arbol_radar.drivers import Listed, Listing  # noqa: E402
from arbol_radar.learning import (  # noqa: E402
    Observation,
    Series,
    estimate,
    learn,
    observations,
    observe,
    pairs,
    runs_between,
)
from arbol_radar.model import FIRST_PROFILE, Learning, Report, Subscription, Weight  # noqa: E402
from arbol_radar.tick import recompute  # noqa: E402
from radar.fixture import RecordFixture, record, usage  # noqa: E402
from radar.support import CLAUDE, CODEX, KIMI, MONDAY, at, codex, kimi, report, window  # noqa: E402

LEARNING = Learning()  # the proposed defaults: a store change of 2 points, 10 pairs, the median


def claude_windows(five: float, week: float, *, five_resets: str | None = None, **more: Any) -> list[dict[str, Any]]:
    """The Claude Subscription's two windows: five hours resetting at 15:00 unless named, seven days on Thursday."""
    return [
        window("session", "Five hours", used=five, resets=five_resets or at(hours=5), minutes=300, **more),
        window("weekly", "Seven days", used=week, resets=at(days=3), minutes=10080),
    ]


def claude_report(five: float, week: float, *, hours: float, name: str, **more: Any) -> Report:
    """A Claude report fetched `hours` after Monday 10:00."""
    return report(CLAUDE, claude_windows(five, week, **more), fetched=at(hours=hours), report_id=name)


def one(first: Report, second: Report, runs: int = 1, learning: Learning = LEARNING) -> Observation:
    found = observe(first, second, runs, learning)
    assert len(found) == 1, found
    return found[0]


class ThePairs(unittest.TestCase):
    """Consecutive `ok` reports of one Subscription, and each gate's change against the store's (SGM-1.11)."""


def observation(ratio: float | None, *, reason: str | None = None, subscription: Subscription = CLAUDE) -> Observation:
    """An observation of the Claude five-hour gate with the given ratio: a store change of 2 over the gate's."""
    gate = 2 / ratio if ratio else None
    return Observation(
        subscription, "Five hours", "Seven days", "a", "b", MONDAY, MONDAY + timedelta(hours=1), 1, 2, gate, reason
    )


class TheEstimate(unittest.TestCase):
    """The calibrated estimate per family and gate: the median of the trusted ratios, its pair count and spread."""

    RATIOS = (0.08, 0.13, 0.1, 0.09, 0.11, 0.1, 0.12, 0.1, 0.09, 0.11)


class ChatRecords(RecordFixture):
    """The check's database with the chat tables emptied, one chat, and its Exchanges added by the check."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.db.execute("TRUNCATE chats, exchanges, messages, tool_calls, runs CASCADE")
        self.chat = str(uuid.uuid4())
        await self.db.execute("INSERT INTO chats (id, created_at) VALUES (%s, %s)", [self.chat, MONDAY])
        self.number = 0

    async def exchange(
        self, ended: datetime | None, *, driver: str = "claude", subscription: str = "anthropic"
    ) -> None:
        """One Exchange of the check's Root whose route names the Driver and the Subscription, ended or open."""
        self.number += 1
        await self.db.execute(
            "INSERT INTO exchanges (id, chat_id, number, state, trunk, build, route, working_folder, accepted_at, "
            "ended_at) VALUES (%s, %s, %s, %s, 'trivial', '1', %s::jsonb, '/tmp', %s, %s)",
            [
                str(uuid.uuid4()),
                self.chat,
                self.number,
                "open" if ended is None else "completed",
                f'{{"driver": "{driver}", "subscription": "{subscription}", "model": "sonnet"}}',
                MONDAY - timedelta(hours=1),
                ended,
            ],
        )


class TheRuns(ChatRecords):
    """The runs of this Mac between two fetch times, from the Root's chat tables, and the observations over the records."""


RATIOS = TheEstimate.RATIOS


class ProfileRecords(ChatRecords):
    """A recorded history of the Claude Subscription with one trusted pair a day, and its listing."""

    async def history(self, ratios: tuple[float, ...]) -> None:
        """One trusted pair a day around one run: 10 % of five hours at 10:00, 2 points more of the week at 11:00.

        The pair from one day's 11:00 to the next day's 10:00 spans a reset of the five hours and no run, so it is
        observed and not trusted.
        """
        for day, ratio in enumerate(ratios):
            five_resets = at(days=day, hours=4)
            for hours, five, week in ((0, 10, 20 + 2 * day), (1, 10 + 2 / ratio, 22 + 2 * day)):
                windows = [
                    window("session", "Five hours", used=five, resets=five_resets, minutes=300),
                    window("weekly", "Seven days", used=week, resets=at(days=20), minutes=10080),
                ]
                moment = MONDAY + timedelta(days=day, hours=hours)
                await self.records.record_report(CLAUDE, usage(windows, fetched=at(days=day, hours=hours)), now=moment)
            await self.exchange(MONDAY + timedelta(days=day, minutes=30))

    def listing(self) -> Listing:
        latest = usage(claude_windows(40, 50, five_resets=at(days=12)), fetched=at(days=11))
        return Listing(("claude",), (Listed(CLAUDE, record(CLAUDE, latest)),))


class TheProfiles(ProfileRecords):
    """A learned profile written as proposed, the profile in use, approval, and a calculation that never uses a proposal."""


class TheCommands(ProfileRecords):
    """`arbol vigor learn`, `arbol vigor profiles` and `arbol vigor approve <version>` as the program answers them."""

    def answer(self, *extra: str) -> tuple[int, str]:
        child = self.frame.start(args=self.vigor(*extra))
        out, err = child.communicate(timeout=20)
        self.assertEqual(err.decode(), "")
        return child.returncode, out.decode()

    def document(self, *extra: str) -> dict[str, Any]:
        status, out = self.answer(*extra)
        self.assertEqual((status, out.count("\n")), (0, 1), out)  # one JSON document, one line
        value: dict[str, Any] = json.loads(out)
        return value

    def refused(self, code: str, *extra: str) -> None:
        status, out = self.answer(*extra)
        self.assertEqual((status, json.loads(out)["error"]["code"]), (1, code), out)


# Archived complete imports; restore needed names in their original scope, not at this file tail.
