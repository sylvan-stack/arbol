"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_dispatch as _support
from backend.test_dispatch import (
    Any,
    Error,
    LIMITS,
    Params,
    Path,
    RETRY_SECONDS,
    ROOT,
    Refused,
    Sending,
    TOTAL_SECONDS,
    WindowFixture,
    asyncio,
    chat,
    install,
    json,
    mock,
    replace,
    save_params,
    starts,
    sys,
    time,
)


class Sending(_support.Sending):

# TEST-TIER-BEGIN tests/backend/test_dispatch.py::Sending.test_two_windows_join_one_start_conflicting_payload_refused_and_new_text_survives
    async def test_two_windows_join_one_start_conflicting_payload_refused_and_new_text_survives(self) -> None:
        """sending.shared-dispatch; sending.newer-text"""
        install(self.frame, self.cluster.address, [{"sleep": 0.15}])
        params = await self.with_draft(self.payload())
        r1, w1 = await self.open()
        r2, w2 = await self.open()
        a = asyncio.create_task(self.call(r1, w1, "chat.send", params))
        await self.wait_starts()
        b = asyncio.create_task(self.call(r2, w2, "chat.send", params))
        changed = await self.backend.drafts.save(await save_params({"chat": chat(1), "text": "and more",
            "baseRevision": params["draft"]["revision"]}))
        with self.assertRaises(Error) as caught:
            await self.execute({**params, "message": "different"})
        self.assertEqual(caught.exception.code, "invalid_input")
        results = await asyncio.gather(a, b)
        self.assertEqual(results[0]["result"], results[1]["result"])
        self.assertEqual(len(starts(self.frame)), 1)
        current = await self.backend.drafts.current({"chat": chat(1)})
        assert current
        self.assertEqual((current["text"], current["revision"]), ("and more", changed["revision"]))
# TEST-TIER-END tests/backend/test_dispatch.py::Sending.test_two_windows_join_one_start_conflicting_payload_refused_and_new_text_survives


# TEST-TIER-BEGIN tests/backend/test_dispatch.py::Sending.test_uncertain_replies_retry_after_return_and_never_overlap_active_child
    async def test_uncertain_replies_retry_after_return_and_never_overlap_active_child(self) -> None:
        """sending.retry-schedule; sending.no-concurrent-start"""
        install(self.frame, self.cluster.address, [{"sleep": 0.65, "raw": "not json"},
            {"reply": {"error": {"code": "no_answer", "message": "No line yet."}}},
            {"reply": {"error": {"code": "in_progress", "message": "Still accepting."}}}, {}])
        self.backend.programs.limits["start"] = 0.5
        self.backend.dispatch.total = 3.0
        params = await self.with_draft(self.payload())
        result = await self.execute(params)
        self.assertTrue(result["accepted"])
        rows = starts(self.frame)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(not row["collision"] for row in rows))
        self.assertGreaterEqual(float(rows[1]["at"]) - float(rows[0]["at"]), 0.64)
        ended = float((self.frame.bin / ("ended-" + params["exchange"] + "-1")).read_text())
        self.assertGreaterEqual(float(rows[2]["at"]) - ended, 0.045)
        self.assertTrue(all(row["exchange"] == params["exchange"] for row in rows))
# TEST-TIER-END tests/backend/test_dispatch.py::Sending.test_uncertain_replies_retry_after_return_and_never_overlap_active_child


# TEST-TIER-BEGIN tests/backend/test_dispatch.py::Sending.test_total_deadline_retains_active_file_and_mark_without_automatic_retry
    async def test_total_deadline_retains_active_file_and_mark_without_automatic_retry(self) -> None:
        """sending.total-bound; sending.uncertain-mark"""
        install(self.frame, self.cluster.address, [{"sleep": 0.5}])
        self.backend.dispatch.total = 0.1
        self.backend.programs.limits["start"] = 0.05
        params = await self.with_draft(self.payload())
        started = time.monotonic()
        with self.assertRaises(Error) as caught:
            await self.execute(params)
        self.assertEqual(caught.exception.code, "no_answer")
        self.assertLess(time.monotonic() - started, 0.3)
        # The deadline bounds the caller, not when the detached Python stand-in finishes importing.
        self.assertEqual(len(await self.wait_starts()), 1)
        current = await self.backend.drafts.current({"chat": chat(1)})
        assert current
        self.assertEqual(current["sentAs"], params["exchange"])
        path = self.frame.root / "requests" / (params["exchange"] + ".json")
        self.assertTrue(path.exists())
        manager = self.backend.programs.running[("start", params["exchange"])].process
        self.assertIsNone(manager.poll())
        with self.assertRaises(Error):
            await self.execute(params)
        self.assertEqual(len(starts(self.frame)), 1)
        await asyncio.wait_for(asyncio.to_thread(manager.wait), 3)
        async with asyncio.timeout(1):
            while path.exists():
                await asyncio.sleep(0.01)
        self.assertEqual(len(starts(self.frame)), 1)
        r, w = await self.open()
        self.assertIsNone((await self.call(r, w, "draft.get", {"chat": chat(1)}))["result"])
        self.backend.dispatch.total = 2.0
        self.backend.programs.limits["start"] = 0.5
        install(self.frame, self.cluster.address, [{}])
        self.assertTrue((await self.execute(params))["duplicate"])
# TEST-TIER-END tests/backend/test_dispatch.py::Sending.test_total_deadline_retains_active_file_and_mark_without_automatic_retry

# TEST-TIER-BEGIN tests/backend/test_dispatch.py::Sending.test_disconnected_caller_and_backend_shutdown_do_not_kill_mutating_start
    async def test_disconnected_caller_and_backend_shutdown_do_not_kill_mutating_start(self) -> None:
        """sending.disconnect; sending.detached-shutdown"""
        install(self.frame, self.cluster.address, [{"sleep": 0.35}])
        params = await self.with_draft(self.payload())
        caller = asyncio.create_task(self.execute(params))
        await self.wait_starts()
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertFalse(self.backend.dispatch.entries[params["exchange"]].task.done())  # type: ignore[union-attr]
        before = time.monotonic()
        self.backend.stopped.set()
        await asyncio.wait_for(self.running, 2)
        self.assertLess(time.monotonic() - before, 2)
        path = self.frame.root / "requests" / (params["exchange"] + ".json")
        self.assertTrue(path.exists())
        await asyncio.sleep(0.4)
        self.assertTrue((self.frame.bin / ("ended-" + params["exchange"] + "-0")).exists())
        self.assertEqual(await self.db.execute("SELECT count(*) FROM exchanges WHERE id=%s", [params["exchange"]]), [(1,)])
# TEST-TIER-END tests/backend/test_dispatch.py::Sending.test_disconnected_caller_and_backend_shutdown_do_not_kill_mutating_start


# TEST-TIER-BEGIN tests/backend/test_dispatch.py::Sending.test_acceptance_survives_database_cleanup_failure_and_later_read_recovers
    async def test_acceptance_survives_database_cleanup_failure_and_later_read_recovers(self) -> None:
        """sending.database-cleanup-recovery"""
        params = await self.with_draft(self.payload())
        with mock.patch.object(self.backend.drafts, "finish", side_effect=Error("database_unavailable")):
            result = await self.execute(params)
        self.assertTrue(result["accepted"])
        current = await self.backend.drafts.current({"chat": chat(1)})
        assert current
        self.assertEqual(current["sentAs"], params["exchange"])
        r, w = await self.open()
        self.assertIsNone((await self.call(r, w, "draft.get", {"chat": chat(1)}))["result"])
# TEST-TIER-END tests/backend/test_dispatch.py::Sending.test_acceptance_survives_database_cleanup_failure_and_later_read_recovers
