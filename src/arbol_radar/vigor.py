"""The loss of a window and the Vigor of a Subscription (SGM-1): a pure calculation over one report, a profile and the clock.

Nothing here runs a program, reads a Driver, opens a connection or writes a file (SGM-1.15): the clock is an argument,
and the result is a record the caller keeps.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta

from arbol_radar.model import SUMMED, Loss, Profile, Rejected, Report, Result, Role, Subscription, Window, stale_after


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
    exhausted = bool(exhausted_by(report, windows))
    if exhausted:
        vigor: float | None = 0.0
    elif store is None:
        vigor = None
    else:
        vigor = min(1.0, total)
    return tuple(losses), vigor, exhausted, tuple(notes)


def exhausted_by(report: Report, windows: tuple[Window, ...]) -> list[Window]:
    """The windows that exhaust the Subscription: reached, gating inference, and no overage (SGM-1.5, SGM-D27).

    Every reached window not scoped to one tool gates inference, whatever it counts; a reached window with paid overage
    switched on does not exhaust the Subscription, since the account keeps spending. Empty while it can be used.
    """
    if report.overage:
        return []
    return [window for window in windows if window.limit_reached and window.scope != "tool"]


def next_change(
    report: Report, windows: tuple[Window, ...], profile: Profile, now: datetime
) -> tuple[datetime | None, float | None]:
    """The next change of the Subscription's Vigor and its value then, on the windows predicted for that moment (SGM-1.6).

    Vigor jumps at a reset: a store's unspent share is lost, a gate opens again. The moment is the earliest reset among
    the windows used. While the Subscription is exhausted it is instead the moment its last reached inference-gating
    window resets, the latest reset among them, since nothing can be spent before (SGM-D34): this is its recovery,
    "0 now, 0.39 at 13:20" (SGM-1.5, SGM-D16). None when no window names a reset time.
    """
    resets = [window.resets_at for window in windows if window.resets_at is not None and window.resets_at > now]
    if not resets:
        return None, None
    gating = [window.resets_at for window in exhausted_by(report, windows) if window.resets_at is not None]
    moment = max(gating) if gating else min(resets)
    then = tuple(predict(window, moment) for window in windows)
    _, value, _, _ = _calculate(report, then, profile, moment)
    return moment, value


def unknown_reason(report: Report | None) -> str | None:
    """Why the Subscription's Vigor cannot be computed, in the chapter's words after `unknown: `; None when it can (SGM-1.9).

    A missing field in an `ok` report is a Driver defect and names the field and the family; an `unsupported` outcome is
    a known gap; `needs_sign_in` and `unavailable` carry the Driver's message; no report means nothing has run and
    nothing was fetched (SGM-D19). An `ok` report without a token or credit window cannot be summed either (SGM-D33).
    """
    if report is None:
        return "no report yet"
    family = report.subscription.family
    if report.outcome == "unsupported":
        return f"allowance not supported for {family}"
    if report.outcome != "ok":
        return f"{report.outcome}: {report.message}" if report.message else report.outcome
    summed = [window for window in report.windows if counted_as(window)[0] is not None]
    for window in summed:
        if window.missing is not None:
            return f"{window.missing} missing in the {family} report"
    if not summed:
        return f"no token or credit window in the {family} report"
    return None


def compute(
    report: Report | None, profile: Profile, now: datetime, *, subscription: Subscription | None = None
) -> Result:
    """The Vigor of the report's Subscription at `now` by `profile` (SGM-1.1 to 1.9), on the windows predicted for `now`.

    Without a report the Subscription is named, and the result is unknown with the reason `no report yet`. A result that
    cannot be computed carries Vigor None and its reason, never zero; its windows are still listed as the report gave
    them, and it has no next change.
    """
    if now.tzinfo is None:
        raise Rejected("clock", "The clock names no time zone.")
    if report is None:
        if subscription is None:
            raise Rejected("subscription", "Without a report, the Subscription is named.")
        return Result(
            subscription=subscription,
            moment=now,
            report=None,
            profile=profile.version,
            windows=(),
            vigor=None,
            exhausted=False,
            unknown=unknown_reason(None),
        )
    reason = unknown_reason(report)
    if report.outcome != "ok":
        return Result(
            subscription=report.subscription,
            moment=now,
            report=report.id,
            profile=profile.version,
            windows=(),
            vigor=None,
            exhausted=False,
            unknown=reason,
        )
    windows = tuple(predict(window, now) for window in report.windows)
    losses, vigor, exhausted, notes = _calculate(report, windows, profile, now)
    moment, value = next_change(report, windows, profile, now) if reason is None else (None, None)
    # Stale when the report is older than the shortest window that is summed or can exhaust the Subscription; the
    # result is still computed, since the report is a floor the owner's other devices may have spent past (SGM-1.8).
    age = now - report.fetched_at
    limit = stale_after(profile, report.windows)
    return Result(
        subscription=report.subscription,
        moment=now,
        report=report.id,
        profile=profile.version,
        windows=losses,
        vigor=vigor if reason is None else None,
        exhausted=exhausted,
        notes=notes,
        predicted=any(window.predicted for window in windows),
        stale=age if limit is not None and age > limit else None,
        unknown=reason,
        next_change=moment,
        next_value=value,
    )
