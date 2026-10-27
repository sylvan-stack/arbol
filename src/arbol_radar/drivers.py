"""The Drivers' Subscriptions with their last usage reports, read through the backend's launcher calls (SGM-1, BKD-0.25).

Every Driver whose launcher `arbol-<driver>-driver` is in the folder of the launchers is asked `subscriptions list`,
which a Driver answers from its stored state without contacting a vendor (DRV-1.14); each Subscription's record carries
its last `ok` usage report as `lastUsage` (DRV-1.18). Nothing else of a Driver is run here: `Programs.call` allows the
account commands alone, and this module asks for `list` only. A Driver that fails is reported beside the others.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from arbol_backend.model import Refused
from arbol_backend.process import Programs
from arbol_radar.model import Subscription

LIST = ["subscriptions", "list"]


@dataclass(frozen=True)
class Listed:
    """One Subscription as its Driver listed it, with its record as delivered (DRV-1, `Subscription`)."""

    subscription: Subscription
    record: Mapping[str, Any]

    @property
    def last_usage(self) -> Mapping[str, Any] | None:
        """The last `ok` usage report the Driver stored with the Subscription, as delivered; None when there is none."""
        value = self.record.get("lastUsage")
        return value if isinstance(value, Mapping) else None


@dataclass(frozen=True)
class Listing:
    """Every Subscription of every Driver among the launchers, and the Drivers that failed, each with the reason."""

    drivers: tuple[str, ...]
    subscriptions: tuple[Listed, ...]
    failures: Mapping[str, str] = field(default_factory=dict)


def drivers_of(programs: Programs) -> tuple[str, ...]:
    """The Drivers whose launcher is in the folder of the launchers, in the order of their names."""
    return tuple(sorted(programs.drivers))


def records_of(driver: str, value: object) -> list[Listed] | None:
    """The Subscription records of a `list` answer; None when the answer is not a list of records with id and family."""
    if not isinstance(value, list):
        return None
    found: list[Listed] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        identifier, family = item.get("id"), item.get("family")
        if not isinstance(identifier, str) or not identifier or not isinstance(family, str) or not family:
            return None
        found.append(Listed(Subscription(driver, identifier, family), dict(item)))
    return found


async def list_subscriptions(programs: Programs) -> Listing:
    """`subscriptions list` of every Driver among the launchers, one after another; a failing Driver is named."""
    drivers = drivers_of(programs)
    found: list[Listed] = []
    failures: dict[str, str] = {}
    for driver in drivers:
        try:
            value = await programs.call(f"arbol-{driver}-driver", list(LIST), kind="account", key=driver)
        except Refused as error:
            failures[driver] = f"{error.code}: {error}"
            continue
        records = records_of(driver, value)
        if records is None:
            failures[driver] = "invalid_reply: the Driver did not answer with a list of Subscription records"
            continue
        found.extend(records)
    return Listing(drivers, tuple(found), failures)
