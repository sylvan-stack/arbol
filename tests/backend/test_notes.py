"""Private files and actual own SQL qualify durable stuck-note publication/recovery."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from backend.live_support import Trunk  # noqa: E402
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

# TEST-TIER-DISABLED-BEGIN tests/backend/test_notes.py::Recovery.test_interrupted_note_goes_to_both_windows_and_one_durable_row
#     async def test_interrupted_note_goes_to_both_windows_and_one_durable_row(self) -> None:
#         """notes.sql-commit; notes.note-event; notes.idempotent"""
#         self.assertEqual(NOTE_SECONDS, 5)
#         trunk = await self.make()
#         clients = [await self.open(), await self.open()]
#         for index, (r, w) in enumerate(clients):
#             await self.subscribe(r, w, str(index), "chat", {"chat": chat(1)})
#         await self.backend.notes.record(trunk.exchange, chat(1))
#         assert self.backend.notes.worker
#         await self.backend.notes.worker
#         for index, (r, _) in enumerate(clients):
#             event = await self.event(r, str(index), "note")
#             self.assertEqual((event["note"]["exchange"], event["note"]["kind"]), (trunk.exchange, "ended_stuck"))
#         rows = await self.db.execute("SELECT kind,at FROM exchange_notes WHERE exchange_id=%s", [trunk.exchange])
#         self.assertEqual(len(rows), 1)
#         self.assertEqual(rows[0][0], "ended_stuck")
#         self.assertFalse(self.path(trunk.exchange).exists())
#         await self.backend.notes.record(trunk.exchange, chat(1))
#         await self.flush()
#         self.assertEqual(await self.db.execute("SELECT kind,at FROM exchange_notes WHERE exchange_id=%s", [trunk.exchange]), rows)
# TEST-TIER-DISABLED-END tests/backend/test_notes.py::Recovery.test_interrupted_note_goes_to_both_windows_and_one_durable_row

# TEST-TIER-DISABLED-BEGIN tests/backend/test_notes.py::Recovery.test_database_away_file_survives_service_restart_until_interrupted_row_is_committed
#     async def test_database_away_file_survives_service_restart_until_interrupted_row_is_committed(self) -> None:
#         """notes.database-away; notes.restart-recovery; notes.pending-row"""
#         trunk = await Trunk.make(self.frame, chat(1))
#         await trunk.accept(self.db)
#         r, w = await self.open()
#         await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
#         await offline(self.cluster)
#         await self.backend.health.probe()
#         trunk.end("interrupted")
#         trunk.die()
#         first = await self.backend.notes.record(trunk.exchange, chat(1))
#         await self.flush()
#         self.assertTrue(self.path(trunk.exchange).exists())
#         self.assertEqual(self.path(trunk.exchange).stat().st_mode & 0o777, 0o600)
#         self.assertEqual((await self.event(r, "chat", "note"))["note"], first)
#         await self.backend.notes.close()
#         self.backend.live.notes.clear()
#         self.backend.notes = Notes(self.backend.identity, self.backend.database, self.backend.chats, self.backend.live)
#         self.backend.notes.start()
#         assert self.backend.notes.worker
#         await self.backend.notes.worker
#         self.assertEqual(self.backend.live.notes[trunk.exchange][1], first)
#         await online(self.cluster)
#         await self.backend.health.probe()
#         await self.flush()
#         self.assertTrue(self.path(trunk.exchange).exists())  # An open row is not a saved interrupted outcome.
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM exchange_notes"), [(0,)])
#         await trunk.save(self.db, state="interrupted", remove=False)
#         await self.flush()
#         self.assertFalse(self.path(trunk.exchange).exists())
#         self.assertEqual(await self.db.execute("SELECT kind FROM exchange_notes WHERE exchange_id=%s", [trunk.exchange]), [("ended_stuck",)])
# TEST-TIER-DISABLED-END tests/backend/test_notes.py::Recovery.test_database_away_file_survives_service_restart_until_interrupted_row_is_committed

# TEST-TIER-DISABLED-BEGIN tests/backend/test_notes.py::Recovery.test_reply_lost_after_sql_commit_keeps_file_and_recovery_is_idempotent
#     async def test_reply_lost_after_sql_commit_keeps_file_and_recovery_is_idempotent(self) -> None:
#         """notes.uncertain-sql; notes.retry-after-commit"""
#         trunk = await self.make()
#         persist = self.backend.notes.persist
#         async def uncertain(note: Any) -> Any:
#             await persist(note)
#             raise TimeoutError("private reply lost after commit")
#         with mock.patch.object(self.backend.notes, "persist", side_effect=uncertain):
#             await self.backend.notes.record(trunk.exchange, chat(1))
#             assert self.backend.notes.worker
#             await self.backend.notes.worker
#         self.assertTrue(self.path(trunk.exchange).exists())
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM exchange_notes"), [(1,)])
#         before = await self.db.execute("SELECT kind,at FROM exchange_notes")
#         await self.flush()
#         self.assertFalse(self.path(trunk.exchange).exists())
#         self.assertEqual(await self.db.execute("SELECT kind,at FROM exchange_notes"), before)
# TEST-TIER-DISABLED-END tests/backend/test_notes.py::Recovery.test_reply_lost_after_sql_commit_keeps_file_and_recovery_is_idempotent

# TEST-TIER-DISABLED-BEGIN tests/backend/test_notes.py::Recovery.test_different_saved_end_or_chat_never_acquires_stuck_note
#     async def test_different_saved_end_or_chat_never_acquires_stuck_note(self) -> None:
#         """notes.true-end; notes.chat-identity"""
#         for state in ("completed", "cancelled", "failed"):
#             trunk = await self.make(state=state)
#             self.backend.notes.files.put({"root": self.backend.identity.root, "exchange": trunk.exchange,
#                 "chat": chat(1), "kind": "ended_stuck", "at": now()})
#             await self.flush()
#             self.assertTrue(self.path(trunk.exchange).exists())
#             self.assertNotIn(trunk.exchange, self.backend.live.notes)
#         trunk = await self.make()
#         self.backend.notes.files.put({"root": self.backend.identity.root, "exchange": trunk.exchange,
#             "chat": chat(2), "kind": "ended_stuck", "at": now()})
#         await self.flush()
#         self.assertTrue(self.path(trunk.exchange).exists())
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM exchange_notes"), [(0,)])
# TEST-TIER-DISABLED-END tests/backend/test_notes.py::Recovery.test_different_saved_end_or_chat_never_acquires_stuck_note

# TEST-TIER-DISABLED-BEGIN tests/backend/test_notes.py::Recovery.test_file_replacement_after_sql_commit_is_preserved
#     async def test_file_replacement_after_sql_commit_is_preserved(self) -> None:
#         """notes.sql-file-race"""
#         trunk = await self.make()
#         remove = self.backend.notes.files.remove
#         replacement: list[bytes] = []
#         def replace(note: Any) -> None:
#             path = self.path(trunk.exchange)
#             path.rename(path.with_suffix(".old"))
#             raw = path.with_suffix(".old").read_bytes()
#             path.write_bytes(raw)
#             path.chmod(0o600)
#             replacement.append(raw)
#             remove(note)
#         with mock.patch.object(self.backend.notes.files, "remove", side_effect=replace):
#             await self.backend.notes.record(trunk.exchange, chat(1))
#             assert self.backend.notes.worker
#             await self.backend.notes.worker
#         self.assertEqual(self.path(trunk.exchange).read_bytes(), replacement[0])
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM exchange_notes"), [(1,)])
#         await self.flush()
#         self.assertFalse(self.path(trunk.exchange).exists())
# TEST-TIER-DISABLED-END tests/backend/test_notes.py::Recovery.test_file_replacement_after_sql_commit_is_preserved

# TEST-TIER-DISABLED-BEGIN tests/backend/test_notes.py::Recovery.test_real_query_block_is_bounded_and_pending_note_remains
#     async def test_real_query_block_is_bounded_and_pending_note_remains(self) -> None:
#         """notes.sql-deadline; notes.no-history-writes"""
#         trunk = await self.make()
#         self.backend.notes.seconds = 0.08
#         async with self.db.session() as session:
#             await session.execute("BEGIN")
#             try:
#                 await session.execute("LOCK TABLE exchange_notes IN ACCESS EXCLUSIVE MODE")
#                 await self.backend.notes.record(trunk.exchange, chat(1))
#                 assert self.backend.notes.worker
#                 await asyncio.wait_for(self.backend.notes.worker, 0.5)
#                 self.assertTrue(self.path(trunk.exchange).exists())
#                 self.assertFalse(self.backend.database.away)
#             finally:
#                 await session.execute("ROLLBACK")
#         await self.flush()
#         self.assertFalse(self.path(trunk.exchange).exists())
#         self.assertEqual(await self.db.execute("SELECT state FROM exchanges WHERE id=%s", [trunk.exchange]), [("interrupted",)])
# TEST-TIER-DISABLED-END tests/backend/test_notes.py::Recovery.test_real_query_block_is_bounded_and_pending_note_remains

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_notes.py:8
# from typing import Any
# TEST-TIER-IMPORTS-END tests/backend/test_notes.py:8
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_notes.py:9
# from unittest import mock
# TEST-TIER-IMPORTS-END tests/backend/test_notes.py:9
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_notes.py:15
# from arbol_backend.metadata import now  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_notes.py:15
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_notes.py:16
# from arbol_backend.notes import NOTE_SECONDS, Notes  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_notes.py:16
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_notes.py:18
# from backend.recovery_support import offline, online  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_notes.py:18
