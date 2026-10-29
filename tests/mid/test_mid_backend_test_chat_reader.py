"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_chat_reader as _support
from backend.test_chat_reader import (
    Any,
    Attention,
    CHAT,
    Chats,
    Cluster,
    Database,
    Frame,
    Jsonb,
    Path,
    ROOT,
    Reader,
    Sequence,
    Session,
    UUID,
    asyncio,
    encoded,
    exchange,
    identity,
    mock,
    parse,
    sys,
    unittest,
)


class Chats(_support.Chats):

# TEST-TIER-BEGIN tests/backend/test_chat_reader.py::Chats.test_repeatable_read_prevents_a_torn_snapshot
    async def test_repeatable_read_prevents_a_torn_snapshot(self) -> None:
        """chats.consistent-snapshot"""
        entered, release = asyncio.Event(), asyncio.Event()
        original = Session.execute
        async def delayed(session: Session, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
            rows = await original(session, sql, params)
            if sql.startswith("SELECT title,created_at"):
                entered.set()
                await release.wait()
            return rows
        with mock.patch.object(Session, "execute", delayed):
            pending = asyncio.create_task(self.reader.chat({"chat": CHAT}))
            await entered.wait()
            await self.db.execute(
                "WITH changed AS (UPDATE chats SET title='after' WHERE id=%s RETURNING id) "
                "UPDATE tool_calls SET result='{}'::jsonb WHERE exchange_id=%s AND position=2",
                [CHAT, exchange(29)],
            )
            release.set()
            before = await pending
        self.assertIsNone(before["chat"]["title"])
        self.assertTrue(before["exchanges"][-2]["items"][2]["cut"])
        after = await self.reader.chat({"chat": CHAT})
        self.assertEqual(after["chat"]["title"], "after")
        self.assertEqual(after["exchanges"][-2]["items"][2]["result"], {})
# TEST-TIER-END tests/backend/test_chat_reader.py::Chats.test_repeatable_read_prevents_a_torn_snapshot
