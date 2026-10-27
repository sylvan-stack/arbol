"""Private boundaries shared by the chat read/update implementation (BKD-D30)."""

from __future__ import annotations

import asyncio
import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Error, Params  # noqa: E402
from arbol_backend.database import Database  # noqa: E402
from arbol_backend.metadata import Attention, inspect  # noqa: E402
from arbol_backend.model import Refused, identity, parse  # noqa: E402
from arbol_backend.process import Programs  # noqa: E402
from arbol_backend.validation import Catalogues, integer, save_paste, text  # noqa: E402
from arbol_backend.views import View  # noqa: E402
from backend.support import Cluster, Frame  # noqa: E402


class Views(unittest.IsolatedAsyncioTestCase):
    async def test_invalidation_rejects_an_older_snapshot_and_reads_coalesce(self) -> None:
        """chats.view-generation"""
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0
        state = 1
        async def load(params: Params) -> Params:
            nonlocal calls
            calls += 1
            captured = state
            entered.set()
            await release.wait()
            return {"kind": "snapshot", "state": captured}
        published: list[Params] = []
        view = View(load, lambda old, new, params: published.append(new))
        self.addAsyncCleanup(view.close)
        first = asyncio.create_task(view.snapshot({"chat": "a"}))
        await entered.wait()
        second = asyncio.create_task(view.snapshot({"chat": "a"}))
        state = 2
        view.invalidate({"chat": "a"})
        release.set()
        one, two = await asyncio.gather(first, second)
        self.assertEqual((one.event["state"], two.event["state"], calls), (2, 2, 2))
        self.assertEqual(published, [{"kind": "snapshot", "state": 2}])
        view.forget_unwatched()
        self.assertFalse(view.states)
        self.assertFalse(view.inflight)
        self.assertFalse(view.generations)

    async def test_different_chat_does_not_wait_and_late_error_is_not_logged(self) -> None:
        """chats.view-isolation"""
        entered, release = asyncio.Event(), asyncio.Event()
        async def load(params: Params) -> Params:
            if params["chat"] == "slow":
                entered.set()
                await release.wait()
                raise Refused("database_unavailable", "password=private-secret")
            return {"kind": "snapshot", "chat": params["chat"]}
        view = View(load, lambda old, new, params: None)
        self.addAsyncCleanup(view.close)
        slow = asyncio.create_task(view.snapshot({"chat": "slow"}))
        await entered.wait()
        self.assertEqual((await view.snapshot({"chat": "fast"})).event["chat"], "fast")
        slow.cancel()
        await asyncio.gather(slow, return_exceptions=True)
        release.set()
        outcome = await view.inflight[view.key({"chat": "slow"})]
        self.assertIsInstance(outcome, Error)
        self.assertNotIn("private-secret", str(outcome))


class Inputs(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.frame = Frame()
        self.selected = identity(ROOT, parse(self.frame.options()), home=self.frame.home)
        self.programs = Programs(self.selected)
        for driver in ("claude", "codex", "pi"):
            self.frame.behavior["arbol-" + driver + "-driver"] = {"output": [{"id": "private", "key": "private-secret"}]}
        self.frame.configure()
        self.catalogues = Catalogues(self.selected, self.programs)
        self.catalogues.start()
        assert self.catalogues.task
        await self.catalogues.task

    async def asyncTearDown(self) -> None:
        await self.catalogues.close()
        self.programs.close()
        self.frame.close()

    async def test_route_ids_are_known_before_any_request_effect(self) -> None:
        """chats.identifier-catalogues"""
        before = self.frame.calls()
        valid: Params = {"chat": "12345678-1234-4234-8234-123456789012", "route": {
            "driver": "claude", "subscription": "private", "model": "test", "effort": "high", "key": "ignored"}}
        result = await self.catalogues.settings(valid)
        self.assertNotIn("key", result["route"])
        self.assertEqual(self.frame.calls(), before)
        for params in ({**valid, "chat": "../../x"}, {**valid, "route": {**valid["route"], "driver": "../claude"}},
                       {**valid, "route": {**valid["route"], "subscription": "unknown"}},
                       {**valid, "route": {**valid["route"], "subscription": "-x"}}):
            with self.assertRaises(Refused) as caught:
                await self.catalogues.settings(params)
            self.assertEqual(caught.exception.code, "invalid_input")
            self.assertEqual(self.frame.calls(), before)
        self.assertEqual(self.catalogues.subscriptions["claude"], {"private"})
        self.assertNotIn("private-secret", str(self.catalogues.subscriptions))
        with self.assertRaises(Refused):
            await self.catalogues.settings({"chat": valid["chat"], "workingFolder": "relative"})
        self.assertEqual(await self.catalogues.settings({"chat": valid["chat"], "workingFolder": str(self.frame.root)}),
                         {"chat": valid["chat"], "workingFolder": str(self.frame.root)})

    async def test_input_primitives_reject_booleans_and_invalid_unicode(self) -> None:
        """chats.input-types"""
        for value in (True, 0, 201, "12"):
            with self.assertRaises(Refused):
                integer(value, 1, 200)
        for raw in ("\0", "\ud800", None):
            with self.assertRaises(Refused):
                text(raw)
        self.assertEqual(integer(12, 1, 200), 12)
        self.assertEqual(text("é🦫"), "é🦫")

    async def test_private_paste_permissions_exact_bytes_and_failure_cleanup(self) -> None:
        """chats.paste-private"""
        value = "é🦫\n" * 10000
        first = Path(save_paste(self.selected, value))
        second = Path(save_paste(self.selected, value))
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), value.encode())
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(first.parent.stat().st_mode), 0o700)
        before = set(first.parent.iterdir())
        with mock.patch("os.write", side_effect=OSError("private-secret")):
            with self.assertRaises(Refused) as caught:
                save_paste(self.selected, value)
        self.assertNotIn("private-secret", str(caught.exception))
        self.assertEqual(set(first.parent.iterdir()), before)
        self.assertEqual(first.read_bytes(), value.encode())

    async def test_paste_refuses_symlinks_and_nonprivate_folder(self) -> None:
        """chats.paste-paths"""
        target = self.frame.base / "outside"
        target.mkdir(mode=0o700)
        link = self.frame.root / "pastes"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(Refused):
            save_paste(self.selected, "x" * 10000)
        self.assertEqual(list(target.iterdir()), [])
        link.unlink()
        link.mkdir(mode=0o755)
        with self.assertRaises(Refused):
            save_paste(self.selected, "x" * 10000)
        self.assertEqual(list(link.iterdir()), [])
        os.chmod(link, 0o700)


class Schema(unittest.IsolatedAsyncioTestCase):
    async def test_exact_layout_presence_and_provenance_without_backend_ddl(self) -> None:
        """chats.layout-inspection"""
        frame = Frame()
        cluster = await asyncio.to_thread(Cluster)
        db = Database(identity(ROOT, parse(frame.options(cluster.address)), home=frame.home))
        try:
            async def layout(lineage: bool) -> bool:
                async with db.session(snapshot=True) as session:
                    return (await inspect(session, lineage=lineage)).complete
            self.assertFalse(await layout(False))
            sql = (ROOT / "tests/backend/own-layout.sql").read_text()
            await db.execute(sql)
            self.assertTrue(await layout(False))
            self.assertTrue(await layout(True))
            await db.execute("ALTER TABLE migrated_chats DROP COLUMN stale")
            self.assertTrue(await layout(False))
            self.assertFalse(await layout(True))
            await db.execute("DROP TABLE drafts")
            self.assertFalse(await layout(False))
            attention = Attention()
            attention.open("layout_incomplete", "The own layout is incomplete.")
            version = attention.topic.version
            attention.open("layout_incomplete", "The own layout is incomplete.")
            self.assertEqual(attention.topic.version, version)
            self.assertEqual(len((await attention.snapshot({})).event["items"]), 1)
            attention.close("layout_incomplete")
            self.assertFalse((await attention.snapshot({})).event["items"])
            self.assertEqual(attention.topic.version, version + 1)
            # Only the test loaded/dropped schema: the production inspector issued SELECTs alone.
        finally:
            await db.close()
            await asyncio.to_thread(cluster.close)
            frame.close()


if __name__ == "__main__":
    unittest.main()
