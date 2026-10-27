"""The read `arbol vigor` of the `arbol` command line (SGM-1.13, SGM-D28), its manual refresh (SGM-D20, SGM-D30), and
the profile commands `arbol vigor learn`, `arbol vigor profiles` and `arbol vigor approve <version>` (SGM-1.11).

`arbol [--root <root>] vigor [--refresh [<driver>/<subscription>]] [--text]` prints the rollup of the latest recorded
calculations of every Subscription of every Driver among the launchers: as one JSON document on standard output, as
every Arbol program answers, or as the Radar's lines with `--text`. A plain read lists the Subscriptions through
`subscriptions list`, which contacts no vendor, reads the latest record of each and recomputes nothing. With
`--refresh` a fresh report of every Subscription, or of the one named, is fetched first through the Driver's
`subscriptions usage`, recorded, and every Subscription is recomputed and recorded, which replaces predicted windows
with the vendor's numbers. The command line works while no backend runs: it opens the Root's database itself.

`learn` runs the learner over the Root's records and writes a proposed profile when a gate's estimate is calibrated,
with each Subscription's Vigor now by the profile in use beside the proposed one; `profiles` lists every profile with
its state and the one in use; `approve <version>` is the owner's approval, the one command that makes a profile the
one the calculation uses. None of them runs a Driver.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from arbol_backend.database import Database
from arbol_backend.model import Identity, Refused
from arbol_backend.process import Programs
from arbol_radar.drivers import Listed, Listing, list_subscriptions
from arbol_radar.learning import Estimate, Learned, learn
from arbol_radar.model import FIRST_PROFILE, Profile, Rejected
from arbol_radar.records import Records, profile_row
from arbol_radar.rollup import Entry, Rollup, as_json, as_text, number, rollup, when
from arbol_radar.tick import recompute
from arbol_radar.vigor import compute

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


def name_of(driver: str, identifier: str) -> str:
    return f"{driver}/{identifier}"


def profile_json(profile: Profile, recorded: datetime | None, in_use: int) -> dict[str, Any]:
    """A profile as `arbol vigor profiles` and `learn` print it, with its state and whether it is the one in use."""
    return {
        "version": profile.version,
        "approval": profile.approval,
        "inUse": profile.version == in_use,
        "recordedAt": recorded.isoformat() if recorded is not None else None,
        "pace": profile.pace,
        "placeholder": profile.placeholder.value,
        "gates": profile_row(profile),
        "staleRule": profile.stale_rule,
        "tickMinutes": profile.tick_minutes,
        "learning": {
            "threshold": profile.learning.threshold,
            "pairs": profile.learning.pairs,
            "estimator": profile.learning.estimator,
        },
    }


def profile_line(profile: Profile, recorded: datetime | None, in_use: int, now: datetime) -> str:
    """One profile as the text form lists it: its version, its state, its weights and when it was recorded."""
    parts = [f"Profile {profile.version}", profile.approval]
    if profile.version == in_use:
        parts.append("in use")
    parts.append(f"{profile.pace} pace, placeholder {profile.placeholder.value:g} for every other gate")
    for (family, label), weight in profile.gates.items():
        spread = (
            f", {weight.low:.2f} to {weight.high:.2f}" if weight.low is not None and weight.high is not None else ""
        )
        parts.append(f"{family} {label} {weight.value:.2f} {weight.source} from {weight.pairs} pairs{spread}")
    parts.append(f"recorded {when(recorded, now)}" if recorded is not None else "not recorded yet")
    return " · ".join(parts)


def estimate_line(item: Estimate) -> str:
    rest = f"; {item.untrusted} not trusted" if item.untrusted else ""
    if item.value is not None and item.low is not None and item.high is not None:
        return (
            f"{item.family} {item.gate}: {item.value:.2f} from {item.trusted} trusted pairs, "
            f"{item.low:.2f} to {item.high:.2f}{rest}"
        )
    return f"{item.family} {item.gate}: {item.trusted} of {item.needed} trusted pairs, {item.missing} missing{rest}"


async def learned_vigor(records: Records, learned: Learned) -> list[dict[str, Any]]:
    """Each Subscription's Vigor now over its last report by the profile in use and by the proposed one; nothing written."""
    found: list[dict[str, Any]] = []
    for series in learned.series:
        report = await records.last_report(series.subscription)
        now = learned.moment
        current = compute(report, learned.profile, now, subscription=series.subscription).vigor
        proposed = (
            compute(report, learned.proposed, now, subscription=series.subscription).vigor
            if learned.proposed is not None
            else None
        )
        name = name_of(series.subscription.driver, series.subscription.id)
        found.append({"subscription": name, "inUse": current, "proposed": proposed})
    return found


def learned_json(learned: Learned, vigor: list[dict[str, Any]]) -> dict[str, Any]:
    """`arbol vigor learn` as one JSON document: what was learned, from what, and the proposal if any (SGM-1.11)."""
    in_use = learned.profile.version
    return {
        "moment": learned.moment.isoformat(),
        "profile": in_use,
        "learning": profile_json(learned.profile, None, in_use)["learning"],
        "subscriptions": [
            {"subscription": name_of(s.subscription.driver, s.subscription.id), "reports": s.reports, "pairs": s.pairs}
            for s in learned.series
        ],
        "observations": [
            {
                "subscription": name_of(o.subscription.driver, o.subscription.id),
                "gate": o.gate,
                "store": o.store,
                "first": o.first,
                "second": o.second,
                "since": o.since.isoformat(),
                "until": o.until.isoformat(),
                "runs": o.runs,
                "storeChange": o.store_change,
                "gateChange": o.gate_change,
                "ratio": o.ratio,
                "trusted": o.trusted,
                "reason": o.reason,
            }
            for o in learned.observations
        ],
        "estimates": [
            {
                "family": e.family,
                "gate": e.gate,
                "trusted": e.trusted,
                "untrusted": e.untrusted,
                "needed": e.needed,
                "missing": e.missing,
                "value": e.value,
                "low": e.low,
                "high": e.high,
            }
            for e in learned.estimates
        ],
        "proposed": profile_json(learned.proposed, learned.moment, in_use) if learned.proposed is not None else None,
        "vigor": vigor,
    }


def learned_text(learned: Learned, vigor: list[dict[str, Any]]) -> str:
    """`arbol vigor learn --text`: the values used, the records, each gate's estimate, the untrusted reasons, the proposal."""
    values = learned.profile.learning
    lines = [
        f"Gate weights learned by profile {learned.profile.version}'s values: a store change of at least "
        f"{values.threshold:g} points, {values.pairs} trusted pairs, the {values.estimator}"
    ]
    lines += [
        f"{name_of(s.subscription.driver, s.subscription.id)}: {s.reports} reports, {s.pairs} pairs"
        for s in learned.series
    ]
    lines += [estimate_line(item) for item in learned.estimates] or ["No gate to learn in the recorded reports"]
    reasons: dict[str, int] = {}
    for observation in learned.observations:
        if observation.reason is not None:
            reasons[observation.reason] = reasons.get(observation.reason, 0) + 1
    lines += [f"not trusted {count}×: {reason}" for reason, count in sorted(reasons.items(), key=lambda r: -r[1])]
    if learned.proposed is None:
        lines.append("Nothing proposed: no gate has enough trusted pairs")
        return "\n".join(lines)
    version = learned.proposed.version
    lines.append(
        f"Proposed: profile {version}, not in use until the owner approves it with arbol vigor approve {version}"
    )
    for item in vigor:
        current, proposed = item["inUse"], item["proposed"]
        if current is not None and proposed is not None:
            lines.append(
                f"{item['subscription']} {number(current)} now by profile {learned.profile.version}, "
                f"{number(proposed)} by profile {version}"
            )
    return "\n".join(lines)


def version_of(value: str | None) -> int:
    if value is None or not value.isdigit() or value.startswith("0"):
        raise Refused("invalid_input", "approve names a recorded profile version, a whole number from 1.")
    return int(value)


async def profile_command(selected: Identity, action: str, value: str | None, *, text: bool, now: datetime) -> str:
    """`learn`, `profiles` or `approve <version>` over the Root's records, as one JSON document or as text lines."""
    version = version_of(value) if action == "approve" else None
    database = Database(selected)
    records = Records(database)
    try:
        await records.require_layout()
        if action == "learn":
            learned = await learn(records, now)
            vigor = await learned_vigor(records, learned)
            return (
                learned_text(learned, vigor)
                if text
                else json.dumps(learned_json(learned, vigor), separators=(",", ":"))
            )
        if version is not None:
            approved = await records.approve(version, now)
            in_use = (await records.in_use()).version
            if text:
                return f"Profile {approved.version} approved: the calculation uses it from the next tick or refresh."
            return json.dumps({"approved": approved.version, "inUse": in_use}, separators=(",", ":"))
        recorded: list[tuple[Profile, datetime | None]] = list(await records.profiles())
        if not any(profile.version == FIRST_PROFILE.version for profile, _ in recorded):
            recorded = [(FIRST_PROFILE, None), *recorded]  # the first profile, in use before it is recorded
        current = (await records.in_use()).version
        if text:
            return "\n".join(profile_line(profile, moment, current, now) for profile, moment in recorded)
        listed = [profile_json(profile, moment, current) for profile, moment in recorded]
        return json.dumps({"inUse": current, "profiles": listed}, separators=(",", ":"))
    finally:
        await database.close()


async def run(selected: Identity, parsed: Mapping[str, str]) -> int:
    """`arbol vigor`: print the rollup as one JSON document, or as the Radar's lines with `--text`; 0 when answered.

    With `learn`, `profiles` or `approve <version>` it answers that profile command instead (SGM-1.11).
    """
    action = parsed.get("action")
    if action is not None:
        answer = await profile_command(
            selected, action, parsed.get("version"), text="--text" in parsed, now=datetime.now(UTC)
        )
        print(answer, flush=True)
        return 0
    choice = options(parsed)
    value = await read(selected, choice)
    print(as_text(value) if choice.text else json.dumps(as_json(value), separators=(",", ":")), flush=True)
    return 0
