"""Commented mid-tier selections; see MID_TIER.md before restoring a case."""

# Restore the needed imports and class header only for an explicit testing task.
# import backend.test_dispatch as _support
# from backend.test_dispatch import (
#     Any,
#     Params,
#     Path,
#     ROOT,
#     Sending,
#     WindowFixture,
#     asyncio,
#     chat,
#     install,
#     save_params,
#     starts,
#     sys,
# )


# class Sending(_support.Sending):
# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_acceptance_private_request_mark_before_start_duplicate_and_archived_preserved
#     async def test_acceptance_private_request_mark_before_start_duplicate_and_archived_preserved(self) -> None:
#         """sending.accepted; sending.mark-before-start; sending.repeat"""
#         params = await self.with_draft(self.payload())
#         await self.backend.chats.mark({"chat": chat(1), "archived": True})
#         self.backend.dispatch.settings = replace(self.backend.settings, small_call_route={"driver": "claude",
#             "subscription": "private", "model": "small"})
#         r, w = await self.open()
#         first = await self.call(r, w, "chat.send", params)
#         self.assertEqual(first["result"]["duplicate"], False)
#         record = starts(self.frame)[0]
#         self.assertEqual(record["mode"], 0o600)
#         self.assertEqual(record["directoryMode"], 0o700)
#         self.assertEqual(record["pid"], record["pgid"])
#         self.assertEqual(record["home"], str(self.frame.home))
#         self.assertEqual(record["pgOverrides"], [])
#         self.assertEqual(record["args"][:2], ["--root", self.backend.identity.root])
#         self.assertIn("smallCallRoute", record["request"])
#         self.assertEqual(record["draft"][0][2], params["exchange"])
#         self.assertFalse((self.frame.root / "requests" / (params["exchange"] + ".json")).exists())
#         self.assertIsNone(await self.backend.drafts.current({"chat": chat(1)}))
#         marks = await self.db.execute("SELECT ongoing,archived_at IS NOT NULL FROM chat_marks WHERE chat_id=%s", [chat(1)])
#         self.assertEqual(marks, [(True, True)])
#         repeated = await self.call(r, w, "chat.send", params)
#         self.assertTrue(repeated["result"]["duplicate"])
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM exchanges"), [(1,)])
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM messages"), [(1,)])
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_acceptance_private_request_mark_before_start_duplicate_and_archived_preserved

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_two_windows_join_one_start_conflicting_payload_refused_and_new_text_survives
#     async def test_two_windows_join_one_start_conflicting_payload_refused_and_new_text_survives(self) -> None:
#         """sending.shared-dispatch; sending.newer-text"""
#         install(self.frame, self.cluster.address, [{"sleep": 0.15}])
#         params = await self.with_draft(self.payload())
#         r1, w1 = await self.open()
#         r2, w2 = await self.open()
#         a = asyncio.create_task(self.call(r1, w1, "chat.send", params))
#         await self.wait_starts()
#         b = asyncio.create_task(self.call(r2, w2, "chat.send", params))
#         changed = await self.backend.drafts.save(await save_params({"chat": chat(1), "text": "and more",
#             "baseRevision": params["draft"]["revision"]}))
#         with self.assertRaises(Error) as caught:
#             await self.execute({**params, "message": "different"})
#         self.assertEqual(caught.exception.code, "invalid_input")
#         results = await asyncio.gather(a, b)
#         self.assertEqual(results[0]["result"], results[1]["result"])
#         self.assertEqual(len(starts(self.frame)), 1)
#         current = await self.backend.drafts.current({"chat": chat(1)})
#         assert current
#         self.assertEqual((current["text"], current["revision"]), ("and more", changed["revision"]))
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_two_windows_join_one_start_conflicting_payload_refused_and_new_text_survives

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_definite_refusal_source_message_and_mark_clear
#     async def test_definite_refusal_source_message_and_mark_clear(self) -> None:
#         """sending.refusal; sending.safe-errors"""
#         r, w = await self.open()
#         for n, (code, source, explanation) in enumerate([
#             ("chat_busy", "trunk", "The chat has an Exchange in progress: " + chat(700)),
#             ("unknown_trunk", "root-manager", "No compatible Trunk."),
#             ("future_refusal", "trunk", "A future refusal is still a refusal."),
#             ("database_unavailable", "trunk", "Authorization Bearer fictional-private-value"),
#         ]):
#             install(self.frame, self.cluster.address, [{"reply": {"error": {"code": code, "message": explanation}}}])
#             params = await self.with_draft(self.payload(exchange=800+n, id=n+1))
#             reply = await self.call(r, w, "chat.send", params)
#             self.assertEqual((reply["error"]["code"], reply["error"]["source"]), (code, source))
#             if code == "database_unavailable":
#                 self.assertNotIn("fictional-private-value", json.dumps(reply))
#             else:
#                 self.assertEqual(reply["error"]["message"], explanation)
#             current = await self.backend.drafts.current({"chat": params["chat"]})
#             assert current
#             self.assertEqual(current["text"], params["message"])
#             self.assertNotIn("sentAs", current)
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM exchanges"), [(0,)])
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_definite_refusal_source_message_and_mark_clear

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_uncertain_replies_retry_after_return_and_never_overlap_active_child
#     async def test_uncertain_replies_retry_after_return_and_never_overlap_active_child(self) -> None:
#         """sending.retry-schedule; sending.no-concurrent-start"""
#         install(self.frame, self.cluster.address, [{"sleep": 0.65, "raw": "not json"},
#             {"reply": {"error": {"code": "no_answer", "message": "No line yet."}}},
#             {"reply": {"error": {"code": "in_progress", "message": "Still accepting."}}}, {}])
#         self.backend.programs.limits["start"] = 0.5
#         self.backend.dispatch.total = 3.0
#         params = await self.with_draft(self.payload())
#         result = await self.execute(params)
#         self.assertTrue(result["accepted"])
#         rows = starts(self.frame)
#         self.assertEqual(len(rows), 4)
#         self.assertTrue(all(not row["collision"] for row in rows))
#         self.assertGreaterEqual(float(rows[1]["at"]) - float(rows[0]["at"]), 0.64)
#         ended = float((self.frame.bin / ("ended-" + params["exchange"] + "-1")).read_text())
#         self.assertGreaterEqual(float(rows[2]["at"]) - ended, 0.045)
#         self.assertTrue(all(row["exchange"] == params["exchange"] for row in rows))
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_uncertain_replies_retry_after_return_and_never_overlap_active_child

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_production_25_15_schedule_uses_same_exchange_after_lost_reply
#     async def test_production_25_15_schedule_uses_same_exchange_after_lost_reply(self) -> None:
#         """sending.production-25-15"""
#         self.assertEqual((LIMITS["start"], RETRY_SECONDS, TOTAL_SECONDS), (25, 15, 120))
#         install(self.frame, self.cluster.address, [{"sleep": 26, "raw": ""}, {}])
#         self.backend.programs.limits["start"] = LIMITS["start"]
#         self.backend.dispatch.retry, self.backend.dispatch.total = RETRY_SECONDS, TOTAL_SECONDS
#         params = await self.with_draft(self.payload())
#         result = await asyncio.wait_for(self.execute(params), 46)
#         self.assertTrue(result["accepted"])
#         rows = starts(self.frame)
#         self.assertEqual(len(rows), 2)
#         self.assertGreaterEqual(float(rows[1]["at"]) - float(rows[0]["at"]), 39.8)
#         self.assertLess(float(rows[1]["at"]) - float(rows[0]["at"]), 42)
#         self.assertTrue(all(not row["collision"] for row in rows))
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_production_25_15_schedule_uses_same_exchange_after_lost_reply

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_total_deadline_retains_active_file_and_mark_without_automatic_retry
#     async def test_total_deadline_retains_active_file_and_mark_without_automatic_retry(self) -> None:
#         """sending.total-bound; sending.uncertain-mark"""
#         install(self.frame, self.cluster.address, [{"sleep": 0.5}])
#         self.backend.dispatch.total = 0.1
#         self.backend.programs.limits["start"] = 0.05
#         params = await self.with_draft(self.payload())
#         started = time.monotonic()
#         with self.assertRaises(Error) as caught:
#             await self.execute(params)
#         self.assertEqual(caught.exception.code, "no_answer")
#         self.assertLess(time.monotonic() - started, 0.3)
#         # The deadline bounds the caller, not when the detached Python stand-in finishes importing.
#         self.assertEqual(len(await self.wait_starts()), 1)
#         current = await self.backend.drafts.current({"chat": chat(1)})
#         assert current
#         self.assertEqual(current["sentAs"], params["exchange"])
#         path = self.frame.root / "requests" / (params["exchange"] + ".json")
#         self.assertTrue(path.exists())
#         manager = self.backend.programs.running[("start", params["exchange"])].process
#         self.assertIsNone(manager.poll())
#         with self.assertRaises(Error):
#             await self.execute(params)
#         self.assertEqual(len(starts(self.frame)), 1)
#         await asyncio.wait_for(asyncio.to_thread(manager.wait), 3)
#         async with asyncio.timeout(1):
#             while path.exists():
#                 await asyncio.sleep(0.01)
#         self.assertEqual(len(starts(self.frame)), 1)
#         r, w = await self.open()
#         self.assertIsNone((await self.call(r, w, "draft.get", {"chat": chat(1)}))["result"])
#         self.backend.dispatch.total = 2.0
#         self.backend.programs.limits["start"] = 0.5
#         install(self.frame, self.cluster.address, [{}])
#         self.assertTrue((await self.execute(params))["duplicate"])
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_total_deadline_retains_active_file_and_mark_without_automatic_retry

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_disconnected_caller_and_backend_shutdown_do_not_kill_mutating_start
#     async def test_disconnected_caller_and_backend_shutdown_do_not_kill_mutating_start(self) -> None:
#         """sending.disconnect; sending.detached-shutdown"""
#         install(self.frame, self.cluster.address, [{"sleep": 0.35}])
#         params = await self.with_draft(self.payload())
#         caller = asyncio.create_task(self.execute(params))
#         await self.wait_starts()
#         caller.cancel()
#         with self.assertRaises(asyncio.CancelledError):
#             await caller
#         self.assertFalse(self.backend.dispatch.entries[params["exchange"]].task.done())  # type: ignore[union-attr]
#         before = time.monotonic()
#         self.backend.stopped.set()
#         await asyncio.wait_for(self.running, 2)
#         self.assertLess(time.monotonic() - before, 2)
#         path = self.frame.root / "requests" / (params["exchange"] + ".json")
#         self.assertTrue(path.exists())
#         await asyncio.sleep(0.4)
#         self.assertTrue((self.frame.bin / ("ended-" + params["exchange"] + "-0")).exists())
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM exchanges WHERE id=%s", [params["exchange"]]), [(1,)])
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_disconnected_caller_and_backend_shutdown_do_not_kill_mutating_start

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_invalid_inputs_and_draft_ownership_precede_any_file_or_child
#     async def test_invalid_inputs_and_draft_ownership_precede_any_file_or_child(self) -> None:
#         """sending.validate-before-effects"""
#         base = await self.with_draft(self.payload())
#         r, w = await self.open()
#         invalid = [
#             {**base, "chat": "../chat"}, {**base, "exchange": "../../x"},
#             {**base, "route": {"driver": "unknown", "subscription": "private", "model": "m"}},
#             {**base, "route": {"driver": "claude", "subscription": "unknown", "model": "m"}},
#             {**base, "route": {"driver": "claude", "subscription": "private"}},
#             {**base, "workingFolder": "relative"}, {**base, "workingFolder": "/absent-arbol-test-folder"},
#             *({**base, "message": body} for body in ["", " ", "a\0b", "a" * (1024*1024+1)]),
#             {**base, "draft": {"revision": True}},
#             {**base, "draft": {"revision": 9999}},
#             {**base, "draft": {"revision": base["draft"]["revision"], "folder": "/different"}},
#             {**base, "message": "text not saved as this revision"},
#         ]
#         for params in invalid:
#             reply = await self.call(r, w, "chat.send", params)
#             self.assertIn(reply["error"]["code"], ("invalid_input", "draft_conflict"))
#         self.assertEqual(starts(self.frame), [])
#         self.assertFalse((self.frame.root / "requests").exists())
#         current = await self.backend.drafts.current({"chat": chat(1)})
#         assert current
#         self.assertNotIn("sentAs", current)
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_invalid_inputs_and_draft_ownership_precede_any_file_or_child

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_new_chat_repository_draft_is_accepted_then_removed
#     async def test_new_chat_repository_draft_is_accepted_then_removed(self) -> None:
#         """sending.repository-draft"""
#         params = await self.with_draft(self.payload(id=900), folder=True)
#         result = await self.execute(params)
#         self.assertEqual(result["chat"], chat(900))
#         self.assertIsNone(await self.backend.drafts.current({"folder": str(self.frame.base)}))
#         self.assertEqual(await self.db.execute("SELECT ongoing FROM chat_marks WHERE chat_id=%s", [chat(900)]), [(True,)])
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_new_chat_repository_draft_is_accepted_then_removed

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_acceptance_survives_database_cleanup_failure_and_later_read_recovers
#     async def test_acceptance_survives_database_cleanup_failure_and_later_read_recovers(self) -> None:
#         """sending.database-cleanup-recovery"""
#         params = await self.with_draft(self.payload())
#         with mock.patch.object(self.backend.drafts, "finish", side_effect=Error("database_unavailable")):
#             result = await self.execute(params)
#         self.assertTrue(result["accepted"])
#         current = await self.backend.drafts.current({"chat": chat(1)})
#         assert current
#         self.assertEqual(current["sentAs"], params["exchange"])
#         r, w = await self.open()
#         self.assertIsNone((await self.call(r, w, "draft.get", {"chat": chat(1)}))["result"])
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_acceptance_survives_database_cleanup_failure_and_later_read_recovers

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_send_again_uses_old_chat_folder_no_message_and_passes_cannot_replace
#     async def test_send_again_uses_old_chat_folder_no_message_and_passes_cannot_replace(self) -> None:
#         """sending.send-again; sending.cannot-replace"""
#         await self.db.execute(
#             "INSERT INTO exchanges(id,chat_id,number,state,trunk,build,route,working_folder,accepted_at,ended_at) "
#             "VALUES(%s,%s,1,'completed','trivial','0','{}',%s,clock_timestamp(),clock_timestamp())",
#             [chat(700), chat(2), str(self.frame.base)])
#         params = {"exchange": chat(700), "newExchange": chat(800), "route": self.payload()["route"]}
#         r, w = await self.open()
#         reply = await self.call(r, w, "exchange.sendAgain", params)
#         self.assertEqual(reply["result"]["chat"], chat(2))
#         record = starts(self.frame)[0]
#         self.assertNotIn("message", record["request"])
#         self.assertEqual(record["request"]["workingFolder"], str(self.frame.base))
#         self.assertEqual(record["args"][-2:], ["--replaces", chat(700)])
#         install(self.frame, self.cluster.address, [{"reply": {"error": {"code": "cannot_replace", "message": "Not last."}}}])
#         reply = await self.call(r, w, "exchange.sendAgain", {**params, "newExchange": chat(801)})
#         self.assertEqual((reply["error"]["code"], reply["error"]["source"]), ("cannot_replace", "trunk"))
#         for other in [{**params, "newExchange": chat(700)}, {**params, "exchange": "../x"},
#                       {**params, "exchange": chat(999)}]:
#             self.assertIn("error", await self.call(r, w, "exchange.sendAgain", other))
#         self.assertEqual(len(starts(self.frame)), 2)
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_send_again_uses_old_chat_folder_no_message_and_passes_cannot_replace

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_malformed_and_mismatched_acceptance_never_clear_draft
#     async def test_malformed_and_mismatched_acceptance_never_clear_draft(self) -> None:
#         """sending.result-validation"""
#         self.backend.dispatch.total = 0.15
#         params = await self.with_draft(self.payload())
#         reply = {"accepted": True, "duplicate": False, "exchange": chat(999), "chat": chat(1), "number": 1}
#         install(self.frame, self.cluster.address, [{"reply": reply}])
#         with self.assertRaises(Refused) as caught:
#             await self.execute(params)
#         self.assertEqual(caught.exception.code, "no_answer")
#         current = await self.backend.drafts.current({"chat": chat(1)})
#         assert current
#         self.assertEqual(current["sentAs"], params["exchange"])
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_malformed_and_mismatched_acceptance_never_clear_draft

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_draft_dispatch_requires_no_schema_or_contract_history_write_permissions
#     async def test_draft_dispatch_requires_no_schema_or_contract_history_write_permissions(self) -> None:
#         """sending.no-ddl-history-writes"""
#         await self.db.execute("CREATE ROLE draft_client LOGIN")
#         await self.db.execute("GRANT USAGE ON SCHEMA public TO draft_client")
#         await self.db.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO draft_client")
#         await self.db.execute("GRANT INSERT,UPDATE,DELETE ON drafts,chat_settings,chat_marks,exchange_notes TO draft_client")
#         await self.db.execute("GRANT USAGE ON SEQUENCE drafts_revision TO draft_client")
#         await self.backend.database.execute("SELECT 1")
#         assert self.backend.database.parameters is not None
#         self.backend.database.parameters["user"] = "draft_client"
#         params = await self.with_draft(self.payload())
#         self.assertTrue((await self.execute(params))["accepted"])
#         self.assertIsNone(await self.backend.drafts.current({"chat": chat(1)}))
#         await self.db.execute("SELECT count(*) FROM chats")
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM messages"), [(1,)])
#         self.assertEqual(await self.db.execute("SELECT last_value FROM drafts_revision"), [(1,)])
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_draft_dispatch_requires_no_schema_or_contract_history_write_permissions

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_stale_draft_and_existing_other_chat_identifier_have_no_dispatch_effect
#     async def test_stale_draft_and_existing_other_chat_identifier_have_no_dispatch_effect(self) -> None:
#         """sending.ownership"""
#         await self.db.execute(
#             "INSERT INTO exchanges(id,chat_id,number,state,trunk,build,route,working_folder,accepted_at,ended_at) "
#             "VALUES(%s,%s,1,'completed','trivial','0','{}',%s,clock_timestamp(),clock_timestamp())",
#             [chat(800), chat(2), str(self.frame.base)])
#         with self.assertRaises(Error) as caught:
#             await self.execute(self.payload())
#         self.assertEqual(caught.exception.code, "invalid_input")
#         self.assertFalse((self.frame.root / "requests").exists())
#         self.assertEqual(starts(self.frame), [])
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_stale_draft_and_existing_other_chat_identifier_have_no_dispatch_effect

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_result_shape_and_safe_forwarding_project_only_known_fields
#     async def test_result_shape_and_safe_forwarding_project_only_known_fields(self) -> None:
#         """sending.acceptance-shape; sending.error-shape"""
#         params = self.payload()
#         valid = {"accepted": True, "duplicate": True, "exchange": params["exchange"], "chat": params["chat"], "number": 1}
#         self.assertEqual(self.backend.dispatch.result({**valid, "credential": "ignored"}, params), valid)
#         invalid: list[Any] = [None, [], {}, {**valid, "accepted": 1}, {**valid, "duplicate": 0},
#             {**valid, "number": True}, {**valid, "number": 0}, {**valid, "chat": chat(9)},
#             {**valid, "root": "other"}, {"error": {"code": "bad/code", "message": "x"}},
#             {"error": {"code": "chat_busy"}}, {"error": {"code": "chat_busy", "message": "x", "source": "unknown"}}]
#         for value in invalid:
#             with self.assertRaises(Error) as caught:
#                 self.backend.dispatch.result(value, params)
#             self.assertEqual(caught.exception.code, "no_answer")
#         assert self.backend.database.parameters is not None
#         self.backend.database.parameters["password"] = "opaquePrivateProofValue"
#         try:
#             with self.assertRaises(Error) as caught:
#                 self.backend.dispatch.result({"error": {"code": "future_code", "source": "root-manager",
#                     "message": "failure opaquePrivateProofValue"}}, params)
#             self.assertEqual((caught.exception.code, caught.exception.source), ("future_code", "root-manager"))
#             self.assertNotIn("opaquePrivateProofValue", str(caught.exception))
#         finally:
#             self.backend.database.parameters["password"] = ""
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_result_shape_and_safe_forwarding_project_only_known_fields

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_other_chats_progress_while_one_start_waits
#     async def test_other_chats_progress_while_one_start_waits(self) -> None:
#         """sending.chat-isolation"""
#         install(self.frame, self.cluster.address, [{"sleep": 0.65}])
#         a = asyncio.create_task(self.execute(self.payload()))
#         await self.wait_starts()
#         install(self.frame, self.cluster.address, [{}])
#         before = time.monotonic()
#         b = await self.execute(self.payload(exchange=801, id=900))
#         self.assertTrue(b["accepted"])
#         self.assertLess(time.monotonic() - before, 0.5)
#         self.assertFalse(a.done())
#         self.assertTrue((await a)["accepted"])
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_other_chats_progress_while_one_start_waits

# TEST-TIER-DISABLED-BEGIN tests/backend/test_dispatch.py::Sending.test_new_message_after_failed_cancelled_or_interrupted_is_delegated
#     async def test_new_message_after_failed_cancelled_or_interrupted_is_delegated(self) -> None:
#         """sending.after-ended-exchange"""
#         for n, state in enumerate(("failed", "cancelled", "interrupted"), 1):
#             await self.db.execute(
#                 "INSERT INTO exchanges(id,chat_id,number,state,error,trunk,build,route,working_folder,accepted_at,ended_at) "
#                 "VALUES(%s,%s,1,%s,CASE WHEN %s='failed' THEN '{\"code\":\"test_failure\"}'::jsonb END,"
#                 "'trivial','0','{}',%s,clock_timestamp(),clock_timestamp())",
#                 [chat(700+n), chat(n), state, state, str(self.frame.base)])
#             result = await self.execute(self.payload(exchange=800+n, id=n))
#             self.assertEqual((result["accepted"], result["number"]), (True, 2))
# TEST-TIER-DISABLED-END tests/backend/test_dispatch.py::Sending.test_new_message_after_failed_cancelled_or_interrupted_is_delegated


# Original deferred imports (restore at the required scope, never blindly at the tail).
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_dispatch.py:6
# import json
# TEST-TIER-IMPORTS-END tests/backend/test_dispatch.py:6

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_dispatch.py:8
# import time
# TEST-TIER-IMPORTS-END tests/backend/test_dispatch.py:8

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_dispatch.py:9
# from dataclasses import replace
# TEST-TIER-IMPORTS-END tests/backend/test_dispatch.py:9

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_dispatch.py:12
# from unittest import mock
# TEST-TIER-IMPORTS-END tests/backend/test_dispatch.py:12

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_dispatch.py:18
# from arbol_backend.bridge import Error, Params  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_dispatch.py:18

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_dispatch.py:19
# from arbol_backend.dispatch import RETRY_SECONDS, TOTAL_SECONDS  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_dispatch.py:19

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_dispatch.py:21
# from arbol_backend.model import Refused  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_dispatch.py:21

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_dispatch.py:22
# from arbol_backend.process import LIMITS  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_dispatch.py:22

raise RuntimeError("Mid-tier tests require an explicitly requested testing task; see MID_TIER.md.")
