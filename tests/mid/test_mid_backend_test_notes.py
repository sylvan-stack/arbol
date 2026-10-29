"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_notes as _support
from backend.test_notes import (
    Any,
    NOTE_SECONDS,
    Notes,
    Path,
    ROOT,
    Recovery,
    Trunk,
    WindowFixture,
    asyncio,
    chat,
    mock,
    now,
    offline,
    online,
    sys,
)


class Recovery(_support.Recovery):


# TEST-TIER-BEGIN tests/backend/test_notes.py::Recovery.test_reply_lost_after_sql_commit_keeps_file_and_recovery_is_idempotent
    async def test_reply_lost_after_sql_commit_keeps_file_and_recovery_is_idempotent(self) -> None:
        """notes.uncertain-sql; notes.retry-after-commit"""
        trunk = await self.make()
        persist = self.backend.notes.persist
        async def uncertain(note: Any) -> Any:
            await persist(note)
            raise TimeoutError("private reply lost after commit")
        with mock.patch.object(self.backend.notes, "persist", side_effect=uncertain):
            await self.backend.notes.record(trunk.exchange, chat(1))
            assert self.backend.notes.worker
            await self.backend.notes.worker
        self.assertTrue(self.path(trunk.exchange).exists())
        self.assertEqual(await self.db.execute("SELECT count(*) FROM exchange_notes"), [(1,)])
        before = await self.db.execute("SELECT kind,at FROM exchange_notes")
        await self.flush()
        self.assertFalse(self.path(trunk.exchange).exists())
        self.assertEqual(await self.db.execute("SELECT kind,at FROM exchange_notes"), before)
# TEST-TIER-END tests/backend/test_notes.py::Recovery.test_reply_lost_after_sql_commit_keeps_file_and_recovery_is_idempotent
