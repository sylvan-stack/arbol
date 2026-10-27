"""Own-Root awake-clock outside looks and revalidated, serialized force requests."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .bridge import Params
from .controls import Controls
from .listings import Listings
from .metadata import Attention, now
from .model import Identity, Refused
from .notes import Notes

LOOK = 30.0
UNCHANGED = 90.0
ACTIVE = {"accepting", "running", "ending"}


def awake() -> float:
    clock = getattr(time, "CLOCK_UPTIME_RAW", time.CLOCK_MONOTONIC)
    return time.clock_gettime(clock)


def signature(row: Params) -> tuple[Any, ...]:
    return row["process"]["pid"], row["process"]["startedAt"], row["chat"], row["trunk"], row["build"]


@dataclass(frozen=True)
class Observation:
    identity: tuple[Any, ...]
    heartbeat: int
    first: float


class Stuck:
    def __init__(self, identity: Identity, listings: Listings, controls: Controls, notes: Notes, attention: Attention,
                 *, clock: Callable[[], float] = awake, look: float = LOOK, unchanged: float = UNCHANGED,
                 poll: float = 1.0) -> None:
        self.identity, self.listings, self.controls, self.notes, self.attention = identity, listings, controls, notes, attention
        self.clock, self.look, self.unchanged, self.poll = clock, look, unchanged, poll
        self.observed: dict[str, Observation] = {}
        self.handled: dict[str, tuple[tuple[Any, ...], int]] = {}
        self.forces: dict[str, asyncio.Task[None]] = {}
        self.failed_notes: dict[str, tuple[str, str]] = {}
        self.note_tasks: dict[str, asyncio.Task[None]] = {}
        self.watcher: asyncio.Task[None] | None = None
        self.closed = False

    def failed(self, root: str) -> None:
        if root == self.identity.root:
            self.observed.clear()

    def observe(self, root: str, value: Params) -> None:
        if self.closed or root != self.identity.root:
            return
        at = self.clock()
        current: dict[str, Observation] = {}
        for row in value["exchanges"]:
            if row["state"] not in ACTIVE or row["process"]["alive"] is not True:
                continue
            exchange, heartbeat, identity = row["exchange"], row["signsOfLife"]["heartbeat"], signature(row)
            previous = self.observed.get(exchange)
            if previous is None or (previous.identity, previous.heartbeat) != (identity, heartbeat) or at < previous.first:
                previous = Observation(identity, heartbeat, at)
                self.handled.pop(exchange, None)
            current[exchange] = previous
            task = self.forces.get(exchange)
            if (at-previous.first >= self.unchanged and self.handled.get(exchange) != (identity, heartbeat)
                    and (task is None or task.done())):
                self.forces[exchange] = asyncio.create_task(self.force(exchange, row["chat"], previous, now()))
        self.observed = current
        for exchange in self.handled.keys() - current.keys():
            self.handled.pop(exchange, None)
        self.retry_notes()

    async def still_stuck(self, exchange: str, expected: Observation) -> bool:
        try:
            value = await self.listings.get(self.identity.root, after=time.monotonic())
        except Refused:
            return False
        actual = next((row for row in value["exchanges"] if row["exchange"] == exchange), None)
        observation = self.observed.get(exchange)
        return (actual is not None and actual["state"] in ACTIVE and actual["process"]["alive"] is True
                and signature(actual) == expected.identity and actual["signsOfLife"]["heartbeat"] == expected.heartbeat
                and observation is not None and observation.identity == expected.identity
                and observation.heartbeat == expected.heartbeat and self.clock()-observation.first >= self.unchanged)

    async def save_note(self, exchange: str, chat: str, at: str) -> None:
        try:
            await self.notes.record(exchange, chat, at=at)
            self.failed_notes.pop(exchange, None)
            if not self.failed_notes:
                self.attention.close("notes_unavailable")
        except (OSError, Refused):
            self.failed_notes[exchange] = (chat, at)
            self.notes.request()  # A complete published file may survive an interrupted final fsync.
            self.attention.open("notes_unavailable", "An Exchange was interrupted because it was stuck, but its note could not be stored.")

    def retry_notes(self) -> None:
        if self.closed:
            return
        for exchange, (chat, at) in list(self.failed_notes.items()):
            task = self.note_tasks.get(exchange)
            if task is None or task.done():
                self.note_tasks[exchange] = asyncio.create_task(self.save_note(exchange, chat, at))

    async def force(self, exchange: str, chat: str, expected: Observation, at: str) -> None:
        async def check() -> bool:
            return await self.still_stuck(exchange, expected)
        try:
            result = await self.controls.force(exchange, chat, check)
            self.handled[exchange] = (expected.identity, expected.heartbeat)
            if result["ended"] == "interrupted":
                await self.save_note(exchange, chat, at)
        except Refused:
            pass  # No invented end or note; a later successful look can supply a new reason.
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def check_once(self) -> None:
        try:
            await self.listings.get(self.identity.root)
        except Refused:
            self.failed(self.identity.root)

    async def watch(self) -> None:
        next_look = self.clock()
        while True:
            at = self.clock()
            if at >= next_look:
                next_look = at+self.look
                await self.check_once()
            await asyncio.sleep(min(self.poll, max(0, next_look-self.clock())))

    def start(self) -> None:
        if self.watcher is None:
            self.watcher = asyncio.create_task(self.watch())

    async def close(self) -> None:
        self.closed = True
        tasks = [*self.forces.values(), *self.note_tasks.values(), *([self.watcher] if self.watcher else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
