"""Shared allowlisted Driver reads and bounded independently failed public accounts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from .account_data import CODE, Public
from .bridge import MAX_LINE, Error, Params, Registry, encode
from .dispatch import Forwarded
from .migration import message
from .process import Programs
from .validation import Catalogues

TOTAL = 25.0
CAPACITY = 8


class Accounts:
    def __init__(self, programs: Programs, catalogues: Catalogues, registry: Registry,
                 secrets: Callable[[], tuple[str, ...]], *, total: float = TOTAL, capacity: int = CAPACITY) -> None:
        self.programs, self.catalogues, self.secrets = programs, catalogues, secrets
        self.total, self.capacity = total, asyncio.Semaphore(capacity)
        self.raws: dict[str, asyncio.Task[list[Any] | Error]] = {}
        self.closed = False
        catalogues.fetch = self.raw
        registry.method("accounts.list", self.list)

    def scan(self) -> list[str]:
        drivers = self.programs.find_drivers()
        self.catalogues.launchers = drivers
        for name in self.catalogues.subscriptions.keys()-drivers:
            self.catalogues.subscriptions.pop(name, None)
        return sorted(drivers)

    def refused(self, value: Any) -> None:
        if not isinstance(value, dict) or "error" not in value:
            return
        error = value["error"]
        if not isinstance(error, dict) or not isinstance(error.get("code"), str) or not CODE.fullmatch(error["code"]):
            raise Error("no_answer", source="driver")
        raise Forwarded(error["code"], "driver", message(error.get("message"), secrets=self.secrets(),
            fallback="The Driver refused this account operation."))

    async def raw_outcome(self, driver: str) -> list[Any] | Error:
        try:
            async with asyncio.timeout(self.total), self.capacity:
                value = await self.programs.call("arbol-"+driver+"-driver", ["subscriptions", "list"],
                                                 kind="account", key="accounts-list-"+driver)
            self.refused(value)
            public = Public(self.secrets())
            rows = public.array(value)
            identifiers = [public.id(public.object(row).get("id")) for row in rows]
            if len(set(identifiers)) != len(identifiers):
                raise Error("no_answer", source="driver")
            self.catalogues.subscriptions[driver] = set(identifiers)
            return rows
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.catalogues.subscriptions.pop(driver, None)
            return error if isinstance(error, Error) else Error("no_answer", source="driver")

    def forget(self, driver: str, task: asyncio.Task[list[Any] | Error]) -> None:
        if self.raws.get(driver) is task:
            self.raws.pop(driver, None)

    async def raw(self, driver: str) -> list[Any]:
        if self.closed:
            raise Error("ended", source="driver")
        task = self.raws.get(driver)
        if task is None or task.done():
            task = asyncio.create_task(self.raw_outcome(driver))
            self.raws[driver] = task
            task.add_done_callback(lambda finished: self.forget(driver, finished))
        result = await asyncio.shield(task)
        if isinstance(result, Error):
            raise result
        return result

    async def list(self, params: Params) -> Params:
        if self.closed:
            raise Error("ended", source="driver")
        drivers = self.scan()
        error = Error("no_answer", source="driver").wire()
        rows: list[Params] = [{"driver": name, "error": error} for name in drivers]
        budget = len(encode({"drivers": rows}))
        limit = MAX_LINE-4096
        if budget > limit:
            raise Error("no_answer", source="driver")
        queue = asyncio.Queue[int]()
        for index in range(len(rows)):
            queue.put_nowait(index)
        async def worker() -> None:
            nonlocal budget
            while not queue.empty():
                index = queue.get_nowait()
                driver = drivers[index]
                try:
                    raw = await self.raw(driver)
                    public = Public(self.secrets())
                    entry: Params = {"driver": driver, "subscriptions": [public.subscription(value) for value in raw]}
                except Exception as refused:
                    entry = {"driver": driver, "error": (refused if isinstance(refused, Error) else Error("no_answer", source="driver")).wire()}
                delta = len(encode(entry))-len(encode(rows[index]))
                if budget+delta <= limit:
                    rows[index] = entry
                    budget += delta
        workers = [asyncio.create_task(worker()) for _ in range(min(CAPACITY, len(rows)))]
        try:
            async with asyncio.timeout(self.total):
                await asyncio.gather(*workers)
        except TimeoutError:
            pass
        finally:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        return {"drivers": rows}

    async def close(self) -> None:
        self.closed = True
        self.catalogues.fetch = None
        tasks = list(self.raws.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.raws.clear()
