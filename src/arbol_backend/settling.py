"""Coalesce own-Root settling reasons and retain unresolved mutation ownership."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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


@dataclass
class Queue:
    root: str
    pending: bool = False
    task: asyncio.Task[None] | None = None


class Settling:
    def __init__(self, programs: Programs, database: Database, live: Live) -> None:
        self.programs, self.database, self.live = programs, database, live
        self.queues = {live.identity.root: Queue(live.identity.root)}
        self.look_pending = False
        self.look: asyncio.Task[None] | None = None
        self.closed = False
        self.read_listing: Callable[[str], Awaitable[Params]] | None = None
        self.on_settled: Callable[[str], None] | None = None
        self.live.on_dead = self.request_listing

    @property
    def worker(self) -> asyncio.Task[None] | None:
        return self.queues[self.live.identity.root].task

    def request(self, root: str | None = None) -> None:
        if self.closed:
            return
        selected = self.live.identity.root if root is None else root
        queue = self.queues.setdefault(selected, Queue(selected))
        queue.pending = True
        if queue.task is None or queue.task.done():
            queue.task = asyncio.create_task(self.work(queue))

    async def work(self, queue: Queue) -> None:
        while queue.pending:
            queue.pending = False
            while True:
                self.programs.reap()
                if self.programs.command_key("settle", queue.root, queue.root) not in self.programs.running:
                    break
                await asyncio.sleep(0.05)
            try:
                await self.database.execute("SELECT 1")
                value = await self.programs.call("arbol-root", ["settle"], kind="settle", root=queue.root)
                if (not isinstance(value, dict) or value.get("root") != queue.root
                        or not isinstance(value.get("results"), list)):
                    raise Error("no_answer")
                if self.on_settled:
                    self.on_settled(queue.root)
            except Refused:
                pass  # No retry without another reason.

    def listed(self, root: str, value: Params) -> None:
        if any(row["state"] in ELIGIBLE for row in value["exchanges"]):
            self.request(root)

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
                if self.read_listing:
                    await self.read_listing(self.live.identity.root)  # Its one shared result callback owns this reason.
                else:
                    raw = await self.programs.call("arbol-root", ["list"], kind="list")
                    self.listed(self.live.identity.root, {"exchanges": listing(raw, self.live.identity.root)})
            except Refused:
                pass

    def start(self) -> None:
        self.request()
        self.request_listing()

    async def close(self) -> None:
        self.closed = True
        self.live.on_dead = None
        tasks = [queue.task for queue in self.queues.values() if queue.task is not None]
        if self.look is not None:
            tasks.append(self.look)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
