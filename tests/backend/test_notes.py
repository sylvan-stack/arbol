# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Private files and actual own SQL qualify durable stuck-note publication/recovery."""

from __future__ import annotations

__all__ = [
    "Any", "NOTE_SECONDS", "Notes", "Path", "ROOT", "Recovery", "Trunk", "WindowFixture", "asyncio", "chat",
    "mock", "now", "offline", "online", "sys",
]
import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.metadata import now  # noqa: E402
from arbol_backend.notes import NOTE_SECONDS, Notes  # noqa: E402
from backend.live_support import Trunk  # noqa: E402
from backend.recovery_support import offline, online  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class Recovery(WindowFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        assert self.backend.notes.worker
        await self.backend.notes.worker

    async def make(self, *, state: str = "interrupted", remove: bool = False) -> Trunk:
        trunk = await Trunk.make(self.frame, chat(1))
        await trunk.accept(self.db)
        await trunk.save(self.db, state=state, remove=remove)
        return trunk

    async def flush(self) -> None:
        self.backend.notes.request()
        assert self.backend.notes.worker
        await asyncio.wait_for(self.backend.notes.worker, 3)

    def path(self, exchange: str) -> Path:
        return self.frame.root / "notes" / (exchange+".json")


# Archived complete imports; restore needed names in their original scope, not at this file tail.
