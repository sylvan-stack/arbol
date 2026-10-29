
# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_working_folders.py::Folders.test_readonly_folder_survives_more_messages_repeat_and_external_workspace_environment
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: folders.readonly-slot; folders.repeat; folders.booking-does-not-move-chat; folders.no-booking
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_working_folders.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_readonly_folder_survives_more_messages_repeat_and_external_workspace_environment(self) -> None:
#         """folders.readonly-slot; folders.repeat; folders.booking-does-not-move-chat; folders.no-booking"""
#         first = await self.send_to(800, self.readonly)
#         await self.call(self.r, self.w, "chat.settings", {"chat": chat(900), "workingFolder": str(self.readonly)})
#         with mock.patch.dict(os.environ, {"ARBOL_ROOT": self.backend.identity.root, "ARBOL_CHAT": chat(900),
#                                          "ARBOL_WORKSPACE": str(self.booked)}):
#             await self.send_to(801, self.readonly)
#             repeated = await self.call(self.r, self.w, "chat.send", first)
#             self.assertTrue(repeated["result"]["duplicate"])
#         records = starts(self.frame)
#         self.assertEqual([row["request"]["workingFolder"] for row in records], [str(self.readonly)]*3)
#         self.assertEqual(await self.db.execute("SELECT working_folder FROM exchanges WHERE chat_id=%s ORDER BY number", [chat(900)]),
#                          [(str(self.readonly),), (str(self.readonly),)])
#         self.assertEqual(await self.db.execute("SELECT working_folder FROM chat_settings WHERE chat_id=%s", [chat(900)]), [(str(self.readonly),)])
#         self.assertEqual(list(self.booked.iterdir()), [])
#         self.assertTrue(all(row["program"] in {"arbol-roots", "arbol-root", "arbol-claude-driver", "arbol-codex-driver", "arbol-pi-driver"}
#                             for row in self.frame.calls()))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_working_folders.py::Folders.test_explicit_other_folder_and_repository_move_are_kept_without_rewriting_history
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: folders.other-choice; folders.explicit-move; folders.history-preserved
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_working_folders.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_explicit_other_folder_and_repository_move_are_kept_without_rewriting_history(self) -> None:
#         """folders.other-choice; folders.explicit-move; folders.history-preserved"""
#         await self.send_to(800, self.readonly)
#         changed = await self.call(self.r, self.w, "chat.settings", {"chat": chat(900), "workingFolder": str(self.other)})
#         self.assertEqual(changed["result"], {})
#         await self.send_to(801, self.other)
#         await self.send_to(802, self.other)
#         self.assertEqual([row["request"]["workingFolder"] for row in starts(self.frame)],
#                          [str(self.readonly), str(self.other), str(self.other)])
#         self.assertEqual(await self.db.execute("SELECT working_folder FROM exchanges WHERE chat_id=%s ORDER BY number", [chat(900)]),
#                          [(str(self.readonly),), (str(self.other),), (str(self.other),)])
#         self.assertEqual(await self.db.execute("SELECT working_folder FROM chat_settings WHERE chat_id=%s", [chat(900)]), [(str(self.other),)])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_working_folders.py::Folders.test_send_again_uses_the_replaced_exchange_folder_after_a_move_and_ignores_competing_input
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: folders.retry-original; folders.retry-after-move; folders.no-folder-substitution
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_working_folders.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_send_again_uses_the_replaced_exchange_folder_after_a_move_and_ignores_competing_input(self) -> None:
#         """folders.retry-original; folders.retry-after-move; folders.no-folder-substitution"""
#         await self.send_to(800, self.readonly)
#         await self.db.execute("UPDATE exchanges SET state='failed',error='{\"code\":\"private_failure\",\"message\":\"Private fixture\"}' WHERE id=%s", [chat(800)])
#         await self.call(self.r, self.w, "chat.settings", {"chat": chat(900), "workingFolder": str(self.other)})
#         reply = await self.call(self.r, self.w, "exchange.sendAgain", {"exchange": chat(800), "newExchange": chat(801),
#             "route": self.route, "workingFolder": str(self.other), "chat": chat(999)})
#         self.assertIn("result", reply)
#         record = starts(self.frame)[-1]
#         self.assertEqual((record["request"]["workingFolder"], record["request"]["chat"]), (str(self.readonly), chat(900)))
#         self.assertNotIn("message", record["request"])
#         self.assertEqual(record["args"][-2:], ["--replaces", chat(800)])
#         self.assertEqual(await self.db.execute("SELECT working_folder FROM chat_settings WHERE chat_id=%s", [chat(900)]), [(str(self.other),)])
#         self.assertEqual(list(self.booked.iterdir()), [])
# LOW-TIER-SOURCE-END
# LOW-TIER-END
