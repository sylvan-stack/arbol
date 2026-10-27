"""The loss of a window and the Vigor of a Subscription (SGM-1): a pure calculation over one report, a profile and the clock.

Nothing here runs a program, reads a Driver, opens a connection or writes a file (SGM-1.15): the clock is an argument,
and the result is a record the caller keeps.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta

from arbol_radar.model import SUMMED, Loss, Profile, Rejected, Report, Result, Role, Window


def loss(window: Window, now: datetime) -> float | None:
    """The share of the window's allowance that expires unused at its even pace from now, never below zero (SGM-1.3).

    r = 1 − usedPercent / 100, t = resetsAt − now, T = windowMinutes, loss = max(0, r − t / T). A reached window loses
    nothing, since nothing is left in it (SGM-1.5). A reset already passed counts as no time left, so the loss never
    exceeds the unspent share; `predict` gives the fresh window first (SGM-1.7). None while a field is unknown.
    """
    if window.used_percent is None or window.resets_at is None or window.window_minutes is None or not window.known:
        return None
    if window.limit_reached:
        return 0.0
    unspent = 1 - window.used_percent / 100
    minutes_left = max(0.0, (window.resets_at - now).total_seconds() / 60)
    return max(0.0, unspent - minutes_left / window.window_minutes)


def counted_as(window: Window) -> tuple[str | None, bool]:
    """What the window is summed as: tokens or credits (SGM-1.2); tokens, and said so, when the Driver named nothing."""
    if window.resource is None:
        return "tokens", True
    if window.resource in SUMMED:
        return window.resource, False
    return None, False


def store_of(candidates: list[Window]) -> Window | None:
    """The store: the longest window that takes part; among equals the one scoped to the coding product (SGM-D25)."""
    lengths = [window.window_minutes for window in candidates if window.window_minutes is not None]
    if not lengths:
        return None
    longest = max(lengths)
    equals = [window for window in candidates if window.window_minutes == longest]
    return next((window for window in equals if window.scope == "product"), equals[0])


def predict(window: Window, now: datetime) -> Window:
    """The window as it stands at `now`: as delivered while its reset is after the clock, else predicted fresh (SGM-1.7).

    A known window whose reset is not after the clock has reset without a newer report, since a report is never newer
    than its own windows' resets (the Interface rejects a reset before the fetch time). The fresh window has used share
    0, its reset one length later, repeated until the reset is after the clock, its reached flag cleared, and is marked
    predicted. A window with an unknown field is left as delivered, so a Driver defect stays visible (SGM-D19).
    """
    if not window.known or window.resets_at is None or window.window_minutes is None or window.resets_at > now:
        return window
    length = timedelta(minutes=window.window_minutes)
    passed = math.floor((now - window.resets_at) / length) + 1  # the resets that passed, this one included
    return replace(
        window,
        used_percent=0.0,
        resets_at=window.resets_at + passed * length,
        limit_reached=False,
        predicted=True,
        raw_used_percent=None,
    )


def _calculate(
    report: Report, windows: tuple[Window, ...], profile: Profile, moment: datetime
) -> tuple[tuple[Loss, ...], float | None, bool, tuple[str, ...]]:
    """The per-window entries, the Vigor, the exhausted state and the notes at `moment` on the windows as given."""
    family = report.subscription.family
    notes: list[str] = []
    counted = {window.label: counted_as(window) for window in windows}
    for window in windows:
        if counted[window.label][1]:
            notes.append(f"{window.label}: the {family} report names no resource; counted as tokens")
    candidates = [window for window in windows if counted[window.label][0] is not None and window.known]
    store = store_of(candidates)
    losses: list[Loss] = []
    total = 0.0
    for window in windows:
        value = loss(window, moment)
        role: Role = "shown"
        weight: float | None = None
        reason: str | None = None
        if counted[window.label][0] is None:
            reason = f"counts {window.resource}; shown, not summed"
        elif not window.known:
            reason = f"{window.missing} unknown; shown, not summed"
        elif window is store:
            role, weight = "store", profile.store_weight
        elif store is not None and window.window_minutes == store.window_minutes:
            reason = "as long as the store and not the coding product's window; shown, not summed"
        else:
            role, weight = "gate", profile.gate_weight(family, window.label).value
        contribution = weight * value if weight is not None and value is not None else None
        total += contribution or 0.0
        losses.append(
            Loss(
                label=window.label,
                resource=window.resource,
                counted_as=counted[window.label][0],
                assumed=counted[window.label][1],
                role=role,
                reached=window.limit_reached is True,
                loss=value,
                weight=weight,
                contribution=contribution,
                reason=reason,
                predicted=window.predicted,
                used_percent=window.used_percent,
                resets_at=window.resets_at,
                window_minutes=window.window_minutes,
            )
        )
    # Exhausted while any window that gates inference is reached, whatever it counts, unless the account spends overage;
    # a window scoped to one tool gates only that tool (SGM-1.5, SGM-D27).
    exhausted = any(window.limit_reached and window.scope != "tool" for window in windows) and not report.overage
    if exhausted:
        vigor: float | None = 0.0
    elif store is None:
        vigor = None
        notes.append("no Vigor: no window takes part in the sum")
    else:
        vigor = min(1.0, total)
    return tuple(losses), vigor, exhausted, tuple(notes)


def compute(report: Report, profile: Profile, now: datetime) -> Result:
    """The Vigor of the report's Subscription at `now` by `profile` (SGM-1.1 to 1.5), on the windows predicted for `now`."""
    if now.tzinfo is None:
        raise Rejected("clock", "The clock names no time zone.")
    family = report.subscription.family
    if report.outcome != "ok":
        return Result(
            subscription=report.subscription,
            moment=now,
            report=report.id,
            profile=profile.version,
            windows=(),
            vigor=None,
            exhausted=False,
            notes=(f"no Vigor: the {family} report's outcome is {report.outcome}",),
        )
    windows = tuple(predict(window, now) for window in report.windows)
    losses, vigor, exhausted, notes = _calculate(report, windows, profile, now)
    return Result(
        subscription=report.subscription,
        moment=now,
        report=report.id,
        profile=profile.version,
        windows=losses,
        vigor=vigor,
        exhausted=exhausted,
        notes=notes,
        predicted=any(window.predicted for window in windows),
    )
