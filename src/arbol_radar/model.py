"""The records of Subscriptions Vigor (SGM-1, Interface): a Subscription, its usage report with its windows, a profile and a result.

A report is read from the Driver Contract's `UsageReport` (DRV-1) as the Driver delivered it. The records are frozen and
hold no behaviour beyond what the Interface rejects and the used-share rules; the calculation is `vigor.py`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

Scope = Literal["subscription", "product", "tool"]
Role = Literal["store", "gate", "shown"]
Source = Literal["placeholder", "learned"]

OUTCOMES = ("ok", "needs_sign_in", "unavailable", "unsupported")
KINDS = ("session", "weekly", "other")
SUMMED = ("tokens", "credits")  # the resources whose windows take part in the sum (SGM-1.2, SGM-D24)
APPROVALS = ("proposed", "approved")  # a profile's approval state: proposed until the owner approves it (SGM-D17)
STALE_RULES = ("shortest-window",)  # the stale rules the calculation knows (SGM-1.8, SGM-D31)
ESTIMATORS = ("median",)  # the estimators the learner knows over a gate's trusted ratios (SGM-1.11)

# What the calculation knows of a family's windows beyond the contract's fields, by the window's label: which window is
# scoped to the coding product the Subscription serves, the store among equal-length longest windows (SGM-D25), and
# which to one tool, which gates only that tool and never exhausts the Subscription (SGM-D27). A window not named here
# is scoped to the Subscription. Kimi's labels are the Pi Driver's (PI-1), z.ai's the Claude Driver's quota mapping.
SCOPES: Mapping[str, Mapping[str, Scope]] = {
    "kimi-coding": {"Monthly, Kimi Code": "product"},
    "zai": {"MCP": "tool"},
}


class Rejected(ValueError):
    """What the Interface rejects; `field` names the offending field of the report, the profile or the call."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class Subscription:
    """One signed-in account with a vendor (DRV-1), named by its Driver and its identifier within it (DRV-D21)."""

    driver: str
    id: str
    family: str


@dataclass(frozen=True)
class Window:
    """One usage window of a report as the Driver delivered it, with the Interface's used-share rules applied."""

    kind: str
    label: str
    resource: str | None  # what the window counts; None when the Driver did not say (Codex, CDX-D31)
    used_percent: float | None  # the share counted, 0 to 100; None when unknown
    resets_at: datetime | None
    window_minutes: float | None
    limit_reached: bool | None
    scope: Scope = "subscription"
    predicted: bool = False
    report: str | None = None  # the id of the report the window comes from
    raw_used_percent: float | None = None  # the delivered share when it was below 0 or above 100
    unknown: str | None = None  # the field that leaves the window unknown, such as "usedPercent"

    def __post_init__(self) -> None:
        if self.window_minutes is not None and not (math.isfinite(self.window_minutes) and self.window_minutes > 0):
            raise Rejected("windowMinutes", f"{self.label}: a window's length is positive, not {self.window_minutes}.")
        if self.used_percent is not None and not 0 <= self.used_percent <= 100:
            raise Rejected(
                "usedPercent", f"{self.label}: the counted share lies within 0 to 100, not {self.used_percent}."
            )
        if self.resets_at is not None and self.resets_at.tzinfo is None:
            raise Rejected("resetsAt", f"{self.label}: the reset time names no time zone.")

    @property
    def missing(self) -> str | None:
        """The field that keeps the window from being known, in the contract's words, or None when all are known."""
        if self.unknown is not None:
            return self.unknown
        if self.used_percent is None:
            return "usedPercent"
        if self.window_minutes is None:
            return "windowMinutes"
        if self.resets_at is None:
            return "resetsAt"
        return None

    @property
    def known(self) -> bool:
        """Whether the used share, the length and the reset time are all known (SGM-1.2)."""
        return self.missing is None


def _number(value: object, name: str, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise Rejected(name, f"{label}: {name} is a finite number, not {value!r}.")
    return float(value)


def _time(value: object, name: str, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise Rejected(name, f"{label}: {name} is an ISO 8601 time, not {value!r}.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise Rejected(name, f"{label}: {name} is not an ISO 8601 time: {value!r}.") from error
    if parsed.tzinfo is None:
        raise Rejected(name, f"{label}: {name} names no time zone: {value!r}.")
    return parsed


def _window(value: object, family: str, report_id: str, index: int) -> Window:
    if not isinstance(value, Mapping):
        raise Rejected("windows", f"Window {index} of the {family} report is not an object.")
    label = value.get("label")
    if not isinstance(label, str) or not label:
        raise Rejected("label", f"Window {index} of the {family} report has no label.")
    kind = value.get("kind")
    if kind not in KINDS:
        raise Rejected("kind", f"{label}: the kind is one of {KINDS}, not {kind!r}.")
    resource = value.get("resource")
    if resource is not None and not isinstance(resource, str):
        raise Rejected("resource", f"{label}: the resource is a word, not {resource!r}.")
    reached = value.get("limitReached")
    if reached is not None and type(reached) is not bool:
        raise Rejected("limitReached", f"{label}: limitReached is a boolean, not {reached!r}.")
    raw = _number(value.get("usedPercent"), "usedPercent", label)
    used, kept, unknown = raw, None, None
    if raw is not None and raw < 0:  # below 0: unknown, the field named (Interface)
        used, kept, unknown = None, raw, "usedPercent"
    elif raw is not None and raw > 100:  # above 100, as Claude reports overage: counted as 100, the raw value kept
        used, kept = 100.0, raw
    return Window(
        kind=kind,
        label=label,
        resource=resource,
        used_percent=used,
        resets_at=_time(value.get("resetsAt"), "resetsAt", label),
        window_minutes=_number(value.get("windowMinutes"), "windowMinutes", label),
        limit_reached=reached,
        scope=SCOPES.get(family, {}).get(label, "subscription"),
        report=report_id,
        raw_used_percent=kept,
        unknown=unknown,
    )


@dataclass(frozen=True)
class Report:
    """A usage report as delivered (DRV-1 `UsageReport`), read into windows, with its arrival and the run that made it."""

    id: str
    subscription: Subscription
    outcome: str
    fetched_at: datetime
    windows: tuple[Window, ...]
    delivered: tuple[Mapping[str, Any], ...]  # the windows as delivered
    extra: Mapping[str, Any]  # as delivered
    arrived_at: datetime
    run: str | None = None  # the run that produced the report, when one did (DRV-4.13)
    message: str | None = None  # the Driver's message, present unless the outcome is `ok`

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise Rejected("outcome", f"The outcome is one of {OUTCOMES}, not {self.outcome!r}.")
        for name, moment in (("fetchedAt", self.fetched_at), ("arrivedAt", self.arrived_at)):
            if moment.tzinfo is None:
                raise Rejected(name, f"The {name} of the {self.subscription.family} report names no time zone.")
        for window in self.windows:
            if window.resets_at is not None and window.resets_at < self.fetched_at:
                raise Rejected(
                    "resetsAt",
                    f"{window.label}: the reset time {window.resets_at.isoformat()} is before the report's fetch time "
                    f"{self.fetched_at.isoformat()}.",
                )

    @property
    def overage(self) -> bool:
        """Whether the account keeps spending past a reached window: the Claude report's `extra.isUsingOverage` (SGM-1.5)."""
        return self.extra.get("isUsingOverage") is True

    @classmethod
    def from_contract(
        cls,
        subscription: Subscription,
        value: Mapping[str, Any],
        *,
        report_id: str,
        arrived_at: datetime,
        run: str | None = None,
    ) -> Report:
        """Read a Driver's `UsageReport` as delivered; what the Interface rejects raises `Rejected`."""
        outcome = value.get("outcome")
        if not isinstance(outcome, str):
            raise Rejected("outcome", f"The {subscription.family} report has no outcome.")
        fetched = _time(value.get("fetchedAt"), "fetchedAt", subscription.family)
        if fetched is None:
            raise Rejected("fetchedAt", f"The {subscription.family} report has no fetchedAt.")
        delivered = value.get("windows", [])
        if not isinstance(delivered, list):
            raise Rejected("windows", f"The windows of the {subscription.family} report are not a list.")
        extra = value.get("extra", {})
        if not isinstance(extra, Mapping):
            raise Rejected("extra", f"The extra of the {subscription.family} report is not an object.")
        message = value.get("message")
        if message is not None and not isinstance(message, str):
            raise Rejected("message", f"The message of the {subscription.family} report is not text.")
        windows = tuple(_window(item, subscription.family, report_id, index) for index, item in enumerate(delivered))
        return cls(
            id=report_id,
            subscription=subscription,
            outcome=outcome,
            fetched_at=fetched,
            windows=windows,
            delivered=tuple(dict(item) for item in delivered),
            extra=dict(extra),
            arrived_at=arrived_at,
            run=run,
            message=message,
        )


@dataclass(frozen=True)
class Weight:
    """A gate's allowance as a share of the store's: learned from report pairs, or the placeholder until one is approved."""

    value: float
    source: Source = "placeholder"
    pairs: int | None = None  # a learned weight: the trusted report pairs it rests on (SGM-1.11)
    low: float | None = None  # and the spread of their ratios, the lowest and the highest
    high: float | None = None


@dataclass(frozen=True)
class Learning:
    """How gate weights are learned from report pairs (SGM-1.11): profile values with proposed defaults (SGM-D36).

    A pair is trusted only when the store moved by at least `threshold` percentage points; a gate's weight is
    calibrated once `pairs` trusted pairs exist, as the `estimator` of their ratios. Reports give whole percentages,
    so a change of 1 point is mostly rounding; at 2 points one ratio is within about half of its value, and the median
    of 10 such ratios is not moved by up to four bad pairs.
    """

    threshold: float = 2.0
    pairs: int = 10
    estimator: str = "median"


@dataclass(frozen=True)
class Profile:
    """The versioned choices of the calculation, in the shape of SGM-0's profile: pace, gate weights and the stale rule."""

    version: int
    approval: str  # "proposed" until the owner approves it (SGM-D15, SGM-D17)
    pace: str  # "even": the window's even pace, the pace that drains the bucket exactly by its reset (SGM-D17)
    placeholder: Weight  # every gate's weight where none is learned (SGM-D15)
    gates: Mapping[tuple[str, str], Weight] = field(default_factory=dict)  # learned weights by (family, label)
    stale_rule: str = "shortest-window"  # stale after the shortest window that is summed or can exhaust (SGM-1.8, D31)
    store_weight: float = 1.0  # the store's weight is 1 (SGM-1.4)
    tick_minutes: float = 3.0  # the backend recomputes every three minutes and no faster (SGM-1.14, SGM-D30)
    learning: Learning = field(default_factory=Learning)  # how its gate weights are learned (SGM-1.11, SGM-D36)

    def __post_init__(self) -> None:
        # The calculation knows the first profile and the versions the Root's own table records (SGM-D37); a version
        # the table does not hold is refused where it is asked for, `Records.profile`.
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise Rejected("version", f"A profile version is a whole number from 1, not {self.version!r}.")
        if self.approval not in APPROVALS:
            raise Rejected("approval", f"A profile's approval is one of {APPROVALS}, not {self.approval!r}.")
        weights = [
            ("placeholder", self.placeholder),
            *((f"{family} {label}", w) for (family, label), w in self.gates.items()),
        ]
        for name, weight in weights:
            if not (math.isfinite(weight.value) and 0 <= weight.value <= 1):
                raise Rejected("weight", f"The weight of {name} lies within [0, 1], not {weight.value}.")
        if self.store_weight != 1:
            raise Rejected("storeWeight", f"The store's weight is 1, not {self.store_weight}.")
        if self.stale_rule not in STALE_RULES:
            raise Rejected(
                "staleRule", f"The calculation knows the stale rules {STALE_RULES}, not {self.stale_rule!r}."
            )
        if not (math.isfinite(self.tick_minutes) and self.tick_minutes > 0):
            raise Rejected(
                "tickMinutes", f"The recompute interval is a positive number of minutes, not {self.tick_minutes}."
            )
        learning = self.learning
        if not (math.isfinite(learning.threshold) and learning.threshold > 0):
            raise Rejected("threshold", f"The store's least change is a positive share, not {learning.threshold}.")
        if isinstance(learning.pairs, bool) or not isinstance(learning.pairs, int) or learning.pairs < 1:
            raise Rejected(
                "pairs", f"A calibrated estimate needs a whole number of pairs from 1, not {learning.pairs!r}."
            )
        if learning.estimator not in ESTIMATORS:
            raise Rejected("estimator", f"The learner knows the estimators {ESTIMATORS}, not {learning.estimator!r}.")

    def gate_weight(self, family: str, label: str) -> Weight:
        """The weight of a gate: the learned one for this family and window, else the placeholder."""
        return self.gates.get((family, label), self.placeholder)


# The first profile: proposed, the even pace, the placeholder 0.1 for every gate, stale after the shortest window that
# is summed or can exhaust the Subscription, recomputed every three minutes, gate weights learned by the proposed
# defaults. The profile in use until the owner approves one (SGM-D37).
FIRST_PROFILE = Profile(version=1, approval="proposed", pace="even", placeholder=Weight(0.1, "placeholder"))


def stale_after(profile: Profile, windows: Iterable[Window]) -> timedelta | None:
    """How old a report may be before a result on it is stale, by the profile's stale rule (SGM-1.8, SGM-D31).

    `shortest-window`: the Subscription's shortest window that takes part in the sum (tokens or credits, or no resource
    and counted as tokens) or can exhaust it (any window not scoped to one tool), five hours for every family today.
    None when no such window has a length: nothing then says the report is stale.
    """
    lengths = [
        window.window_minutes
        for window in windows
        if window.window_minutes is not None
        and (window.scope != "tool" or window.resource is None or window.resource in SUMMED)
    ]
    return timedelta(minutes=min(lengths)) if lengths else None


@dataclass(frozen=True)
class Loss:
    """One window's part in a result: its loss and, when it is summed, its weight and contribution."""

    label: str
    resource: str | None
    counted_as: str | None  # "tokens" or "credits" when the window can be summed; None when it is shown only
    assumed: bool  # the Driver named no resource and the window counted as tokens (CDX-D31)
    role: Role  # the store, a gate, or shown and not summed
    reached: bool
    loss: float | None  # None when a field of the window is unknown
    weight: float | None
    contribution: float | None  # weight × loss for a summed window
    reason: str | None  # why a window is shown and not summed
    predicted: bool = False  # the window was predicted fresh after a reset without a newer report (SGM-1.7)
    used_percent: float | None = None  # the window as used: its share, reset time and length, predicted or delivered
    resets_at: datetime | None = None
    window_minutes: float | None = None


@dataclass(frozen=True)
class Result:
    """One calculation of a Subscription's Vigor (SGM-1, Interface)."""

    subscription: Subscription
    moment: datetime
    report: str | None  # the id of the report used; None while there is no report yet (SGM-1.9)
    profile: int  # the profile version used
    windows: tuple[Loss, ...]
    vigor: float | None
    exhausted: bool
    notes: tuple[str, ...] = ()  # what the calculation says on the result, such as a window counted as tokens
    predicted: bool = False  # a predicted window was used (SGM-1.7)
    stale: timedelta | None = None  # the report's age when the result is stale (SGM-1.8)
    unknown: str | None = None  # the reason when Vigor cannot be computed (SGM-1.9)
    next_change: datetime | None = None  # the earliest reset among the windows (SGM-1.6)
    next_value: float | None = None  # the Vigor at that moment
