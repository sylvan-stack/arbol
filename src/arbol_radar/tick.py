"""The recompute of Subscriptions Vigor (SGM-1.14, SGM-D30): every three minutes while the backend runs, and on a refresh.

One tick lists every Subscription of every Driver among the launchers through `subscriptions list`, which contacts no
vendor, records every report newer than the last recorded one of its Subscription, and recalculates and records every
Subscription's Vigor at the tick's moment, so a reset that passed takes effect at that tick and never earlier. The
`Ticker` is what the backend's loop calls at every wake: it ticks once the profile's interval has passed since the
last tick, three minutes, and no faster. A Root whose database lacks the Vigor tables refuses with `layout_incomplete`
and nothing is run; the backend swallows it and runs on without Vigor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from arbol_backend.process import Programs
from arbol_radar.drivers import Listing, list_subscriptions
from arbol_radar.model import FIRST_PROFILE, Profile, Rejected, Report, Result
from arbol_radar.records import Records


@dataclass(frozen=True)
class Tick:
    """What one tick did: the listing it read, the reports it recorded, the results it recorded, and what failed."""

    moment: datetime
    listing: Listing
    reports: tuple[Report, ...]  # the reports recorded at this tick, newer than the last recorded ones
    results: tuple[Result, ...]  # one result per listed Subscription, recorded
    failures: dict[str, str] = field(default_factory=dict)  # by Driver, or by `driver/subscription` for a report


async def recompute(records: Records, listing: Listing, profile: Profile, now: datetime) -> Tick:
    """Record every listed report newer than the last recorded one, then calculate and record every Subscription."""
    reports: list[Report] = []
    results: list[Result] = []
    failures = dict(listing.failures)
    for listed in listing.subscriptions:
        subscription = listed.subscription
        if listed.last_usage is not None:
            try:
                report = await records.record_report(subscription, listed.last_usage, now=now)
            except Rejected as error:
                failures[f"{subscription.driver}/{subscription.id}"] = f"invalid_report: {error}"
            else:
                if report is not None:
                    reports.append(report)
        results.append(await records.calculate(subscription, profile, now))
    return Tick(now, listing, tuple(reports), tuple(results), failures)


async def tick(programs: Programs, records: Records, profile: Profile, now: datetime) -> Tick:
    """One tick of SGM-1.14 at `now`: the Drivers listed, new reports recorded, every Subscription recalculated."""
    await records.require_layout()
    return await recompute(records, await list_subscriptions(programs), profile, now)


def utc_now() -> datetime:
    return datetime.now(UTC)


class Ticker:
    """The backend's tick: called at every wake of its loop, it ticks once the profile's interval has passed (SGM-D30)."""

    def __init__(
        self,
        programs: Programs,
        records: Records,
        profile: Profile = FIRST_PROFILE,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.programs, self.records, self.profile, self.clock = programs, records, profile, clock
        self.last: datetime | None = None  # when the last tick started; None before the first

    @property
    def interval(self) -> timedelta:
        """The profile's recompute interval: three minutes in profile 1, and nothing ticks faster."""
        return timedelta(minutes=self.profile.tick_minutes)

    def due(self, now: datetime) -> bool:
        return self.last is None or now - self.last >= self.interval

    async def wake(self) -> Tick | None:
        """Tick when the interval has passed since the last tick, else do nothing; the first wake ticks at once.

        The moment is taken before the tick, so a tick that takes time or fails moves the next one no closer: a
        database that refuses is tried again one interval later, never sooner.
        """
        now = self.clock()
        if not self.due(now):
            return None
        self.last = now
        return await tick(self.programs, self.records, self.profile, now)
