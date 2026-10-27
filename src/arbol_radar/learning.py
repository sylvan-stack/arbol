"""Learning the gate weights of Subscriptions Vigor from recorded report pairs (SGM-1.11, SGM-D15, SGM-D17).

For two consecutive `ok` reports of one Subscription around one run of this Mac, the change in the store's used share
divided by the change in a gate's used share is one observation of the gate's allowance as a share of the store's.
Every device of the same account spends from the same windows, and the record cannot tell another device's spending
apart, so an observation is trusted only when both windows moved without a reset between the reports, the store by at
least the profile's threshold and by no more than the gate, and exactly one run of this Mac for the Subscription ended
between the two fetch times: an Exchange of the current Root whose route names the Driver and the Subscription. Every
other observation is kept with its reason. Nothing here approves a profile (SGM-D17).
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from arbol_backend.database import Database
from arbol_radar.model import FIRST_PROFILE, Learning, Report, Subscription, Window
from arbol_radar.records import Records
from arbol_radar.vigor import compute

# The runs of this Mac for a Subscription between two fetch times: the Exchanges of the current Root whose route names
# the Driver and the Subscription (RCT-3, `exchanges.route`) and that ended after the first and at or before the second.
RUNS = (
    "SELECT count(*) FROM exchanges WHERE route->>'driver'=%s AND route->>'subscription'=%s "
    "AND ended_at > %s AND ended_at <= %s"
)


@dataclass(frozen=True)
class Observation:
    """One gate of one pair of consecutive reports: the store's and the gate's change, their ratio, and its trust."""

    subscription: Subscription
    gate: str  # the gate's label
    store: str  # the store's label
    first: str  # the id of the earlier report
    second: str  # the id of the later report
    since: datetime  # the earlier report's fetch time
    until: datetime  # the later report's fetch time
    runs: int  # the runs of this Mac for the Subscription that ended between the two fetch times
    store_change: float | None  # the change of the store's used share, in percentage points; None when not comparable
    gate_change: float | None
    reason: str | None  # why the observation is not trusted; None when it is

    @property
    def trusted(self) -> bool:
        return self.reason is None

    @property
    def ratio(self) -> float | None:
        """The store's change over the gate's: the gate's allowance as a share of the store's; None without both."""
        if self.store_change is None or self.gate_change is None or self.gate_change <= 0:
            return None
        return self.store_change / self.gate_change


@dataclass(frozen=True)
class Estimate:
    """One family's gate over its trusted observations: the calibrated estimate with its spread, or what is missing."""

    family: str
    gate: str
    trusted: int  # the trusted observations, the pairs the estimate rests on
    untrusted: int
    needed: int  # the trusted pairs a calibrated estimate needs, the profile's value
    value: float | None  # the profile's estimator over the trusted ratios, once `needed` exist; None before
    low: float | None  # the spread: the lowest and the highest trusted ratio; None without one
    high: float | None

    @property
    def missing(self) -> int:
        """How many trusted pairs are still missing for a calibrated estimate."""
        return max(0, self.needed - self.trusted)

    @property
    def calibrated(self) -> bool:
        return self.value is not None


def points(value: float) -> str:
    return f"{value:g}"


def roles(report: Report) -> tuple[str | None, tuple[str, ...]]:
    """The store's label and the gates' labels of a report, as the calculation gives them (SGM-1.4)."""
    windows = compute(report, FIRST_PROFILE, report.fetched_at).windows
    store = next((entry.label for entry in windows if entry.role == "store"), None)
    return store, tuple(entry.label for entry in windows if entry.role == "gate")


def movement(label: str, before: Window, after: Window | None, until: datetime) -> tuple[float | None, str | None]:
    """A window's change in used share from one report to the next, and why it cannot be trusted, if it cannot."""
    if after is None:
        return None, f"{label} is missing from the later report"
    if not after.known or before.used_percent is None or after.used_percent is None:
        return None, f"{label} is unknown in the later report"
    if before.resets_at is not None and before.resets_at <= until:
        return None, f"{label} reset between the reports"
    if before.raw_used_percent is not None or after.raw_used_percent is not None:
        return None, f"{label} counted above 100"
    change = after.used_percent - before.used_percent
    return change, None if change > 0 else f"{label} did not move"


def observe(first: Report, second: Report, runs: int, learning: Learning) -> list[Observation]:
    """Every gate's observation of a pair of consecutive `ok` reports of one Subscription, with its trust (SGM-1.11)."""
    store, gates = roles(first)
    if store is None:
        return []
    earlier = {window.label: window for window in first.windows}
    later = {window.label: window for window in second.windows}
    found: list[Observation] = []
    for gate in gates:
        store_change, store_reason = movement(store, earlier[store], later.get(store), second.fetched_at)
        gate_change, gate_reason = movement(gate, earlier[gate], later.get(gate), second.fetched_at)
        reason = store_reason or gate_reason
        if reason is None and store_change is not None and gate_change is not None:
            if store_change > gate_change:
                reason = f"the store moved more than {gate}"
            elif store_change < learning.threshold:
                reason = (
                    f"the store moved by {points(store_change)}, below the threshold of {points(learning.threshold)}"
                )
            elif runs == 0:
                reason = "no run of this Mac ended between the reports"
            elif runs > 1:
                reason = f"{runs} runs of this Mac ended between the reports"
        found.append(
            Observation(
                subscription=first.subscription,
                gate=gate,
                store=store,
                first=first.id,
                second=second.id,
                since=first.fetched_at,
                until=second.fetched_at,
                runs=runs,
                store_change=store_change,
                gate_change=gate_change,
                reason=reason,
            )
        )
    return found


def estimate(found: Sequence[Observation], learning: Learning, gates: Iterable[tuple[str, str]] = ()) -> list[Estimate]:
    """The estimate of every family's gate that was observed or is named, by family and gate (SGM-1.11).

    A gate's observations of every Subscription of its family count together, since the weight is the family's. The
    calibrated estimate is the profile's estimator, the median, over the trusted ratios once the profile's number of
    pairs is reached; before that the estimate says how many are missing. Untrusted observations never count.
    """
    keys = sorted({(observation.subscription.family, observation.gate) for observation in found} | set(gates))
    estimates: list[Estimate] = []
    for family, gate in keys:
        own = [o for o in found if (o.subscription.family, o.gate) == (family, gate)]
        ratios = sorted(o.ratio for o in own if o.trusted and o.ratio is not None)
        value = statistics.median(ratios) if ratios and len(ratios) >= learning.pairs else None
        estimates.append(
            Estimate(
                family=family,
                gate=gate,
                trusted=len(ratios),
                untrusted=len(own) - len(ratios),
                needed=learning.pairs,
                value=value,
                low=ratios[0] if ratios else None,
                high=ratios[-1] if ratios else None,
            )
        )
    return estimates


def pairs(reports: Sequence[Report]) -> list[tuple[Report, Report]]:
    """The consecutive `ok` reports of one Subscription, oldest first: the pairs the learner observes."""
    usable = sorted((report for report in reports if report.outcome == "ok"), key=lambda report: report.fetched_at)
    return list(pairwise(usable))


async def runs_between(database: Database, subscription: Subscription, since: datetime, until: datetime) -> int:
    """The runs of this Mac for the Subscription that ended between two fetch times, from the Root's chat tables."""
    rows = await database.execute(RUNS, [subscription.driver, subscription.id, since, until])
    return int(rows[0][0]) if rows else 0


async def observations(records: Records, learning: Learning) -> list[Observation]:
    """Every gate's observation over the recorded reports of every Subscription of the Root's `vigor_reports`."""
    await records.require_layout()
    found: list[Observation] = []
    for subscription in await records.reported():
        for first, second in pairs(await records.reports(subscription)):
            runs = await runs_between(records.database, subscription, first.fetched_at, second.fetched_at)
            found.extend(observe(first, second, runs, learning))
    return found
