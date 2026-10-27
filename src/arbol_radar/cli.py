"""The read `arbol vigor` of the `arbol` command line (SGM-1.13, SGM-D28) and its manual refresh (SGM-D20, SGM-D30).

`arbol [--root <root>] vigor [--refresh [<driver>/<subscription>]] [--text]` prints the rollup of the latest recorded
calculations of every Subscription of every Driver among the launchers: as one JSON document on standard output, as
every Arbol program answers, or as the Radar's lines with `--text`. A plain read lists the Subscriptions through
`subscriptions list`, which contacts no vendor, reads the latest record of each and recomputes nothing. With
`--refresh` a fresh report of every Subscription, or of the one named, is fetched first through the Driver's
`subscriptions usage`, recorded, and every Subscription is recomputed and recorded, which replaces predicted windows
with the vendor's numbers. The command line works while no backend runs: it opens the Root's database itself.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from arbol_backend.database import Database
from arbol_backend.model import Identity, Refused
from arbol_backend.process import Programs
from arbol_radar.drivers import Listed, Listing, list_subscriptions
from arbol_radar.model import FIRST_PROFILE, Profile, Rejected
from arbol_radar.records import Records
from arbol_radar.rollup import Entry, Rollup, as_json, as_text, rollup
from arbol_radar.tick import recompute

USAGE = ["subscriptions", "usage"]


@dataclass(frozen=True)
class Options:
    """The options of `arbol vigor`: a refresh of every Subscription or of the one named, and the text form."""

    refresh: bool = False
    target: tuple[str, str] | None = None  # the one Subscription to refresh, as (driver, id); None for every one
    text: bool = False


def options(parsed: Mapping[str, str]) -> Options:
    """The options from the parsed command line: `--refresh` with its optional `<driver>/<subscription>`, `--text`."""
    target: tuple[str, str] | None = None
    value = parsed.get("--refresh")
    if value:
        driver, slash, identifier = value.partition("/")
        if not slash or not driver or not identifier:
            raise Refused("invalid_input", "--refresh names one Subscription as <driver>/<subscription>.")
        target = (driver, identifier)
    return Options(refresh="--refresh" in parsed, target=target, text="--text" in parsed)


def label_of(listed: Listed) -> str:
    """The Subscription's label as its Driver lists it (DRV-1), or its identifier when the record gives none."""
    value = listed.record.get("label")
    return value if isinstance(value, str) and value.strip() else listed.subscription.id


async def refresh(
    programs: Programs, records: Records, listing: Listing, target: tuple[str, str] | None, now: datetime
) -> dict[str, str]:
    """Fetch a fresh report of every listed Subscription, or of the one named, through `subscriptions usage` (SGM-D20).

    Each report is recorded as it arrives, whatever its outcome, so a sign-in need or an unreachable vendor shows as
    unknown with the Driver's message. A Subscription whose fetch failed is named with the reason; one that no Driver
    lists is refused before anything runs, unless its Driver failed to list, which the listing already says.
    """
    chosen = [
        item
        for item in listing.subscriptions
        if target is None or (item.subscription.driver, item.subscription.id) == target
    ]
    if target is not None and not chosen and target[0] not in listing.failures:
        raise Refused("invalid_input", f"No Driver among the launchers lists the Subscription {target[0]}/{target[1]}.")
    failures: dict[str, str] = {}
    for item in chosen:
        subscription = item.subscription
        name = f"{subscription.driver}/{subscription.id}"
        try:
            value = await programs.call(
                f"arbol-{subscription.driver}-driver",
                [*USAGE, subscription.id],
                kind="account",
                key=subscription.driver,
            )
        except Refused as error:
            failures[name] = f"{error.code}: {error}"
            continue
        if not isinstance(value, Mapping):
            failures[name] = "invalid_reply: the Driver did not answer with a usage report"
            continue
        try:
            await records.record_report(subscription, value, now=now)
        except Rejected as error:
            failures[name] = f"invalid_report: {error}"
    return failures


async def read(
    selected: Identity, choice: Options, *, now: datetime | None = None, profile: Profile = FIRST_PROFILE
) -> Rollup:
    """The rollup of the latest records of every Subscription of every Driver among the launchers (SGM-1.13).

    A plain read recomputes nothing and contacts no vendor (SGM-D30). With `refresh`, the fresh reports are recorded
    first and every Subscription is recomputed and recorded, as a tick does, so a report the vendor just gave replaces
    every predicted window (SGM-D20). A Subscription without a record is listed as such; a Root whose database lacks
    the Vigor tables refuses with `layout_incomplete` before any Driver is run.
    """
    moment = now or datetime.now(UTC)
    programs = Programs(selected)
    database = Database(selected)
    records = Records(database)
    try:
        await records.require_layout()
        listing = await list_subscriptions(programs)
        failures = dict(listing.failures)
        if choice.refresh:
            failures.update(await refresh(programs, records, listing, choice.target, moment))
            failures.update((await recompute(records, listing, profile, moment)).failures)
        entries = [
            Entry(item.subscription, label_of(item), await records.last_result(item.subscription))
            for item in listing.subscriptions
        ]
        return rollup(moment, entries, failures)
    finally:
        await database.close()
        programs.close()


async def run(selected: Identity, parsed: Mapping[str, str]) -> int:
    """`arbol vigor`: print the rollup as one JSON document, or as the Radar's lines with `--text`; 0 when answered."""
    choice = options(parsed)
    value = await read(selected, choice)
    print(as_text(value) if choice.text else json.dumps(as_json(value), separators=(",", ":")), flush=True)
    return 0
