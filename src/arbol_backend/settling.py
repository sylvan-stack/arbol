"""Settle verified pending Exchange UUIDs without substituting Builds."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .bridge import Params
from .database import Database
from .model import Refused
from .process import Programs

ELIGIBLE = {"unaccepted", "unsaved", "interrupted"}


class Settling:
    def __init__(self, programs: Programs, database: Database, read_listing: Callable[[], Awaitable[Params]]) -> None:
        self.programs, self.database, self.read_listing = programs, database, read_listing
        self.eligible: set[str] = set()
        self.pending: set[str] = set()
        self.worker: asyncio.Task[None] | None = None
        self.look: asyncio.Task[None] | None = None
        self.closed = False
        self.on_settled: Callable[[], None] | None = None

    def request(self) -> None:
        if not self.closed:
            self.pending.update(self.eligible)
            self.start_worker()

    def start_worker(self) -> None:
        if self.pending and (self.worker is None or self.worker.done()):
            self.worker = asyncio.create_task(self.work())

    async def work(self) -> None:
        while self.pending:
            exchange = min(self.pending)
            self.pending.remove(exchange)
            try:
                self.programs.reap()
                if ("settle", exchange) in self.programs.running:
                    continue  # The detached runtime is still the owner of the earlier call.
                await self.database.execute("SELECT 1")
                value = await self.programs.call("arbol-exchanges", ["settle", exchange], kind="settle", key=exchange)
                if not isinstance(value, dict) or "root" in value or not isinstance(value.get("results"), list):
                    continue
                saved = [row for row in value["results"] if isinstance(row, dict) and row.get("exchange") == exchange
                         and "error" not in row and isinstance(row.get("settled"), str)]
                if len(saved) == 1 and self.on_settled:
                    self.on_settled()
            except Refused:
                pass  # The runtime retains an unverified folder. Reopen, reconnect or a new observation can retry.

    def listed(self, value: Params) -> None:
        current = {row["exchange"] for row in value["exchanges"] if row["state"] in ELIGIBLE}
        self.pending.update(current - self.eligible)
        self.eligible = current
        if not self.closed:
            self.start_worker()

    async def observe(self) -> None:
        try:
            await self.read_listing()
        except Refused:
            pass

    def start(self) -> None:
        if not self.closed and (self.look is None or self.look.done()):
            self.look = asyncio.create_task(self.observe())

    async def close(self) -> None:
        self.closed = True
        tasks = [task for task in (self.worker, self.look) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
