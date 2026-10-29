"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_drafts as _support
from backend.test_drafts import (
    Any,
    Drafts,
    Error,
    MAX_TEXT,
    Params,
    Path,
    ROOT,
    WindowFixture,
    asyncio,
    chat,
    content,
    mock,
    save_params,
    sys,
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
