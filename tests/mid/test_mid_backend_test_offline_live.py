"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_offline_live as _support
from backend.test_offline_live import (
    Offline,
    Path,
    ROOT,
    Trunk,
    WindowFixture,
    asyncio,
    chat,
    json,
    offline,
    online,
    sys,
    time,
)


class Offline(_support.Offline):
# TEST-TIER-BEGIN tests/backend/test_offline_live.py::Offline.test_two_existing_windows_continue_whole_lines_and_unsaved_while_new_chat_is_refused
    async def test_two_existing_windows_continue_whole_lines_and_unsaved_while_new_chat_is_refused(self) -> None:
        """recovery.offline-lines; recovery.open-chat-retained; recovery.unsaved; recovery.new-chat-refused"""
        trunk, r, w = await self.opened()
        r2, w2 = await self.open()
        await self.subscribe(r2, w2, "second", "chat", {"chat": chat(1)})
        await self.event(r2, "second", "lines")
        await offline(self.cluster)
        await self.backend.health.probe()
        self.assertTrue(self.backend.database.away)
        before = time.monotonic()
        next_line = trunk.event("text_delta", text="continues without SQL")
        self.assertEqual((await self.event(r, "chat", "lines"))["lines"], [next_line])
        self.assertEqual((await self.event(r2, "second", "lines"))["lines"], [next_line])
        self.assertLess(time.monotonic()-before, 0.25)
        await self.send(w, {"type": "subscribe", "id": "new", "topic": "chat", "params": {"chat": chat(2)}})
        refused = await self.until(r, lambda value: value["type"] == "ended" and value["id"] == "new")
        self.assertEqual(refused["error"]["code"], "database_unavailable")
        snapshot = await self.subscribe(r, w, "attention", "attention", {})
        self.assertIn("database_unreachable", [item["id"] for item in snapshot["items"]])
        trunk.end("completed")
        trunk.die()
        unsaved = await self.until(r, lambda value: value["type"] == "event" and value.get("id") == "chat"
            and value["event"].get("kind") == "exchange" and value["event"]["exchange"]["state"] == "unsaved")
        self.assertEqual(unsaved["event"]["exchange"]["end"]["state"], "completed")
        active = (await self.call(r, w, "subscriptions.check"))["result"]["subscriptions"]
        self.assertIn("chat", [item["id"] for item in active])
        self.assertFalse(any(value["type"] == "event" and value["event"]["kind"] == "saved" for value in self.pending[r]))
        await online(self.cluster)
        await self.backend.health.probe()
        await trunk.save(self.db, answer="actual saved answer")
        saved = (await self.event(r, "chat", "saved"))["exchange"]
        self.assertEqual((saved["state"], saved["items"][-1]["text"]), ("completed", "actual saved answer"))
# TEST-TIER-END tests/backend/test_offline_live.py::Offline.test_two_existing_windows_continue_whole_lines_and_unsaved_while_new_chat_is_refused

# TEST-TIER-BEGIN tests/backend/test_offline_live.py::Offline.test_sql_lock_before_an_outage_is_classified_does_not_hold_file_polls
    async def test_sql_lock_before_an_outage_is_classified_does_not_hold_file_polls(self) -> None:
        """recovery.slow-sql-file-isolation; recovery.slow-refresh-preserves-subscription"""
        trunk, r, w = await self.opened()
        async with self.db.session() as session:
            await session.execute("BEGIN")
            try:
                await session.execute("LOCK TABLE exchanges IN ACCESS EXCLUSIVE MODE")
                for text in ("while SQL is locked", "after the poll refresh deadline"):
                    before = time.monotonic()
                    line = trunk.event("text_delta", text=text)
                    self.assertEqual((await self.event(r, "chat", "lines"))["lines"], [line])
                    self.assertLess(time.monotonic()-before, 0.25)
                    self.assertFalse(self.backend.database.away)
                    await asyncio.sleep(0.85)
            finally:
                await session.execute("ROLLBACK")
        active = (await self.call(r, w, "subscriptions.check"))["result"]["subscriptions"]
        self.assertIn("chat", [item["id"] for item in active])
# TEST-TIER-END tests/backend/test_offline_live.py::Offline.test_sql_lock_before_an_outage_is_classified_does_not_hold_file_polls

# TEST-TIER-BEGIN tests/backend/test_offline_live.py::Offline.test_offline_partial_append_and_file_replacement_replay_use_last_captured_snapshot
    async def test_offline_partial_append_and_file_replacement_replay_use_last_captured_snapshot(self) -> None:
        """recovery.offline-partial; recovery.offline-replay-generation"""
        trunk, r, w = await self.opened()
        await offline(self.cluster)
        await self.backend.health.probe()
        raw = json.dumps({"n": 2, "event": {"runId": trunk.exchange+".1", "type": "text_delta", "text": "partial"}}).encode()
        trunk.append(raw)
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(0.2):
                await self.event(r, "chat", "lines")
        trunk.append(b"\n")
        self.assertEqual((await self.event(r, "chat", "lines"))["lines"], [json.loads(raw)])
        replacement = {"n": 1, "event": {"runId": trunk.exchange+".1", "type": "text", "text": "replacement"}}
        path = trunk.folder / "events.jsonl"
        path.write_text(json.dumps(replacement)+"\n")
        snapshot = await self.event(r, "chat", "snapshot")
        self.assertEqual(snapshot["exchanges"][0]["state"], "open")
        self.assertEqual((await self.event(r, "chat", "lines"))["lines"], [replacement])
        active = (await self.call(r, w, "subscriptions.check"))["result"]["subscriptions"]
        self.assertIn("chat", [item["id"] for item in active])
# TEST-TIER-END tests/backend/test_offline_live.py::Offline.test_offline_partial_append_and_file_replacement_replay_use_last_captured_snapshot

# TEST-TIER-BEGIN tests/backend/test_offline_live.py::Offline.test_new_unconfirmed_folder_never_supplies_answer_and_failed_draft_save_keeps_sql_text
    async def test_new_unconfirmed_folder_never_supplies_answer_and_failed_draft_save_keeps_sql_text(self) -> None:
        """recovery.row-proof-before-stream; recovery.draft-refusal"""
        trunk, r, w = await self.opened()
        draft = (await self.call(r, w, "draft.save", {"chat": chat(1), "text": "kept original", "baseRevision": None}))["result"]
        await offline(self.cluster)
        await self.backend.health.probe()
        unknown = await Trunk.make(self.frame, chat(1))
        unknown.value["acceptedAt"] = "2026-10-27T00:00:00Z"
        unknown.save_record()
        unknown.event("text", text="not confirmed by a row")
        refusal = await self.call(r, w, "draft.save", {"chat": chat(1), "text": "owner keeps this in composer", "baseRevision": draft["revision"]})
        self.assertEqual(refusal["error"]["code"], "database_unavailable")
        await asyncio.sleep(0.9)
        live = trunk.event("text_delta", text="still live")
        self.assertEqual((await self.event(r, "chat", "lines"))["lines"], [live])
        self.assertFalse(any(value["type"] == "event" and value["event"].get("exchange") == unknown.exchange
            and value["event"]["kind"] == "lines" for value in self.pending[r]))
        await online(self.cluster)
        await self.backend.health.probe()
        current = (await self.call(r, w, "draft.get", {"chat": chat(1)}))["result"]
        self.assertEqual((current["text"], current["revision"]), ("kept original", draft["revision"]))
        updated = (await self.call(r, w, "draft.save", {"chat": chat(1), "text": "owner keeps this in composer", "baseRevision": draft["revision"]}))["result"]
        self.assertGreater(updated["revision"], draft["revision"])
        self.assertEqual((await self.call(r, w, "draft.get", {"chat": chat(1)}))["result"]["text"], "owner keeps this in composer")
# TEST-TIER-END tests/backend/test_offline_live.py::Offline.test_new_unconfirmed_folder_never_supplies_answer_and_failed_draft_save_keeps_sql_text
