"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_return as _support
from backend.test_return import (
    Any,
    Attention,
    Backend,
    Database,
    Health,
    Params,
    Path,
    ROOT,
    Refused,
    Returned,
    Session,
    Snapshot,
    Trunk,
    WindowFixture,
    asyncio,
    calls,
    chat,
    install,
    mock,
    offline,
    online,
    sys,
    time,
)


class Returned(_support.Returned):


# TEST-TIER-BEGIN tests/backend/test_return.py::Returned.test_second_outage_discards_an_inflight_return_then_next_return_refreshes
    async def test_second_outage_discards_an_inflight_return_then_next_return_refreshes(self) -> None:
        """recovery.epoch-race; recovery.live-stream-survives-return"""
        trunk = await Trunk.make(self.frame, chat(1))
        await trunk.accept(self.db)
        r, w = await self.open()
        await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
        await asyncio.sleep(0.15)
        entered, release = asyncio.Event(), asyncio.Event()
        topic = self.backend.chats.chat_view.topic
        original = topic.snapshot
        async def delayed(value: Params) -> Snapshot:
            snapshot = await original(value)
            if not entered.is_set():
                entered.set()
                await release.wait()
            return snapshot
        with mock.patch.object(topic, "snapshot", delayed):
            self.backend.health.failed("first private outage")
            self.backend.health.connected()
            await asyncio.wait_for(entered.wait(), 2)
            self.backend.health.failed("second private outage")
            release.set()
            await self.recovered()
            line = trunk.event("text_delta", text="same stream after a second loss")
            self.assertEqual((await self.event(r, "chat", "lines"))["lines"], [line])
            self.assertFalse(any(message.get("event", {}).get("kind") == "snapshot" for message in self.pending[r]))
        self.backend.health.connected()
        await self.recovered()
        self.assertEqual((await self.event(r, "chat", "snapshot"))["exchanges"][0]["exchange"], trunk.exchange)
# TEST-TIER-END tests/backend/test_return.py::Returned.test_second_outage_discards_an_inflight_return_then_next_return_refreshes


# TEST-TIER-BEGIN tests/backend/test_return.py::Returned.test_pending_note_survives_a_whole_backend_restart_while_database_is_away
    async def test_pending_note_survives_a_whole_backend_restart_while_database_is_away(self) -> None:
        """recovery.backend-restart; recovery.pending-note-snapshot"""
        trunk = await Trunk.make(self.frame, chat(1))
        await trunk.accept(self.db)
        await offline(self.cluster)
        await self.backend.health.probe()
        trunk.end("interrupted")
        trunk.die()
        note = await self.backend.notes.record(trunk.exchange, chat(1))
        assert self.backend.notes.worker
        await self.backend.notes.worker
        self.backend.stopped.set()
        await self.running
        self.backend = Backend(self.backend.identity)
        self.running = asyncio.create_task(self.backend.run())
        async with asyncio.timeout(2):
            while not (self.frame.root / "backend.sock").exists() or self.backend.notes.worker is None:
                await asyncio.sleep(0.01)
        await self.backend.notes.worker
        self.assertEqual(self.backend.live.notes[trunk.exchange][1], note)
        await online(self.cluster)
        await self.backend.health.probe()
        await trunk.save(self.db, state="interrupted", remove=False)
        self.backend.recovery.settled(self.backend.identity.root)
        assert self.backend.notes.worker
        await self.backend.notes.worker
        r, w = await self.open()
        snapshot = await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
        self.assertEqual(snapshot["exchanges"][0]["note"], note)
        self.assertEqual(await self.db.execute("SELECT count(*) FROM exchange_notes"), [(1,)])
# TEST-TIER-END tests/backend/test_return.py::Returned.test_pending_note_survives_a_whole_backend_restart_while_database_is_away

# TEST-TIER-BEGIN tests/backend/test_return.py::Returned.test_delayed_return_snapshot_cannot_reopen_an_already_saved_exchange
    async def test_delayed_return_snapshot_cannot_reopen_an_already_saved_exchange(self) -> None:
        """recovery.saved-snapshot-race"""
        trunk = await Trunk.make(self.frame, chat(1))
        await trunk.accept(self.db)
        first_line = trunk.event("text_delta", text="tracked before return")
        r, w = await self.open()
        await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
        self.assertEqual((await self.event(r, "chat", "lines"))["lines"], [first_line])
        entered, release = asyncio.Event(), asyncio.Event()
        topic = self.backend.chats.chat_view.topic
        original = topic.snapshot
        async def delayed(value: Params) -> Snapshot:
            snapshot = await original(value)
            if not entered.is_set():
                entered.set()
                await release.wait()
            return snapshot
        self.backend.recovery.retry = 0.01
        with mock.patch.object(topic, "snapshot", delayed):
            self.backend.health.failed("private outage")
            self.backend.health.connected()
            await asyncio.wait_for(entered.wait(), 2)
            trunk.end("completed")
            trunk.die()
            await trunk.save(self.db, answer="durable newer answer")
            saved = await self.event(r, "chat", "saved")
            self.assertEqual(saved["exchange"]["state"], "completed")
            release.set()
            await self.recovered()
            snapshot = await self.event(r, "chat", "snapshot")
            self.assertEqual((snapshot["exchanges"][0]["state"], snapshot["exchanges"][0]["items"][-1]["text"]),
                             ("completed", "durable newer answer"))
# TEST-TIER-END tests/backend/test_return.py::Returned.test_delayed_return_snapshot_cannot_reopen_an_already_saved_exchange
