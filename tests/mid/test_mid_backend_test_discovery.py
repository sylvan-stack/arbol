"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_discovery as _support
from backend.test_discovery import (
    AcrossRoots,
    Any,
    CAPACITY,
    Error,
    MAX_LINE,
    Params,
    Path,
    ROOT,
    Refused,
    TOTAL,
    WindowFixture,
    asyncio,
    calls,
    chat,
    configure,
    encoded,
    install,
    json,
    mock,
    now,
    stop_params,
    sys,
    time,
)


class AcrossRoots(_support.AcrossRoots):


# TEST-TIER-BEGIN tests/backend/test_discovery.py::AcrossRoots.test_two_roots_with_same_uuid_have_separate_shared_stops_and_no_foreign_chat_reads
    async def test_two_roots_with_same_uuid_have_separate_shared_stops_and_no_foreign_chat_reads(self) -> None:
        """discovery.stop-root-identity; discovery.same-uuid; discovery.foreign-no-chat-read"""
        exchange = chat(912)
        self.behavior = {self.own: {"stop": {"sleep": 0.15}}, "t2": {"stop": {"sleep": 0.15}}}
        self.configure()
        with mock.patch.object(self.backend.controls, "notice", wraps=self.backend.controls.notice) as notice:
            tasks = [asyncio.create_task(self.backend.controls.stop(await stop_params({"exchange": exchange, **extra})))
                for extra in ({}, {}, {"root": "t2"}, {"root": "t2"})]
            await self.count(2, kind="stop")
            self.assertIn(("stop", exchange), self.backend.programs.running)
            self.assertIn(("stop", "t2:"+exchange), self.backend.programs.running)
            replies = await asyncio.gather(*tasks)
            self.assertEqual(replies, [{"ended": "cancelled"}]*4)
            self.assertEqual(notice.call_count, 2)  # Only the own-Root run looks for a chat, before/after start.
        self.assertEqual(len(calls(self.frame, kind="stop", root=self.own)), 1)
        self.assertEqual(len(calls(self.frame, kind="stop", root="t2")), 1)
        self.assertFalse(self.backend.live.stopping)
# TEST-TIER-END tests/backend/test_discovery.py::AcrossRoots.test_two_roots_with_same_uuid_have_separate_shared_stops_and_no_foreign_chat_reads


# TEST-TIER-BEGIN tests/backend/test_discovery.py::AcrossRoots.test_retained_foreign_settle_does_not_hold_own_root_and_repeats_are_serial
    async def test_retained_foreign_settle_does_not_hold_own_root_and_repeats_are_serial(self) -> None:
        """discovery.retained-root-mutation; discovery.independent-roots"""
        self.behavior = {"t2": {"settle": {"sleep": 0.3}}}
        self.configure()
        self.backend.programs.limits["settle"] = 0.05
        self.backend.settling.request("t2")
        await self.count(1, kind="settle", root="t2")
        assert self.backend.settling.queues["t2"].task
        await self.backend.settling.queues["t2"].task
        self.assertIn(("settle", "t2:t2"), self.backend.programs.running)
        self.backend.settling.request(self.own)
        assert self.backend.settling.worker
        await self.backend.settling.worker
        self.assertEqual(len(calls(self.frame, kind="settle", root=self.own)), 1)
        self.behavior["t2"]["settle"] = {}
        self.configure()
        self.backend.programs.limits["settle"] = 0.5
        self.backend.settling.request("t2")
        assert self.backend.settling.queues["t2"].task
        await self.backend.settling.queues["t2"].task
        starts = calls(self.frame, kind="settle", root="t2")
        ended = calls(self.frame, kind="settle", root="t2", phase="finish")
        self.assertEqual(len(starts), 2)
        self.assertLessEqual(ended[0]["at"], starts[1]["at"])
# TEST-TIER-END tests/backend/test_discovery.py::AcrossRoots.test_retained_foreign_settle_does_not_hold_own_root_and_repeats_are_serial
