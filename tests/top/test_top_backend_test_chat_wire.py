"""Individually selected top-tier cases. Shared fixtures retain their original paths."""
from __future__ import annotations

import backend.test_chat_wire as _support
from backend.test_chat_wire import (
    Any,
    Sequence,
    Session,
    asyncio,
    chat,
    mock,
)


class Windows(_support.InstallationWindows):
    async def test_late_older_write_reply_cannot_publish_stale_settings(self) -> None:
        """chats.mutation-publication-order"""
        subscriber, subscriber_writer = await self.open()
        first, first_writer = await self.open()
        second, second_writer = await self.open()
        await self.subscribe(subscriber, subscriber_writer, "chat", "chat", {"chat": chat(1)})
        entered, release = asyncio.Event(), asyncio.Event()
        original = Session.execute

        async def delayed(session: Session, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
            rows = await original(session, sql, params)
            if sql.startswith("INSERT INTO chat_settings") and params is not None and params[1] is None:
                entered.set()
                await release.wait()
            return rows

        with mock.patch.object(Session, "execute", delayed):
            async with asyncio.TaskGroup() as calls:
                first_call = calls.create_task(self.call(first, first_writer, "chat.settings", {
                    "chat": chat(1), "route": {"driver": "claude", "subscription": "private", "model": "test"}}))
                try:
                    await asyncio.wait_for(entered.wait(), 3)
                    result = await self.call(second, second_writer, "chat.settings", {
                        "chat": chat(1), "workingFolder": str(self.fixture.work)})
                    self.assertEqual(result["result"], {})
                    latest = await self.event(subscriber, "chat", "settings")
                    self.assertEqual(latest["settings"]["workingFolder"], str(self.fixture.work))
                    self.assertEqual(latest["settings"]["route"]["model"], "test")
                finally:
                    release.set()
            self.assertEqual(first_call.result()["result"], {})
        await asyncio.sleep(0.1)
        await self.call(subscriber, subscriber_writer, "subscriptions.check")
        for message in self.pending[subscriber]:
            if message["type"] == "event" and message["event"]["kind"] == "settings":
                self.assertEqual(message["event"]["settings"]["workingFolder"], str(self.fixture.work))
