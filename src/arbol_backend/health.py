"""Classified own-database availability, attention and bounded five-second probes."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from .database import Database
from .metadata import Attention
from .model import Refused

RETRY = 5.0


class Health:
    def __init__(self, database: Database, attention: Attention, *, retry: float = RETRY) -> None:
        self.database, self.attention, self.retry = database, attention, retry
        self.epoch = 0
        self.cause = ""
        self.on_return: Callable[[int], Awaitable[None]] | None = None
        self.on_away: Callable[[], None] | None = None
        self.monitor: asyncio.Task[None] | None = None
        self.recoveries: set[asyncio.Task[None]] = set()
        self.database.on_failure = self.failed
        self.database.on_connected = self.connected

    def failed(self, cause: str) -> None:
        if not self.database.away:
            self.database.away = True
            self.epoch += 1
            self.cause = cause
            self.attention.open("database_unreachable", cause+" New messages cannot be sent; answers in progress go on.")
            if self.on_away:
                self.on_away()

    def connected(self) -> None:
        if not self.database.away:
            return
        self.database.away = False
        self.epoch += 1
        self.cause = ""
        self.attention.close("database_unreachable")
        if self.on_return:
            task = asyncio.create_task(self.recover(self.epoch))
            self.recoveries.add(task)
            task.add_done_callback(self.recoveries.discard)

    async def recover(self, epoch: int) -> None:
        try:
            if self.on_return and epoch == self.epoch and not self.database.away:
                await self.on_return(epoch)
        except Refused:
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # Keep diagnostics fixed; the next actual transition can retry recovery.

    async def probe(self) -> None:
        try:
            async with asyncio.timeout(self.database.seconds):
                if self.database.away:
                    await self.database.renew()
                async with self.database.session(probe=True) as session:
                    await session.execute("SELECT 1")
            self.connected()
        except (TimeoutError, Refused, OSError):
            self.failed("The database server does not answer.")

    async def watch(self) -> None:
        while True:
            started = time.monotonic()
            await self.probe()
            await asyncio.sleep(max(0, self.retry-(time.monotonic()-started)))

    def start(self) -> None:
        if self.monitor is None:
            self.monitor = asyncio.create_task(self.watch())

    async def close(self) -> None:
        tasks = [*self.recoveries, *([self.monitor] if self.monitor is not None else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.recoveries.clear()
        self.database.on_failure = None
        self.database.on_connected = None
        self.on_away = None
        self.on_return = None
