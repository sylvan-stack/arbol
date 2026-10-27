"""Partial own-connection PostgreSQL sizes and confirmed local data-disk measurements."""

from __future__ import annotations

import asyncio

from .bridge import Error, Params, Registry
from .health import Health
from .metadata import now
from .model import Refused
from .roots import Roots
from .storage import LocalDisk

TOTAL = 25.0
SIZE_PROBLEM = "This database's size is not available."
DISK_PROBLEM = "The database server's local data disk could not be measured."


class Measurements:
    def __init__(self, health: Health, roots: Roots, registry: Registry, *, total: float = TOTAL,
                 disk: LocalDisk | None = None) -> None:
        self.health, self.database, self.roots = health, health.database, roots
        self.total, self.disk = total, disk or LocalDisk()
        self.task: asyncio.Task[Params] | None = None
        self.closed = False
        registry.method("health.measure", self.measure)

    def server(self) -> Params:
        return ({"ok": False, "problem": self.health.cause or "The database server does not answer."}
                if self.database.away else {"ok": True})

    async def read_disk(self, report: Params, raw: str, host: str, server: str | None) -> None:
        try:
            report.update(await self.disk.get(raw, host, server))
        except Exception:
            report["diskProblem"] = DISK_PROBLEM

    async def collect(self) -> Params:
        report: Params = {"measuredAt": now(), "server": {"ok": False, "problem": "The database check did not finish."}, "roots": []}
        disk_task: asyncio.Task[None] | None = None
        try:
            async with asyncio.timeout(self.total):
                await self.health.probe()
                report["server"] = self.server()
                try:
                    records = await self.roots.database_records()
                    report["roots"] = [{**row, "problem": row.get("problem", SIZE_PROBLEM)} for row in records]
                except Refused:
                    report["catalogueProblem"] = "The retained Roots could not be listed."
                if self.database.away:
                    report["diskProblem"] = DISK_PROBLEM
                else:
                    try:
                        async with self.database.session() as session:
                            try:
                                rows = await session.execute("SELECT current_setting('data_directory'), inet_server_addr()::text")
                                if (len(rows) != 1 or len(rows[0]) != 2 or not isinstance(rows[0][0], str) or
                                        rows[0][1] is not None and not isinstance(rows[0][1], str)):
                                    report["diskProblem"] = DISK_PROBLEM
                                else:
                                    disk_task = asyncio.create_task(self.read_disk(report, rows[0][0], session.connection.info.host, rows[0][1]))
                            except Refused:
                                report["diskProblem"] = DISK_PROBLEM
                            for row in report["roots"]:
                                if not row["database"]:
                                    continue
                                try:
                                    sizes = await session.execute("SELECT pg_database_size(%s::name)", [row["database"]])
                                    if len(sizes) == 1 and len(sizes[0]) == 1 and type(sizes[0][0]) is int and sizes[0][0] >= 0:
                                        row["bytes"] = sizes[0][0]
                                        row.pop("problem", None)
                                except Refused as error:
                                    row["problem"] = ("This database's size query exceeded its time limit." if error.code == "timeout" else SIZE_PROBLEM)
                                    if self.database.away:
                                        break
                            if disk_task is not None:
                                await disk_task
                    except Refused:
                        report["diskProblem"] = DISK_PROBLEM
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            for row in report["roots"]:
                if "bytes" not in row:
                    row["problem"] = "This database's size measurement did not finish within its time limit."
            if "freeBytes" not in report or "dataFolderBytes" not in report:
                report["diskProblem"] = "The storage measurement exceeded its time limit."
        except Exception:
            report["diskProblem"] = DISK_PROBLEM
        finally:
            if disk_task is not None:
                disk_task.cancel()
                await asyncio.gather(disk_task, return_exceptions=True)
        if self.database.away:
            report["server"] = self.server()
        report["measuredAt"] = now()
        return report

    async def measure(self, params: Params) -> Params:
        if self.closed:
            raise Error("ended")
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.collect())
        return await asyncio.shield(self.task)

    async def close(self) -> None:
        self.closed = True
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
