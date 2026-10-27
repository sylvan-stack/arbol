"""Subscriptions Vigor: predicted windows, the next change, stale and unknown, with fixed reports, clock and profile (SGM-1)."""

from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_radar.model import FIRST_PROFILE, Profile, Rejected, Weight, Window, stale_after  # noqa: E402
from arbol_radar.vigor import compute, next_change, predict, unknown_reason  # noqa: E402
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

RESET = MONDAY + timedelta(hours=3, minutes=20)  # the worked example's five-hour reset, 13:20
FIVE_HOURS = timedelta(hours=5)


class PredictedWindows(unittest.TestCase):
    """A fresh window after a reset without a newer report (SGM-1.7, SGM-D20)."""

    def test_a_passed_reset_predicts_the_fresh_window_and_marks_it(self) -> None:
        """radar.predict-fresh"""
        now = MONDAY + timedelta(hours=4)  # 14:00: the five-hour window reset at 13:20, the report is from 09:55
        result = compute(report(CLAUDE, claude()), FIRST_PROFILE, now)
        five, week = by_label(result)["Five hours"], by_label(result)["Seven days"]
        self.assertTrue(result.predicted)
        self.assertEqual(
            (five.predicted, five.used_percent, five.resets_at, five.window_minutes, five.reached),
            (True, 0.0, RESET + FIVE_HOURS, 300.0, False),
        )
        assert five.loss is not None and week.loss is not None and result.vigor is not None
        self.assertAlmostEqual(five.loss, 1 - 260 / 300)  # forty minutes into the fresh window, nothing spent
        self.assertEqual((week.predicted, week.used_percent, week.resets_at), (False, 20.0, MONDAY + timedelta(days=3)))
        self.assertAlmostEqual(week.loss, 0.8 - 4080 / 10080)
        self.assertAlmostEqual(result.vigor, 0.1 * five.loss + week.loss)
        before = compute(report(CLAUDE, claude()), FIRST_PROFILE, MONDAY)
        self.assertFalse(before.predicted)
        self.assertEqual([entry.predicted for entry in before.windows], [False, False])

    def test_two_passed_resets_predict_the_window_two_lengths_later(self) -> None:
        """radar.predict-two-resets"""
        now = MONDAY + timedelta(hours=9)  # 19:00: 13:20 and 18:20 passed
        five = by_label(compute(report(CLAUDE, claude()), FIRST_PROFILE, now))["Five hours"]
        self.assertEqual((five.predicted, five.used_percent, five.resets_at), (True, 0.0, RESET + 2 * FIVE_HOURS))
        delivered = report(CLAUDE, claude()).windows[0]
        self.assertEqual(predict(delivered, now).resets_at, RESET + 2 * FIVE_HOURS)
        self.assertEqual(predict(delivered, RESET + 2 * FIVE_HOURS).resets_at, RESET + 3 * FIVE_HOURS)
        self.assertEqual(predict(delivered, MONDAY + timedelta(days=30)).resets_at, RESET + 144 * FIVE_HOURS)

    def test_the_prediction_starts_at_the_reset_and_not_before(self) -> None:
        """radar.predict-at-the-reset"""
        delivered = report(CLAUDE, claude()).windows[0]
        self.assertIs(predict(delivered, RESET - timedelta(seconds=1)), delivered)
        self.assertIs(predict(delivered, MONDAY), delivered)
        fresh = predict(delivered, RESET)
        self.assertEqual((fresh.predicted, fresh.used_percent, fresh.resets_at), (True, 0.0, RESET + FIVE_HOURS))
        self.assertEqual(
            (fresh.kind, fresh.label, fresh.resource, fresh.window_minutes, fresh.scope, fresh.report),
            ("session", "Five hours", "tokens", 300.0, "subscription", "r1"),
        )
        self.assertFalse(delivered.predicted)  # the delivered window is unchanged

    def test_a_reached_window_is_predicted_fresh_with_its_reached_flag_cleared(self) -> None:
        """radar.predict-reached-cleared"""
        now = MONDAY + timedelta(hours=4)
        reached = report(CLAUDE, claude(100, reached=True), extra={"isUsingOverage": False})
        self.assertTrue(compute(reached, FIRST_PROFILE, MONDAY).exhausted)
        result = compute(reached, FIRST_PROFILE, now)
        five = by_label(result)["Five hours"]
        self.assertEqual(
            (result.exhausted, result.predicted, five.reached, five.used_percent), (False, True, False, 0.0)
        )
        assert result.vigor is not None
        self.assertAlmostEqual(result.vigor, 0.1 * (1 - 260 / 300) + 0.8 - 4080 / 10080)
        over = report(CLAUDE, [window("session", "Five hours", used=130, resets=at(hours=3, minutes=20)), claude()[1]])
        fresh = predict(over.windows[0], now)
        self.assertEqual((fresh.used_percent, fresh.raw_used_percent), (0.0, None))

    def test_a_window_with_an_unknown_field_is_not_predicted(self) -> None:
        """radar.predict-unknown-kept"""
        now = MONDAY + timedelta(hours=4)
        for name, w in (
            ("usedPercent", window("session", "Five hours", used=None, resets=at(hours=3, minutes=20))),
            ("usedPercent", window("session", "Five hours", used=-5, resets=at(hours=3, minutes=20))),
            ("windowMinutes", window("session", "Five hours", used=35, resets=at(hours=3, minutes=20), minutes=None)),
            ("resetsAt", window("session", "Five hours", used=35, resets=None)),
        ):
            with self.subTest(field=name):
                delivered = report(CLAUDE, [w, claude()[1]]).windows[0]
                self.assertIs(predict(delivered, now), delivered)
                five = by_label(compute(report(CLAUDE, [w, claude()[1]]), FIRST_PROFILE, now))["Five hours"]
                self.assertEqual(
                    (five.predicted, five.role, five.reason), (False, "shown", f"{name} unknown; shown, not summed")
                )
        kept = Window(
            "session", "Five hours", "tokens", None, RESET, 300, False, raw_used_percent=-5, unknown="usedPercent"
        )
        self.assertIs(predict(kept, now), kept)

    def test_a_newer_report_replaces_the_prediction(self) -> None:
        """radar.predict-newer-report"""
        now = MONDAY + timedelta(hours=9)  # 19:00
        old = compute(report(CLAUDE, claude()), FIRST_PROFILE, now)
        self.assertTrue(old.predicted)
        newer = report(
            CLAUDE,
            [
                window("session", "Five hours", used=12, resets=at(hours=13, minutes=20), minutes=300),
                window("weekly", "Seven days", used=23, resets=at(days=3), minutes=10080),
            ],
            fetched=at(hours=8, minutes=30),
            report_id="r2",
        )
        result = compute(newer, FIRST_PROFILE, now)
        five = by_label(result)["Five hours"]
        self.assertEqual((result.predicted, result.report), (False, "r2"))
        self.assertEqual((five.predicted, five.used_percent, five.resets_at), (False, 12.0, RESET + 2 * FIVE_HOURS))
        self.assertEqual(by_label(old)["Five hours"].resets_at, five.resets_at)  # the prediction had the same reset


class TheNextChange(unittest.TestCase):
    """The earliest reset among the windows and the Vigor at that moment on the predicted windows (SGM-1.6, SGM-D16)."""

    def test_the_claude_example_changes_at_13_20_to_0_39(self) -> None:
        """radar.next-change-claude"""
        result = compute(report(CLAUDE, claude(), extra={"isUsingOverage": False}), FIRST_PROFILE, MONDAY)
        assert result.vigor is not None and result.next_value is not None
        self.assertEqual((round(result.vigor, 2), result.exhausted, result.next_change), (0.37, False, RESET))
        self.assertAlmostEqual(result.next_value, 0.8 - 4120 / 10080)
        self.assertEqual(round(result.next_value, 2), 0.39)
        self.assertFalse(result.predicted)  # the prediction for 13:20 does not mark the result of 10:00

    def test_the_exhausted_claude_example_recovers_at_13_20_to_0_39(self) -> None:
        """radar.recovery-claude"""
        reached = report(CLAUDE, claude(100, reached=True), extra={"isUsingOverage": False})
        result = compute(reached, FIRST_PROFILE, MONDAY)
        assert result.next_value is not None
        self.assertEqual((result.exhausted, result.vigor, result.next_change), (True, 0.0, RESET))
        self.assertAlmostEqual(result.next_value, 0.8 - 4120 / 10080)
        self.assertEqual(round(result.next_value, 2), 0.39)
        at_reset = compute(reached, FIRST_PROFILE, RESET)  # the recovery, computed at that moment
        assert at_reset.vigor is not None
        self.assertEqual((at_reset.exhausted, at_reset.predicted, round(at_reset.vigor, 2)), (False, True, 0.39))
        self.assertEqual(result.next_value, at_reset.vigor)

    def test_the_earliest_reset_decides_whatever_the_window_counts(self) -> None:
        """radar.next-change-earliest"""
        result = compute(report(KIMI, kimi()), FIRST_PROFILE, MONDAY)
        assert result.vigor is not None and result.next_value is not None
        self.assertEqual((round(result.vigor, 2), result.next_change), (0.47, MONDAY + timedelta(hours=1)))
        self.assertAlmostEqual(result.next_value, 0.6 - 5700 / 43200)  # the month an hour on; the calls window fresh
        codex_result = compute(report(CODEX, codex()), FIRST_PROFILE, MONDAY)
        assert codex_result.next_value is not None
        self.assertEqual(codex_result.next_change, MONDAY + timedelta(hours=2, minutes=30))
        self.assertAlmostEqual(codex_result.next_value, 0.3 - 1290 / 10080)

    def test_a_subscription_still_exhausted_at_the_next_change_has_the_value_0(self) -> None:
        """radar.next-change-exhausted-still"""
        windows = [
            window("session", "5-hour window", resource=None, used=50, resets=at(hours=2, minutes=30), minutes=300),
            window("weekly", "Weekly window", resource=None, used=100, resets=at(days=1), minutes=10080, reached=True),
        ]
        result = compute(report(CODEX, windows), FIRST_PROFILE, MONDAY)
        self.assertEqual((result.exhausted, result.vigor), (True, 0.0))
        self.assertEqual((result.next_change, result.next_value), (MONDAY + timedelta(hours=2, minutes=30), 0.0))
        at_week = compute(report(CODEX, windows), FIRST_PROFILE, MONDAY + timedelta(days=1))
        assert at_week.vigor is not None
        self.assertEqual((at_week.exhausted, at_week.predicted), (False, True))  # the week predicted fresh
        self.assertAlmostEqual(at_week.vigor, 0.1 * (1 - 210 / 300))  # the five-hour window, fresh since 08:30

    def test_a_predicted_window_sets_the_next_change_too(self) -> None:
        """radar.next-change-predicted"""
        now = MONDAY + timedelta(hours=4)
        result = compute(report(CLAUDE, claude()), FIRST_PROFILE, now)
        assert result.next_value is not None
        self.assertEqual((result.predicted, result.next_change), (True, RESET + FIVE_HOURS))
        self.assertAlmostEqual(result.next_value, 0.8 - 3820 / 10080)  # the week at 18:20; the five-hour window fresh

    def test_the_store_reset_drops_the_value(self) -> None:
        """radar.next-change-store-reset"""
        windows = [
            window("session", "Five hours", used=0, resets=at(hours=3), minutes=300),
            window("weekly", "Seven days", used=0, resets=at(hours=2), minutes=10080),
        ]
        result = compute(report(CLAUDE, windows), FIRST_PROFILE, MONDAY)
        assert result.next_value is not None
        self.assertEqual(result.vigor, 1.0)
        self.assertEqual(result.next_change, MONDAY + timedelta(hours=2))
        self.assertAlmostEqual(result.next_value, 0.1 * (1 - 60 / 300))  # the week fresh, the five-hour window alone

    def test_no_reset_time_means_no_next_change(self) -> None:
        """radar.next-change-none"""
        windows = [window("other", "MCP", resource="calls", used=10, resets=None, minutes=43200)]
        result = compute(report(ZAI, windows), FIRST_PROFILE, MONDAY)
        self.assertEqual((result.next_change, result.next_value), (None, None))
        self.assertEqual(
            next_change(report(ZAI, windows), report(ZAI, windows).windows, FIRST_PROFILE, MONDAY), (None, None)
        )
        empty = compute(report(ZAI, [], outcome="unsupported", message="no allowance reading"), FIRST_PROFILE, MONDAY)
        self.assertEqual((empty.next_change, empty.next_value), (None, None))


class Stale(unittest.TestCase):
    """A result on a report older than the shortest window that is summed or can exhaust the Subscription (SGM-1.8)."""

    def test_a_claude_result_is_stale_after_five_idle_hours_and_still_computed(self) -> None:
        """radar.stale-claude-five-hours"""
        now = MONDAY + timedelta(hours=5)  # 15:00; the report is from 09:55
        result = compute(report(CLAUDE, claude()), FIRST_PROFILE, now)
        self.assertEqual(result.stale, timedelta(hours=5, minutes=5))
        assert result.vigor is not None
        self.assertEqual(
            (result.predicted, round(result.vigor, 2)), (True, 0.43)
        )  # the five-hour window fresh at 13:20
        self.assertEqual(by_label(result)["Seven days"].used_percent, 20.0)  # the floor the report gives
        self.assertIsNone(compute(report(CLAUDE, claude()), FIRST_PROFILE, MONDAY).stale)

    def test_stale_begins_when_the_report_is_older_than_the_window_not_at_its_length(self) -> None:
        """radar.stale-boundary"""
        exactly = MONDAY + timedelta(hours=4, minutes=55)  # five hours after 09:55
        self.assertIsNone(compute(report(CLAUDE, claude()), FIRST_PROFILE, exactly).stale)
        just_after = exactly + timedelta(seconds=1)
        self.assertEqual(
            compute(report(CLAUDE, claude()), FIRST_PROFILE, just_after).stale, FIVE_HOURS + timedelta(seconds=1)
        )

    def test_a_kimi_result_is_stale_after_five_hours_by_its_window_of_calls(self) -> None:
        """radar.stale-kimi-calls"""
        now = MONDAY + timedelta(hours=5, minutes=30)
        result = compute(report(KIMI, kimi()), FIRST_PROFILE, now)
        self.assertEqual(result.stale, timedelta(hours=5, minutes=35))
        assert result.vigor is not None
        self.assertEqual(round(result.vigor, 2), 0.47)
        self.assertEqual(by_label(result)["Five hours"].predicted, True)  # the calls window reset at 11:00
        monthly_only = compute(report(KIMI, kimi()[1:]), FIRST_PROFILE, now)
        self.assertIsNone(monthly_only.stale)  # with its credit windows alone the report is stale after a month
        self.assertEqual(
            compute(report(KIMI, kimi()[1:]), FIRST_PROFILE, MONDAY + timedelta(days=30, seconds=1)).stale,
            timedelta(days=30, minutes=5, seconds=1),
        )

    def test_the_rule_is_the_shortest_window_that_is_summed_or_can_exhaust(self) -> None:
        """radar.stale-rule-profile"""
        self.assertEqual(FIRST_PROFILE.stale_rule, "shortest-window")
        self.assertEqual(stale_after(FIRST_PROFILE, report(CLAUDE, claude()).windows), FIVE_HOURS)
        self.assertEqual(stale_after(FIRST_PROFILE, report(CODEX, codex()).windows), FIVE_HOURS)
        self.assertEqual(stale_after(FIRST_PROFILE, report(KIMI, kimi()).windows), FIVE_HOURS)
        tool_scoped = report(
            ZAI,
            [
                window("weekly", "Weekly", used=20, resets=at(days=3), minutes=10080),
                window("other", "MCP", resource="calls", used=10, resets=at(days=20), minutes=43200),
            ],
        )
        self.assertEqual(stale_after(FIRST_PROFILE, tool_scoped.windows), timedelta(days=7))
        shorter_tool = report(ZAI, [window("other", "MCP", resource="calls", used=10, resets=at(hours=1), minutes=60)])
        self.assertIsNone(stale_after(FIRST_PROFILE, shorter_tool.windows))  # a tool's window alone sets no rule
        no_length = report(CLAUDE, [window("session", "Five hours", used=35, resets=at(hours=3), minutes=None)])
        self.assertIsNone(stale_after(FIRST_PROFILE, no_length.windows))
        self.assertIsNone(stale_after(FIRST_PROFILE, ()))
        with self.assertRaises(Rejected) as caught:
            Profile(1, "proposed", "even", Weight(0.1), stale_rule="fixed")
        self.assertEqual(caught.exception.field, "staleRule")


class Unknown(unittest.TestCase):
    """A result that cannot be computed is unknown with its reason, never zero (SGM-1.9, SGM-D19)."""

    def test_a_token_window_of_an_ok_report_lacking_a_field_names_the_field_and_the_family(self) -> None:
        """radar.unknown-missing-field"""
        windows = [codex()[0], window("weekly", "Weekly window", resource=None, used=70, resets=None, minutes=10080)]
        result = compute(report(CODEX, windows), FIRST_PROFILE, MONDAY)
        self.assertEqual((result.vigor, result.unknown), (None, "resetsAt missing in the chatgpt report"))
        self.assertEqual((result.exhausted, result.next_change, result.next_value), (False, None, None))
        self.assertEqual([entry.label for entry in result.windows], ["5-hour window", "Weekly window"])  # still shown
        self.assertEqual(by_label(result)["Weekly window"].reason, "resetsAt unknown; shown, not summed")
        for name, w in (
            (
                "usedPercent",
                window("weekly", "Weekly window", resource=None, used=None, resets=at(days=1), minutes=10080),
            ),
            (
                "windowMinutes",
                window("weekly", "Weekly window", resource=None, used=70, resets=at(days=1), minutes=None),
            ),
        ):
            with self.subTest(field=name):
                r = report(CODEX, [codex()[0], w])
                self.assertEqual(unknown_reason(r), f"{name} missing in the chatgpt report")
                self.assertIsNone(compute(r, FIRST_PROFILE, MONDAY).vigor)
        calls = report(KIMI, [window("session", "Five hours", resource="calls", used=70, resets=None), *kimi()[1:]])
        self.assertIsNone(unknown_reason(calls))  # a window that is not summed may lack a field
        assert compute(calls, FIRST_PROFILE, MONDAY).vigor is not None

    def test_a_used_share_below_0_is_named_as_missing(self) -> None:
        """radar.unknown-below-zero"""
        r = report(CLAUDE, [window("session", "Five hours", used=-5, resets=at(hours=3, minutes=20)), claude()[1]])
        result = compute(r, FIRST_PROFILE, MONDAY)
        self.assertEqual((result.vigor, result.unknown), (None, "usedPercent missing in the anthropic report"))
        self.assertEqual(by_label(result)["Five hours"].used_percent, None)
        later = compute(r, FIRST_PROFILE, MONDAY + timedelta(hours=4))  # the reset passed: the defect stays visible
        self.assertEqual(
            (later.vigor, later.unknown, later.predicted), (None, "usedPercent missing in the anthropic report", False)
        )

    def test_an_unsupported_family_is_a_known_gap(self) -> None:
        """radar.unknown-unsupported"""
        r = report(ZAI, [], outcome="unsupported", message="no allowance reading for zai through Pi")
        result = compute(r, FIRST_PROFILE, MONDAY)
        self.assertEqual((result.vigor, result.unknown), (None, "allowance not supported for zai"))
        self.assertEqual((result.windows, result.exhausted, result.stale, result.next_change), ((), False, None, None))
        self.assertEqual(result.report, "r1")

    def test_a_sign_in_need_and_an_unreachable_vendor_carry_the_message(self) -> None:
        """radar.unknown-outcome-message"""
        signed_out = report(KIMI, [], outcome="needs_sign_in", message="the token was rejected")
        self.assertEqual(compute(signed_out, FIRST_PROFILE, MONDAY).unknown, "needs_sign_in: the token was rejected")
        unreachable = report(CODEX, [], outcome="unavailable", message="the app server did not answer")
        self.assertEqual(
            compute(unreachable, FIRST_PROFILE, MONDAY).unknown, "unavailable: the app server did not answer"
        )
        silent = report(CODEX, [], outcome="unavailable")
        self.assertEqual(compute(silent, FIRST_PROFILE, MONDAY).unknown, "unavailable")

    def test_no_report_yet(self) -> None:
        """radar.unknown-no-report"""
        result = compute(None, FIRST_PROFILE, MONDAY, subscription=ZAI)
        self.assertEqual((result.subscription, result.moment, result.report, result.profile), (ZAI, MONDAY, None, 1))
        self.assertEqual(
            (result.vigor, result.unknown, result.windows, result.exhausted), (None, "no report yet", (), False)
        )
        self.assertEqual(
            (result.stale, result.predicted, result.next_change, result.next_value), (None, False, None, None)
        )
        self.assertEqual(unknown_reason(None), "no report yet")
        with self.assertRaises(Rejected) as caught:
            compute(None, FIRST_PROFILE, MONDAY)
        self.assertEqual(caught.exception.field, "subscription")

    def test_unknown_is_never_zero_and_never_blank(self) -> None:
        """radar.unknown-never-zero"""
        cases = [
            report(
                CODEX,
                [codex()[0], window("weekly", "Weekly window", resource=None, used=70, resets=None, minutes=10080)],
            ),
            report(ZAI, [], outcome="unsupported", message="why"),
            report(KIMI, [], outcome="needs_sign_in", message="why"),
            report(CODEX, [], outcome="unavailable"),
            None,
        ]
        for r in cases:
            with self.subTest(report=r):
                result = compute(r, FIRST_PROFILE, MONDAY, subscription=ZAI)
                self.assertIsNone(result.vigor)
                self.assertTrue(result.unknown)
                if r is None or r.outcome != "ok":
                    self.assertEqual(result.notes, ())
        known = compute(report(CLAUDE, claude()), FIRST_PROFILE, MONDAY)
        self.assertEqual((known.unknown, unknown_reason(report(CLAUDE, claude()))), (None, None))
        assert known.vigor is not None

    def test_an_ok_report_without_a_token_or_credit_window_cannot_be_summed(self) -> None:
        """radar.unknown-no-summed-window"""
        only_calls = compute(report(KIMI, kimi()[:1]), FIRST_PROFILE, MONDAY)
        self.assertEqual(
            (only_calls.vigor, only_calls.unknown), (None, "no token or credit window in the kimi-coding report")
        )
        self.assertEqual(by_label(only_calls)["Five hours"].role, "shown")
        empty = compute(report(CODEX, []), FIRST_PROFILE, MONDAY)
        self.assertEqual((empty.vigor, empty.unknown), (None, "no token or credit window in the chatgpt report"))
        reached = compute(report(KIMI, kimi(five_reached=True)[:1]), FIRST_PROFILE, MONDAY)
        self.assertEqual((reached.vigor, reached.exhausted), (None, True))  # exhausted is a fact; the value is unknown

    def test_a_missing_field_keeps_an_exhausted_subscription_unknown(self) -> None:
        """radar.unknown-exhausted"""
        windows = [claude(100, reached=True)[0], window("weekly", "Seven days", used=20, resets=None, minutes=10080)]
        result = compute(report(CLAUDE, windows, extra={"isUsingOverage": False}), FIRST_PROFILE, MONDAY)
        self.assertEqual((result.vigor, result.exhausted), (None, True))
        self.assertEqual(result.unknown, "resetsAt missing in the anthropic report")
        self.assertEqual((result.next_change, result.next_value), (None, None))


if __name__ == "__main__":
    unittest.main()
