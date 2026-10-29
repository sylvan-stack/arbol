"""Commented mid-tier selections; see MID_TIER.md before restoring a case."""

# Restore the needed imports and class header only for an explicit testing task.
# import backend.test_chat_reader as _support
# from backend.test_chat_reader import (
#     Attention,
#     CHAT,
#     Chats,
#     Cluster,
#     Database,
#     Frame,
#     Jsonb,
#     Path,
#     ROOT,
#     Reader,
#     UUID,
#     asyncio,
#     exchange,
#     identity,
#     parse,
#     sys,
#     unittest,
# )


# class Chats(_support.Chats):
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


# Original deferred imports (restore at the required scope, never blindly at the tail).
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

raise RuntimeError("Mid-tier tests require an explicitly requested testing task; see MID_TIER.md.")
