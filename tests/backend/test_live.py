# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Multiple real socket windows follow private contract folders from their first line."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import MAX_LINE, Params  # noqa: E402
from arbol_backend.exchange_files import processes  # noqa: E402
from backend.live_support import Trunk  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class Windows(WindowFixture):
    async def lines(self, reader: asyncio.StreamReader, id: str, through: int) -> list[Params]:
        found: list[Params] = []
        while not found or found[-1]["n"] < through:
            found += (await self.event(reader, id, "lines"))["lines"]
        return found


    async def test_replacement_snapshot_and_truncated_file_restart_replay(self) -> None:
        """live.snapshot-generation; live.truncated-file"""
        trunk = await Trunk.make(self.frame, chat(1))
        await trunk.accept(self.db)
        for n in range(3):
            trunk.event("text_delta", text=str(n))
        r, w = await self.open()
        key = {"chat": chat(1)}
        await self.subscribe(r, w, "chat", "chat", key)
        self.assertEqual([line["n"] for line in await self.lines(r, "chat", 3)], [1, 2, 3])
        snapshot = await self.backend.chats.chat_view.snapshot(key)
        self.backend.chats.chat_view.topic.publish(snapshot.event, params=key)
        await self.event(r, "chat", "snapshot")
        self.assertEqual([line["n"] for line in await self.lines(r, "chat", 3)], [1, 2, 3])
        replacement = {"n": 1, "event": {"runId": trunk.exchange+".1", "type": "text", "text": "replacement"}}
        path = trunk.folder / "events.jsonl"
        path.write_text(json.dumps(replacement)+"\n")
        await self.event(r, "chat", "snapshot")
        self.assertEqual(await self.lines(r, "chat", 1), [replacement])
        replacement["event"]["text"] = "atomic replacement"  # type: ignore[index]
        temporary = path.with_suffix(".new")
        temporary.write_text(json.dumps(replacement)+"\n")
        temporary.chmod(0o600)
        temporary.replace(path)
        await self.event(r, "chat", "snapshot")
        self.assertEqual(await self.lines(r, "chat", 1), [replacement])

    async def test_outside_folder_is_announced_within_a_second_and_process_checks_are_shared(self) -> None:
        """live.outside-folder; live.shared-process-observation"""
        r, w = await self.open()
        await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
        await asyncio.sleep(0.1)
        trunk = await Trunk.make(self.frame, chat(1))
        before = time.monotonic()
        await trunk.accept(self.db)
        status = await self.event(r, "chat", "exchange")
        self.assertEqual(status["exchange"]["exchange"], trunk.exchange)
        self.assertLess(time.monotonic()-before, 1)
        count = 0
        async def observed(pids: set[int], **kwargs: Any) -> Any:
            nonlocal count
            count += 1
            return await processes(pids, **kwargs)
        with mock.patch("arbol_backend.live.processes", side_effect=observed):
            r2, w2 = await self.open()
            await self.subscribe(r2, w2, "chat2", "chat", {"chat": chat(1)})
            await self.event(r2, "chat2", "exchange")
            await asyncio.sleep(1.4)
        self.assertLessEqual(count, 2)

    async def test_replay_restart_yields_to_other_ready_work(self) -> None:
        """live.replay-restart-yields"""
        sub = mock.Mock()
        sub.active, sub.ready, sub.snapshots = True, True, 1
        order: list[str] = []
        peer: asyncio.Task[None] | None = None
        async def progress() -> None:
            order.append("peer")
        async def step(*args: Any) -> None:
            nonlocal peer
            order.append("step")
            if order == ["step"]:
                peer = asyncio.create_task(progress())
                from arbol_backend.live import Restart
                raise Restart()
            sub.active = False
        self.backend.live.ready.set()
        with mock.patch.object(self.backend.live, "step", side_effect=step):
            await self.backend.live.follow(sub)
        assert peer is not None
        await peer
        self.assertEqual(order[:3], ["step", "peer", "step"])

    async def test_atomic_record_retirement_keeps_the_subscription_through_saved_completion(self) -> None:
        """live.retired-record-subscription; live.retired-record-saved"""
        trunk = await Trunk.make(self.frame, chat(1))
        await trunk.accept(self.db)
        trunk.event("text_delta", text="Before replacement")
        r, w = await self.open()
        await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
        await self.lines(r, "chat", 1)
        opened = os.open
        retired: list[int] = []
        def raced(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            fd = opened(path, flags, *args, **kwargs)
            if path == "record.json" and not retired:
                trunk.save_record()
                self.assertEqual(os.fstat(fd).st_nlink, 0)
                retired.append(fd)
            return fd
        with mock.patch("arbol_backend.exchange_files.os.open", side_effect=raced):
            await self.backend.live.scan()
        self.assertEqual(len(retired), 1)
        self.assertNotIn(trunk.exchange, self.backend.live.unreadable)
        trunk.event("text_delta", text="After replacement")
        await self.lines(r, "chat", 2)
        trunk.end()
        await trunk.save(self.db, answer="Saved after an atomic metadata replacement")
        saved = (await self.event(r, "chat", "saved"))["exchange"]
        self.assertEqual(saved["state"], "completed")
        self.assertEqual(saved["items"][-1]["text"], "Saved after an atomic metadata replacement")

    async def test_saved_rows_follow_folder_removal_and_old_ended_folders_never_regress(self) -> None:
        """live.saved; live.row-first; live.old-ended-folder"""
        trunk = await Trunk.make(self.frame, chat(1))
        await trunk.accept(self.db)
        trunk.event("text", text="live answer")
        r, w = await self.open()
        await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
        await self.lines(r, "chat", 1)
        await trunk.save(self.db, answer="saved answer")
        saved = (await self.event(r, "chat", "saved"))["exchange"]
        self.assertEqual((saved["exchange"], saved["state"], saved["items"][-1]["text"]),
                         (trunk.exchange, "completed", "saved answer"))
        old = await Trunk.make(self.frame, chat(2))
        await old.accept(self.db)
        await old.save(self.db, remove=False)
        for n in range(2, 16):
            await self.db.execute(
                "INSERT INTO exchanges(id,chat_id,number,state,trunk,build,route,working_folder,accepted_at,ended_at) "
                "VALUES(%s,%s,%s,'completed','trivial','0','{}',%s,clock_timestamp(),clock_timestamp())",
                [chat(8000+n), chat(2), n, str(self.frame.base)])
        r2, w2 = await self.open()
        snapshot = await self.subscribe(r2, w2, "ended", "chat", {"chat": chat(2)})
        self.assertEqual(len(snapshot["exchanges"]), 12)
        self.assertNotIn(old.exchange, [row["exchange"] for row in snapshot["exchanges"]])
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(0.3):
                await self.event(r2, "ended", "exchange")

    async def test_oversized_line_and_wrapped_boundary_are_small_truthful_markers(self) -> None:
        """live.oversized-wire; live.batch-boundary"""
        trunk = await Trunk.make(self.frame, chat(1))
        await trunk.accept(self.db)
        prefix = b'{"event":{"type":"text","runId":"private","text":"'
        suffix = b'"},"n":1}\n'
        trunk.append(prefix + b"x" * MAX_LINE + suffix)
        # Fits as a file line, but not after adding its Bridge/lines wrapper.
        raw = b'{"n":2,"event":{"type":"text","runId":"private","text":"'
        raw += b"x" * (MAX_LINE-len(raw)-len(b'"}}\n')-1) + b'"}}\n'
        self.assertEqual(len(raw), MAX_LINE-1)
        trunk.append(raw)
        r, w = await self.open()
        await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
        lines = await self.lines(r, "chat", 2)
        self.assertEqual(lines, [{"n": 1, "tooLarge": True, "bytes": len(prefix)+MAX_LINE+len(suffix)},
                                {"n": 2, "tooLarge": True, "bytes": len(raw)}])

    async def test_slow_live_window_does_not_hold_other_chat_or_calls(self) -> None:
        """live.slow-window-isolation"""
        slow = await Trunk.make(self.frame, chat(1))
        good = await Trunk.make(self.frame, chat(2))
        await slow.accept(self.db)
        await good.accept(self.db)
        for _ in range(100):
            slow.event("text", text="x" * 1024 * 1024)
        good.event("text", text="other chat")
        bad_reader, bad_writer = await self.open()
        await self.subscribe(bad_reader, bad_writer, "slow", "chat", {"chat": chat(1)})
        await self.event(bad_reader, "slow", "exchange")
        r, w = await self.open()
        before = time.monotonic()
        await self.subscribe(r, w, "good", "chat", {"chat": chat(2)})
        self.assertEqual((await self.lines(r, "good", 1))[0]["event"]["text"], "other chat")
        reply = await self.call(r, w, "root.get")
        self.assertTrue(reply["result"]["layoutComplete"])
        self.assertLess(time.monotonic()-before, 0.5)
        async with asyncio.timeout(8):
            while any(sub.id == "slow" for sub in self.backend.chats.chat_view.topic.listeners):
                await asyncio.sleep(0.05)
        self.assertTrue(any(sub.id == "good" for sub in self.backend.chats.chat_view.topic.listeners))
# Archived complete imports; restore needed names in their original scope, not at this file tail.
