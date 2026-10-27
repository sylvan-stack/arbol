"""Coalesce own-Root settling reasons and retain unresolved mutation ownership."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from .bridge import Error, Params, uuid_id
from .database import Database
from .exchange_files import timestamp
from .live import Live
from .model import BUILD_ID, Refused
from .process import Programs

ELIGIBLE = {"unaccepted", "unsaved", "interrupted"}


def listing(value: Any, root: str) -> list[Params]:
    if (not isinstance(value, dict) or value.get("root") != root or not isinstance(value.get("exchanges"), list)
            or not isinstance(value.get("unreadable"), list)):
        raise Error("no_answer")
    for id in value["unreadable"]:
        uuid_id(id)
    for row in value["exchanges"]:
        if (not isinstance(row, dict) or row.get("root") != root or not isinstance(row.get("state"), str)
                or not row["state"] or not isinstance(row.get("process"), dict)
                or not isinstance(row.get("signsOfLife"), dict)
                or not isinstance(row.get("trunk"), str) or not re.fullmatch(r"[a-z][a-z0-9]{0,31}", row["trunk"])
                or not isinstance(row.get("build"), str) or (row["build"] != "0" and not BUILD_ID.fullmatch(row["build"]))):
            raise Error("no_answer")
        uuid_id(row.get("exchange"))
        uuid_id(row.get("chat"))
        process, life = row["process"], row["signsOfLife"]
        if (type(process.get("pid")) is not int or process["pid"] < 1 or type(process.get("alive")) is not bool
                or type(life.get("heartbeat")) is not int or life["heartbeat"] < 0
                or not isinstance(life.get("waitingFor"), str) or not life["waitingFor"]):
            raise Error("no_answer")
        timestamp(process.get("startedAt"))
        timestamp(life.get("since"))
    return value["exchanges"]  # type: ignore[no-any-return]


class Settling:
    def __init__(self, programs: Programs, database: Database, live: Live) -> None:
        self.programs, self.database, self.live = programs, database, live
        self.pending = False
        self.look_pending = False
        self.worker: asyncio.Task[None] | None = None
        self.look: asyncio.Task[None] | None = None
        self.closed = False
        self.live.on_dead = self.request_listing

    def request(self) -> None:
        if self.closed:
            return
        self.pending = True
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self.work())

    async def work(self) -> None:
        while self.pending:
            self.pending = False
            # A returned timeout is not a returned manager. A new reason may wait for it,
            # but never launches another settle while its actual process is retained.
            while True:
                self.programs.reap()
                if ("settle", self.live.identity.root) not in self.programs.running:
                    break
                await asyncio.sleep(0.05)
            try:
                await self.database.execute("SELECT 1")
                value = await self.programs.call("arbol-root", ["settle"], kind="settle")
                if (not isinstance(value, dict) or value.get("root") != self.live.identity.root
                        or not isinstance(value.get("results"), list)):
                    raise Error("no_answer")
            except Refused:
                pass  # No retry without another reason; recovery/public attention belongs to SYL-252.

    def request_listing(self) -> None:
        if self.closed:
            return
        self.look_pending = True
        if self.look is None or self.look.done():
            self.look = asyncio.create_task(self.observe())

    async def observe(self) -> None:
        while self.look_pending:
            self.look_pending = False
            try:
                value = await self.programs.call("arbol-root", ["list"], kind="list")
                rows = listing(value, self.live.identity.root)
                if any(row["state"] in ELIGIBLE for row in rows):
                    self.request()
            except Refused:
                pass

    def start(self) -> None:
        self.request()
        self.request_listing()

    async def close(self) -> None:
        self.closed = True
        self.live.on_dead = None
        tasks = [task for task in (self.worker, self.look) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
