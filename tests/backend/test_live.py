# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Multiple real socket windows follow private contract folders from their first line."""

from __future__ import annotations
import json
import time
from typing import Any
from unittest import mock


import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import MAX_LINE, Params  # noqa: E402
from arbol_backend.exchange_files import processes  # noqa: E402
from backend.live_support import Trunk  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402

from arbol_backend.bridge import Params  # noqa: E402
from backend.test_chat_wire import WindowFixture  # noqa: E402


class Windows(WindowFixture):
    async def lines(self, reader: asyncio.StreamReader, id: str, through: int) -> list[Params]:
        found: list[Params] = []
        while not found or found[-1]["n"] < through:
            found += (await self.event(reader, id, "lines"))["lines"]
        return found


# Archived complete imports; restore needed names in their original scope, not at this file tail.
