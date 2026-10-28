"""Subscriptions Vigor: the loss of a window and the Vigor of a Subscription, with fixed reports, clock and profile (SGM-1)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_radar.model import Rejected  # noqa: E402


class Records(unittest.TestCase):
    """The records of the Interface, the used-share rules and what the Interface rejects."""

    def rejected(self, field: str, call: Any, *args: Any, **kwargs: Any) -> None:
        with self.assertRaises(Rejected) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.field, field)


# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::Records.test_a_used_share_below_0_marks_the_window_unknown_with_the_field_named
#     def test_a_used_share_below_0_marks_the_window_unknown_with_the_field_named(self) -> None:
#         """radar.used-share-below-zero"""
#         five = report(CLAUDE, [window("session", "Five hours", used=-5, resets=at(hours=3), minutes=300)]).windows[0]
#         self.assertEqual((five.used_percent, five.raw_used_percent, five.unknown), (None, -5.0, "usedPercent"))
#         self.assertEqual((five.missing, five.known), ("usedPercent", False))
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::Records.test_a_used_share_below_0_marks_the_window_unknown_with_the_field_named

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::Records.test_a_used_share_above_100_counts_as_100_with_the_raw_value_kept
#     def test_a_used_share_above_100_counts_as_100_with_the_raw_value_kept(self) -> None:
#         """radar.used-share-above-hundred"""
#         r = report(CLAUDE, [window("session", "Five hours", used=130, resets=at(hours=3), minutes=300)])
#         five = r.windows[0]
#         self.assertEqual(
#             (five.used_percent, five.raw_used_percent, five.unknown, five.known), (100.0, 130.0, None, True)
#         )
#         self.assertEqual(r.delivered[0]["usedPercent"], 130)
#         exact = report(CLAUDE, [window("session", "Five hours", used=100, resets=at(hours=3), minutes=300)]).windows[0]
#         self.assertEqual((exact.used_percent, exact.raw_used_percent), (100.0, None))
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::Records.test_a_used_share_above_100_counts_as_100_with_the_raw_value_kept

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::Records.test_a_weight_outside_0_to_1_is_rejected
#     def test_a_weight_outside_0_to_1_is_rejected(self) -> None:
#         """radar.reject-weight"""
#         for value in (-0.1, 1.5, float("nan"), float("inf")):
#             with self.subTest(value=value):
#                 self.rejected("weight", Profile, 1, "proposed", "even", Weight(value))
#                 self.rejected(
#                     "weight",
#                     Profile,
#                     1,
#                     "proposed",
#                     "even",
#                     Weight(0.1),
#                     gates={("anthropic", "Five hours"): Weight(value, "learned")},
#                 )
#         Profile(1, "proposed", "even", Weight(0.0))
#         Profile(1, "proposed", "even", Weight(1.0))
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::Records.test_a_weight_outside_0_to_1_is_rejected

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::Records.test_a_store_weight_other_than_1_is_rejected
#     def test_a_store_weight_other_than_1_is_rejected(self) -> None:
#         """radar.reject-store-weight"""
#         for value in (0.9, 0.0, 1.5):
#             with self.subTest(value=value):
#                 self.rejected("storeWeight", Profile, 1, "proposed", "even", Weight(0.1), store_weight=value)
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::Records.test_a_store_weight_other_than_1_is_rejected

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::Records.test_a_nonpositive_length_is_rejected
#     def test_a_nonpositive_length_is_rejected(self) -> None:
#         """radar.reject-length"""
#         for value in (0, -5, float("nan")):
#             with self.subTest(value=value):
#                 self.rejected(
#                     "windowMinutes",
#                     report,
#                     CLAUDE,
#                     [window("session", "Five hours", used=1, resets=at(hours=1), minutes=value)],
#                 )
#                 self.rejected("windowMinutes", Window, "session", "Five hours", "tokens", 1, MONDAY, value, False)
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::Records.test_a_nonpositive_length_is_rejected

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::Records.test_a_reset_time_before_the_fetch_time_is_rejected
#     def test_a_reset_time_before_the_fetch_time_is_rejected(self) -> None:
#         """radar.reject-reset-before-fetch"""
#         self.rejected(
#             "resetsAt", report, CLAUDE, [window("session", "Five hours", used=1, resets="2026-10-26T09:54:59Z")]
#         )
#         report(CLAUDE, [window("session", "Five hours", used=1, resets="2026-10-26T09:55:00Z")])  # equal is accepted
#         early = Window("session", "Five hours", "tokens", 1, MONDAY - timedelta(seconds=1), 300, False)
#         self.rejected("resetsAt", Report, "r1", CLAUDE, "ok", MONDAY, (early,), (), {}, MONDAY)
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::Records.test_a_reset_time_before_the_fetch_time_is_rejected

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::Records.test_a_profile_version_the_calculation_does_not_know_is_rejected
#     def test_a_profile_version_the_calculation_does_not_know_is_rejected(self) -> None:
#         """radar.reject-profile-version"""
#         # A version is a whole number from 1; one the Root's table does not record is refused where it is asked for
#         # (`radar.learn-approve-refusals`), since a learned profile is recorded there (SGM-D37).
#         for version in (0, -1, True):
#             with self.subTest(version=version):
#                 self.rejected("version", Profile, version, "proposed", "even", Weight(0.1))
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::Records.test_a_profile_version_the_calculation_does_not_know_is_rejected

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::Records.test_a_malformed_report_is_rejected_with_its_field_named
#     def test_a_malformed_report_is_rejected_with_its_field_named(self) -> None:
#         """radar.reject-malformed"""
#         base = window("session", "Five hours", used=1, resets=at(hours=1))
#         cases: list[tuple[str, dict[str, Any]]] = [
#             ("outcome", {"outcome": "fine", "fetchedAt": at(), "windows": []}),
#             ("outcome", {"fetchedAt": at(), "windows": []}),
#             ("fetchedAt", {"outcome": "ok", "windows": []}),
#             ("fetchedAt", {"outcome": "ok", "fetchedAt": "2026-10-26T09:55:00", "windows": []}),
#             ("windows", {"outcome": "ok", "fetchedAt": at(), "windows": {}}),
#             ("windows", {"outcome": "ok", "fetchedAt": at(), "windows": [1]}),
#             ("extra", {"outcome": "ok", "fetchedAt": at(), "windows": [], "extra": []}),
#             ("message", {"outcome": "unavailable", "fetchedAt": at(), "windows": [], "message": 5}),
#             ("label", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "label": ""}]}),
#             ("kind", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "kind": "daily"}]}),
#             ("resource", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "resource": 3}]}),
#             ("usedPercent", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "usedPercent": "35"}]}),
#             ("usedPercent", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "usedPercent": True}]}),
#             ("resetsAt", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "resetsAt": "soon"}]}),
#             (
#                 "resetsAt",
#                 {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "resetsAt": "2026-10-26T13:20:00"}]},
#             ),
#             ("windowMinutes", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "windowMinutes": "300"}]}),
#             ("limitReached", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "limitReached": 0}]}),
#         ]
#         for field, value in cases:
#             with self.subTest(field=field, value=value):
#                 self.rejected(field, Report.from_contract, CLAUDE, value, report_id="r1", arrived_at=MONDAY)
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::Records.test_a_malformed_report_is_rejected_with_its_field_named


class WindowsThatTakePart(unittest.TestCase):
    """Which windows take part in the sum, the store and the gates (SGM-1.2, SGM-D24, SGM-D25)."""

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::WindowsThatTakePart.test_only_tokens_and_credits_are_summed_and_an_absent_resource_counts_as_tokens
#     def test_only_tokens_and_credits_are_summed_and_an_absent_resource_counts_as_tokens(self) -> None:
#         """radar.take-part-resource"""
#         windows = [
#             window("other", "Tokens", resource="tokens", used=20, resets=at(days=1), minutes=10080),
#             window("other", "Credits", resource="credits", used=20, resets=at(days=1), minutes=1440),
#             window("other", "Calls", resource="calls", used=20, resets=at(days=1), minutes=1440),
#             window("other", "Unnamed", resource=None, used=20, resets=at(days=1), minutes=1440),
#             window("other", "Something else", resource="requests", used=20, resets=at(days=1), minutes=1440),
#         ]
#         result = compute(report(CODEX, windows), FIRST_PROFILE, MONDAY)
#         entries = by_label(result)
#         self.assertEqual(entries["Tokens"].role, "store")
#         self.assertEqual((entries["Credits"].role, entries["Credits"].counted_as), ("gate", "credits"))
#         self.assertEqual((entries["Calls"].role, entries["Calls"].reason), ("shown", "counts calls; shown, not summed"))
#         self.assertEqual(
#             (entries["Unnamed"].role, entries["Unnamed"].counted_as, entries["Unnamed"].assumed),
#             ("gate", "tokens", True),
#         )
#         self.assertEqual(entries["Something else"].role, "shown")
#         self.assertEqual(entries["Something else"].reason, "counts requests; shown, not summed")
#         self.assertEqual(result.notes, ("Unnamed: the chatgpt report names no resource; counted as tokens",))
#         assert entries["Calls"].loss is not None
#         self.assertEqual(round(entries["Calls"].loss, 2), 0.0)  # its loss is still computed and shown
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::WindowsThatTakePart.test_only_tokens_and_credits_are_summed_and_an_absent_resource_counts_as_tokens

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::WindowsThatTakePart.test_a_window_lacking_a_field_is_shown_and_not_summed
#     def test_a_window_lacking_a_field_is_shown_and_not_summed(self) -> None:
#         """radar.take-part-known"""
#         for name, w in (
#             ("usedPercent", window("weekly", "Seven days", used=None, resets=at(days=3), minutes=10080)),
#             ("usedPercent", window("weekly", "Seven days", used=-5, resets=at(days=3), minutes=10080)),
#             ("windowMinutes", window("weekly", "Seven days", used=20, resets=at(days=3), minutes=None)),
#             ("resetsAt", window("weekly", "Seven days", used=20, resets=None, minutes=10080)),
#         ):
#             with self.subTest(field=name, value=w):
#                 windows = [window("session", "Five hours", used=35, resets=at(hours=3, minutes=20), minutes=300), w]
#                 result = compute(report(CLAUDE, windows), FIRST_PROFILE, MONDAY)
#                 week = by_label(result)["Seven days"]
#                 self.assertEqual((week.role, week.loss, week.contribution), ("shown", None, None))
#                 self.assertEqual(week.reason, f"{name} unknown; shown, not summed")
#                 self.assertEqual(by_label(result)["Five hours"].role, "store")
#                 self.assertEqual((result.vigor, result.unknown), (None, f"{name} missing in the anthropic report"))
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::WindowsThatTakePart.test_a_window_lacking_a_field_is_shown_and_not_summed

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::WindowsThatTakePart.test_the_longest_window_is_the_store_and_shorter_ones_gates
#     def test_the_longest_window_is_the_store_and_shorter_ones_gates(self) -> None:
#         """radar.store-longest"""
#         windows = [
#             window("session", "Five hours", used=0, resets=at(minutes=1), minutes=300),
#             window("weekly", "Seven days", used=0, resets=at(minutes=1), minutes=10080),
#             window("other", "A day", used=0, resets=at(minutes=1), minutes=1440),
#         ]
#         result = compute(report(CLAUDE, windows), FIRST_PROFILE, MONDAY)
#         roles = {entry.label: (entry.role, entry.weight) for entry in result.windows}
#         self.assertEqual(roles, {"Five hours": ("gate", 0.1), "Seven days": ("store", 1.0), "A day": ("gate", 0.1)})
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::WindowsThatTakePart.test_the_longest_window_is_the_store_and_shorter_ones_gates

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::WindowsThatTakePart.test_among_equal_lengths_the_coding_product_window_is_the_store
#     def test_among_equal_lengths_the_coding_product_window_is_the_store(self) -> None:
#         """radar.store-coding-product"""
#         windows = list(reversed(kimi()))  # the total delivered first: the order does not decide
#         result = compute(report(KIMI, windows), FIRST_PROFILE, MONDAY)
#         roles = {entry.label: entry.role for entry in result.windows}
#         self.assertEqual(
#             roles, {"Monthly, all Kimi products": "shown", "Monthly, Kimi Code": "store", "Five hours": "shown"}
#         )
#         self.assertEqual(result.windows[0].label, "Monthly, all Kimi products")
#         total = by_label(result)["Monthly, all Kimi products"]
#         self.assertEqual(total.reason, "as long as the store and not the coding product's window; shown, not summed")
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::WindowsThatTakePart.test_among_equal_lengths_the_coding_product_window_is_the_store

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::WindowsThatTakePart.test_among_equal_lengths_without_a_coding_product_window_the_first_delivered_is_the_store
#     def test_among_equal_lengths_without_a_coding_product_window_the_first_delivered_is_the_store(self) -> None:
#         """radar.store-equal-fallback"""
#         windows = [
#             window("other", "Month A", resource="credits", used=40, resets=at(days=4), minutes=43200),
#             window("other", "Month B", resource="credits", used=10, resets=at(days=4), minutes=43200),
#         ]
#         result = compute(report(CODEX, windows), FIRST_PROFILE, MONDAY)
#         self.assertEqual([entry.role for entry in result.windows], ["store", "shown"])
#         assert result.vigor is not None
#         self.assertEqual(round(result.vigor, 2), 0.47)
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::WindowsThatTakePart.test_among_equal_lengths_without_a_coding_product_window_the_first_delivered_is_the_store

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::WindowsThatTakePart.test_a_report_without_numbers_gives_no_vigor
#     def test_a_report_without_numbers_gives_no_vigor(self) -> None:
#         """radar.outcome-not-ok"""
#         for outcome in ("needs_sign_in", "unavailable", "unsupported"):
#             with self.subTest(outcome=outcome):
#                 result = compute(report(ZAI, [], outcome=outcome, message="why"), FIRST_PROFILE, MONDAY)
#                 self.assertEqual((result.vigor, result.windows, result.exhausted, result.notes), (None, (), False, ()))
#                 self.assertIsNotNone(result.unknown)  # the reason is SYL-296's, checked in test_change
#         only_calls = compute(report(KIMI, kimi()[:1]), FIRST_PROFILE, MONDAY)
#         self.assertEqual((only_calls.vigor, only_calls.notes), (None, ()))
#         self.assertEqual(only_calls.unknown, "no token or credit window in the kimi-coding report")
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::WindowsThatTakePart.test_a_report_without_numbers_gives_no_vigor

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::WindowsThatTakePart.test_the_clock_is_an_argument_that_names_its_time_zone
#     def test_the_clock_is_an_argument_that_names_its_time_zone(self) -> None:
#         """radar.clock-argument"""
#         r = report(CLAUDE, claude())
#         with self.assertRaises(Rejected) as caught:
#             compute(r, FIRST_PROFILE, MONDAY.replace(tzinfo=None))
#         self.assertEqual(caught.exception.field, "clock")
#         later = compute(r, FIRST_PROFILE, MONDAY + timedelta(hours=2))
#         self.assertEqual(later.moment, MONDAY + timedelta(hours=2))
#         assert later.vigor is not None
#         self.assertGreater(later.vigor, 0.37)  # the same report two hours later loses more of the week
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::WindowsThatTakePart.test_the_clock_is_an_argument_that_names_its_time_zone


class LossOfAWindow(unittest.TestCase):
    """The loss of one window at its even pace (SGM-1.3)."""

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::LossOfAWindow.test_the_rows_of_the_worked_examples
#     def test_the_rows_of_the_worked_examples(self) -> None:
#         """radar.loss-rows"""
#         rows = [
#             ("Five hours", 35, 200, 300, 0.0),
#             ("Seven days", 20, 4320, 10080, 0.37),
#             ("Weekly window", 70, 1440, 10080, 0.16),
#             ("Five hours, calls", 70, 60, 300, 0.10),
#             ("Month, Kimi Code share", 40, 5760, 43200, 0.47),
#         ]
#         for label, used, minutes_left, length, expected in rows:
#             with self.subTest(window=label):
#                 w = Window("other", label, "tokens", used, MONDAY + timedelta(minutes=minutes_left), length, False)
#                 value = loss(w, MONDAY)
#                 assert value is not None
#                 self.assertEqual(round(value, 2), expected)
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::LossOfAWindow.test_the_rows_of_the_worked_examples

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::LossOfAWindow.test_never_below_zero_nothing_at_the_start_and_nearly_all_near_the_reset
#     def test_never_below_zero_nothing_at_the_start_and_nearly_all_near_the_reset(self) -> None:
#         """radar.loss-bounds"""
#         ahead = Window("session", "ahead of pace", "tokens", 90, MONDAY + timedelta(minutes=200), 300, False)
#         self.assertEqual(loss(ahead, MONDAY), 0.0)
#         at_start = Window("weekly", "full at its start", "tokens", 0, MONDAY + timedelta(minutes=10080), 10080, False)
#         self.assertEqual(loss(at_start, MONDAY), 0.0)
#         near_reset = Window("weekly", "a minute to go", "tokens", 10, MONDAY + timedelta(minutes=1), 10080, False)
#         near = loss(near_reset, MONDAY)
#         assert near is not None
#         self.assertAlmostEqual(near, 0.9 - 1 / 10080)
#         reached = Window("session", "reached", "tokens", 100, MONDAY + timedelta(minutes=100), 300, True)
#         self.assertEqual(loss(reached, MONDAY), 0.0)
#         reached_early = Window("session", "reached below 100", "tokens", 97, MONDAY + timedelta(minutes=100), 300, True)
#         self.assertEqual(loss(reached_early, MONDAY), 0.0)
#         passed = Window("session", "reset passed", "tokens", 40, MONDAY - timedelta(minutes=30), 300, False)
#         self.assertEqual(loss(passed, MONDAY), 0.6)
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::LossOfAWindow.test_never_below_zero_nothing_at_the_start_and_nearly_all_near_the_reset

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::LossOfAWindow.test_none_while_a_field_is_unknown
#     def test_none_while_a_field_is_unknown(self) -> None:
#         """radar.loss-unknown"""
#         for name, w in (
#             ("usedPercent", Window("session", "no share", "tokens", None, MONDAY + timedelta(minutes=100), 300, False)),
#             (
#                 "windowMinutes",
#                 Window("session", "no length", "tokens", 40, MONDAY + timedelta(minutes=100), None, False),
#             ),
#             ("resetsAt", Window("session", "no reset", "tokens", 40, None, 300, False)),
#             (
#                 "usedPercent",
#                 Window(
#                     "session",
#                     "below zero",
#                     "tokens",
#                     None,
#                     MONDAY,
#                     300,
#                     False,
#                     raw_used_percent=-5,
#                     unknown="usedPercent",
#                 ),
#             ),
#         ):
#             with self.subTest(field=name):
#                 self.assertIsNone(loss(w, MONDAY))
#                 self.assertEqual(w.missing, name)
#                 self.assertFalse(w.known)
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::LossOfAWindow.test_none_while_a_field_is_unknown


class WorkedExamples(unittest.TestCase):
    """The chapter's worked examples: Claude 0.37, Codex 0.16, Kimi Code 0.47, and 0.39 at 13:20 (SGM-1.1, SGM-1.4)."""

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::WorkedExamples.test_claude_loses_more_than_a_third_of_its_week
#     def test_claude_loses_more_than_a_third_of_its_week(self) -> None:
#         """radar.example-claude"""
#         result = compute(report(CLAUDE, claude(), extra={"isUsingOverage": False}), FIRST_PROFILE, MONDAY)
#         self.assertEqual((result.subscription, result.moment, result.report, result.profile), (CLAUDE, MONDAY, "r1", 1))
#         five, week = by_label(result)["Five hours"], by_label(result)["Seven days"]
#         self.assertEqual((five.role, five.weight, five.loss, five.contribution), ("gate", 0.1, 0.0, 0.0))
#         self.assertEqual((week.role, week.weight), ("store", 1.0))
#         assert week.loss is not None and week.contribution is not None and result.vigor is not None
#         self.assertAlmostEqual(week.loss, 0.8 - 4320 / 10080)
#         self.assertEqual(round(week.loss, 2), 0.37)
#         self.assertEqual(round(week.contribution, 2), 0.37)
#         self.assertEqual(round(result.vigor, 2), 0.37)
#         self.assertFalse(result.exhausted)
#         self.assertEqual((result.notes, result.unknown, result.stale, result.predicted), ((), None, None, False))
#         assert result.next_value is not None
#         self.assertEqual(
#             (result.next_change, round(result.next_value, 2)), (MONDAY + timedelta(hours=3, minutes=20), 0.39)
#         )
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::WorkedExamples.test_claude_loses_more_than_a_third_of_its_week

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::WorkedExamples.test_codex_week_with_a_day_to_go_counts_its_windows_as_tokens
#     def test_codex_week_with_a_day_to_go_counts_its_windows_as_tokens(self) -> None:
#         """radar.example-codex"""
#         result = compute(report(CODEX, codex()), FIRST_PROFILE, MONDAY)
#         five, week = by_label(result)["5-hour window"], by_label(result)["Weekly window"]
#         self.assertEqual(
#             (five.resource, five.counted_as, five.assumed, five.role, five.loss), (None, "tokens", True, "gate", 0.0)
#         )
#         self.assertEqual((week.counted_as, week.assumed, week.role), ("tokens", True, "store"))
#         assert week.loss is not None and result.vigor is not None
#         self.assertEqual(round(week.loss, 2), 0.16)
#         self.assertEqual(round(result.vigor, 2), 0.16)
#         self.assertEqual(
#             result.notes,
#             (
#                 "5-hour window: the chatgpt report names no resource; counted as tokens",
#                 "Weekly window: the chatgpt report names no resource; counted as tokens",
#             ),
#         )
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::WorkedExamples.test_codex_week_with_a_day_to_go_counts_its_windows_as_tokens

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::WorkedExamples.test_kimi_month_loses_nearly_half_with_calls_and_the_total_shown_only
#     def test_kimi_month_loses_nearly_half_with_calls_and_the_total_shown_only(self) -> None:
#         """radar.example-kimi"""
#         result = compute(report(KIMI, kimi()), FIRST_PROFILE, MONDAY)
#         entries = by_label(result)
#         calls, code, total = entries["Five hours"], entries["Monthly, Kimi Code"], entries["Monthly, all Kimi products"]
#         self.assertEqual((calls.counted_as, calls.role, calls.weight, calls.contribution), (None, "shown", None, None))
#         assert calls.loss is not None and code.loss is not None and result.vigor is not None
#         self.assertEqual(round(calls.loss, 2), 0.10)
#         self.assertEqual(calls.reason, "counts calls; shown, not summed")
#         self.assertEqual((code.role, code.weight, code.counted_as), ("store", 1.0, "credits"))
#         self.assertEqual(round(code.loss, 2), 0.47)
#         self.assertEqual((total.role, total.contribution), ("shown", None))
#         self.assertEqual(round(result.vigor, 2), 0.47)
#         self.assertFalse(result.exhausted)
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::WorkedExamples.test_kimi_month_loses_nearly_half_with_calls_and_the_total_shown_only

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::WorkedExamples.test_a_fresh_five_hour_window_at_13_20_gives_0_39
#     def test_a_fresh_five_hour_window_at_13_20_gives_0_39(self) -> None:
#         """radar.example-13-20"""
#         later = MONDAY + timedelta(hours=3, minutes=20)
#         windows = [
#             window("session", "Five hours", used=0, resets=at(hours=8, minutes=20), minutes=300),
#             window("weekly", "Seven days", used=20, resets=at(days=3), minutes=10080),
#         ]
#         result = compute(report(CLAUDE, windows, fetched=at(hours=3, minutes=20)), FIRST_PROFILE, later)
#         assert result.vigor is not None
#         self.assertEqual(by_label(result)["Five hours"].loss, 0.0)
#         self.assertAlmostEqual(result.vigor, 0.8 - 4120 / 10080)
#         self.assertEqual(round(result.vigor, 2), 0.39)
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::WorkedExamples.test_a_fresh_five_hour_window_at_13_20_gives_0_39

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::WorkedExamples.test_the_three_subscriptions_rank_kimi_claude_codex
#     def test_the_three_subscriptions_rank_kimi_claude_codex(self) -> None:
#         """radar.example-ranking"""
#         reports = (
#             ("Kimi Code", report(KIMI, kimi())),
#             ("Claude", report(CLAUDE, claude())),
#             ("Codex", report(CODEX, codex())),
#         )
#         values = {name: compute(r, FIRST_PROFILE, MONDAY).vigor for name, r in reports}
#         ranked = sorted(values, key=lambda name: values[name] or 0, reverse=True)
#         self.assertEqual(ranked, ["Kimi Code", "Claude", "Codex"])
#         self.assertEqual([round(values[name] or 0, 2) for name in ranked], [0.47, 0.37, 0.16])
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::WorkedExamples.test_the_three_subscriptions_rank_kimi_claude_codex


class Weights(unittest.TestCase):
    """The weights and the capped sum (SGM-1.4, SGM-D15)."""

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::Weights.test_each_gate_takes_the_profile_weight_and_the_store_1
#     def test_each_gate_takes_the_profile_weight_and_the_store_1(self) -> None:
#         """radar.gate-weights"""
#         learned = Profile(
#             1, "proposed", "even", Weight(0.1), gates={("anthropic", "Five hours"): Weight(0.25, "learned")}
#         )
#         windows = [
#             window("session", "Five hours", used=0, resets=at(minutes=1), minutes=300),
#             window("weekly", "Seven days", used=50, resets=at(minutes=1), minutes=10080),
#         ]
#         result = compute(report(CLAUDE, windows), learned, MONDAY)
#         five, week = by_label(result)["Five hours"], by_label(result)["Seven days"]
#         assert five.contribution is not None and week.contribution is not None and result.vigor is not None
#         self.assertEqual(five.weight, 0.25)
#         self.assertAlmostEqual(five.contribution, 0.25 * (1 - 1 / 300))
#         self.assertEqual(week.weight, 1.0)
#         self.assertAlmostEqual(week.contribution, 0.5 - 1 / 10080)
#         self.assertAlmostEqual(result.vigor, five.contribution + week.contribution)
#         self.assertEqual(learned.gate_weight("anthropic", "Five hours"), Weight(0.25, "learned"))
#         self.assertEqual(learned.gate_weight("anthropic", "Seven days"), Weight(0.1, "placeholder"))
#         placeholder = compute(report(CLAUDE, windows), FIRST_PROFILE, MONDAY)
#         self.assertEqual(by_label(placeholder)["Five hours"].weight, 0.1)
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::Weights.test_each_gate_takes_the_profile_weight_and_the_store_1

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::Weights.test_the_sum_is_capped_at_1
#     def test_the_sum_is_capped_at_1(self) -> None:
#         """radar.sum-cap"""
#         windows = [
#             window("session", "Five hours", used=0, resets=at(minutes=1), minutes=300),
#             window("weekly", "Seven days", used=0, resets=at(minutes=1), minutes=10080),
#         ]
#         result = compute(report(CLAUDE, windows), FIRST_PROFILE, MONDAY)
#         total = sum(entry.contribution or 0 for entry in result.windows)
#         self.assertGreater(total, 1)
#         self.assertEqual(result.vigor, 1.0)
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::Weights.test_the_sum_is_capped_at_1


class ExhaustedSubscriptions(unittest.TestCase):
    """The exhausted state (SGM-1.5, SGM-D27); the recovery is computed on predicted windows and is not here."""

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::ExhaustedSubscriptions.test_a_reached_five_hour_window_exhausts_and_vigor_is_0
#     def test_a_reached_five_hour_window_exhausts_and_vigor_is_0(self) -> None:
#         """radar.exhausted-reached"""
#         result = compute(
#             report(CLAUDE, claude(100, reached=True), extra={"isUsingOverage": False}), FIRST_PROFILE, MONDAY
#         )
#         self.assertTrue(result.exhausted)
#         self.assertEqual(result.vigor, 0.0)
#         five, week = by_label(result)["Five hours"], by_label(result)["Seven days"]
#         self.assertEqual((five.reached, five.loss, five.contribution), (True, 0.0, 0.0))
#         assert week.loss is not None
#         self.assertEqual(round(week.loss, 2), 0.37)  # the week's loss is still on the record
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::ExhaustedSubscriptions.test_a_reached_five_hour_window_exhausts_and_vigor_is_0

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::ExhaustedSubscriptions.test_a_reached_window_with_overage_does_not_exhaust
#     def test_a_reached_window_with_overage_does_not_exhaust(self) -> None:
#         """radar.exhausted-overage"""
#         result = compute(
#             report(CLAUDE, claude(100, reached=True), extra={"isUsingOverage": True}), FIRST_PROFILE, MONDAY
#         )
#         assert result.vigor is not None
#         self.assertFalse(result.exhausted)
#         self.assertEqual(by_label(result)["Five hours"].loss, 0.0)
#         self.assertEqual(round(result.vigor, 2), 0.37)
#         for extra in ({"isUsingOverage": "yes"}, {"isUsingOverage": 1}, {}):
#             with self.subTest(extra=extra):
#                 self.assertTrue(
#                     compute(report(CLAUDE, claude(100, reached=True), extra=extra), FIRST_PROFILE, MONDAY).exhausted
#                 )
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::ExhaustedSubscriptions.test_a_reached_window_with_overage_does_not_exhaust

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::ExhaustedSubscriptions.test_a_reached_window_of_calls_exhausts
#     def test_a_reached_window_of_calls_exhausts(self) -> None:
#         """radar.exhausted-calls"""
#         result = compute(report(KIMI, kimi(five_reached=True)), FIRST_PROFILE, MONDAY)
#         self.assertTrue(result.exhausted)
#         self.assertEqual(result.vigor, 0.0)
#         self.assertEqual(by_label(result)["Five hours"].role, "shown")
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::ExhaustedSubscriptions.test_a_reached_window_of_calls_exhausts

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::ExhaustedSubscriptions.test_a_reached_window_shown_and_not_summed_exhausts_too
#     def test_a_reached_window_shown_and_not_summed_exhausts_too(self) -> None:
#         """radar.exhausted-shown-window"""
#         result = compute(report(KIMI, kimi(total_reached=True)), FIRST_PROFILE, MONDAY)
#         self.assertTrue(result.exhausted)
#         self.assertEqual(result.vigor, 0.0)
#         self.assertEqual(by_label(result)["Monthly, all Kimi products"].role, "shown")
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::ExhaustedSubscriptions.test_a_reached_window_shown_and_not_summed_exhausts_too

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::ExhaustedSubscriptions.test_a_window_scoped_to_one_tool_does_not_exhaust
#     def test_a_window_scoped_to_one_tool_does_not_exhaust(self) -> None:
#         """radar.exhausted-tool-scoped"""
#         windows = [
#             window("session", "5-hour window", used=30, resets=at(hours=4), minutes=300),
#             window("weekly", "Weekly window", used=20, resets=at(days=3), minutes=10080),
#             window("other", "MCP", resource="calls", used=100, resets=at(days=20), minutes=43200, reached=True),
#         ]
#         zai = compute(report(ZAI, windows), FIRST_PROFILE, MONDAY)
#         self.assertFalse(zai.exhausted)
#         assert zai.vigor is not None
#         self.assertEqual(round(zai.vigor, 2), 0.37)
#         self.assertEqual(by_label(zai)["MCP"].role, "shown")
#         another = compute(report(Subscription("pi", "deepseek", "deepseek"), windows), FIRST_PROFILE, MONDAY)
#         self.assertTrue(another.exhausted)  # the same label of another family is scoped to the Subscription
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::ExhaustedSubscriptions.test_a_window_scoped_to_one_tool_does_not_exhaust

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::ExhaustedSubscriptions.test_a_used_share_above_100_loses_nothing_and_below_0_is_shown_only
#     def test_a_used_share_above_100_loses_nothing_and_below_0_is_shown_only(self) -> None:
#         """radar.used-share-in-the-sum"""
#         over = report(
#             CLAUDE,
#             [window("session", "Five hours", used=130, resets=at(hours=3), minutes=300), claude()[1]],
#             extra={"isUsingOverage": True},
#         )
#         self.assertEqual(by_label(compute(over, FIRST_PROFILE, MONDAY))["Five hours"].loss, 0.0)
#         below = report(CLAUDE, [window("session", "Five hours", used=-5, resets=at(hours=3), minutes=300), claude()[1]])
#         result = compute(below, FIRST_PROFILE, MONDAY)
#         entry = by_label(result)["Five hours"]
#         self.assertEqual(
#             (entry.role, entry.loss, entry.reason), ("shown", None, "usedPercent unknown; shown, not summed")
#         )
#         week = by_label(result)["Seven days"]
#         assert week.contribution is not None
#         self.assertEqual(round(week.contribution, 2), 0.37)  # the week's part is still on the record
#         self.assertEqual((result.vigor, result.unknown), (None, "usedPercent missing in the anthropic report"))
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::ExhaustedSubscriptions.test_a_used_share_above_100_loses_nothing_and_below_0_is_shown_only


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

# TEST-TIER-DISABLED-BEGIN tests/radar/test_vigor.py::Advisory.test_the_package_imports_nothing_that_runs_a_program_or_writes_a_file
#     def test_the_package_imports_nothing_that_runs_a_program_or_writes_a_file(self) -> None:
#         """radar.advisory-imports"""
#         files = sorted((ROOT / "src/arbol_radar").glob("*.py"))
#         for path in files:
#             allowed = self.ALLOWED_IMPORTS | self.REACHES.get(path.name, set())
#             tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
#             for node in ast.walk(tree):
#                 if isinstance(node, ast.Import):
#                     for alias in node.names:
#                         self.assertIn(alias.name, allowed, f"{path.name} imports {alias.name}")
#                 elif isinstance(node, ast.ImportFrom):
#                     self.assertEqual(node.level, 0, f"{path.name} has a relative import")
#                     self.assertIn(node.module, allowed, f"{path.name} imports from {node.module}")
#                 elif isinstance(node, ast.Name):
#                     forbidden = self.FORBIDDEN_NAMES - ({"print"} if path.name in self.PRINTS else set())
#                     self.assertNotIn(node.id, forbidden, f"{path.name} uses {node.id}")
# TEST-TIER-DISABLED-END tests/radar/test_vigor.py::Advisory.test_the_package_imports_nothing_that_runs_a_program_or_writes_a_file


if __name__ == "__main__":
    unittest.main()

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/radar/test_vigor.py:5
# import ast
# TEST-TIER-IMPORTS-END tests/radar/test_vigor.py:5
# TEST-TIER-IMPORTS-BEGIN tests/radar/test_vigor.py:8
# from datetime import timedelta
# TEST-TIER-IMPORTS-END tests/radar/test_vigor.py:8
# TEST-TIER-IMPORTS-BEGIN tests/radar/test_vigor.py:15
# from arbol_radar.model import FIRST_PROFILE, Profile, Rejected, Report, Subscription, Weight, Window  # noqa: E402
# TEST-TIER-IMPORTS-END tests/radar/test_vigor.py:15
# TEST-TIER-IMPORTS-BEGIN tests/radar/test_vigor.py:16
# from arbol_radar.vigor import compute, loss  # noqa: E402
# TEST-TIER-IMPORTS-END tests/radar/test_vigor.py:16
# TEST-TIER-IMPORTS-BEGIN tests/radar/test_vigor.py:17
# from radar.support import (  # noqa: E402
#     CLAUDE,
#     CODEX,
#     KIMI,
#     MONDAY,
#     ZAI,
#     at,
#     by_label,
#     claude,
#     codex,
#     kimi,
#     report,
#     window,
# )
# TEST-TIER-IMPORTS-END tests/radar/test_vigor.py:17
