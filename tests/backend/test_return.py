# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Actual private outage/return and delayed wire snapshots cannot regress newer state."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from backend.test_chat_wire import WindowFixture  # noqa: E402


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
