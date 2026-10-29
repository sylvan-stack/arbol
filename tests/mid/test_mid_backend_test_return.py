"""Commented mid-tier selections; see MID_TIER.md before restoring a case."""

# Restore the needed imports and class header only for an explicit testing task.
# import backend.test_return as _support
# from backend.test_return import (
#     Path,
#     ROOT,
#     Returned,
#     WindowFixture,
#     asyncio,
#     sys,
# )


# class Returned(_support.Returned):
# TEST-TIER-DISABLED-BEGIN tests/backend/test_return.py::Returned.test_repeated_actual_return_refreshes_every_topic_in_two_windows_and_preserves_draft
#     async def test_repeated_actual_return_refreshes_every_topic_in_two_windows_and_preserves_draft(self) -> None:
#         """recovery.all-topic-snapshots; recovery.repeated-return; recovery.draft-preserved"""
#         clients = [await self.open(), await self.open()]
#         params = {"chat": chat(1)}
#         draft = (await self.call(*clients[0], "draft.save", {**params, "text": "keep this Draft", "baseRevision": None}))["result"]
#         for r, w in clients:
#             for topic in ("root", "chats", "chat", "draft", "attention"):
#                 await self.subscribe(r, w, topic, topic, params if topic in {"chat", "draft"} else {})
#         install(self.frame, {})
#         for _ in range(2):
#             before = len(calls(self.frame, kind="settle", root=self.backend.identity.root))
#             await offline(self.cluster)
#             await self.backend.health.probe()
#             for r, _ in clients:
#                 await self.event(r, "attention", "opened")
#             await online(self.cluster)
#             await self.backend.health.probe()
#             await self.recovered()
#             for r, _ in clients:
#                 await self.event(r, "attention", "closed")
#                 for topic in ("root", "chats", "chat", "draft", "attention"):
#                     value = await self.event(r, topic, "snapshot")
#                     if topic == "draft":
#                         self.assertEqual((value["draft"]["text"], value["draft"]["revision"]), ("keep this Draft", draft["revision"]))
#                     if topic == "attention":
#                         self.assertNotIn("database_unreachable", [item["id"] for item in value["items"]])
#             async with asyncio.timeout(2):
#                 while len(calls(self.frame, kind="settle", root=self.backend.identity.root)) <= before:
#                     await asyncio.sleep(0.01)
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM drafts"), [(1,)])
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM exchanges"), [(0,)])
# TEST-TIER-DISABLED-END tests/backend/test_return.py::Returned.test_repeated_actual_return_refreshes_every_topic_in_two_windows_and_preserves_draft

# TEST-TIER-DISABLED-BEGIN tests/backend/test_return.py::Returned.test_successful_handshake_but_stalled_select_does_not_close_attention
#     async def test_successful_handshake_but_stalled_select_does_not_close_attention(self) -> None:
#         """recovery.whole-probe-confirmation; recovery.renew-lock-bound"""
#         db = Database(self.backend.identity, seconds=0.08)
#         health = Health(db, Attention())
#         health.failed("private outage")
#         returned = mock.AsyncMock()
#         health.on_return = returned
#         original = Session.execute
#         async def stalled(session: Session, sql: str, params: Any = None) -> Any:
#             if sql == "SELECT 1":
#                 await asyncio.sleep(1)
#             return await original(session, sql, params)
#         try:
#             with mock.patch.object(Session, "execute", stalled):
#                 await health.probe()
#             self.assertTrue(db.away)
#             self.assertIn("database_unreachable", health.attention.items)
#             returned.assert_not_awaited()
#             async with db.credentials_lock:
#                 before = time.monotonic()
#                 await health.probe()
#                 self.assertLess(time.monotonic()-before, 0.3)
#             self.assertTrue(db.away)
#             await health.probe()
#             await asyncio.gather(*list(health.recoveries))
#             returned.assert_awaited_once()
#             self.assertFalse(db.away)
#         finally:
#             await health.close()
#             await db.close()
# TEST-TIER-DISABLED-END tests/backend/test_return.py::Returned.test_successful_handshake_but_stalled_select_does_not_close_attention

# TEST-TIER-DISABLED-BEGIN tests/backend/test_return.py::Returned.test_normal_credential_waiter_rechecks_the_away_gate
#     async def test_normal_credential_waiter_rechecks_the_away_gate(self) -> None:
#         """recovery.credential-lock-race"""
#         db = Database(self.backend.identity)
#         health = Health(db, Attention())
#         try:
#             async with db.credentials_lock:
#                 waiting = asyncio.create_task(db.execute("SELECT 1"))
#                 await asyncio.sleep(0)
#                 health.failed("private outage")
#             with self.assertRaises(Refused) as caught:
#                 await waiting
#             self.assertEqual(caught.exception.code, "database_unavailable")
#             self.assertTrue(db.away)
#             self.assertIsNone(db.parameters)
#         finally:
#             await health.close()
#             await db.close()
# TEST-TIER-DISABLED-END tests/backend/test_return.py::Returned.test_normal_credential_waiter_rechecks_the_away_gate

# TEST-TIER-DISABLED-BEGIN tests/backend/test_return.py::Returned.test_delayed_return_snapshot_cannot_overwrite_a_newer_draft_delta
#     async def test_delayed_return_snapshot_cannot_overwrite_a_newer_draft_delta(self) -> None:
#         """recovery.draft-snapshot-race"""
#         r, w = await self.open()
#         params = {"chat": chat(1)}
#         saved = (await self.call(r, w, "draft.save", {**params, "text": "old", "baseRevision": None}))["result"]
#         await self.subscribe(r, w, "draft", "draft", params)
#         entered, release = asyncio.Event(), asyncio.Event()
#         topic = self.backend.drafts.view.topic
#         original = topic.snapshot
#         async def delayed(value: Params) -> Snapshot:
#             snapshot = await original(value)
#             if not entered.is_set():
#                 entered.set()
#                 await release.wait()
#             return snapshot
#         with mock.patch.object(topic, "snapshot", delayed):
#             self.backend.health.failed("private outage")
#             self.backend.health.connected()
#             await asyncio.wait_for(entered.wait(), 2)
#             result = await self.call(r, w, "draft.save", {**params, "text": "newer", "baseRevision": saved["revision"]})
#             self.assertIn("result", result)
#             self.assertEqual((await self.event(r, "draft", "draft"))["draft"]["text"], "newer")
#             release.set()
#             await self.recovered()
#             self.assertEqual((await self.event(r, "draft", "snapshot"))["draft"]["text"], "newer")
#         await self.call(r, w, "subscriptions.check")
#         self.assertFalse(any(message.get("event", {}).get("kind") == "snapshot" and
#             message["event"].get("draft", {}).get("text") == "old" for message in self.pending[r]))
# TEST-TIER-DISABLED-END tests/backend/test_return.py::Returned.test_delayed_return_snapshot_cannot_overwrite_a_newer_draft_delta

# TEST-TIER-DISABLED-BEGIN tests/backend/test_return.py::Returned.test_second_outage_discards_an_inflight_return_then_next_return_refreshes
#     async def test_second_outage_discards_an_inflight_return_then_next_return_refreshes(self) -> None:
#         """recovery.epoch-race; recovery.live-stream-survives-return"""
#         trunk = await Trunk.make(self.frame, chat(1))
#         await trunk.accept(self.db)
#         r, w = await self.open()
#         await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
#         await asyncio.sleep(0.15)
#         entered, release = asyncio.Event(), asyncio.Event()
#         topic = self.backend.chats.chat_view.topic
#         original = topic.snapshot
#         async def delayed(value: Params) -> Snapshot:
#             snapshot = await original(value)
#             if not entered.is_set():
#                 entered.set()
#                 await release.wait()
#             return snapshot
#         with mock.patch.object(topic, "snapshot", delayed):
#             self.backend.health.failed("first private outage")
#             self.backend.health.connected()
#             await asyncio.wait_for(entered.wait(), 2)
#             self.backend.health.failed("second private outage")
#             release.set()
#             await self.recovered()
#             line = trunk.event("text_delta", text="same stream after a second loss")
#             self.assertEqual((await self.event(r, "chat", "lines"))["lines"], [line])
#             self.assertFalse(any(message.get("event", {}).get("kind") == "snapshot" for message in self.pending[r]))
#         self.backend.health.connected()
#         await self.recovered()
#         self.assertEqual((await self.event(r, "chat", "snapshot"))["exchanges"][0]["exchange"], trunk.exchange)
# TEST-TIER-DISABLED-END tests/backend/test_return.py::Returned.test_second_outage_discards_an_inflight_return_then_next_return_refreshes

# TEST-TIER-DISABLED-BEGIN tests/backend/test_return.py::Returned.test_slow_other_root_does_not_delay_own_snapshots_or_note_retry_after_settling
#     async def test_slow_other_root_does_not_delay_own_snapshots_or_note_retry_after_settling(self) -> None:
#         """recovery.independent-discovery; recovery.settled-note-retry"""
#         trunk = await Trunk.make(self.frame, chat(1))
#         await trunk.accept(self.db)
#         r, w = await self.open()
#         await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
#         self.frame.behavior["arbol-roots"]["output"].append({"root": "t2", "name": "Private other", "status": "working", "current": False})
#         self.frame.configure()
#         install(self.frame, {"t2": {"list": {"sleep": 1}}})
#         await offline(self.cluster)
#         await self.backend.health.probe()
#         trunk.end("interrupted")
#         trunk.die()
#         await self.backend.notes.record(trunk.exchange, chat(1))
#         assert self.backend.notes.worker
#         await self.backend.notes.worker
#         path = self.frame.root / "notes" / (trunk.exchange+".json")
#         self.assertTrue(path.exists())
#         await online(self.cluster)
#         before = time.monotonic()
#         await self.backend.health.probe()
#         await self.recovered()
#         await self.event(r, "chat", "snapshot")
#         self.assertLess(time.monotonic()-before, 0.8)
#         self.assertEqual(len(calls(self.frame, kind="list", root="t2", phase="finish")), 0)
#         if self.backend.notes.worker:
#             await self.backend.notes.worker
#         self.assertTrue(path.exists())
#         await trunk.save(self.db, state="interrupted", remove=False)
#         self.backend.recovery.settled(self.backend.identity.root)
#         assert self.backend.notes.worker
#         await self.backend.notes.worker
#         self.assertFalse(path.exists())
#         self.assertEqual(await self.db.execute("SELECT kind FROM exchange_notes"), [("ended_stuck",)])
# TEST-TIER-DISABLED-END tests/backend/test_return.py::Returned.test_slow_other_root_does_not_delay_own_snapshots_or_note_retry_after_settling

# TEST-TIER-DISABLED-BEGIN tests/backend/test_return.py::Returned.test_pending_note_survives_a_whole_backend_restart_while_database_is_away
#     async def test_pending_note_survives_a_whole_backend_restart_while_database_is_away(self) -> None:
#         """recovery.backend-restart; recovery.pending-note-snapshot"""
#         trunk = await Trunk.make(self.frame, chat(1))
#         await trunk.accept(self.db)
#         await offline(self.cluster)
#         await self.backend.health.probe()
#         trunk.end("interrupted")
#         trunk.die()
#         note = await self.backend.notes.record(trunk.exchange, chat(1))
#         assert self.backend.notes.worker
#         await self.backend.notes.worker
#         self.backend.stopped.set()
#         await self.running
#         self.backend = Backend(self.backend.identity)
#         self.running = asyncio.create_task(self.backend.run())
#         async with asyncio.timeout(2):
#             while not (self.frame.root / "backend.sock").exists() or self.backend.notes.worker is None:
#                 await asyncio.sleep(0.01)
#         await self.backend.notes.worker
#         self.assertEqual(self.backend.live.notes[trunk.exchange][1], note)
#         await online(self.cluster)
#         await self.backend.health.probe()
#         await trunk.save(self.db, state="interrupted", remove=False)
#         self.backend.recovery.settled(self.backend.identity.root)
#         assert self.backend.notes.worker
#         await self.backend.notes.worker
#         r, w = await self.open()
#         snapshot = await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
#         self.assertEqual(snapshot["exchanges"][0]["note"], note)
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM exchange_notes"), [(1,)])
# TEST-TIER-DISABLED-END tests/backend/test_return.py::Returned.test_pending_note_survives_a_whole_backend_restart_while_database_is_away

# TEST-TIER-DISABLED-BEGIN tests/backend/test_return.py::Returned.test_delayed_return_snapshot_cannot_reopen_an_already_saved_exchange
#     async def test_delayed_return_snapshot_cannot_reopen_an_already_saved_exchange(self) -> None:
#         """recovery.saved-snapshot-race"""
#         trunk = await Trunk.make(self.frame, chat(1))
#         await trunk.accept(self.db)
#         first_line = trunk.event("text_delta", text="tracked before return")
#         r, w = await self.open()
#         await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
#         self.assertEqual((await self.event(r, "chat", "lines"))["lines"], [first_line])
#         entered, release = asyncio.Event(), asyncio.Event()
#         topic = self.backend.chats.chat_view.topic
#         original = topic.snapshot
#         async def delayed(value: Params) -> Snapshot:
#             snapshot = await original(value)
#             if not entered.is_set():
#                 entered.set()
#                 await release.wait()
#             return snapshot
#         self.backend.recovery.retry = 0.01
#         with mock.patch.object(topic, "snapshot", delayed):
#             self.backend.health.failed("private outage")
#             self.backend.health.connected()
#             await asyncio.wait_for(entered.wait(), 2)
#             trunk.end("completed")
#             trunk.die()
#             await trunk.save(self.db, answer="durable newer answer")
#             saved = await self.event(r, "chat", "saved")
#             self.assertEqual(saved["exchange"]["state"], "completed")
#             release.set()
#             await self.recovered()
#             snapshot = await self.event(r, "chat", "snapshot")
#             self.assertEqual((snapshot["exchanges"][0]["state"], snapshot["exchanges"][0]["items"][-1]["text"]),
#                              ("completed", "durable newer answer"))
# TEST-TIER-DISABLED-END tests/backend/test_return.py::Returned.test_delayed_return_snapshot_cannot_reopen_an_already_saved_exchange

# TEST-TIER-DISABLED-BEGIN tests/backend/test_return.py::Returned.test_transient_return_snapshot_refusal_is_retried_without_another_outage
#     async def test_transient_return_snapshot_refusal_is_retried_without_another_outage(self) -> None:
#         """recovery.transient-snapshot-retry"""
#         r, w = await self.open()
#         await self.subscribe(r, w, "draft", "draft", {"chat": chat(1)})
#         topic = self.backend.drafts.view.topic
#         original = topic.snapshot
#         attempts = 0
#         async def flaky(value: Params) -> Snapshot:
#             nonlocal attempts
#             attempts += 1
#             if attempts == 1:
#                 raise Refused("timeout", "private delayed read")
#             return await original(value)
#         self.backend.recovery.retry = 0.03
#         with mock.patch.object(topic, "snapshot", flaky):
#             self.backend.health.failed("private outage")
#             self.backend.health.connected()
#             await self.recovered()
#             self.assertIsNone((await self.event(r, "draft", "snapshot"))["draft"])
#         self.assertEqual(attempts, 2)
#         self.assertFalse(self.backend.database.away)
# TEST-TIER-DISABLED-END tests/backend/test_return.py::Returned.test_transient_return_snapshot_refusal_is_retried_without_another_outage


# Original deferred imports (restore at the required scope, never blindly at the tail).
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:7
# import time
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:7

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:9
# from typing import Any
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:9

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:10
# from unittest import mock
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:10

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:16
# from arbol_backend.bridge import Params, Snapshot  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:16

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:17
# from arbol_backend.database import Database, Session  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:17

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:18
# from arbol_backend.health import Health  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:18

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:19
# from arbol_backend.metadata import Attention  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:19

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:20
# from arbol_backend.model import Refused  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:20

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:21
# from arbol_backend.server import Backend  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:21

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:22
# from backend.discovery_support import calls, install  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:22

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:23
# from backend.live_support import Trunk  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:23

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:24
# from backend.recovery_support import offline, online  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:24

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_return.py:25
# from backend.test_chat_wire import WindowFixture, chat  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_return.py:25

raise RuntimeError("Mid-tier tests require an explicitly requested testing task; see MID_TIER.md.")
