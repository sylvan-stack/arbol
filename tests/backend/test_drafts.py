"""Two-window Draft CAS and accepted-mark recovery on private PostgreSQL/socket."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Error, Params  # noqa: E402
from arbol_backend.drafts import MAX_TEXT, content, save_params  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class Drafts(WindowFixture):
    async def saved(self, params: Params) -> int:
        normalized = await save_params(params)
        return int((await self.backend.drafts.save(normalized))["revision"])

    async def seed_exchange(self, exchange: str, id: str, number: int = 1) -> None:
        await self.db.execute(
            "INSERT INTO exchanges(id,chat_id,number,state,trunk,build,route,working_folder,accepted_at,ended_at) "
            "VALUES(%s,%s,%s,'completed','trivial','0','{}',%s,clock_timestamp(),clock_timestamp())",
            [exchange, id, number, str(self.frame.base)])

    async def test_scopes_global_counter_exact_text_and_missing_chat(self) -> None:
        """drafts.scope-counter"""
        r, w = await self.open()
        body = "  exact\n🙂 text \t"
        first = await self.call(r, w, "draft.save", {"chat": chat(1), "text": body, "baseRevision": None})
        revision = first["result"]["revision"]
        current = (await self.call(r, w, "draft.get", {"chat": chat(1)}))["result"]
        self.assertEqual((current["text"], current["revision"], current["chat"]), (body, revision, chat(1)))
        key = {"folder": str(self.frame.base / "gone/../repository")}
        second = await self.call(r, w, "draft.save", {**key, "text": "new chat", "baseRevision": None})
        self.assertGreater(second["result"]["revision"], revision)
        state = (await self.call(r, w, "draft.get", key))["result"]
        self.assertEqual(state["folder"], str(self.frame.base / "repository"))
        missing = await self.call(r, w, "draft.save", {"chat": chat(999), "text": body, "baseRevision": None})
        self.assertEqual(missing["error"]["code"], "not_found")
        self.assertEqual(await self.db.execute("SELECT count(*) FROM chats"), [(201,)])

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

    async def test_utf8_size_and_all_invalid_params_leave_no_rows(self) -> None:
        """drafts.validation; drafts.utf8-boundary"""
        r, w = await self.open()
        invalid: list[Params] = [
            {"chat": "../x", "text": "x", "baseRevision": None},
            {"chat": chat(1), "folder": "/tmp", "text": "x", "baseRevision": None},
            {"folder": "relative", "text": "x", "baseRevision": None},
            {"chat": chat(1), "text": "x"},
            *({"chat": chat(1), "text": "x", "baseRevision": value} for value in [0, -1, True, 1.0, 2**63]),
            {"chat": chat(1), "text": "a\0b", "baseRevision": None},
            {"chat": chat(1), "text": "🙂" * (MAX_TEXT // 4) + "a", "baseRevision": None},
        ]
        for params in invalid:
            reply = await self.call(r, w, "draft.save", params)
            self.assertEqual(reply["error"]["code"], "invalid_input", str(params)[:120])
        with self.assertRaises(Error):
            content("\ud800")
        self.assertEqual(await self.db.execute("SELECT count(*) FROM drafts"), [(0,)])
        exact = "🙂" * (MAX_TEXT // 4)
        revision = await self.saved({"chat": chat(1), "text": exact, "baseRevision": None})
        self.assertEqual((await self.backend.drafts.current({"chat": chat(1)}))["text"], exact)  # type: ignore[index]
        await self.backend.drafts.save(await save_params({"chat": chat(1), "text": "", "baseRevision": revision}))
        self.assertIsNone(await self.backend.drafts.current({"chat": chat(1)}))

    async def test_chat_and_folder_subscriptions_publish_revisions_and_marks_without_regression(self) -> None:
        """drafts.subscriptions; drafts.sent-mark"""
        r1, w1 = await self.open()
        r2, w2 = await self.open()
        key = {"chat": chat(1)}
        await self.subscribe(r1, w1, "draft", "draft", key)
        await self.subscribe(r2, w2, "chat", "chat", key)
        revision = (await self.call(r1, w1, "draft.save", {**key, "text": "send me", "baseRevision": None}))["result"]["revision"]
        self.assertEqual((await self.event(r1, "draft", "draft"))["draft"]["revision"], revision)
        self.assertEqual((await self.event(r2, "chat", "draft"))["draft"]["revision"], revision)
        params = {**key, "exchange": chat(800), "message": "send me", "draft": {"revision": revision},
                  "route": {"driver": "claude", "subscription": "private", "model": "model"},
                  "workingFolder": str(self.frame.base)}
        await self.backend.drafts.mark(params)
        self.assertEqual((await self.event(r1, "draft", "draft"))["draft"]["sentAs"], chat(800))
        current = await self.backend.drafts.current(key)
        assert current
        self.assertEqual(current["sentRequest"], {name: params[name] for name in ("chat", "route", "workingFolder")})
        later = await self.saved({**key, "text": "new words", "baseRevision": revision})
        self.assertGreater(later, revision)
        current = await self.backend.drafts.current(key)
        assert current
        self.assertNotIn("sentAs", current)
        folder = {"folder": str(self.frame.base)}
        await self.subscribe(r1, w1, "new-chat", "draft", folder)
        await self.saved({**folder, "text": "repository", "baseRevision": None})
        self.assertEqual((await self.event(r1, "new-chat", "draft"))["draft"]["text"], "repository")

    async def test_later_read_recovers_accepted_mark_outside_read_only_and_preserves_newer_text(self) -> None:
        """drafts.accepted-recovery; drafts.newer-text"""
        key = {"chat": chat(1)}
        revision = await self.saved({**key, "text": "original", "baseRevision": None})
        params = {**key, "exchange": chat(800), "message": "original", "draft": {"revision": revision},
                  "route": {"driver": "claude", "subscription": "private", "model": "model"},
                  "workingFolder": str(self.frame.base)}
        marked = await self.backend.drafts.mark(params)
        await self.seed_exchange(chat(800), chat(1))
        r, w = await self.open()
        self.assertIsNone((await self.call(r, w, "draft.get", key))["result"])
        self.assertEqual(await self.db.execute("SELECT ongoing FROM chat_marks WHERE chat_id=%s", [chat(1)]), [(True,)])
        revision = await self.saved({**key, "text": "new text", "baseRevision": None})
        await self.backend.drafts.finish(params, marked, accepted=False)
        current = await self.backend.drafts.current(key)
        assert current
        self.assertEqual(current["revision"], revision)
        # A forged mark to an accepted Exchange in another chat is not enough to erase text.
        await self.db.execute("UPDATE drafts SET sent_as=%s,sent_request=jsonb_build_object('chat',%s::text) "
                              "WHERE chat_id=%s", [chat(800), chat(2), chat(1)])
        self.assertIsNotNone((await self.call(r, w, "draft.get", key))["result"])

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
