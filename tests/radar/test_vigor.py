"""Subscriptions Vigor: the loss of a window and the Vigor of a Subscription, with fixed reports, clock and profile (SGM-1)."""

from __future__ import annotations

import sys
import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from arbol_radar.model import (  # noqa: E402
    FIRST_PROFILE,
    Loss,
    Profile,
    Rejected,
    Report,
    Result,
    Subscription,
    Weight,
    Window,
)
from arbol_radar.vigor import compute  # noqa: E402

MONDAY = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)  # the worked examples' Monday 10:00
CLAUDE = Subscription("claude", "anthropic", "anthropic")
CODEX = Subscription("codex", "chatgpt", "chatgpt")
KIMI = Subscription("pi", "kimi-coding", "kimi-coding")
ZAI = Subscription("pi", "zai", "zai")


def at(*, days: float = 0, hours: float = 0, minutes: float = 0) -> str:
    return (MONDAY + timedelta(days=days, hours=hours, minutes=minutes)).isoformat().replace("+00:00", "Z")


def window(
    kind: str,
    label: str,
    *,
    resource: str | None = "tokens",
    used: float | None = 0,
    resets: str | None = None,
    minutes: float | None = 300,
    reached: bool | None = False,
) -> dict[str, Any]:
    value: dict[str, Any] = {"kind": kind, "label": label}
    if resource is not None:
        value["resource"] = resource
    if used is not None:
        value["usedPercent"] = used
    if resets is not None:
        value["resetsAt"] = resets
    if minutes is not None:
        value["windowMinutes"] = minutes
    if reached is not None:
        value["limitReached"] = reached
    return value


def report(
    subscription: Subscription,
    windows: list[dict[str, Any]],
    *,
    fetched: str = "2026-10-26T09:55:00Z",
    extra: dict[str, Any] | None = None,
    outcome: str = "ok",
    message: str | None = None,
) -> Report:
    value: dict[str, Any] = {"outcome": outcome, "fetchedAt": fetched, "windows": windows}
    if extra is not None:
        value["extra"] = extra
    if message is not None:
        value["message"] = message
    return Report.from_contract(subscription, value, report_id="r1", arrived_at=MONDAY)


def claude(five_used: float = 35, week_used: float = 20, *, reached: bool = False) -> list[dict[str, Any]]:
    """The worked example: five hours 35 % used, resets 13:20; seven days 20 % used, resets Thursday 10:00."""
    return [
        window("session", "Five hours", used=five_used, resets=at(hours=3, minutes=20), minutes=300, reached=reached),
        window("weekly", "Seven days", used=week_used, resets=at(days=3), minutes=10080),
    ]


def codex() -> list[dict[str, Any]]:
    """The worked example: 70 % of the week used with 24 hours to its reset, the five-hour window on pace; no resource."""
    return [
        window("session", "5-hour window", resource=None, used=50, resets=at(hours=2, minutes=30), minutes=300),
        window("weekly", "Weekly window", resource=None, used=70, resets=at(days=1), minutes=10080),
    ]


def kimi(five_reached: bool = False, total_reached: bool = False) -> list[dict[str, Any]]:
    """The worked example: 26 days into the 30-day cycle, 40 % of the code share used, five hours 70 % with an hour to go."""
    return [
        window(
            "session", "Five hours", resource="calls", used=70, resets=at(hours=1), minutes=300, reached=five_reached
        ),
        window("other", "Monthly, Kimi Code", resource="credits", used=40, resets=at(days=4), minutes=43200),
        window(
            "other",
            "Monthly, all Kimi products",
            resource="credits",
            used=55,
            resets=at(days=4),
            minutes=43200,
            reached=total_reached,
        ),
    ]


def by_label(result: Result) -> dict[str, Loss]:
    return {entry.label: entry for entry in result.windows}


class Records(unittest.TestCase):
    """The records of the Interface, the used-share rules and what the Interface rejects."""

    def rejected(self, field: str, call: Any, *args: Any, **kwargs: Any) -> None:
        with self.assertRaises(Rejected) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.field, field)

    def test_the_first_profile(self) -> None:
        """radar.first-profile"""
        self.assertEqual(FIRST_PROFILE.version, 1)
        self.assertEqual(FIRST_PROFILE.approval, "proposed")
        self.assertEqual(FIRST_PROFILE.pace, "even")
        self.assertEqual(FIRST_PROFILE.placeholder, Weight(0.1, "placeholder"))
        self.assertEqual(dict(FIRST_PROFILE.gates), {})
        self.assertEqual(FIRST_PROFILE.stale_rule, "shortest-window")
        self.assertEqual(FIRST_PROFILE.store_weight, 1.0)
        self.assertEqual(FIRST_PROFILE.gate_weight("chatgpt", "5-hour window"), Weight(0.1, "placeholder"))

    def test_a_report_is_read_as_delivered(self) -> None:
        """radar.report-as-delivered"""
        r = Report.from_contract(
            CLAUDE,
            {
                "outcome": "ok",
                "fetchedAt": "2026-10-26T09:55:00Z",
                "windows": claude(),
                "extra": {"isUsingOverage": False},
            },
            report_id="r7",
            arrived_at=MONDAY,
            run="run-1",
        )
        self.assertEqual(
            (r.id, r.subscription, r.outcome, r.arrived_at, r.run, r.message),
            ("r7", CLAUDE, "ok", MONDAY, "run-1", None),
        )
        self.assertEqual(r.fetched_at, datetime(2026, 10, 26, 9, 55, tzinfo=UTC))
        self.assertEqual(r.delivered, tuple(claude()))
        self.assertEqual(r.extra, {"isUsingOverage": False})
        self.assertFalse(r.overage)
        five = r.windows[0]
        self.assertEqual(
            (five.kind, five.label, five.resource, five.used_percent), ("session", "Five hours", "tokens", 35.0)
        )
        self.assertEqual(
            (five.resets_at, five.window_minutes, five.limit_reached),
            (MONDAY + timedelta(hours=3, minutes=20), 300.0, False),
        )
        self.assertEqual(
            (five.scope, five.predicted, five.report, five.raw_used_percent, five.unknown),
            ("subscription", False, "r7", None, None),
        )
        self.assertTrue(five.known)
        kimi_report = report(KIMI, kimi())
        self.assertEqual([w.scope for w in kimi_report.windows], ["subscription", "product", "subscription"])
        absent = report(CODEX, codex()).windows[0]
        self.assertEqual((absent.resource, absent.used_percent, absent.limit_reached), (None, 50.0, False))
        unsupported = report(ZAI, [], outcome="unsupported", message="no allowance reading")
        self.assertEqual((unsupported.windows, unsupported.message), ((), "no allowance reading"))

    def test_a_used_share_below_0_marks_the_window_unknown_with_the_field_named(self) -> None:
        """radar.used-share-below-zero"""
        five = report(CLAUDE, [window("session", "Five hours", used=-5, resets=at(hours=3), minutes=300)]).windows[0]
        self.assertEqual((five.used_percent, five.raw_used_percent, five.unknown), (None, -5.0, "usedPercent"))
        self.assertEqual((five.missing, five.known), ("usedPercent", False))

    def test_a_used_share_above_100_counts_as_100_with_the_raw_value_kept(self) -> None:
        """radar.used-share-above-hundred"""
        r = report(CLAUDE, [window("session", "Five hours", used=130, resets=at(hours=3), minutes=300)])
        five = r.windows[0]
        self.assertEqual(
            (five.used_percent, five.raw_used_percent, five.unknown, five.known), (100.0, 130.0, None, True)
        )
        self.assertEqual(r.delivered[0]["usedPercent"], 130)
        exact = report(CLAUDE, [window("session", "Five hours", used=100, resets=at(hours=3), minutes=300)]).windows[0]
        self.assertEqual((exact.used_percent, exact.raw_used_percent), (100.0, None))

    def test_a_weight_outside_0_to_1_is_rejected(self) -> None:
        """radar.reject-weight"""
        for value in (-0.1, 1.5, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.rejected("weight", Profile, 1, "proposed", "even", Weight(value))
                self.rejected(
                    "weight",
                    Profile,
                    1,
                    "proposed",
                    "even",
                    Weight(0.1),
                    gates={("anthropic", "Five hours"): Weight(value, "learned")},
                )
        Profile(1, "proposed", "even", Weight(0.0))
        Profile(1, "proposed", "even", Weight(1.0))

    def test_a_store_weight_other_than_1_is_rejected(self) -> None:
        """radar.reject-store-weight"""
        for value in (0.9, 0.0, 1.5):
            with self.subTest(value=value):
                self.rejected("storeWeight", Profile, 1, "proposed", "even", Weight(0.1), store_weight=value)

    def test_a_nonpositive_length_is_rejected(self) -> None:
        """radar.reject-length"""
        for value in (0, -5, float("nan")):
            with self.subTest(value=value):
                self.rejected(
                    "windowMinutes",
                    report,
                    CLAUDE,
                    [window("session", "Five hours", used=1, resets=at(hours=1), minutes=value)],
                )
                self.rejected("windowMinutes", Window, "session", "Five hours", "tokens", 1, MONDAY, value, False)

    def test_a_reset_time_before_the_fetch_time_is_rejected(self) -> None:
        """radar.reject-reset-before-fetch"""
        self.rejected(
            "resetsAt", report, CLAUDE, [window("session", "Five hours", used=1, resets="2026-10-26T09:54:59Z")]
        )
        report(CLAUDE, [window("session", "Five hours", used=1, resets="2026-10-26T09:55:00Z")])  # equal is accepted
        early = Window("session", "Five hours", "tokens", 1, MONDAY - timedelta(seconds=1), 300, False)
        self.rejected("resetsAt", Report, "r1", CLAUDE, "ok", MONDAY, (early,), (), {}, MONDAY)

    def test_a_profile_version_the_calculation_does_not_know_is_rejected(self) -> None:
        """radar.reject-profile-version"""
        for version in (0, 2):
            with self.subTest(version=version):
                self.rejected("version", Profile, version, "proposed", "even", Weight(0.1))

    def test_a_malformed_report_is_rejected_with_its_field_named(self) -> None:
        """radar.reject-malformed"""
        base = window("session", "Five hours", used=1, resets=at(hours=1))
        cases: list[tuple[str, dict[str, Any]]] = [
            ("outcome", {"outcome": "fine", "fetchedAt": at(), "windows": []}),
            ("outcome", {"fetchedAt": at(), "windows": []}),
            ("fetchedAt", {"outcome": "ok", "windows": []}),
            ("fetchedAt", {"outcome": "ok", "fetchedAt": "2026-10-26T09:55:00", "windows": []}),
            ("windows", {"outcome": "ok", "fetchedAt": at(), "windows": {}}),
            ("windows", {"outcome": "ok", "fetchedAt": at(), "windows": [1]}),
            ("extra", {"outcome": "ok", "fetchedAt": at(), "windows": [], "extra": []}),
            ("message", {"outcome": "unavailable", "fetchedAt": at(), "windows": [], "message": 5}),
            ("label", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "label": ""}]}),
            ("kind", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "kind": "daily"}]}),
            ("resource", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "resource": 3}]}),
            ("usedPercent", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "usedPercent": "35"}]}),
            ("usedPercent", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "usedPercent": True}]}),
            ("resetsAt", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "resetsAt": "soon"}]}),
            (
                "resetsAt",
                {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "resetsAt": "2026-10-26T13:20:00"}]},
            ),
            ("windowMinutes", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "windowMinutes": "300"}]}),
            ("limitReached", {"outcome": "ok", "fetchedAt": at(), "windows": [{**base, "limitReached": 0}]}),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.rejected(field, Report.from_contract, CLAUDE, value, report_id="r1", arrived_at=MONDAY)

    def test_the_records_are_frozen(self) -> None:
        """radar.records-frozen"""
        r = report(CLAUDE, claude())
        with self.assertRaises(FrozenInstanceError):
            r.windows[0].used_percent = 1.0  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            FIRST_PROFILE.placeholder = Weight(0.2)  # type: ignore[misc]


class WindowsThatTakePart(unittest.TestCase):
    """Which windows take part in the sum, the store and the gates (SGM-1.2, SGM-D24, SGM-D25)."""

    def test_only_tokens_and_credits_are_summed_and_an_absent_resource_counts_as_tokens(self) -> None:
        """radar.take-part-resource"""
        windows = [
            window("other", "Tokens", resource="tokens", used=20, resets=at(days=1), minutes=10080),
            window("other", "Credits", resource="credits", used=20, resets=at(days=1), minutes=1440),
            window("other", "Calls", resource="calls", used=20, resets=at(days=1), minutes=1440),
            window("other", "Unnamed", resource=None, used=20, resets=at(days=1), minutes=1440),
            window("other", "Something else", resource="requests", used=20, resets=at(days=1), minutes=1440),
        ]
        result = compute(report(CODEX, windows), FIRST_PROFILE, MONDAY)
        entries = by_label(result)
        self.assertEqual(entries["Tokens"].role, "store")
        self.assertEqual((entries["Credits"].role, entries["Credits"].counted_as), ("gate", "credits"))
        self.assertEqual((entries["Calls"].role, entries["Calls"].reason), ("shown", "counts calls; shown, not summed"))
        self.assertEqual(
            (entries["Unnamed"].role, entries["Unnamed"].counted_as, entries["Unnamed"].assumed),
            ("gate", "tokens", True),
        )
        self.assertEqual(entries["Something else"].role, "shown")
        self.assertEqual(entries["Something else"].reason, "counts requests; shown, not summed")
        self.assertEqual(result.notes, ("Unnamed: the chatgpt report names no resource; counted as tokens",))
        assert entries["Calls"].loss is not None
        self.assertEqual(round(entries["Calls"].loss, 2), 0.0)  # its loss is still computed and shown

    def test_a_window_lacking_a_field_is_shown_and_not_summed(self) -> None:
        """radar.take-part-known"""
        for name, w in (
            ("usedPercent", window("weekly", "Seven days", used=None, resets=at(days=3), minutes=10080)),
            ("usedPercent", window("weekly", "Seven days", used=-5, resets=at(days=3), minutes=10080)),
            ("windowMinutes", window("weekly", "Seven days", used=20, resets=at(days=3), minutes=None)),
            ("resetsAt", window("weekly", "Seven days", used=20, resets=None, minutes=10080)),
        ):
            with self.subTest(field=name, value=w):
                windows = [window("session", "Five hours", used=35, resets=at(hours=3, minutes=20), minutes=300), w]
                result = compute(report(CLAUDE, windows), FIRST_PROFILE, MONDAY)
                week = by_label(result)["Seven days"]
                self.assertEqual((week.role, week.loss, week.contribution), ("shown", None, None))
                self.assertEqual(week.reason, f"{name} unknown; shown, not summed")
                self.assertEqual(by_label(result)["Five hours"].role, "store")

    def test_the_longest_window_is_the_store_and_shorter_ones_gates(self) -> None:
        """radar.store-longest"""
        windows = [
            window("session", "Five hours", used=0, resets=at(minutes=1), minutes=300),
            window("weekly", "Seven days", used=0, resets=at(minutes=1), minutes=10080),
            window("other", "A day", used=0, resets=at(minutes=1), minutes=1440),
        ]
        result = compute(report(CLAUDE, windows), FIRST_PROFILE, MONDAY)
        roles = {entry.label: (entry.role, entry.weight) for entry in result.windows}
        self.assertEqual(roles, {"Five hours": ("gate", 0.1), "Seven days": ("store", 1.0), "A day": ("gate", 0.1)})

    def test_among_equal_lengths_the_coding_product_window_is_the_store(self) -> None:
        """radar.store-coding-product"""
        windows = list(reversed(kimi()))  # the total delivered first: the order does not decide
        result = compute(report(KIMI, windows), FIRST_PROFILE, MONDAY)
        roles = {entry.label: entry.role for entry in result.windows}
        self.assertEqual(
            roles, {"Monthly, all Kimi products": "shown", "Monthly, Kimi Code": "store", "Five hours": "shown"}
        )
        self.assertEqual(result.windows[0].label, "Monthly, all Kimi products")
        total = by_label(result)["Monthly, all Kimi products"]
        self.assertEqual(total.reason, "as long as the store and not the coding product's window; shown, not summed")

    def test_among_equal_lengths_without_a_coding_product_window_the_first_delivered_is_the_store(self) -> None:
        """radar.store-equal-fallback"""
        windows = [
            window("other", "Month A", resource="credits", used=40, resets=at(days=4), minutes=43200),
            window("other", "Month B", resource="credits", used=10, resets=at(days=4), minutes=43200),
        ]
        result = compute(report(CODEX, windows), FIRST_PROFILE, MONDAY)
        self.assertEqual([entry.role for entry in result.windows], ["store", "shown"])
        assert result.vigor is not None
        self.assertEqual(round(result.vigor, 2), 0.47)

    def test_a_report_without_numbers_gives_no_vigor(self) -> None:
        """radar.outcome-not-ok"""
        for outcome in ("needs_sign_in", "unavailable", "unsupported"):
            with self.subTest(outcome=outcome):
                result = compute(report(ZAI, [], outcome=outcome, message="why"), FIRST_PROFILE, MONDAY)
                self.assertEqual((result.vigor, result.windows, result.exhausted), (None, (), False))
                self.assertEqual(result.notes, (f"no Vigor: the zai report's outcome is {outcome}",))
        only_calls = compute(report(KIMI, kimi()[:1]), FIRST_PROFILE, MONDAY)
        self.assertEqual((only_calls.vigor, only_calls.notes), (None, ("no Vigor: no window takes part in the sum",)))

    def test_the_clock_is_an_argument_that_names_its_time_zone(self) -> None:
        """radar.clock-argument"""
        r = report(CLAUDE, claude())
        with self.assertRaises(Rejected) as caught:
            compute(r, FIRST_PROFILE, MONDAY.replace(tzinfo=None))
        self.assertEqual(caught.exception.field, "clock")
        later = compute(r, FIRST_PROFILE, MONDAY + timedelta(hours=2))
        self.assertEqual(later.moment, MONDAY + timedelta(hours=2))
        assert later.vigor is not None
        self.assertGreater(later.vigor, 0.37)  # the same report two hours later loses more of the week


if __name__ == "__main__":
    unittest.main()
