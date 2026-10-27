"""The Radar's rollup of Subscriptions Vigor (SGM-1.12, SGM-D18): every Subscription's latest result, sorted by Vigor.

The headline is the highest Vigor, named with its Subscription; the list beneath keeps every Subscription visible, the
unknown ones with their reason below the known ones and those without a record yet last. Values are never added across
Subscriptions: a sum of Claude's and Codex's shares means nothing. A Subscription, not an Intelligence Provider, is
the unit. The rollup is a record over results that were computed before; nothing here computes, reads or writes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import Any

from arbol_radar.model import Result, Subscription
from arbol_radar.records import loss_row


@dataclass(frozen=True)
class Entry:
    """One Subscription on the Radar: its label as the Driver lists it and its latest recorded result, if any."""

    subscription: Subscription
    label: str
    result: Result | None  # the latest recorded calculation; None while nothing was recorded for the Subscription

    @property
    def vigor(self) -> float | None:
        return self.result.vigor if self.result is not None else None

    @property
    def name(self) -> str:
        """The Subscription as the Radar names it: its Driver and its identifier, such as `claude/anthropic`."""
        return f"{self.subscription.driver}/{self.subscription.id}"

    @property
    def rank(self) -> tuple[int, float, str]:
        """Known results first, highest Vigor first; then unknown ones; then Subscriptions without a record; by name."""
        if self.result is None:
            return (2, 0.0, self.name)
        if self.result.vigor is None:
            return (1, 0.0, self.name)
        return (0, -self.result.vigor, self.name)


@dataclass(frozen=True)
class Rollup:
    """The Rollup record (SGM-1, Interface): the moment, every Subscription's result, the headline value and Subscription."""

    moment: datetime
    entries: tuple[Entry, ...]  # sorted as `Entry.rank` says
    failures: Mapping[str, str] = field(
        default_factory=dict
    )  # the Drivers and Subscriptions that failed, each with why

    @property
    def headline(self) -> Entry | None:
        """The highest Vigor with its Subscription; None while no Subscription has a known Vigor."""
        first = self.entries[0] if self.entries else None
        return first if first is not None and first.vigor is not None else None


def rollup(moment: datetime, entries: list[Entry], failures: Mapping[str, str] | None = None) -> Rollup:
    """The rollup of the entries at `moment`, sorted by Vigor with unknown Subscriptions kept visible below."""
    return Rollup(moment, tuple(sorted(entries, key=lambda entry: entry.rank)), dict(failures or {}))


def number(value: float) -> str:
    """A Vigor as the Radar prints it: two decimals, `0` for zero."""
    return "0" if value == 0 else f"{value:.2f}"


def minutes(value: timedelta) -> float:
    return round(value.total_seconds() / 60, 1)


def result_json(result: Result) -> dict[str, Any]:
    """A result as the JSON answer carries it: every field of the Result record (SGM-1, Interface)."""
    return {
        "moment": result.moment.isoformat(),
        "report": result.report,
        "profile": result.profile,
        "vigor": result.vigor,
        "exhausted": result.exhausted,
        "predicted": result.predicted,
        "stale": {"reportAgeMinutes": minutes(result.stale)} if result.stale is not None else None,
        "unknown": result.unknown,
        "nextChange": (
            {"at": result.next_change.isoformat(), "vigor": result.next_value}
            if result.next_change is not None
            else None
        ),
        "notes": list(result.notes),
        "windows": [loss_row(entry) for entry in result.windows],
    }


def as_json(value: Rollup) -> dict[str, Any]:
    """The rollup as one JSON document: the headline, every Subscription in the Radar's order, the failures."""
    headline = value.headline
    return {
        "moment": value.moment.isoformat(),
        "headline": (
            {
                "vigor": headline.vigor,
                "driver": headline.subscription.driver,
                "subscription": headline.subscription.id,
                "label": headline.label,
            }
            if headline is not None
            else None
        ),
        "subscriptions": [
            {
                "driver": entry.subscription.driver,
                "subscription": entry.subscription.id,
                "family": entry.subscription.family,
                "label": entry.label,
                "result": result_json(entry.result) if entry.result is not None else None,
            }
            for entry in value.entries
        ],
        "failures": dict(value.failures),
    }


def when(moment: datetime, now: datetime, zone: tzinfo | None = None) -> str:
    """A moment as the Radar's lines print it, in local time: `13:20` today, `Thu 10:00` within the week, else the date."""
    local, today = moment.astimezone(zone), now.astimezone(zone)
    if local.date() == today.date():
        return local.strftime("%H:%M")
    if abs(local - today) < timedelta(days=6):
        return local.strftime("%a %H:%M")
    return local.strftime("%Y-%m-%d %H:%M")


def age(value: timedelta) -> str:
    total = int(value.total_seconds() // 60)
    hours, remainder = divmod(total, 60)
    if hours >= 48:
        return f"{hours // 24} d {hours % 24} h"
    return f"{hours} h {remainder} min" if hours else f"{remainder} min"


def line(entry: Entry, now: datetime, zone: tzinfo | None = None) -> str:
    """One Subscription's line: its name, its Vigor or why it has none, its next change, its state and its moment."""
    parts = [entry.name]
    result = entry.result
    if result is None:
        return f"{entry.name} · no record yet"
    if result.vigor is None:
        parts.append(f"unknown: {result.unknown}")
    else:
        parts[0] = f"{entry.name} {number(result.vigor)}"
        if result.exhausted and result.next_change is not None and result.next_value is not None:
            parts.append(f"exhausted, recovers {when(result.next_change, now, zone)}, {number(result.next_value)}")
        elif result.exhausted:
            parts.append("exhausted")
        elif result.next_change is not None and result.next_value is not None:
            parts.append(f"next change {when(result.next_change, now, zone)}, {number(result.next_value)}")
    if result.predicted:
        parts.append("predicted")
    if result.stale is not None:
        parts.append(f"stale, report {age(result.stale)} old")
    parts.append(f"recorded {when(result.moment, now, zone)}")
    return " · ".join(parts)


def as_text(value: Rollup, zone: tzinfo | None = None) -> str:
    """The Radar's lines: the headline named with its Subscription, then one line per Subscription in order.

    Moments are printed in the local time zone, or in `zone` when one is given.
    """
    headline = value.headline
    lines = [
        f"Subscriptions Vigor: {number(headline.vigor)}, {headline.label}"
        if headline is not None and headline.vigor is not None
        else "Subscriptions Vigor: unknown"
    ]
    lines.extend(line(entry, value.moment, zone) for entry in value.entries)
    if value.failures:
        lines.append("Failed: " + "; ".join(f"{name} · {reason}" for name, reason in sorted(value.failures.items())))
    return "\n".join(lines)
