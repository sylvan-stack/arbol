"""Actual contract/layout SQL and concurrent writers, in a private PostgreSQL cluster."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from psycopg.types.json import Jsonb  # noqa: E402

from arbol_backend.chat_data import Reader  # noqa: E402
from arbol_backend.database import Database  # noqa: E402
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

# TEST-TIER-DISABLED-BEGIN tests/backend/test_chat_reader.py::Chats.test_snapshot_visible_history_usage_cut_tool_and_older_pages
#     async def test_snapshot_visible_history_usage_cut_tool_and_older_pages(self) -> None:
#         """chats.contract-assembly; chats.tool-cuts; chats.exchange-pages"""
#         snapshot = await self.reader.chat({"chat": CHAT})
#         self.assertEqual(snapshot["chat"]["exchangeCount"], 29)
#         self.assertEqual(snapshot["chat"]["usage"], {"inputTokens": 468, "outputTokens": 67})
#         self.assertEqual([e["number"] for e in snapshot["exchanges"]], list(range(19, 31)))
#         self.assertTrue(snapshot["more"])
#         self.assertEqual(snapshot["exchanges"][-1]["items"], [
#             {"position": 0, "kind": "message", "role": "user", "text": "first 30"}])
#         self.assertEqual(len(snapshot["exchanges"][-3]["items"]), 2)  # sub-agent tool omitted
#         tool = snapshot["exchanges"][-2]["items"][2]
#         self.assertTrue(tool["cut"])
#         self.assertLessEqual(len(encoded(tool["input"])), 8192)
#         self.assertLessEqual(len(encoded(tool["result"])), 8192)
#         self.assertEqual((tool["ask"], tool["answer"]), ({"question": "q"}, {"answer": "a"}))
#         self.assertNotIn("private-secret", str(snapshot))
#         whole = await self.reader.tool({"exchange": exchange(29), "position": 2})
#         self.assertEqual(whole, {"input": self.large, "result": self.large})
#         older = await self.reader.page_exchanges({"chat": CHAT, "beforeNumber": 19, "limit": 12})
#         self.assertEqual([e["number"] for e in older["exchanges"]], list(range(7, 19)))
#         self.assertTrue(older["more"])
#         oldest = await self.reader.page_exchanges({"chat": CHAT, "beforeNumber": 7, "limit": 12})
#         self.assertEqual([e["number"] for e in oldest["exchanges"]], [1, 2, 3, 4, 6])
#         self.assertFalse(oldest["more"])
# TEST-TIER-DISABLED-END tests/backend/test_chat_reader.py::Chats.test_snapshot_visible_history_usage_cut_tool_and_older_pages

# TEST-TIER-DISABLED-BEGIN tests/backend/test_chat_reader.py::Chats.test_repeatable_read_prevents_a_torn_snapshot
#     async def test_repeatable_read_prevents_a_torn_snapshot(self) -> None:
#         """chats.consistent-snapshot"""
#         entered, release = asyncio.Event(), asyncio.Event()
#         original = Session.execute
#         async def delayed(session: Session, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
#             rows = await original(session, sql, params)
#             if sql.startswith("SELECT title,created_at"):
#                 entered.set()
#                 await release.wait()
#             return rows
#         with mock.patch.object(Session, "execute", delayed):
#             pending = asyncio.create_task(self.reader.chat({"chat": CHAT}))
#             await entered.wait()
#             await self.db.execute(
#                 "WITH changed AS (UPDATE chats SET title='after' WHERE id=%s RETURNING id) "
#                 "UPDATE tool_calls SET result='{}'::jsonb WHERE exchange_id=%s AND position=2",
#                 [CHAT, exchange(29)],
#             )
#             release.set()
#             before = await pending
#         self.assertIsNone(before["chat"]["title"])
#         self.assertTrue(before["exchanges"][-2]["items"][2]["cut"])
#         after = await self.reader.chat({"chat": CHAT})
#         self.assertEqual(after["chat"]["title"], "after")
#         self.assertEqual(after["exchanges"][-2]["items"][2]["result"], {})
# TEST-TIER-DISABLED-END tests/backend/test_chat_reader.py::Chats.test_repeatable_read_prevents_a_torn_snapshot

# TEST-TIER-DISABLED-BEGIN tests/backend/test_chat_reader.py::Chats.test_missing_chat_and_missing_own_schema_still_serve_contract_data
#     async def test_missing_chat_and_missing_own_schema_still_serve_contract_data(self) -> None:
#         """chats.missing-chat; chats.layout-degraded"""
#         missing = await self.reader.chat({"chat": str(UUID(int=999))})
#         self.assertEqual(missing["chat"]["exchangeCount"], 0)
#         self.assertEqual(missing["exchanges"], [])
#         self.assertFalse(missing["more"])
#         self.assertIsNone(missing["draft"])
#         await self.db.execute("DROP TABLE drafts")
#         snapshot = await self.reader.chat({"chat": CHAT})
#         self.assertEqual(snapshot["chat"]["exchangeCount"], 29)
#         self.assertEqual(snapshot["settings"], {})
#         self.assertEqual(snapshot["marks"], {"ongoing": False})
#         self.assertIn("layout_incomplete", self.attention.items)
#         self.assertFalse(await self.reader.complete())
#         await self.db.execute((ROOT / "tests/backend/own-layout.sql").read_text())
#         self.assertTrue(await self.reader.complete())
#         self.assertNotIn("layout_incomplete", self.attention.items)
# TEST-TIER-DISABLED-END tests/backend/test_chat_reader.py::Chats.test_missing_chat_and_missing_own_schema_still_serve_contract_data

# TEST-TIER-DISABLED-BEGIN tests/backend/test_chat_reader.py::Chats.test_local_metadata_and_provenance_are_read_without_an_older_connection
#     async def test_local_metadata_and_provenance_are_read_without_an_older_connection(self) -> None:
#         """chats.own-root-provenance"""
#         self.reader.lineage = True
#         await self.db.execute("INSERT INTO migrated_chats VALUES(%s,'older',%s,30,now(),true)", [CHAT, CHAT])
#         await self.db.execute("INSERT INTO drafts VALUES(%s,%s,NULL,'unsent',91,NULL,NULL,now())", [str(UUID(int=91)), CHAT])
#         await self.db.execute("INSERT INTO chat_settings VALUES(%s,%s,'/private/next',now())",
#                               [CHAT, Jsonb({"driver": "pi", "subscription": "private", "model": "test"})])
#         await self.db.execute("INSERT INTO chat_marks VALUES(%s,true,now(),now())", [CHAT])
#         await self.db.execute("INSERT INTO exchange_notes VALUES(%s,'ended_stuck',now())", [exchange(29)])
#         snapshot = await self.reader.chat({"chat": CHAT})
#         self.assertEqual(snapshot["chat"]["migration"], {"fromRoot": "older", "fromChat": CHAT, "stale": True})
#         self.assertEqual(snapshot["draft"]["revision"], 91)
#         self.assertEqual(snapshot["settings"]["workingFolder"], "/private/next")
#         self.assertTrue(snapshot["marks"]["ongoing"])
#         self.assertEqual(snapshot["exchanges"][-2]["note"]["kind"], "ended_stuck")
#         summaries = (await self.reader.summaries({}))["chats"]
#         self.assertTrue(summaries[0]["archived"])
#         self.assertTrue(summaries[0]["hasDraft"])
#         self.assertEqual(summaries[0]["firstMessage"], "first 1")
#         self.assertTrue(summaries[0]["migration"]["stale"])
#         self.assertEqual(set(self.db.parameters or {}), {"host", "port", "user", "dbname", "password", "passfile"})
#         self.assertEqual((self.db.parameters or {})["dbname"], "arbol_test")
# TEST-TIER-DISABLED-END tests/backend/test_chat_reader.py::Chats.test_local_metadata_and_provenance_are_read_without_an_older_connection


if __name__ == "__main__":
    unittest.main()

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_chat_reader.py:8
# from collections.abc import Sequence
# TEST-TIER-IMPORTS-END tests/backend/test_chat_reader.py:8
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_chat_reader.py:10
# from typing import Any
# TEST-TIER-IMPORTS-END tests/backend/test_chat_reader.py:10
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_chat_reader.py:11
# from unittest import mock
# TEST-TIER-IMPORTS-END tests/backend/test_chat_reader.py:11
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_chat_reader.py:20
# from arbol_backend.chat_data import Reader, encoded  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_chat_reader.py:20
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_chat_reader.py:21
# from arbol_backend.database import Database, Session  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_chat_reader.py:21
