"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_live as _support
from backend.test_live import (
    Any,
    MAX_LINE,
    Params,
    Path,
    ROOT,
    Trunk,
    WindowFixture,
    Windows,
    asyncio,
    chat,
    json,
    mock,
    processes,
    sys,
    time,
)


class Windows(_support.Windows):
# TEST-TIER-BEGIN tests/backend/test_live.py::Windows.test_three_late_windows_get_complete_compacted_history_and_new_whole_lines
    async def test_three_late_windows_get_complete_compacted_history_and_new_whole_lines(self) -> None:
        """live.windows; live.replay; live.poll-latency"""
        trunk = await Trunk.make(self.frame, chat(1))
        await trunk.accept(self.db)
        source = [trunk.event("started", subscriptionId="private", toolVersion="fixture", driverBuild="0"),
            trunk.event("text_delta", text="a"), trunk.event("text_delta", text="b"), trunk.event("text", text="ab"),
            trunk.event("thinking_delta", text="piece"), trunk.event("thinking", text="whole"),
            trunk.event("tool_started", callId="c", name="shell", input={"command": "private"}),
            trunk.event("tool_output_delta", callId="c", text="piece"),
            trunk.event("tool_finished", callId="c", ok=True, result="whole"),
            trunk.event("text_delta", text="unfinished")]
        for n in range(11, 41):
            source.append(trunk.event("notice", code="private_notice", message=str(n), future={"shape": [1, 2]}))
        expected = [line for line in source if line["n"] not in {2, 3, 5, 8}]
        clients = []
        for index in range(3):
            reader, writer = await self.open()
            snapshot = await self.subscribe(reader, writer, "chat-"+str(index), "chat", {"chat": chat(1)})
            self.assertEqual(snapshot["exchanges"][0]["items"], [{"position": 0, "kind": "message", "role": "user", "text": "private request"}])
            self.assertEqual(await self.lines(reader, "chat-"+str(index), 40), expected)
            clients.append((reader, writer, "chat-"+str(index)))
        raw = json.dumps({"n": 41, "event": {"runId": trunk.exchange+".1", "seq": 41,
            "at": "2026-10-27T00:00:00Z", "type": "text_delta", "text": "partial becomes whole line"}}, separators=(",", ":")).encode()
        trunk.append(raw)
        reader, _, id = clients[0]
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(0.3):
                await self.event(reader, id, "lines")
        before = time.monotonic()
        trunk.append(b"\n")
        for reader, _, id in clients:
            self.assertEqual((await self.lines(reader, id, 41))[-1], json.loads(raw))
        self.assertLess(time.monotonic()-before, 0.25)
# TEST-TIER-END tests/backend/test_live.py::Windows.test_three_late_windows_get_complete_compacted_history_and_new_whole_lines

# TEST-TIER-BEGIN tests/backend/test_live.py::Windows.test_replacement_snapshot_and_truncated_file_restart_replay
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
# TEST-TIER-END tests/backend/test_live.py::Windows.test_replacement_snapshot_and_truncated_file_restart_replay

# TEST-TIER-BEGIN tests/backend/test_live.py::Windows.test_outside_folder_is_announced_within_a_second_and_process_checks_are_shared
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
# TEST-TIER-END tests/backend/test_live.py::Windows.test_outside_folder_is_announced_within_a_second_and_process_checks_are_shared

# TEST-TIER-BEGIN tests/backend/test_live.py::Windows.test_saved_rows_follow_folder_removal_and_old_ended_folders_never_regress
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
# TEST-TIER-END tests/backend/test_live.py::Windows.test_saved_rows_follow_folder_removal_and_old_ended_folders_never_regress

# TEST-TIER-BEGIN tests/backend/test_live.py::Windows.test_oversized_line_and_wrapped_boundary_are_small_truthful_markers
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
# TEST-TIER-END tests/backend/test_live.py::Windows.test_oversized_line_and_wrapped_boundary_are_small_truthful_markers

# TEST-TIER-BEGIN tests/backend/test_live.py::Windows.test_slow_live_window_does_not_hold_other_chat_or_calls
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
# TEST-TIER-END tests/backend/test_live.py::Windows.test_slow_live_window_does_not_hold_other_chat_or_calls
