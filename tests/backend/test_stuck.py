# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""In-process awake clocks and real private managers qualify causal stuck-force notes."""

from __future__ import annotations
import json
import os
import time
from unittest import mock


import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Error, Params  # noqa: E402
from arbol_backend.dispatch import Entry  # noqa: E402
from arbol_backend.stuck import LOOK, UNCHANGED, Stuck, awake  # noqa: E402

from arbol_backend.bridge import Params  # noqa: E402
from arbol_backend.stuck import Stuck  # noqa: E402
from backend.discovery_support import calls, configure, install  # noqa: E402
from backend.live_support import Trunk, now  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class Outside(WindowFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.backend.stuck.close()
        if self.backend.discovery.task:
            await self.backend.discovery.task
        await asyncio.gather(*self.backend.listings.tasks.values())
        self.clock = Clock()
        self.backend.stuck = Stuck(self.backend.identity, self.backend.listings, self.backend.controls,
            self.backend.notes, self.backend.chats.attention, clock=self.clock, poll=0.005)
        self.backend.listings.on_failed = self.backend.stuck.failed
        self.own = self.backend.identity.root
        self.trunk = await Trunk.make(self.frame, chat(1))
        await self.trunk.accept(self.db)
        self.row: Params = {"root": self.own, "exchange": self.trunk.exchange, "chat": chat(1),
            "trunk": "trivial", "build": "0", "state": "running", "process": {**self.trunk.value["process"], "alive": True},
            "signsOfLife": {"heartbeat": 41, "waitingFor": "driver", "since": now()}}
        self.behavior: dict[str, Any] = {self.own: {"force": {"output": self.reply("interrupted")}}}
        install(self.frame, self.behavior)
        self.configure()

    def reply(self, ended: str) -> Params:
        return {"root": self.own, "exchange": self.trunk.exchange, "ended": ended, "forced": True}

    def configure(self) -> None:
        self.behavior[self.own]["list"] = {"output": {"root": self.own, "exchanges": [self.row], "unreadable": []}}
        configure(self.frame, self.behavior)

    async def look(self, at: float, *, heartbeat: int | None = None) -> None:
        self.clock.value = at
        if heartbeat is not None:
            self.row["signsOfLife"]["heartbeat"] = heartbeat
        self.configure()
        await self.backend.stuck.check_once()

    async def forced(self) -> None:
        await asyncio.gather(*self.backend.stuck.forces.values())
        if self.backend.notes.worker:
            await self.backend.notes.worker

    def stops(self, *, force: bool | None = None) -> list[Params]:
        rows = calls(self.frame, kind="stop")
        return [row for row in rows if force is None or ("--force" in row["args"]) == force]

    async def started(self, count: int, *, force: bool | None = None) -> list[Params]:
        async with asyncio.timeout(3):
            while len(rows := self.stops(force=force)) < count:
                await asyncio.sleep(0.01)
        return rows


# Archived complete imports; restore needed names in their original scope, not at this file tail.
