# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Private SQL loss/locks never stall an already opened chat's contract-file stream."""

from __future__ import annotations
import json
import time


import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from backend.recovery_support import offline, online  # noqa: E402

from backend.live_support import Trunk  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class Offline(WindowFixture):
    async def opened(self) -> tuple[Trunk, asyncio.StreamReader, asyncio.StreamWriter]:
        trunk = await Trunk.make(self.frame, chat(1))
        await trunk.accept(self.db)
        first = trunk.event("text_delta", text="before loss")
        r, w = await self.open()
        await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
        self.assertEqual((await self.event(r, "chat", "lines"))["lines"], [first])
        return trunk, r, w


# Archived complete imports; restore needed names in their original scope, not at this file tail.
