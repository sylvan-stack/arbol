# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Awake scheduling and real socket/SQL recovery qualify storage attention ownership."""

from __future__ import annotations
import signal
from collections.abc import Callable, Sequence
from typing import Any
from unittest import mock


import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Params, Registry  # noqa: E402
from arbol_backend.database import Session  # noqa: E402
from arbol_backend.measurements import GIB, INTERVAL, Measurements  # noqa: E402
from arbol_backend.storage import LocalDisk  # noqa: E402
from backend.live_support import Trunk  # noqa: E402
from backend.recovery_support import offline, online  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402

from backend.test_chat_wire import WindowFixture  # noqa: E402


async def until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.005)


class Clock:
    value = 0.0

    def __call__(self) -> float:
        return self.value


class Watching(WindowFixture):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


# Archived complete imports; restore needed names in their original scope, not at this file tail.
