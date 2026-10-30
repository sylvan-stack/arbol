# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Actual contract/layout SQL and concurrent writers, in a private PostgreSQL cluster."""

from __future__ import annotations

__all__ = [
    "Any", "Attention", "CHAT", "Chats", "Cluster", "Database", "Frame", "Jsonb", "Path", "ROOT", "Reader",
    "Sequence", "Session", "UUID", "asyncio", "encoded", "exchange", "identity", "mock", "parse", "sys",
    "unittest",
]
import asyncio
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from psycopg.types.json import Jsonb  # noqa: E402

from arbol_backend.chat_data import Reader, encoded  # noqa: E402
from arbol_backend.database import Database, Session  # noqa: E402
from arbol_backend.metadata import Attention  # noqa: E402
from arbol_backend.model import identity, parse  # noqa: E402
from backend.support import Cluster, Frame  # noqa: E402

CHAT = str(UUID(int=100))


def exchange(number: int) -> str:
    return str(UUID(int=1000 + number))


class Chats(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.frame = Frame()
        self.cluster = await asyncio.to_thread(Cluster)
        self.db = Database(identity(ROOT, parse(self.frame.options(self.cluster.address)), home=self.frame.home))
        self.attention = Attention()
        self.reader = Reader(self.db, self.attention)
        await self.db.execute((ROOT / "tests/backend/own-layout.sql").read_text())
        await self.db.execute("INSERT INTO chats VALUES(%s,NULL,'2026-10-27T00:00:00Z')", [CHAT])
        for n in range(1, 31):
            await self.db.execute(
                "INSERT INTO exchanges(id,chat_id,number,state,trunk,build,route,working_folder,accepted_at,ended_at) "
                "VALUES(%s,%s,%s,%s,'trivial','1',%s,'/private/work',"
                "'2026-10-27T01:00:00Z'::timestamptz+%s*interval '1 minute',"
                "CASE WHEN %s=30 THEN NULL ELSE '2026-10-27T01:00:01Z'::timestamptz+%s*interval '1 minute' END)",
                [exchange(n), CHAT, n, "open" if n == 30 else "completed",
                 Jsonb({"driver": "claude", "subscription": "private", "model": "test", "apiKey": "private-secret"}), n, n, n],
            )
            await self.db.execute("INSERT INTO messages VALUES(%s,0,'user',%s),(%s,1,'assistant','answer')",
                                  [exchange(n), "first " + str(n), exchange(n)])
            await self.db.execute(
                "INSERT INTO runs(exchange_id,run_id,kind,outcome,usage,started,ended_at) "
                "VALUES(%s,%s,'agent','completed',%s,%s,'2026-10-27T02:00:00Z')",
                [exchange(n), str(n), Jsonb({"inputTokens": n, "outputTokens": 2}),
                 Jsonb({"type": "started", "subscription": "private", "model": "test", "key": "private-secret"})],
            )
        await self.db.execute("UPDATE exchanges SET replaced_by=%s WHERE id=%s", [exchange(6), exchange(5)])
        self.large = {"text": 'é🦫"' * 10000}
        for n, parent in ((29, None), (30, None), (28, "parent")):
            await self.db.execute(
                "INSERT INTO tool_calls(exchange_id,position,run_id,call_id,parent_call_id,name,input,ok,result,ask,answer) "
                "VALUES(%s,2,'run','tool',%s,'private-tool',%s,true,%s,%s,%s)",
                [exchange(n), parent, Jsonb(self.large), Jsonb(self.large), Jsonb({"question": "q"}), Jsonb({"answer": "a"})],
            )
        await self.db.execute(
            "INSERT INTO runs(exchange_id,run_id,kind,outcome,usage,ended_at) "
            "VALUES(%s,'small','small','completed',%s,'2026-10-27T02:00:00Z')",
            [exchange(5), Jsonb({"inputTokens": 3, "outputTokens": 7})],
        )

    async def asyncTearDown(self) -> None:
        await self.db.close()
        await asyncio.to_thread(self.cluster.close)
        self.frame.close()


# Archived complete imports; restore needed names in their original scope, not at this file tail.
