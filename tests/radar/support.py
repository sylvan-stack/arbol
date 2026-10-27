"""Fixed reports, clock and Subscriptions for the checks of Subscriptions Vigor: the chapter's worked examples (SGM-1)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from arbol_radar.model import Loss, Report, Result, Subscription  # noqa: E402

MONDAY = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)  # the worked examples' Monday 10:00
FETCHED = "2026-10-26T09:55:00Z"  # when the worked examples' reports were fetched
CLAUDE = Subscription("claude", "anthropic", "anthropic")
CODEX = Subscription("codex", "chatgpt", "chatgpt")
KIMI = Subscription("pi", "kimi-coding", "kimi-coding")
ZAI = Subscription("pi", "zai", "zai")


def at(*, days: float = 0, hours: float = 0, minutes: float = 0) -> str:
    """A moment relative to Monday 10:00, as the contract writes it."""
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
    """One window as a Driver delivers it; a `None` leaves the field absent."""
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
    fetched: str = FETCHED,
    extra: dict[str, Any] | None = None,
    outcome: str = "ok",
    message: str | None = None,
    report_id: str = "r1",
    arrived: datetime = MONDAY,
) -> Report:
    """A `UsageReport` as a Driver delivers it, read into a Report."""
    value: dict[str, Any] = {"outcome": outcome, "fetchedAt": fetched, "windows": windows}
    if extra is not None:
        value["extra"] = extra
    if message is not None:
        value["message"] = message
    return Report.from_contract(subscription, value, report_id=report_id, arrived_at=arrived)


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
    """The result's per-window entries by the window's label."""
    return {entry.label: entry for entry in result.windows}
