"""Combine independent Root metadata within one bounded Bridge reply."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .bridge import MAX_LINE, Error, Params, Registry
from .chat_data import encoded
from .listings import CAPACITY, Listings
from .model import Refused
from .roots import Roots

TOTAL = 25.0


class Discovery:
    def __init__(self, roots: Roots, listings: Listings, registry: Registry, *, total: float = TOTAL) -> None:
        self.roots, self.listings, self.total = roots, listings, total
        self.task: asyncio.Task[Params | Error] | None = None
        registry.method("roots.list", self.get)

    async def read(self) -> Params:
        started = time.monotonic()
        try:
            async with asyncio.timeout(self.total):
                catalogue = await self.roots.catalogue()
        except TimeoutError as error:
            raise Error("no_answer", source="roots") from error
        self.listings.forget({row["root"] for row in catalogue} | {self.roots.identity.root})
        failure = Error("no_answer", source="root-manager").wire()
        entries: list[Params] = [{"root": row, "error": failure} for row in catalogue]
        sizes = [len(encoded(entry)) for entry in entries]
        size = len(encoded({"roots": entries}))
        work = iter(enumerate(catalogue))
        async def worker() -> None:
            nonlocal size
            for index, info in work:
                try:
                    listed = await self.listings.get(info["root"])
                    entry: Params = {"root": info, "exchanges": listed["exchanges"]}
                    if listed["unreadable"]:
                        entry["error"] = Error("no_answer", source="root-manager").wire()
                except Refused as error:
                    entry = {"root": info, "error": error.wire() if isinstance(error, Error) else failure}
                length = len(encoded(entry))
                if size-sizes[index]+length <= MAX_LINE-4096:
                    size += length-sizes[index]
                    sizes[index], entries[index] = length, entry
        workers = [asyncio.create_task(worker()) for _ in range(min(CAPACITY, len(catalogue)))]
        try:
            async with asyncio.timeout(max(0, self.total-(time.monotonic()-started))):
                await asyncio.gather(*workers)
        except TimeoutError:
            pass  # The untouched entries keep a truthful bounded per-Root no-answer.
        finally:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        return {"roots": entries}

    async def outcome(self) -> Params | Error:
        try:
            return await self.read()
        except Refused as error:
            return error if isinstance(error, Error) else Error("no_answer", source="roots")
        except asyncio.CancelledError:
            raise
        except Exception:
            return Error("no_answer", source="roots")

    async def get(self, params: Params) -> Any:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.outcome())
        result = await asyncio.shield(self.task)
        if isinstance(result, Error):
            raise result
        return result

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
