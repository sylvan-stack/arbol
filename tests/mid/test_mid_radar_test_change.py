"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import radar.test_change as _support
from radar.test_change import (
    CLAUDE,
    CODEX,
    FIRST_PROFILE,
    FIVE_HOURS,
    KIMI,
    MONDAY,
    Path,
    PredictedWindows,
    Profile,
    RESET,
    ROOT,
    Rejected,
    Stale,
    TheNextChange,
    Unknown,
    Weight,
    Window,
    ZAI,
    at,
    by_label,
    claude,
    codex,
    compute,
    kimi,
    next_change,
    predict,
    report,
    stale_after,
    sys,
    timedelta,
    unittest,
    unknown_reason,
    window,
)


class TheNextChange(_support.TheNextChange):


# TEST-TIER-BEGIN tests/radar/test_change.py::TheNextChange.test_an_exhausted_subscription_recovers_when_its_last_reached_gating_window_resets
    def test_an_exhausted_subscription_recovers_when_its_last_reached_gating_window_resets(self) -> None:
        """radar.next-change-exhausted-still"""
        windows = [
            window("session", "5-hour window", resource=None, used=50, resets=at(hours=2, minutes=30), minutes=300),
            window("weekly", "Weekly window", resource=None, used=100, resets=at(days=1), minutes=10080, reached=True),
        ]
        result = compute(report(CODEX, windows), FIRST_PROFILE, MONDAY)
        self.assertEqual((result.exhausted, result.vigor), (True, 0.0))
        # Not the unreached five-hour window's reset at 12:30, where the week still gates it: the week's reset (SGM-D34).
        self.assertEqual(result.next_change, MONDAY + timedelta(days=1))
        at_week = compute(report(CODEX, windows), FIRST_PROFILE, MONDAY + timedelta(days=1))
        assert at_week.vigor is not None
        self.assertEqual((at_week.exhausted, at_week.predicted), (False, True))  # the week predicted fresh
        self.assertAlmostEqual(at_week.vigor, 0.1 * (1 - 210 / 300))  # the five-hour window, fresh since 08:30
        self.assertEqual(result.next_value, at_week.vigor)
        both = [
            window("session", "5-hour window", resource=None, used=100, resets=at(hours=2, minutes=30), reached=True),
            window("weekly", "Weekly window", resource=None, used=100, resets=at(days=1), minutes=10080, reached=True),
        ]
        two = compute(report(CODEX, both), FIRST_PROFILE, MONDAY)
        self.assertEqual((two.exhausted, two.next_change), (True, MONDAY + timedelta(days=1)))  # the last to reset
        self.assertEqual(two.next_value, at_week.vigor)
# TEST-TIER-END tests/radar/test_change.py::TheNextChange.test_an_exhausted_subscription_recovers_when_its_last_reached_gating_window_resets
