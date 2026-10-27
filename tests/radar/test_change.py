"""Subscriptions Vigor: predicted windows, the next change, stale and unknown, with fixed reports, clock and profile (SGM-1)."""

from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_radar.model import FIRST_PROFILE, Window  # noqa: E402
from arbol_radar.vigor import compute, predict  # noqa: E402
from radar.support import CLAUDE, MONDAY, at, by_label, claude, report, window  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
