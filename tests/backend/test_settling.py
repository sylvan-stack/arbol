# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Own-Root queue reasons, database gating, listing identity and retained real children."""

from __future__ import annotations
import os
import time
from unittest import mock


import asyncio
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Error, Params  # noqa: E402
from arbol_backend.model import Refused  # noqa: E402
from arbol_backend.process import LIMITS  # noqa: E402
from arbol_backend.settling import listing  # noqa: E402
from backend.live_support import Trunk, now  # noqa: E402

from arbol_backend.bridge import Params  # noqa: E402
from backend.live_support import now  # noqa: E402
from backend.support import STANDIN  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class Settles(WindowFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        assert self.backend.settling.worker and self.backend.settling.look
        await self.backend.settling.worker
        await self.backend.settling.look
        if self.backend.discovery.task is not None:
            await self.backend.discovery.task
        await asyncio.gather(*self.backend.listings.tasks.values())
        self.initial = self.calls()
        code = STANDIN.replace("config=json.loads((base/'behavior.json').read_text()).get(name,{})",
            "config=json.loads((base/'behavior.json').read_text()).get(name,{})\nconfig=config.get('commands',{}).get(sys.argv[3],config)")
        self.frame.bin.joinpath("arbol-root").write_text("#!/bin/sh\nexec "+shlex.quote(sys.executable)+" -I -c "+shlex.quote(code)+' "$0" "$@"\n')
        self.configure()

    def configure(self, *, settle_sleep: float = 0, list_sleep: float = 0, rows: list[Params] | None = None,
                  root: str | None = None, status: int = 0) -> None:
        own = self.backend.identity.root
        self.frame.behavior["arbol-root"] = {"commands": {
            "settle": {"sleep": settle_sleep, "status": status, "output": {"root": own, "results": []}},
            "list": {"sleep": list_sleep, "output": {"root": root or own, "exchanges": rows or [], "unreadable": []}}}}
        self.frame.configure()

    def calls(self, kind: str = "settle") -> list[Params]:
        return [row for row in self.frame.calls() if row["program"] == "arbol-root" and row["args"][2] == kind]

    async def count(self, n: int, kind: str = "settle") -> list[Params]:
        async with asyncio.timeout(3):
            while len(rows := self.calls(kind)) < n:
                await asyncio.sleep(0.01)
        return rows

    async def done(self) -> None:
        assert self.backend.settling.worker
        await asyncio.wait_for(self.backend.settling.worker, 3)

    def row(self, state: str) -> Params:
        return {"root": self.backend.identity.root, "exchange": chat(850), "chat": chat(1), "state": state,
            "trunk": "trivial", "build": "0", "process": {"pid": 100, "startedAt": now(), "alive": False},
            "signsOfLife": {"heartbeat": 1, "waitingFor": "database", "since": now()}}


# Archived complete imports; restore needed names in their original scope, not at this file tail.
