# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Actual private outage/return and delayed wire snapshots cannot regress newer state."""

from __future__ import annotations

__all__ = [
    "Any", "Attention", "Backend", "Database", "Health", "Params", "Path", "ROOT", "Refused", "Returned", "Session",
    "Snapshot", "Trunk", "WindowFixture", "asyncio", "calls", "chat", "install", "mock", "offline", "online",
    "sys", "time",
]
import asyncio
import sys
import time
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Params, Snapshot  # noqa: E402
from arbol_backend.database import Database, Session  # noqa: E402
from arbol_backend.health import Health  # noqa: E402
from arbol_backend.metadata import Attention  # noqa: E402
from arbol_backend.model import Refused  # noqa: E402
from arbol_backend.server import Backend  # noqa: E402
from backend.discovery_support import calls, install  # noqa: E402
from backend.live_support import Trunk  # noqa: E402
from backend.recovery_support import offline, online  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class Returned(WindowFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        assert self.backend.health.monitor and self.backend.discovery.task
        self.backend.health.monitor.cancel()
        await asyncio.gather(self.backend.health.monitor, return_exceptions=True)
        self.backend.health.monitor = None
        await self.backend.discovery.task
        if self.backend.settling.worker:
            await self.backend.settling.worker
        if self.backend.notes.worker:
            await self.backend.notes.worker

    async def recovered(self) -> None:
        await asyncio.gather(*list(self.backend.health.recoveries))


# Archived complete imports; restore needed names in their original scope, not at this file tail.
