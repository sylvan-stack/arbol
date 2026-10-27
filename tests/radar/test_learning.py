"""Learning the gate weights of Subscriptions Vigor as a versioned profile (SGM-1.11, SGM-D15, SGM-D17), with fixed reports.

Pairs of consecutive reports and their trust are pure; the runs between two fetch times come from the chat tables of a
database of the check's own, as `tests/radar/fixture.py` makes it.
"""

from __future__ import annotations

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

    def test_a_pair_around_one_run_that_moved_both_windows_is_trusted_with_its_ratio(self) -> None:
        """radar.learn-trusted"""
        found = one(claude_report(10, 20, hours=0, name="a"), claude_report(30, 22, hours=1, name="b"))
        self.assertEqual((found.gate, found.store), ("Five hours", "Seven days"))
        self.assertEqual((found.first, found.second, found.runs), ("a", "b", 1))
        self.assertEqual((found.store_change, found.gate_change), (2, 20))
        self.assertAlmostEqual(found.ratio or 0, 0.1)
        self.assertTrue(found.trusted)
        self.assertIsNone(found.reason)
        self.assertEqual((found.since, found.until), (MONDAY, MONDAY + timedelta(hours=1)))

    def test_a_window_that_did_not_move_marks_the_pair_untrusted(self) -> None:
        """radar.learn-still"""
        cases = {
            "Five hours did not move": (
                claude_report(10, 20, hours=0, name="a"),
                claude_report(10, 22, hours=1, name="b"),
            ),
            "Seven days did not move": (
                claude_report(10, 20, hours=0, name="a"),
                claude_report(30, 20, hours=1, name="b"),
            ),
        }
        for reason, (first, second) in cases.items():
            with self.subTest(reason=reason):
                found = one(first, second)
                self.assertEqual(found.reason, reason)
                self.assertFalse(found.trusted)

    def test_no_run_or_several_runs_between_the_reports_mark_the_pair_untrusted(self) -> None:
        """radar.learn-runs"""
        first, second = claude_report(10, 20, hours=0, name="a"), claude_report(30, 22, hours=1, name="b")
        self.assertEqual(one(first, second, 0).reason, "no run of this Mac ended between the reports")
        self.assertEqual(one(first, second, 2).reason, "2 runs of this Mac ended between the reports")
        self.assertIsNotNone(one(first, second, 0).ratio)  # the ratio is kept beside the reason

    def test_a_store_change_below_the_threshold_marks_the_pair_untrusted(self) -> None:
        """radar.learn-threshold"""
        first, second = claude_report(10, 20, hours=0, name="a"), claude_report(20, 21, hours=1, name="b")
        self.assertEqual(one(first, second).reason, "the store moved by 1, below the threshold of 2")
        self.assertTrue(one(first, second, learning=Learning(threshold=1)).trusted)

    def test_a_store_that_moved_more_than_its_gate_marks_the_pair_untrusted(self) -> None:
        """radar.learn-store-faster"""
        first, second = claude_report(10, 20, hours=0, name="a"), claude_report(13, 25, hours=1, name="b")
        self.assertEqual(one(first, second).reason, "the store moved more than Five hours")

    def test_a_window_that_reset_between_the_reports_marks_the_pair_untrusted(self) -> None:
        """radar.learn-reset"""
        first = claude_report(80, 20, hours=0, name="a", five_resets=at(hours=1))
        second = claude_report(10, 22, hours=2, name="b", five_resets=at(hours=6))
        found = one(first, second)
        self.assertEqual(found.reason, "Five hours reset between the reports")
        self.assertIsNone(found.gate_change)
        self.assertIsNone(found.ratio)

    def test_an_unknown_missing_or_overage_window_marks_the_pair_untrusted(self) -> None:
        """radar.learn-unknown"""
        first = claude_report(10, 20, hours=0, name="a")
        missing = report(
            CLAUDE, [window("weekly", "Seven days", used=22, resets=at(days=3), minutes=10080)], fetched=at(hours=1)
        )
        unknown = report(
            CLAUDE,
            [
                window("session", "Five hours", used=None, resets=at(hours=5), minutes=300),
                window("weekly", "Seven days", used=22, resets=at(days=3), minutes=10080),
            ],
            fetched=at(hours=1),
        )
        above = claude_report(104, 30, hours=1, name="b")
        self.assertEqual(one(first, missing).reason, "Five hours is missing from the later report")
        self.assertEqual(one(first, unknown).reason, "Five hours is unknown in the later report")
        self.assertEqual(one(first, above).reason, "Five hours counted above 100")

    def test_a_subscription_without_a_gate_gives_no_observation(self) -> None:
        """radar.learn-no-gate"""
        week_only = [window("weekly", "Weekly window", resource=None, used=29, resets=at(days=6), minutes=10080)]
        later = [window("weekly", "Weekly window", resource=None, used=50, resets=at(days=6), minutes=10080)]
        self.assertEqual(observe(report(CODEX, week_only), report(CODEX, later, fetched=at(hours=1)), 1, LEARNING), [])
        # Kimi Code's five-hour window counts calls and its other month is shown: it has no gate to learn.
        self.assertEqual(observe(report(KIMI, kimi()), report(KIMI, kimi(), fetched=at(minutes=1)), 1, LEARNING), [])
        # Codex with its five-hour window has one gate.
        self.assertEqual(
            [
                o.gate
                for o in observe(report(CODEX, codex()), report(CODEX, codex(), fetched=at(minutes=1)), 1, LEARNING)
            ],
            ["5-hour window"],
        )

    def test_pairs_are_consecutive_ok_reports_oldest_first(self) -> None:
        """radar.learn-pairs"""
        a = claude_report(10, 20, hours=0, name="a")
        b = report(CLAUDE, [], fetched=at(hours=1), outcome="unavailable", message="offline", report_id="b")
        c = claude_report(30, 22, hours=2, name="c")
        d = claude_report(40, 23, hours=3, name="d")
        self.assertEqual([(x.id, y.id) for x, y in pairs([d, b, a, c])], [("a", "c"), ("c", "d")])
        self.assertEqual(pairs([a]), [])


def observation(ratio: float | None, *, reason: str | None = None, subscription: Subscription = CLAUDE) -> Observation:
    """An observation of the Claude five-hour gate with the given ratio: a store change of 2 over the gate's."""
    gate = 2 / ratio if ratio else None
    return Observation(
        subscription, "Five hours", "Seven days", "a", "b", MONDAY, MONDAY + timedelta(hours=1), 1, 2, gate, reason
    )


class TheEstimate(unittest.TestCase):
    """The calibrated estimate per family and gate: the median of the trusted ratios, its pair count and spread."""

    RATIOS = (0.08, 0.13, 0.1, 0.09, 0.11, 0.1, 0.12, 0.1, 0.09, 0.11)

    def test_enough_trusted_pairs_give_the_median_with_its_count_and_spread(self) -> None:
        """radar.learn-estimate"""
        found = [observation(r) for r in self.RATIOS] + [observation(0.5, reason="2 runs of this Mac ended between")]
        (gate,) = estimate(found, LEARNING)
        self.assertEqual(
            (gate.family, gate.gate, gate.trusted, gate.untrusted, gate.needed), ("anthropic", "Five hours", 10, 1, 10)
        )
        self.assertAlmostEqual(gate.value or 0, 0.1)
        self.assertAlmostEqual(gate.low or 0, 0.08)
        self.assertAlmostEqual(gate.high or 0, 0.13)
        self.assertTrue(gate.calibrated)
        self.assertEqual(gate.missing, 0)

    def test_too_few_trusted_pairs_say_how_many_are_missing(self) -> None:
        """radar.learn-too-few"""
        found = [observation(r) for r in self.RATIOS[:3]] + [observation(None, reason="Five hours did not move")]
        (gate,) = estimate(found, LEARNING)
        self.assertEqual((gate.trusted, gate.untrusted, gate.missing), (3, 1, 7))
        self.assertIsNone(gate.value)
        self.assertFalse(gate.calibrated)
        self.assertEqual((gate.low, gate.high), (0.08, 0.13))
        (none,) = estimate([], LEARNING, [("anthropic", "Five hours")])  # a gate never observed
        self.assertEqual((none.trusted, none.missing, none.value, none.low), (0, 10, None, None))
        self.assertTrue(estimate(found, Learning(pairs=3))[0].calibrated)

    def test_the_subscriptions_of_one_family_count_together_and_families_apart(self) -> None:
        """radar.learn-family"""
        other = Subscription("claude", "test-anthropic", "anthropic")
        found = [observation(r) for r in self.RATIOS[:5]] + [
            observation(r, subscription=other) for r in self.RATIOS[5:]
        ]
        found.append(Observation(CODEX, "5-hour window", "Weekly window", "c", "d", MONDAY, MONDAY, 1, 2, 10, None))
        anthropic, chatgpt = estimate(found, LEARNING)
        self.assertEqual((anthropic.family, anthropic.trusted), ("anthropic", 10))
        self.assertTrue(anthropic.calibrated)
        self.assertEqual(
            (chatgpt.family, chatgpt.gate, chatgpt.trusted, chatgpt.missing), ("chatgpt", "5-hour window", 1, 9)
        )


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

    async def test_the_runs_between_two_fetch_times_are_the_routed_exchanges_that_ended_between(self) -> None:
        """radar.learn-runs-between"""
        await self.exchange(MONDAY)  # ended at the first fetch time: before the interval
        await self.exchange(MONDAY + timedelta(minutes=30))
        await self.exchange(MONDAY + timedelta(hours=1))  # ended at the second fetch time: inside
        await self.exchange(MONDAY + timedelta(minutes=40), subscription="test-anthropic")
        await self.exchange(MONDAY + timedelta(minutes=40), driver="pi")
        await self.exchange(None)  # still open
        self.assertEqual(await runs_between(self.db, CLAUDE, MONDAY, MONDAY + timedelta(hours=1)), 2)
        self.assertEqual(
            await runs_between(self.db, CLAUDE, MONDAY + timedelta(hours=1), MONDAY + timedelta(hours=2)), 0
        )
        other = Subscription("claude", "test-anthropic", "anthropic")
        self.assertEqual(await runs_between(self.db, other, MONDAY, MONDAY + timedelta(hours=1)), 1)

    async def test_the_observations_over_the_recorded_reports_of_every_subscription(self) -> None:
        """radar.learn-observations"""
        for hours, five, week in ((0, 10, 20), (1, 30, 22), (2, 31, 22)):
            await self.records.record_report(
                CLAUDE, usage(claude_windows(five, week), fetched=at(hours=hours)), now=MONDAY + timedelta(hours=hours)
            )
        await self.records.record_report(KIMI, usage(kimi()), now=MONDAY)
        await self.exchange(MONDAY + timedelta(minutes=50))
        found = await observations(self.records, LEARNING)
        self.assertEqual(
            [(o.subscription, o.runs, o.reason) for o in found],
            [
                (CLAUDE, 1, None),
                (CLAUDE, 0, "Seven days did not move"),
            ],
        )
        self.assertEqual(await self.records.reported(), [CLAUDE, KIMI])


if __name__ == "__main__":
    unittest.main()


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

    async def test_enough_trusted_pairs_write_a_proposed_profile_one_version_above_the_highest(self) -> None:
        """radar.learn-propose"""
        await self.history(RATIOS)
        now = MONDAY + timedelta(days=11)
        learned = await learn(self.records, now)
        self.assertEqual(learned.profile, FIRST_PROFILE)  # learned by the values of the profile in use
        self.assertEqual(learned.series, (Series(CLAUDE, 20, 19),))
        (gate,) = learned.estimates
        self.assertEqual((gate.trusted, gate.untrusted, gate.missing), (10, 9, 0))
        proposed = learned.proposed
        assert proposed is not None
        self.assertEqual((proposed.version, proposed.approval), (2, "proposed"))
        weight = proposed.gates[("anthropic", "Five hours")]
        self.assertEqual((weight.source, weight.pairs), ("learned", 10))
        self.assertAlmostEqual(weight.value, 0.1)
        self.assertAlmostEqual(weight.low or 0, 0.08)
        self.assertAlmostEqual(weight.high or 0, 0.13)
        carried = (FIRST_PROFILE.pace, FIRST_PROFILE.placeholder, FIRST_PROFILE.stale_rule, FIRST_PROFILE.learning)
        self.assertEqual((proposed.pace, proposed.placeholder, proposed.stale_rule, proposed.learning), carried)
        self.assertEqual(await self.records.profile(2), proposed)
        rows = {row[0]: row for row in await self.db.execute("SELECT version, approval, gates FROM vigor_profiles", [])}
        self.assertEqual(sorted(rows), [1, 2])
        self.assertEqual(rows[2][1], "proposed")
        (entry,) = rows[2][2]
        self.assertEqual(
            {key: entry[key] for key in ("family", "label", "source", "pairs", "estimator", "threshold", "needed")},
            {
                "family": "anthropic",
                "label": "Five hours",
                "source": "learned",
                "pairs": 10,
                "estimator": "median",
                "threshold": 2.0,
                "needed": 10,
            },
        )
        again = await learn(self.records, now)
        assert again.proposed is not None
        self.assertEqual(again.proposed.version, 3)  # one above the highest, approved or not

    async def test_too_few_trusted_pairs_write_nothing_and_say_how_many_are_missing(self) -> None:
        """radar.learn-nothing-proposed"""
        await self.history(RATIOS[:3])
        learned = await learn(self.records, MONDAY + timedelta(days=3))
        self.assertIsNone(learned.proposed)
        (gate,) = learned.estimates
        self.assertEqual((gate.trusted, gate.missing, gate.value), (3, 7, None))
        self.assertEqual(await self.count("vigor_profiles"), 1)  # the first profile alone
        self.assertEqual(await self.records.in_use(), FIRST_PROFILE)

    async def test_a_calculation_uses_the_profile_in_use_and_never_a_proposed_one(self) -> None:
        """radar.learn-never-proposed"""
        await self.history(RATIOS)
        now = MONDAY + timedelta(days=11)
        proposed = (await learn(self.records, now)).proposed
        assert proposed is not None
        self.assertEqual(await self.records.in_use(), FIRST_PROFILE)
        tick = await recompute(self.records, self.listing(), FIRST_PROFILE, now)
        self.assertEqual([result.profile for result in tick.results], [1])
        with self.assertRaises(Refused) as caught:
            await self.records.calculate(CLAUDE, proposed, now)
        self.assertEqual(caught.exception.code, "profile_not_approved")
        approved = await self.records.approve(2, now)
        self.assertEqual((approved.version, approved.approval), (2, "approved"))
        self.assertEqual(await self.records.in_use(), approved)
        later = await recompute(self.records, self.listing(), FIRST_PROFILE, now + timedelta(minutes=3))
        (result,) = later.results
        self.assertEqual(result.profile, 2)
        five = next(entry for entry in result.windows if entry.label == "Five hours")
        self.assertAlmostEqual(five.weight or 0, 0.1)
        self.assertEqual(
            [row[0] for row in await self.db.execute("SELECT profile FROM vigor_results ORDER BY moment", [])], [1, 2]
        )

    async def test_a_replay_takes_any_recorded_version_a_proposed_one_included(self) -> None:
        """radar.learn-replay-any"""
        await self.history(RATIOS)
        now = MONDAY + timedelta(days=11)
        await recompute(self.records, self.listing(), FIRST_PROFILE, now)
        await learn(self.records, now)
        proposed = await self.records.profile(2)
        assert proposed is not None and proposed.approval == "proposed"
        (replay,) = await self.records.replay(CLAUDE, proposed)
        self.assertEqual((replay.recorded.profile, replay.replayed.profile), (1, 2))
        self.assertFalse(replay.same)
        self.assertEqual(await self.count("vigor_results"), 1)  # a replay writes nothing

    async def test_approval_refuses_an_unknown_an_approved_and_an_older_profile(self) -> None:
        """radar.learn-approve-refusals"""
        now = MONDAY + timedelta(days=11)
        cases: list[tuple[int, str]] = [(7, "unknown_profile")]
        with self.assertRaises(Refused) as caught:
            await self.records.approve(7, now)
        self.assertEqual(caught.exception.code, "unknown_profile")
        self.assertIsNone(await self.records.profile(7))
        await self.history(RATIOS)
        await learn(self.records, now)
        await learn(self.records, now)
        await self.records.approve(3, now)
        for version, code in [(3, "already_approved"), (2, "older_profile"), *cases]:
            with self.subTest(version=version):
                with self.assertRaises(Refused) as caught:
                    await self.records.approve(version, now)
                self.assertEqual(caught.exception.code, code)
        self.assertEqual((await self.records.in_use()).version, 3)

    async def test_the_first_profile_can_be_approved_and_learned_weights_carry_into_a_proposal(self) -> None:
        """radar.learn-carried"""
        now = MONDAY + timedelta(days=11)
        first = await self.records.approve(1, now)
        self.assertEqual((first.version, first.approval), (1, "approved"))
        self.assertEqual(await self.records.in_use(), first)
        anthropic = {("anthropic", "Five hours"): Weight(0.11, "learned", 12, 0.09, 0.14)}
        second = await self.records.propose(anthropic, first, now)
        await self.records.approve(second.version, now)
        chatgpt = {("chatgpt", "5-hour window"): Weight(0.2, "learned", 10, 0.15, 0.3)}
        third = await self.records.propose(chatgpt, await self.records.in_use(), now)
        self.assertEqual((third.version, third.approval), (3, "proposed"))
        self.assertEqual(dict(third.gates), anthropic | chatgpt)
        self.assertEqual(await self.records.profile(3), third)
        self.assertEqual([profile.version for profile, _ in await self.records.profiles()], [1, 2, 3])


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

    async def test_learn_profiles_and_approve_answer_as_json_and_text(self) -> None:
        """radar.learn-commands"""
        await self.history(RATIOS)
        listed = self.document("profiles")
        self.assertEqual(listed["inUse"], 1)
        self.assertEqual(
            [(p["version"], p["approval"], p["inUse"], p["recordedAt"]) for p in listed["profiles"]],
            [(1, "proposed", True, None)],
        )
        status, out = self.answer("learn", "--text")
        self.assertEqual(status, 0)
        lines = out.splitlines()
        self.assertEqual(
            lines[0],
            "Gate weights learned by profile 1's values: a store change of at least 2 points, 10 trusted pairs, the median",
        )
        self.assertIn("claude/anthropic: 20 reports, 19 pairs", lines)
        self.assertIn("anthropic Five hours: 0.10 from 10 trusted pairs, 0.08 to 0.13; 9 not trusted", lines)
        self.assertIn("Proposed: profile 2, not in use until the owner approves it with arbol vigor approve 2", lines)
        learned = self.document("learn")
        self.assertEqual(
            (learned["profile"], learned["proposed"]["version"], learned["proposed"]["approval"]), (1, 3, "proposed")
        )
        self.assertFalse(learned["proposed"]["inUse"])
        self.assertEqual(learned["subscriptions"], [{"subscription": "claude/anthropic", "reports": 20, "pairs": 19}])
        self.assertEqual(len(learned["observations"]), 19)
        self.assertEqual(sum(o["trusted"] for o in learned["observations"]), 10)
        self.assertEqual([v["subscription"] for v in learned["vigor"]], ["claude/anthropic"])
        status, out = self.answer("profiles", "--text")
        lines = out.splitlines()
        self.assertTrue(
            lines[0].startswith(
                "Profile 1 · proposed · in use · even pace, placeholder 0.1 for every other gate · recorded "
            ),
            lines[0],
        )
        self.assertTrue(
            lines[1].startswith(
                "Profile 2 · proposed · even pace, placeholder 0.1 for every other gate · anthropic Five hours 0.10 learned from 10 pairs, 0.08 to 0.13 · recorded "
            ),
            lines[1],
        )
        self.assertEqual(self.document("approve", "2"), {"approved": 2, "inUse": 2})
        self.assertEqual(self.document("profiles")["inUse"], 2)
        status, out = self.answer("approve", "3", "--text")
        self.assertEqual(
            (status, out), (0, "Profile 3 approved: the calculation uses it from the next tick or refresh.\n")
        )

    async def test_what_the_profile_commands_refuse(self) -> None:
        """radar.learn-command-refusals"""
        await self.history(RATIOS[:3])
        self.assertIsNone(self.document("learn")["proposed"])  # too few pairs: nothing written
        self.assertEqual(await self.count("vigor_profiles"), 1)
        for value in ("x", "0", "02", "-1"):
            with self.subTest(value=value):
                self.refused("invalid_input", "approve", value)
        self.refused("unknown_profile", "approve", "9")
        self.refused("invalid_input", "learn", "--refresh")
        self.refused("invalid_input", "approve")
        self.assertEqual(self.document("approve", "1"), {"approved": 1, "inUse": 1})
        self.refused("already_approved", "approve", "1")
        await self.db.execute("DROP TABLE vigor_results")
        try:
            self.refused("layout_incomplete", "profiles")
        finally:
            await self.db.execute((ROOT / "tests/radar/layout.sql").read_text(encoding="utf-8"))
