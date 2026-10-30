"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_drafts as _support
from backend.test_drafts import (
    Any,
    Params,
    asyncio,
    chat,
    mock,
)


class Drafts(_support.Drafts):

# TEST-TIER-BEGIN tests/backend/test_drafts.py::Drafts.test_competing_first_saves_updates_deletes_and_no_revision_reuse
    async def test_competing_first_saves_updates_deletes_and_no_revision_reuse(self) -> None:
        """drafts.cas-races; drafts.conflict-null"""
        r1, w1 = await self.open()
        r2, w2 = await self.open()
        async def pair(base: int | None, a: str, b: str) -> list[Params]:
            return list(await asyncio.gather(
                self.call(r1, w1, "draft.save", {"chat": chat(1), "text": a, "baseRevision": base}),
                self.call(r2, w2, "draft.save", {"chat": chat(1), "text": b, "baseRevision": base})))
        replies = await pair(None, "A", "B")
        winner = next(item["result"]["revision"] for item in replies if "result" in item)
        failure = next(item["error"] for item in replies if "error" in item)
        self.assertEqual((failure["code"], failure["draft"]["revision"]), ("draft_conflict", winner))
        replies = await pair(winner, "C", "D")
        newer = next(item["result"]["revision"] for item in replies if "result" in item)
        self.assertGreater(newer, winner)
        self.assertEqual(next(item["error"]["draft"]["revision"] for item in replies if "error" in item), newer)
        replies = await pair(newer, "", "")
        self.assertEqual(sum("result" in item for item in replies), 1)
        failure = next(item["error"] for item in replies if "error" in item)
        self.assertEqual((failure["code"], failure["draft"]), ("draft_conflict", None))
        recreated = await self.saved({"chat": chat(1), "text": "after deletion", "baseRevision": None})
        self.assertGreater(recreated, newer)
        stale = await self.call(r1, w1, "draft.save", {"chat": chat(1), "text": "lost", "baseRevision": winner})
        self.assertEqual(stale["error"]["draft"]["text"], "after deletion")
# TEST-TIER-END tests/backend/test_drafts.py::Drafts.test_competing_first_saves_updates_deletes_and_no_revision_reuse


# TEST-TIER-BEGIN tests/backend/test_drafts.py::Drafts.test_save_during_reconciliation_survives_its_conditional_delete
    async def test_save_during_reconciliation_survives_its_conditional_delete(self) -> None:
        """drafts.cleanup-cas"""
        key = {"chat": chat(1)}
        revision = await self.saved({**key, "text": "original", "baseRevision": None})
        await self.backend.drafts.mark({**key, "exchange": chat(800), "message": "original",
            "draft": {"revision": revision}, "route": {}, "workingFolder": str(self.frame.base)})
        await self.seed_exchange(chat(800), chat(1))
        real = self.backend.database.execute
        async def raced(sql: str, args: Any = None) -> list[tuple[Any, ...]]:
            if sql.startswith("WITH removed"):
                await self.saved({**key, "text": "newer", "baseRevision": revision})
            return await real(sql, args)
        with mock.patch.object(self.backend.database, "execute", side_effect=raced):
            await self.backend.drafts.reconcile(key)
        current = await self.backend.drafts.current(key)
        assert current
        self.assertEqual(current["text"], "newer")
# TEST-TIER-END tests/backend/test_drafts.py::Drafts.test_save_during_reconciliation_survives_its_conditional_delete

# TEST-TIER-BEGIN tests/backend/test_drafts.py::Drafts.test_acceptance_between_capture_and_reconciliation_never_returns_a_stale_mark
    async def test_acceptance_between_capture_and_reconciliation_never_returns_a_stale_mark(self) -> None:
        """drafts.capture-acceptance-race"""
        key = {"chat": chat(1)}
        revision = await self.saved({**key, "text": "original", "baseRevision": None})
        await self.backend.drafts.mark({**key, "exchange": chat(800), "message": "original",
            "draft": {"revision": revision}, "route": {}, "workingFolder": str(self.frame.base)})
        real = self.backend.chats.reader.chat
        committed = False
        async def raced(params: Params) -> Params:
            nonlocal committed
            state = await real(params)
            if not committed:
                committed = True
                await self.seed_exchange(chat(800), chat(1))
                await self.backend.drafts.reconcile(key)
            return state
        with mock.patch.object(self.backend.chats.reader, "chat", side_effect=raced):
            state = await self.backend.drafts.chat(key)
        self.assertIsNone(state["draft"])
        self.assertEqual(state["chat"]["exchangeCount"], 1)
        self.assertTrue(state["marks"]["ongoing"])
# TEST-TIER-END tests/backend/test_drafts.py::Drafts.test_acceptance_between_capture_and_reconciliation_never_returns_a_stale_mark

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_drafts.py::Drafts.test_scopes_global_counter_exact_text_and_missing_chat
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: drafts.scope-counter
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_drafts.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_scopes_global_counter_exact_text_and_missing_chat(self) -> None:
#         """drafts.scope-counter"""
#         r, w = await self.open()
#         body = "  exact\n🙂 text \t"
#         first = await self.call(r, w, "draft.save", {"chat": chat(1), "text": body, "baseRevision": None})
#         revision = first["result"]["revision"]
#         current = (await self.call(r, w, "draft.get", {"chat": chat(1)}))["result"]
#         self.assertEqual((current["text"], current["revision"], current["chat"]), (body, revision, chat(1)))
#         key = {"folder": str(self.frame.base / "gone/../repository")}
#         second = await self.call(r, w, "draft.save", {**key, "text": "new chat", "baseRevision": None})
#         self.assertGreater(second["result"]["revision"], revision)
#         state = (await self.call(r, w, "draft.get", key))["result"]
#         self.assertEqual(state["folder"], str(self.frame.base / "repository"))
#         missing = await self.call(r, w, "draft.save", {"chat": chat(999), "text": body, "baseRevision": None})
#         self.assertEqual(missing["error"]["code"], "not_found")
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM chats"), [(201,)])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_drafts.py::Drafts.test_utf8_size_and_all_invalid_params_leave_no_rows
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: drafts.validation; drafts.utf8-boundary
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_drafts.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_utf8_size_and_all_invalid_params_leave_no_rows(self) -> None:
#         """drafts.validation; drafts.utf8-boundary"""
#         r, w = await self.open()
#         invalid: list[Params] = [
#             {"chat": "../x", "text": "x", "baseRevision": None},
#             {"chat": chat(1), "folder": "/tmp", "text": "x", "baseRevision": None},
#             {"folder": "relative", "text": "x", "baseRevision": None},
#             {"chat": chat(1), "text": "x"},
#             *({"chat": chat(1), "text": "x", "baseRevision": value} for value in [0, -1, True, 1.0, 2**63]),
#             {"chat": chat(1), "text": "a\0b", "baseRevision": None},
#             {"chat": chat(1), "text": "🙂" * (MAX_TEXT // 4) + "a", "baseRevision": None},
#         ]
#         for params in invalid:
#             reply = await self.call(r, w, "draft.save", params)
#             self.assertEqual(reply["error"]["code"], "invalid_input", str(params)[:120])
#         with self.assertRaises(Error):
#             content("\ud800")
#         self.assertEqual(await self.db.execute("SELECT count(*) FROM drafts"), [(0,)])
#         exact = "🙂" * (MAX_TEXT // 4)
#         revision = await self.saved({"chat": chat(1), "text": exact, "baseRevision": None})
#         self.assertEqual((await self.backend.drafts.current({"chat": chat(1)}))["text"], exact)  # type: ignore[index]
#         await self.backend.drafts.save(await save_params({"chat": chat(1), "text": "", "baseRevision": revision}))
#         self.assertIsNone(await self.backend.drafts.current({"chat": chat(1)}))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_drafts.py::Drafts.test_chat_and_folder_subscriptions_publish_revisions_and_marks_without_regression
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: drafts.subscriptions; drafts.sent-mark
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_drafts.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_chat_and_folder_subscriptions_publish_revisions_and_marks_without_regression(self) -> None:
#         """drafts.subscriptions; drafts.sent-mark"""
#         r1, w1 = await self.open()
#         r2, w2 = await self.open()
#         key = {"chat": chat(1)}
#         await self.subscribe(r1, w1, "draft", "draft", key)
#         await self.subscribe(r2, w2, "chat", "chat", key)
#         revision = (await self.call(r1, w1, "draft.save", {**key, "text": "send me", "baseRevision": None}))["result"]["revision"]
#         self.assertEqual((await self.event(r1, "draft", "draft"))["draft"]["revision"], revision)
#         self.assertEqual((await self.event(r2, "chat", "draft"))["draft"]["revision"], revision)
#         params = {**key, "exchange": chat(800), "message": "send me", "draft": {"revision": revision},
#                   "route": {"driver": "claude", "subscription": "private", "model": "model"},
#                   "workingFolder": str(self.frame.base)}
#         await self.backend.drafts.mark(params)
#         self.assertEqual((await self.event(r1, "draft", "draft"))["draft"]["sentAs"], chat(800))
#         current = await self.backend.drafts.current(key)
#         assert current
#         self.assertEqual(current["sentRequest"], {name: params[name] for name in ("chat", "route", "workingFolder")})
#         later = await self.saved({**key, "text": "new words", "baseRevision": revision})
#         self.assertGreater(later, revision)
#         current = await self.backend.drafts.current(key)
#         assert current
#         self.assertNotIn("sentAs", current)
#         folder = {"folder": str(self.frame.base)}
#         await self.subscribe(r1, w1, "new-chat", "draft", folder)
#         await self.saved({**folder, "text": "repository", "baseRevision": None})
#         self.assertEqual((await self.event(r1, "new-chat", "draft"))["draft"]["text"], "repository")
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_drafts.py::Drafts.test_later_read_recovers_accepted_mark_outside_read_only_and_preserves_newer_text
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: drafts.accepted-recovery; drafts.newer-text
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_drafts.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_later_read_recovers_accepted_mark_outside_read_only_and_preserves_newer_text(self) -> None:
#         """drafts.accepted-recovery; drafts.newer-text"""
#         key = {"chat": chat(1)}
#         revision = await self.saved({**key, "text": "original", "baseRevision": None})
#         params = {**key, "exchange": chat(800), "message": "original", "draft": {"revision": revision},
#                   "route": {"driver": "claude", "subscription": "private", "model": "model"},
#                   "workingFolder": str(self.frame.base)}
#         marked = await self.backend.drafts.mark(params)
#         await self.seed_exchange(chat(800), chat(1))
#         r, w = await self.open()
#         self.assertIsNone((await self.call(r, w, "draft.get", key))["result"])
#         self.assertEqual(await self.db.execute("SELECT ongoing FROM chat_marks WHERE chat_id=%s", [chat(1)]), [(True,)])
#         revision = await self.saved({**key, "text": "new text", "baseRevision": None})
#         await self.backend.drafts.finish(params, marked, accepted=False)
#         current = await self.backend.drafts.current(key)
#         assert current
#         self.assertEqual(current["revision"], revision)
#         # A forged mark to an accepted Exchange in another chat is not enough to erase text.
#         await self.db.execute("UPDATE drafts SET sent_as=%s,sent_request=jsonb_build_object('chat',%s::text) "
#                               "WHERE chat_id=%s", [chat(800), chat(2), chat(1)])
#         self.assertIsNotNone((await self.call(r, w, "draft.get", key))["result"])
# LOW-TIER-SOURCE-END
# LOW-TIER-END
