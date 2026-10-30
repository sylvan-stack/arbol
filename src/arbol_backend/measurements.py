"""Partial own-connection PostgreSQL sizes and confirmed local data-disk measurements."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from .bridge import Error, Params, Registry
from .database import Session
from .health import Health
from .metadata import now
from .model import Refused
from .roots import Roots
from .storage import LocalDisk
from .stuck import awake

TOTAL = 25.0
INTERVAL = 300.0
GIB = 1024**3
SIZE_PROBLEM = "This database's size is not available."
DISK_PROBLEM = "The database server's local data disk could not be measured."


class Measurements:
    def __init__(self, health: Health, roots: Roots, registry: Registry, *, total: float = TOTAL,
                 disk: LocalDisk | None = None, clock: Callable[[], float] = awake,
                 interval: float = INTERVAL, poll: float = 1) -> None:
        self.health, self.database, self.roots = health, health.database, roots
        self.total, self.disk = total, disk or LocalDisk()
        self.task: asyncio.Task[Params] | None = None
        self.clock, self.interval, self.poll = clock, interval, poll
        self.watcher: asyncio.Task[None] | None = None
        self.return_waiter: asyncio.Task[None] | None = None
        self.result_epoch = -1
        self.closed = False
        registry.method("health.measure", self.measure)

    def server(self) -> Params:
        return ({"ok": False, "problem": self.health.cause or "The database server does not answer."}
                if self.database.away else {"ok": True})

    @staticmethod
    def amount(value: int) -> str:
        return f"{value/GIB:.1f} GiB" if value >= GIB else f"{value/(1024**2):.1f} MiB"

    def mark(self, report: Params) -> None:
        free = report.get("freeBytes")
        if type(free) is not int or self.closed:
            return  # Only an actual new reading can clear an earlier low-space warning.
        if free >= 10*GIB:
            self.health.attention.close("space_low")
            return
        warning = "urgent" if free < 2*GIB else "low"
        report["warning"] = warning
        folder = report.get("dataFolderBytes")
        detail = ("Data folder uses "+self.amount(folder)+". " if type(folder) is int else "Data folder size is unavailable. ")
        known = [row for row in report["roots"] if type(row.get("bytes")) is int]
        if known:
            largest = max(known, key=lambda row: row["bytes"])
            detail += str(largest["name"])+"'s chats take "+self.amount(largest["bytes"])+"."
        else:
            detail += "Database sizes are unavailable."
        self.health.attention.open("space_low", self.amount(free)+" left on the disk of the database. "+detail,
                                   severity="urgent" if warning == "urgent" else "warning")

    async def read_disk(self, report: Params, raw: str, host: str, server: str | None) -> None:
        try:
            report.update(await self.disk.get(raw, host, server))
        except Exception:
            report["diskProblem"] = DISK_PROBLEM

    async def limited_disk(self, report: Params, session: Session) -> tuple[str, str, str | None] | None:
        """Confirm the installed server without granting the limited role settings access."""
        try:
            rows = await session.execute("SELECT pg_backend_pid(), EXTRACT(EPOCH FROM pg_postmaster_start_time())::double precision, inet_server_addr()::text")
            if (len(rows) != 1 or len(rows[0]) != 3 or type(rows[0][0]) is not int
                    or type(rows[0][1]) not in (int, float)
                    or rows[0][2] is not None and not isinstance(rows[0][2], str)):
                raise ValueError("No authenticated process metadata.")
            pid, started, server = rows[0]
            host = session.connection.info.host
            if not self.disk.local(host, server):
                raise ValueError("The database server is not local.")
            candidate = self.database.identity.home / "Library/Application Support/Arbol/database/data"
            path = await asyncio.to_thread(self.disk.confirm, candidate, pid, float(started))
            return str(path), host, server
        except asyncio.CancelledError:
            raise
        except Exception:
            report["diskProblem"] = DISK_PROBLEM
            return None

    async def collect(self) -> Params:
        report: Params = {"measuredAt": now(), "server": {"ok": False, "problem": "The database check did not finish."}, "roots": []}
        disk_task: asyncio.Task[None] | None = None
        epoch = -1
        try:
            async with asyncio.timeout(self.total):
                await self.health.probe()
                epoch = self.health.epoch
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
                                attested = await self.limited_disk(report, session)
                                if attested is not None:
                                    disk_task = asyncio.create_task(self.read_disk(report, *attested))
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
        self.mark(report)
        self.result_epoch = epoch
        return report

    async def measure(self, params: Params) -> Params:
        if self.closed:
            raise Error("ended")
        self.request()
        assert self.task is not None
        return await asyncio.shield(self.task)

    def request(self) -> None:
        if not self.closed and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self.collect())

    async def refresh_after_return(self, previous: asyncio.Task[Params], epoch: int) -> None:
        await asyncio.shield(previous)
        if (not self.closed and not self.database.away and self.health.epoch == epoch and
                self.task is previous and self.result_epoch != epoch):
            self.request()

    def returned(self) -> None:
        if self.closed:
            return
        previous = self.task
        if previous is None or previous.done():
            self.request()
        else:
            if self.return_waiter is not None:
                self.return_waiter.cancel()
            self.return_waiter = asyncio.create_task(self.refresh_after_return(previous, self.health.epoch))

    async def watch(self) -> None:
        next_measure = self.clock()
        while True:
            at = self.clock()
            if at >= next_measure:
                self.request()
                next_measure = at+self.interval
            await asyncio.sleep(min(self.poll, max(0, next_measure-self.clock())))

    def start(self) -> None:
        if self.watcher is None and not self.closed:
            self.watcher = asyncio.create_task(self.watch())

    async def close(self) -> None:
        self.closed = True
        tasks = [*([self.task] if self.task is not None else []), *([self.watcher] if self.watcher is not None else []),
                 *([self.return_waiter] if self.return_waiter is not None else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
