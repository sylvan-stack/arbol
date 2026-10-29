"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_health as _support
from backend.test_health import (
    Attention,
    Availability,
    Database,
    Health,
    Path,
    RETRY,
    ROOT,
    Refused,
    SECONDS,
    WindowFixture,
    asyncio,
    json,
    mock,
    offline,
    online,
    psycopg,
    replace,
    sys,
    time,
)


class Availability(_support.Availability):

# TEST-TIER-BEGIN tests/backend/test_health.py::Availability.test_statement_timeout_or_sql_refusal_does_not_mark_a_server_away
    async def test_statement_timeout_or_sql_refusal_does_not_mark_a_server_away(self) -> None:
        """recovery.statement-timeout; recovery.sql-error-is-not-loss"""
        self.backend.database.seconds = 0.08
        with self.assertRaises(Refused) as caught:
            await self.backend.database.execute("SELECT pg_sleep(3)")
        self.assertEqual(caught.exception.code, "timeout")
        self.assertFalse(self.backend.database.away)
        with self.assertRaises(Refused):
            await self.backend.database.execute("SELECT no_such_private_column")
        self.assertFalse(self.backend.database.away)
        self.assertNotIn("database_unreachable", self.backend.chats.attention.items)
        self.assertEqual(await self.backend.database.execute("SELECT 1"), [(1,)])
# TEST-TIER-END tests/backend/test_health.py::Availability.test_statement_timeout_or_sql_refusal_does_not_mark_a_server_away

# TEST-TIER-BEGIN tests/backend/test_health.py::Availability.test_connection_deadline_is_unavailable_and_the_whole_probe_is_bounded
    async def test_connection_deadline_is_unavailable_and_the_whole_probe_is_bounded(self) -> None:
        """recovery.connection-deadline; recovery.probe-bound"""
        self.assertEqual((SECONDS, RETRY), (5, 5))
        writers: list[asyncio.StreamWriter] = []
        def stalled(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writers.append(writer)
        server = await asyncio.start_server(stalled, "127.0.0.1", 0)
        address = f"postgresql://bkd@127.0.0.1:{server.sockets[0].getsockname()[1]}/arbol_test"
        db = Database(replace(self.backend.identity, database=address), seconds=0.12)
        attention = Attention()
        health = Health(db, attention)
        try:
            before = time.monotonic()
            await health.probe()
            self.assertLess(time.monotonic()-before, 0.4)
            self.assertTrue(db.away)
            self.assertEqual(attention.items["database_unreachable"]["kind"], "database_unreachable")
            with self.assertRaises(Refused) as caught:
                await db.execute("SELECT 1")
            self.assertEqual(caught.exception.code, "database_unavailable")
        finally:
            await health.close()
            await db.close()
            server.close()
            for writer in writers:
                writer.close()
            server.close_clients()
            await server.wait_closed()
# TEST-TIER-END tests/backend/test_health.py::Availability.test_connection_deadline_is_unavailable_and_the_whole_probe_is_bounded
