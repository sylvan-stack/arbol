"""The records of Subscriptions Vigor in the current Root's database (SGM-1.10, SGM-D22, SGM-D29).

Every report is recorded as it arrives when its fetchedAt is newer than the last recorded one of its Subscription; every
calculation is recorded with its inputs, the profile version, each window's loss and the result; a named profile can be
replayed over the recorded reports of a Subscription (SGM-1.14). The three tables, `vigor_profiles`, `vigor_reports`
and `vigor_results`, come from each Root's own layout (RTM-1): nothing here creates one (BKD-0.6), and a database that
lacks them refuses with `layout_incomplete`. The connection is the backend's `Database`, bounded and autocommitted.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from arbol_backend.database import Database
from arbol_backend.model import Refused
from arbol_radar.model import Loss, Profile, Report, Result, Role, Subscription, Weight
from arbol_radar.vigor import compute

TABLES = ("vigor_profiles", "vigor_reports", "vigor_results")
REPORT_COLUMNS = "id, outcome, fetched_at, message, windows, extra, arrived_at, run"
RESULT_COLUMNS = (
    "id, moment, report, profile, losses, vigor, exhausted, predicted, stale, unknown, notes, next_change, next_value"
)


@dataclass(frozen=True)
class Replay:
    """One recorded result beside the result of computing it again, at its moment, over its report, by a profile."""

    recorded: Result
    replayed: Result

    @property
    def same(self) -> bool:
        return self.recorded == self.replayed


def loss_row(entry: Loss) -> dict[str, Any]:
    """A `Loss` entry as the `losses` column holds it: the window as used, its role, loss, weight and contribution."""
    return {
        "label": entry.label,
        "resource": entry.resource,
        "countedAs": entry.counted_as,
        "assumed": entry.assumed,
        "role": entry.role,
        "reached": entry.reached,
        "loss": entry.loss,
        "weight": entry.weight,
        "contribution": entry.contribution,
        "reason": entry.reason,
        "predicted": entry.predicted,
        "usedPercent": entry.used_percent,
        "resetsAt": entry.resets_at.isoformat() if entry.resets_at is not None else None,
        "windowMinutes": entry.window_minutes,
    }


def _role(value: object) -> Role:
    if value == "store":
        return "store"
    if value == "gate":
        return "gate"
    if value == "shown":
        return "shown"
    raise Refused("database_unavailable", "A recorded loss entry names an unknown role.")


def _loss(value: Mapping[str, Any]) -> Loss:
    resets = value.get("resetsAt")
    return Loss(
        label=str(value["label"]),
        resource=value.get("resource"),
        counted_as=value.get("countedAs"),
        assumed=bool(value.get("assumed")),
        role=_role(value.get("role")),
        reached=bool(value.get("reached")),
        loss=value.get("loss"),
        weight=value.get("weight"),
        contribution=value.get("contribution"),
        reason=value.get("reason"),
        predicted=bool(value.get("predicted")),
        used_percent=value.get("usedPercent"),
        resets_at=datetime.fromisoformat(resets) if isinstance(resets, str) else None,
        window_minutes=value.get("windowMinutes"),
    )


def profile_row(profile: Profile) -> list[dict[str, Any]]:
    """The learned gate weights of a profile as the `gates` column holds them, with their marking."""
    return [
        {"family": family, "label": label, "value": weight.value, "source": weight.source}
        for (family, label), weight in profile.gates.items()
    ]


class Records:
    """The Vigor tables of one Root's database, through the backend's bounded connection."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def layout(self) -> bool:
        """Whether the Root's database has the three tables of the Vigor records; the Arbol process creates none."""
        rows = await self.database.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p') AND c.relname = ANY(%s)",
            [list(TABLES)],
        )
        return bool(rows and rows[0][0] == len(TABLES))

    async def require_layout(self) -> None:
        if not await self.layout():
            raise Refused("layout_incomplete", "The Root's own layout lacks the Subscriptions Vigor tables.")

    async def ensure_profile(self, profile: Profile, now: datetime) -> bool:
        """Write the profile when the table has no profile of its version; True when it was written now."""
        await self.require_layout()
        rows = await self.database.execute(
            "INSERT INTO vigor_profiles (version, approval, pace, placeholder, gates, stale_rule, recorded_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (version) DO NOTHING RETURNING version",
            [
                profile.version,
                profile.approval,
                profile.pace,
                profile.placeholder.value,
                Jsonb(profile_row(profile)),
                profile.stale_rule,
                now,
            ],
        )
        return bool(rows)

    async def profile(self, version: int) -> Profile | None:
        """The recorded profile of a version, as the calculation takes it; None when the table has none."""
        rows = await self.database.execute(
            "SELECT approval, pace, placeholder, gates, stale_rule FROM vigor_profiles WHERE version=%s", [version]
        )
        if not rows:
            return None
        approval, pace, placeholder, gates, rule = rows[0]
        return Profile(
            version=version,
            approval=str(approval),
            pace=str(pace),
            placeholder=Weight(float(placeholder), "placeholder"),
            gates={
                (str(gate["family"]), str(gate["label"])): Weight(float(gate["value"]), gate.get("source", "learned"))
                for gate in gates
            },
            stale_rule=str(rule),
        )

    async def record_report(
        self, subscription: Subscription, value: Mapping[str, Any], *, now: datetime, run: str | None = None
    ) -> Report | None:
        """Record a Driver's `UsageReport` as delivered when its fetchedAt is newer than the last recorded one.

        The report is read first, so what the Interface rejects raises `Rejected` and writes nothing. None when the
        Subscription already has a report fetched at that moment or later: the row is not written again (SGM-1.10).
        """
        await self.require_layout()
        report = Report.from_contract(subscription, value, report_id=str(uuid.uuid4()), arrived_at=now, run=run)
        rows = await self.database.execute(
            "INSERT INTO vigor_reports (id, driver, subscription, family, outcome, fetched_at, message, windows, extra, "
            "arrived_at, run) SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s WHERE NOT EXISTS "
            "(SELECT 1 FROM vigor_reports WHERE driver=%s AND subscription=%s AND fetched_at >= %s) RETURNING id",
            [
                report.id,
                subscription.driver,
                subscription.id,
                subscription.family,
                report.outcome,
                report.fetched_at,
                report.message,
                Jsonb(list(report.delivered)),
                Jsonb(dict(report.extra)),
                report.arrived_at,
                report.run,
                subscription.driver,
                subscription.id,
                report.fetched_at,
            ],
        )
        return report if rows else None

    def _report(self, subscription: Subscription, row: Sequence[Any]) -> Report:
        identifier, outcome, fetched, message, windows, extra, arrived, run = row
        value: dict[str, Any] = {
            "outcome": outcome,
            "fetchedAt": fetched.isoformat(),
            "windows": windows,
            "extra": extra,
        }
        if message is not None:
            value["message"] = message
        return Report.from_contract(
            subscription, value, report_id=str(identifier), arrived_at=arrived, run=str(run) if run else None
        )

    async def reported(self) -> list[Subscription]:
        """Every Subscription with a recorded report, by its Driver and identifier."""
        rows = await self.database.execute(
            "SELECT DISTINCT driver, subscription, family FROM vigor_reports ORDER BY driver, subscription, family", []
        )
        return [Subscription(str(driver), str(identifier), str(family)) for driver, identifier, family in rows]

    async def reports(self, subscription: Subscription) -> list[Report]:
        """Every recorded report of the Subscription, oldest first."""
        rows = await self.database.execute(
            f"SELECT {REPORT_COLUMNS} FROM vigor_reports WHERE driver=%s AND subscription=%s ORDER BY fetched_at",
            [subscription.driver, subscription.id],
        )
        return [self._report(subscription, row) for row in rows]

    async def last_report(self, subscription: Subscription) -> Report | None:
        """The last recorded report of the Subscription, the one with the latest fetchedAt; None when there is none."""
        rows = await self.database.execute(
            f"SELECT {REPORT_COLUMNS} FROM vigor_reports WHERE driver=%s AND subscription=%s "
            "ORDER BY fetched_at DESC LIMIT 1",
            [subscription.driver, subscription.id],
        )
        return self._report(subscription, rows[0]) if rows else None

    async def record_result(self, result: Result) -> str:
        """Record one calculation with everything the Result record names; the row's identifier."""
        await self.require_layout()
        identifier = str(uuid.uuid4())
        await self.database.execute(
            f"INSERT INTO vigor_results ({RESULT_COLUMNS}, driver, subscription, family) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                identifier,
                result.moment,
                result.report,
                result.profile,
                Jsonb([loss_row(entry) for entry in result.windows]),
                result.vigor,
                result.exhausted,
                result.predicted,
                result.stale,
                result.unknown,
                Jsonb(list(result.notes)),
                result.next_change,
                result.next_value,
                result.subscription.driver,
                result.subscription.id,
                result.subscription.family,
            ],
        )
        return identifier

    @staticmethod
    def _result(subscription: Subscription, row: Sequence[Any]) -> Result:
        _, moment, report, profile, losses, vigor, exhausted, predicted, stale, unknown, notes, change, value = row
        return Result(
            subscription=subscription,
            moment=moment,
            report=str(report) if report is not None else None,
            profile=int(profile),
            windows=tuple(_loss(entry) for entry in losses),
            vigor=vigor,
            exhausted=bool(exhausted),
            notes=tuple(str(note) for note in notes),
            predicted=bool(predicted),
            stale=stale if isinstance(stale, timedelta) else None,
            unknown=unknown,
            next_change=change,
            next_value=value,
        )

    async def results(self, subscription: Subscription) -> list[Result]:
        """Every recorded calculation of the Subscription, oldest first."""
        rows = await self.database.execute(
            f"SELECT {RESULT_COLUMNS} FROM vigor_results WHERE driver=%s AND subscription=%s ORDER BY moment, id",
            [subscription.driver, subscription.id],
        )
        return [self._result(subscription, row) for row in rows]

    async def last_result(self, subscription: Subscription) -> Result | None:
        """The latest recorded calculation of the Subscription; None when there is none."""
        rows = await self.database.execute(
            f"SELECT {RESULT_COLUMNS} FROM vigor_results WHERE driver=%s AND subscription=%s "
            "ORDER BY moment DESC, id DESC LIMIT 1",
            [subscription.driver, subscription.id],
        )
        return self._result(subscription, rows[0]) if rows else None

    async def calculate(self, subscription: Subscription, profile: Profile, now: datetime) -> Result:
        """Compute the Subscription's Vigor at `now` over its last recorded report by `profile`, and record it."""
        await self.ensure_profile(profile, now)
        result = compute(await self.last_report(subscription), profile, now, subscription=subscription)
        await self.record_result(result)
        return result

    async def replay(self, subscription: Subscription, profile: Profile) -> list[Replay]:
        """Compute every recorded calculation of the Subscription again, at its moment over its report, by `profile`.

        With the profile the calculations were made by, every replayed result equals the recorded one; with a changed
        profile the replay shows what the formula would have given over the same history (SGM-1.14). Nothing is written.
        """
        reports = {report.id: report for report in await self.reports(subscription)}
        replays: list[Replay] = []
        for recorded in await self.results(subscription):
            report = reports.get(recorded.report) if recorded.report is not None else None
            if recorded.report is not None and report is None:
                raise Refused("database_unavailable", "A recorded result names a report that is not recorded.")
            replays.append(Replay(recorded, compute(report, profile, recorded.moment, subscription=subscription)))
        return replays
