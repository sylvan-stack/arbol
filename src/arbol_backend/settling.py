"""Coalesce own-Root settling reasons and retain unresolved mutation ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .bridge import Error, Params
from .database import Database
from .live import Live
from .model import Refused
from .process import Programs

ELIGIBLE = {"unaccepted", "unsaved", "interrupted"}


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
        self.read_listing: Callable[[], Awaitable[Params]] | None = None
        self.eligible: frozenset[str] = frozenset()
        self.on_settled: Callable[[str], None] | None = None

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

    def listed(self, value: Params) -> None:
        pending = frozenset(row["exchange"] for row in value["exchanges"] if row["state"] in ELIGIBLE)
        if pending - self.eligible:
            self.request()
        self.eligible = pending

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
                    await self.read_listing()
            except Refused:
                pass

    def start(self) -> None:
        self.request()
        self.request_listing()

    async def close(self) -> None:
        self.closed = True
        tasks = [queue.task for queue in self.queues.values() if queue.task is not None]
        if self.look is not None:
            tasks.append(self.look)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
