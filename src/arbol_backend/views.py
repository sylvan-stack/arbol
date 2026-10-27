"""Coalesced consistent views; a committed invalidation rejects an older in-flight read."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from .bridge import Error, Params, Snapshot, Topic, Validator, no_params
from .model import Refused

Loader = Callable[[Params], Awaitable[Params]]
Publisher = Callable[[Params | None, Params, Params], None]


class View:
    def __init__(self, loader: Loader, publish: Publisher, validate: Validator = no_params) -> None:
        self.loader, self.publish = loader, publish
        self.topic = Topic(self.snapshot, validate)
        self.states: dict[str, Params] = {}
        self.generations: dict[str, int] = {}
        self.inflight: dict[str, asyncio.Task[Snapshot | Error]] = {}

    @staticmethod
    def key(params: Params) -> str:
        return json.dumps(params, sort_keys=True, separators=(",", ":"))

    def invalidate(self, params: Params | None = None) -> None:
        keys = {self.key(params)} if params is not None else set(self.states) | set(self.inflight)
        for key in keys:
            self.generations[key] = self.generations.get(key, 0) + 1

    async def outcome(self, params: Params, key: str) -> Snapshot | Error:
        try:
            for _ in range(3):
                generation = self.generations.get(key, 0)
                state = await self.loader(params)
                if generation != self.generations.get(key, 0):
                    continue
                # Captured state, publication and its cutoff are indivisible to other tasks.
                self.publish(self.states.get(key), state, params)
                self.states[key] = state
                return Snapshot(self.topic.version, state)
            return Error("timeout")
        except Refused as error:
            return error if isinstance(error, Error) else Error(error.code)
        except Exception:
            return Error("database_unavailable")

    async def snapshot(self, params: Params) -> Snapshot:
        key = self.key(params)
        task = self.inflight.get(key)
        if task is None or task.done():
            task = asyncio.create_task(self.outcome(params, key))
            self.inflight[key] = task
        result = await asyncio.shield(task)
        if isinstance(result, Error):
            raise result
        return result

    def forget_unwatched(self) -> None:
        active = {self.key(sub.params) for sub in self.topic.listeners}
        for key in (set(self.states) | set(self.inflight) | set(self.generations)) - active:
            self.states.pop(key, None)
            task = self.inflight.get(key)
            if task is None or task.done():
                self.inflight.pop(key, None)
                self.generations.pop(key, None)

    async def close(self) -> None:
        tasks = list(self.inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.inflight.clear()
        self.states.clear()
