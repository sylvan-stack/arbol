"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_chat_migration as _support
from backend.test_chat_migration import (
    CHAT,
    LIMITS,
    asyncio,
    time,
)


class Delegation(_support.Delegation):


# TEST-TIER-BEGIN tests/backend/test_chat_migration.py::Delegation.test_timeout_tracks_late_mutation_and_shutdown_does_not_kill_it
    async def test_timeout_tracks_late_mutation_and_shutdown_does_not_kill_it(self) -> None:
        """chats.reimport-uncertain"""
        await self.db.execute("UPDATE migrated_chats SET stale=true")
        self.config["chat"] = {"sleep": 0.4, "output": self.import_result(), "sql": "UPDATE migrated_chats SET stale=false"}
        self.configure()
        backend = await self.start()
        backend.programs.limits["reimport"] = 0.05
        self.assertEqual((LIMITS["reimport"], LIMITS["migrate-check"]), (90, 90))
        await self.settle_check(backend)
        reader, writer = await self.open()
        reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
        self.assertEqual(reply["error"]["code"], "no_answer")
        child = backend.programs.running[("reimport", CHAT)]
        self.assertIsNone(child.process.poll())
        self.children.append(child.process)
        reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
        self.assertEqual(reply["error"]["code"], "no_answer")
        started = time.monotonic()
        backend.stopped.set()
        assert self.running
        await asyncio.wait_for(self.running, 2)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(await asyncio.to_thread(child.process.wait, timeout=2), 0)
        self.assertFalse((await self.db.execute("SELECT stale FROM migrated_chats"))[0][0])
        self.assertEqual(len(self.calls("chat")), 1)
# TEST-TIER-END tests/backend/test_chat_migration.py::Delegation.test_timeout_tracks_late_mutation_and_shutdown_does_not_kill_it

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_chat_migration.py::Delegation.test_comparison_coalesces_and_does_not_delay_local_reads_or_poll
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: chats.migration-check-coalescing
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_chat_migration.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_comparison_coalesces_and_does_not_delay_local_reads_or_poll(self) -> None:
#         """chats.migration-check-coalescing"""
#         self.config["check"] = {"sleep": 0.4, "output": {**self.check_result(), "stale": [CHAT]},
#                                 "sql": "UPDATE migrated_chats SET stale=true"}
#         self.configure()
#         backend = await self.start()
#         first, first_writer = await self.open()
#         second, second_writer = await self.open()
#         initial = await self.subscribe(first, first_writer, "list", "chats")
#         self.assertFalse(initial["event"]["chats"][0]["migration"]["stale"])
#         started = time.monotonic()
#         one, two = await asyncio.gather(self.call(first, first_writer, "chats.page"),
#                                        self.call(second, second_writer, "chats.page"))
#         self.assertIn("result", one)
#         self.assertIn("result", two)
#         self.assertLess(time.monotonic() - started, 0.3)
#         await self.settle_check(backend)
#         changed = await self.until(first, "event", "list")
#         self.assertTrue(changed["event"]["chats"][0]["migration"]["stale"])
#         await asyncio.sleep(0.3)
#         self.assertEqual(len(self.calls("check")), 1)
#         self.assertTrue(all(row["home"] == str(self.frame.home) for row in self.calls()))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_chat_migration.py::Delegation.test_failed_comparison_keeps_last_known_and_later_success_clears_attention
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: chats.migration-unavailable
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_chat_migration.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_failed_comparison_keeps_last_known_and_later_success_clears_attention(self) -> None:
#         """chats.migration-unavailable"""
#         await self.db.execute("UPDATE migrated_chats SET stale=true")
#         self.config["check"] = {"status": 1, "output": {"error": {"code": "busy", "message": "Comparison is busy; saved marks stay last-known."}}}
#         self.configure()
#         backend = await self.start()
#         await self.settle_check(backend)
#         reader, writer = await self.open()
#         attention = await self.subscribe(reader, writer, "attention", "attention")
#         self.assertEqual(attention["event"]["items"][0]["id"], "migration_unavailable")
#         self.assertIn("saved marks stay last-known", attention["event"]["items"][0]["message"])
#         self.assertTrue((await self.db.execute("SELECT stale FROM migrated_chats"))[0][0])
#         self.config["check"] = {"output": self.check_result(), "sql": "UPDATE migrated_chats SET stale=false"}
#         self.configure()
#         self.assertIn("result", await self.call(reader, writer, "chats.page"))
#         await self.settle_check(backend)
#         self.assertEqual((await self.until(reader, "event", "attention"))["event"],
#                          {"kind": "closed", "id": "migration_unavailable"})
#         self.assertEqual(len(self.calls("check")), 2)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_chat_migration.py::Delegation.test_reimport_maps_both_actions_and_preserves_unrelated_local_input
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: chats.reimport-results; chats.reimport-local-input
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_chat_migration.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_reimport_maps_both_actions_and_preserves_unrelated_local_input(self) -> None:
#         """chats.reimport-results; chats.reimport-local-input"""
#         backend = await self.start()
#         await self.settle_check(backend)
#         reader, writer = await self.open()
#         before = [await self.db.execute("SELECT to_jsonb(t)::text FROM " + table + " t")
#                   for table in ("drafts", "chat_settings", "chat_marks")]
#         await self.subscribe(reader, writer, "chat", "chat", {"chat": CHAT})
#         for action in ("replaced", "copied"):
#             self.config["chat"] = {"output": {**self.import_result(action), "apiKey": "private-secret"},
#                                     "sql": "UPDATE migrated_chats SET stale=false" if action == "replaced" else
#                                     "INSERT INTO chats SELECT '" + COPY + "'::uuid,title,created_at FROM chats WHERE id='" + CHAT + "'; "
#                                     "INSERT INTO migrated_chats SELECT '" + COPY + "'::uuid,from_root,from_chat,ended_through,migrated_at,false "
#                                     "FROM migrated_chats WHERE chat_id='" + CHAT + "'"}
#             self.configure()
#             reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
#             self.assertEqual(reply["result"], {"chat": CHAT if action == "replaced" else COPY,
#                                               "previousChat": CHAT, "action": action, "fromRoot": "older", "fromChat": CHAT})
#             self.assertNotIn("private-secret", str(reply))
#             after = [await self.db.execute("SELECT to_jsonb(t)::text FROM " + table + " t")
#                      for table in ("drafts", "chat_settings", "chat_marks")]
#             self.assertEqual(after, before)
#         copied = await backend.chats.reader.chat({"chat": COPY})
#         self.assertIsNone(copied["draft"])
#         self.assertFalse(copied["chat"]["migration"]["stale"])
#         self.assertEqual(len(self.calls("chat")), 2)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_chat_migration.py::Delegation.test_two_calls_share_one_unresolved_import
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: chats.reimport-coalescing
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_chat_migration.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_two_calls_share_one_unresolved_import(self) -> None:
#         """chats.reimport-coalescing"""
#         self.config["chat"]["sleep"] = 0.25
#         self.configure()
#         backend = await self.start()
#         await self.settle_check(backend)
#         first, first_writer = await self.open()
#         second, second_writer = await self.open()
#         replies = await asyncio.gather(self.call(first, first_writer, "chat.reimport", {"chat": CHAT}),
#                                        self.call(second, second_writer, "chat.reimport", {"chat": CHAT}))
#         self.assertEqual(replies[0]["result"], replies[1]["result"])
#         self.assertEqual(len(self.calls("chat")), 1)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_chat_migration.py::Delegation.test_invalid_copy_and_malformed_result_never_trigger_an_automatic_retry
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: chats.reimport-validation
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_chat_migration.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_invalid_copy_and_malformed_result_never_trigger_an_automatic_retry(self) -> None:
#         """chats.reimport-validation"""
#         backend = await self.start()
#         await self.settle_check(backend)
#         reader, writer = await self.open()
#         for value in ("../../x", "ABCDEFAB-1234-4234-8234-123456789012", None):
#             reply = await self.call(reader, writer, "chat.reimport", {"chat": value})
#             self.assertEqual(reply["error"]["code"], "invalid_input")
#         reply = await self.call(reader, writer, "chat.reimport", {"chat": str(UUID(int=999))})
#         self.assertEqual(reply["error"]["code"], "not_found")
#         self.assertFalse(self.calls("chat"))
#         self.config["chat"]["output"]["root"] = "wrongroot"
#         self.configure()
#         reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
#         self.assertEqual((reply["error"]["code"], reply["error"]["source"]), ("no_answer", "roots"))
#         await asyncio.sleep(0.3)
#         self.assertEqual(len(self.calls("chat")), 1)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_chat_migration.py::Delegation.test_forwarded_refusal_keeps_code_source_and_only_a_bounded_safe_message
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: chats.migration-errors
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_chat_migration.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_forwarded_refusal_keeps_code_source_and_only_a_bounded_safe_message(self) -> None:
#         """chats.migration-errors"""
#         backend = await self.start()
#         await self.settle_check(backend)
#         reader, writer = await self.open()
#         assert backend.database.parameters is not None
#         backend.database.parameters["password"] = "opaque-private-value"
#         for message in ("The selected copy is busy.", "password=private-secret", "Rejected opaque-private-value", "x" * 2000):
#             self.config["chat"] = {"status": 1, "output": {"error": {"code": "busy", "message": message}}}
#             self.configure()
#             reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
#             self.assertEqual((reply["error"]["code"], reply["error"]["source"]), ("busy", "roots"))
#             self.assertNotIn("private-secret", str(reply))
#             self.assertNotIn("opaque-private-value", str(reply))
#             self.assertLessEqual(len(reply["error"]["message"].encode()), 1024)
#             if message == "The selected copy is busy.":
#                 self.assertEqual(reply["error"]["message"], message)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_chat_migration.py::Delegation.test_missing_provenance_columns_are_layout_incomplete_without_any_compare
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: chats.provenance-layout
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_chat_migration.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_missing_provenance_columns_are_layout_incomplete_without_any_compare(self) -> None:
#         """chats.provenance-layout"""
#         await self.db.execute("ALTER TABLE migrated_chats DROP COLUMN stale")
#         backend = await self.start()
#         await self.settle_check(backend)
#         reader, writer = await self.open()
#         result = await self.call(reader, writer, "root.get")
#         self.assertFalse(result["result"]["layoutComplete"])
#         rows = (await self.call(reader, writer, "chats.page"))["result"]["chats"]
#         self.assertNotIn("migration", rows[0])
#         reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
#         self.assertEqual(reply["error"]["code"], "layout_incomplete")
#         self.assertFalse(self.calls())
#         self.assertIn("layout_incomplete", backend.chats.attention.items)
# LOW-TIER-SOURCE-END
# LOW-TIER-END
