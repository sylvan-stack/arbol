"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_stuck as _support
from backend.test_stuck import (
    Any,
    Clock,
    Entry,
    Error,
    LOOK,
    Outside,
    Params,
    Path,
    ROOT,
    Stuck,
    Trunk,
    UNCHANGED,
    WindowFixture,
    asyncio,
    awake,
    calls,
    chat,
    configure,
    install,
    json,
    mock,
    now,
    os,
    sys,
    time,
)


class Outside(_support.Outside):


# TEST-TIER-BEGIN tests/backend/test_stuck.py::Outside.test_process_identity_failed_look_and_unreadable_record_reset_proof
    async def test_process_identity_failed_look_and_unreadable_record_reset_proof(self) -> None:
        """stuck.identity; stuck.failed-look; stuck.unreadable"""
        await self.look(0)
        self.row["process"]["startedAt"] = "2026-10-27T03:00:00.000Z"
        await self.look(60)
        await self.look(90)
        self.assertEqual(self.stops(), [])
        self.behavior[self.own]["list"] = {"raw": "not JSON"}
        configure(self.frame, self.behavior)
        self.clock.value = 120
        await self.backend.stuck.check_once()
        self.assertFalse(self.backend.stuck.observed)
        await self.look(150)
        self.behavior[self.own]["list"] = {"output": {"root": self.own, "exchanges": [], "unreadable": [self.trunk.exchange]}}
        configure(self.frame, self.behavior)
        self.clock.value = 180
        await self.backend.stuck.check_once()
        self.assertFalse(self.backend.stuck.observed)
        await self.look(210)
        await self.look(299)
        self.assertEqual(self.stops(), [])
        await self.look(300)
        await self.forced()
        self.assertEqual(len(self.stops(force=True)), 1)
# TEST-TIER-END tests/backend/test_stuck.py::Outside.test_process_identity_failed_look_and_unreadable_record_reset_proof


# TEST-TIER-BEGIN tests/backend/test_stuck.py::Outside.test_fresh_heartbeat_after_waiting_for_uncertain_manual_stop_cancels_force
    async def test_fresh_heartbeat_after_waiting_for_uncertain_manual_stop_cancels_force(self) -> None:
        """stuck.revalidate-after-stop; stuck.healthy-queue-cancel"""
        self.behavior[self.own]["stop"] = {"sleep": 0.2, "status": 1,
            "output": {"error": {"code": "no_answer", "message": "No confirmed outcome."}}}
        self.configure()
        await self.look(0)
        manual = asyncio.create_task(self.backend.controls.stop({"exchange": self.trunk.exchange}))
        await self.started(1, force=False)
        await self.look(90)
        self.clock.value = 100
        self.row["signsOfLife"]["heartbeat"] = 42
        self.configure()
        await asyncio.gather(manual, return_exceptions=True)
        await self.forced()
        self.assertFalse(self.stops(force=True))
        self.assertFalse((self.frame.root/"notes"/(self.trunk.exchange+".json")).exists())
        await self.look(190)
        await self.forced()
        self.assertEqual(len(self.stops(force=True)), 1)
# TEST-TIER-END tests/backend/test_stuck.py::Outside.test_fresh_heartbeat_after_waiting_for_uncertain_manual_stop_cancels_force


# TEST-TIER-BEGIN tests/backend/test_stuck.py::Outside.test_user_stop_joining_cancelled_force_continues_as_an_ordinary_stop
    async def test_user_stop_joining_cancelled_force_continues_as_an_ordinary_stop(self) -> None:
        """stuck.user-stop-after-force-cancel"""
        await self.look(0)
        async def accepting() -> Params:
            await asyncio.sleep(0.2)
            return {}
        start = asyncio.create_task(accepting())
        self.backend.dispatch.entries[self.trunk.exchange] = Entry("private", chat=chat(1), task=start)
        await self.look(90)
        key = (self.own, self.trunk.exchange)
        async with asyncio.timeout(2):
            while key not in self.backend.controls.force_tasks:
                await asyncio.sleep(0.005)
        user = asyncio.create_task(self.backend.controls.stop({"exchange": self.trunk.exchange}))
        self.clock.value = 100
        self.row["signsOfLife"]["heartbeat"] = 42
        self.configure()
        self.assertEqual(await user, {"ended": "cancelled"})
        await self.forced()
        self.assertFalse(self.stops(force=True))
        self.assertEqual(len(self.stops(force=False)), 1)
# TEST-TIER-END tests/backend/test_stuck.py::Outside.test_user_stop_joining_cancelled_force_continues_as_an_ordinary_stop
