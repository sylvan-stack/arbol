# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Two-window Draft CAS and accepted-mark recovery on private PostgreSQL/socket."""

from __future__ import annotations

__all__ = [
    "Any", "Drafts", "Error", "MAX_TEXT", "Params", "Path", "ROOT", "WindowFixture", "asyncio", "chat", "content",
    "mock", "save_params", "sys",
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
from arbol_backend.bridge import Error, Params  # noqa: E402
from arbol_backend.drafts import MAX_TEXT, content, save_params  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class Drafts(WindowFixture):
    async def saved(self, params: Params) -> int:
        normalized = await save_params(params)
        return int((await self.backend.drafts.save(normalized))["revision"])

    async def seed_exchange(self, exchange: str, id: str, number: int = 1) -> None:
        await self.db.execute(
            "INSERT INTO exchanges(id,chat_id,number,state,trunk,build,route,working_folder,accepted_at,ended_at) "
            "VALUES(%s,%s,%s,'completed','trivial','0','{}',%s,clock_timestamp(),clock_timestamp())",
            [exchange, id, number, str(self.frame.base)])


# Archived complete imports; restore needed names in their original scope, not at this file tail.
