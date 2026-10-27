"""In-process awake clocks and real private managers qualify causal stuck-force notes."""

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
from arbol_backend.bridge import Error, Params  # noqa: E402
from arbol_backend.dispatch import Entry  # noqa: E402
from arbol_backend.stuck import LOOK, UNCHANGED, Stuck, awake  # noqa: E402
from backend.discovery_support import calls, configure, install  # noqa: E402
from backend.live_support import Trunk, now  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class Outside(WindowFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.backend.stuck.close()
        if self.backend.discovery.task:
            await self.backend.discovery.task
        await asyncio.gather(*self.backend.listings.tasks.values())
        self.clock = Clock()
        self.backend.stuck = Stuck(self.backend.identity, self.backend.listings, self.backend.controls,
            self.backend.notes, self.backend.chats.attention, clock=self.clock, poll=0.005)
        self.backend.listings.on_failed = self.backend.stuck.failed
        self.own = self.backend.identity.root
        self.trunk = await Trunk.make(self.frame, chat(1))
        await self.trunk.accept(self.db)
        self.row: Params = {"root": self.own, "exchange": self.trunk.exchange, "chat": chat(1),
            "trunk": "trivial", "build": "0", "state": "running", "process": {**self.trunk.value["process"], "alive": True},
            "signsOfLife": {"heartbeat": 41, "waitingFor": "driver", "since": now()}}
        self.behavior: dict[str, Any] = {self.own: {"force": {"output": self.reply("interrupted")}}}
        install(self.frame, self.behavior)
        self.configure()

    def reply(self, ended: str) -> Params:
        return {"root": self.own, "exchange": self.trunk.exchange, "ended": ended, "forced": True}

    def configure(self) -> None:
        self.behavior[self.own]["list"] = {"output": {"root": self.own, "exchanges": [self.row], "unreadable": []}}
        configure(self.frame, self.behavior)

    async def look(self, at: float, *, heartbeat: int | None = None) -> None:
        self.clock.value = at
        if heartbeat is not None:
            self.row["signsOfLife"]["heartbeat"] = heartbeat
        self.configure()
        await self.backend.stuck.check_once()

    async def forced(self) -> None:
        await asyncio.gather(*self.backend.stuck.forces.values())
        if self.backend.notes.worker:
            await self.backend.notes.worker

    def stops(self, *, force: bool | None = None) -> list[Params]:
        rows = calls(self.frame, kind="stop")
        return [row for row in rows if force is None or ("--force" in row["args"]) == force]

    async def started(self, count: int, *, force: bool | None = None) -> list[Params]:
        async with asyncio.timeout(3):
            while len(rows := self.stops(force=force)) < count:
                await asyncio.sleep(0.01)
        return rows

    async def test_exact_0_30_60_90_force_and_note_uses_decision_time(self) -> None:
        """stuck.awake-30-90; stuck.force-route; stuck.decision-time; stuck.note"""
        self.assertEqual((LOOK, UNCHANGED), (30, 90))
        for at in (0, 30, 60, 89):
            await self.look(at)
            self.assertEqual(self.stops(), [])
        with mock.patch("arbol_backend.stuck.now", return_value="2026-10-27T03:04:05.000Z"):
            await self.look(90)
        await self.forced()
        self.assertEqual(len(self.stops(force=True)), 1)
        self.assertEqual(self.stops()[0]["args"], ["--root", self.own, "stop", "--force", self.trunk.exchange])
        note = json.loads((self.frame.root/"notes"/(self.trunk.exchange+".json")).read_bytes())
        self.assertEqual((note["kind"], note["at"]), ("ended_stuck", "2026-10-27T03:04:05.000Z"))
        await self.look(120)
        await self.forced()
        self.assertEqual(len(self.stops(force=True)), 1)

    async def test_advancing_heartbeat_never_forces_for_any_wait_and_changed_heartbeat_starts_again(self) -> None:
        """stuck.heartbeat-progress; stuck.waiting-is-not-stuck; stuck.reset"""
        for index, waiting in enumerate(("answer", "tool", "driver", "small-call", "database", "future-wait")):
            self.row["signsOfLife"]["waitingFor"] = waiting
            await self.look(index*90, heartbeat=42+index)
            await self.look(index*90+89)
            self.assertEqual(self.stops(), [])
        await self.look(6*90, heartbeat=100)
        await self.look(6*90+89)
        self.assertEqual(self.stops(), [])
        await self.look(6*90+90)
        await self.forced()
        self.assertEqual(len(self.stops(force=True)), 1)

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

    async def test_scheduler_uses_awake_time_and_ignores_wall_clock_or_time_asleep(self) -> None:
        """stuck.sleep-excluded; stuck.scheduler; stuck.native-clock"""
        with mock.patch("arbol_backend.stuck.time.clock_gettime", return_value=12.5) as read:
            self.assertEqual(awake(), 12.5)
            read.assert_called_once_with(getattr(time, "CLOCK_UPTIME_RAW", time.CLOCK_MONOTONIC))
        self.backend.stuck.start()
        async with asyncio.timeout(2):
            while not calls(self.frame, kind="list"):
                await asyncio.sleep(0.01)
        with mock.patch("arbol_backend.stuck.time.time", return_value=time.time()+86400):
            await asyncio.sleep(0.08)  # The awake clock did not advance while wall time jumped.
        self.assertEqual(len(calls(self.frame, kind="list")), 1)
        self.assertFalse(self.stops())
        for count, at in enumerate((30, 60), 2):
            self.clock.value = at
            async with asyncio.timeout(2):
                while len(calls(self.frame, kind="list")) < count:
                    await asyncio.sleep(0.01)
        self.assertFalse(self.stops())
        self.clock.value = 90
        await self.started(1, force=True)
        await self.forced()
        self.assertEqual(len(self.stops(force=True)), 1)

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

    async def test_pending_manual_interrupted_reply_is_not_mislabeled_as_stuck_force(self) -> None:
        """stuck.manual-stop-cause; stuck.no-false-note"""
        self.behavior[self.own]["stop"] = {"sleep": 0.15, "output": self.reply("interrupted")}
        self.configure()
        await self.look(0)
        manual = asyncio.create_task(self.backend.controls.stop({"exchange": self.trunk.exchange}))
        await self.started(1, force=False)
        await self.look(90)
        self.assertEqual(await manual, {"ended": "interrupted"})
        await self.forced()
        self.assertFalse(self.stops(force=True))
        self.assertFalse((self.frame.root/"notes"/(self.trunk.exchange+".json")).exists())

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

    async def test_future_root_refusal_named_not_stuck_does_not_trigger_another_user_stop(self) -> None:
        """stuck.refusal-is-not-internal-cancel"""
        self.behavior[self.own]["force"] = {"sleep": 0.15, "status": 1,
            "output": {"error": {"code": "not_stuck", "message": "A future manager refusal."}}}
        self.configure()
        await self.look(0)
        await self.look(90)
        await self.started(1, force=True)
        with self.assertRaises(Error) as caught:
            await self.backend.controls.stop({"exchange": self.trunk.exchange})
        self.assertEqual(caught.exception.wire(), {"code": "not_stuck", "source": "root-manager", "message": "A future manager refusal."})
        await self.forced()
        self.assertEqual(len(self.stops()), 1)
        self.assertFalse((self.frame.root/"notes"/(self.trunk.exchange+".json")).exists())

    async def test_every_live_candidate_state_and_only_interrupted_force_gets_note(self) -> None:
        """stuck.candidate-states; stuck.true-force-end"""
        note_calls = 0
        for index, (state, ended) in enumerate((("accepting", "interrupted"), ("running", "completed"),
            ("ending", "failed"), ("running", "cancelled"), ("running", "saved"), ("running", "none")), 1):
            if index > 1:
                self.trunk = await Trunk.make(self.frame, chat(index))
                await self.trunk.accept(self.db)
            self.row.update(exchange=self.trunk.exchange, chat=chat(index), state=state,
                process={**self.trunk.value["process"], "alive": True})
            if state == "ending":
                self.row["end"] = {"state": "failed", "at": now()}
            else:
                self.row.pop("end", None)
            self.behavior[self.own]["force"] = {"output": self.reply(ended)}
            await self.look(0)
            await self.look(90)
            await self.forced()
            exists = (self.frame.root/"notes"/(self.trunk.exchange+".json")).exists()
            self.assertEqual(exists, ended == "interrupted")
            note_calls += ended == "interrupted"
        self.assertEqual(len(self.stops(force=True)), 6)
        self.assertEqual(note_calls, 1)

    async def test_foreign_frozen_work_is_discovered_but_never_automatically_forced(self) -> None:
        """stuck.own-root-only"""
        other = {**self.row, "root": "t2"}
        for at in (0, 30, 60, 90, 180):
            self.clock.value = at
            self.backend.stuck.observe("t2", {"exchanges": [other], "unreadable": []})
        await self.forced()
        self.assertFalse(self.stops())
        self.assertFalse(self.backend.stuck.observed)

    async def test_cancelled_force_caller_keeps_actual_manager_and_later_reason_never_overlaps_it(self) -> None:
        """stuck.cancelled-caller; stuck.retained-force; stuck.force-serial"""
        self.behavior[self.own]["force"]["sleep"] = 0.3
        self.configure()
        self.backend.programs.limits["stop"] = 0.05
        await self.look(0)
        await self.look(90)
        first = (await self.started(1, force=True))[0]
        self.backend.stuck.forces[self.trunk.exchange].cancel()
        await asyncio.gather(*self.backend.stuck.forces.values(), return_exceptions=True)
        await asyncio.sleep(0.07)
        os.kill(first["pid"], 0)
        self.behavior[self.own]["force"].pop("sleep")
        self.configure()
        self.backend.programs.limits["stop"] = 0.5
        await self.look(120)
        await self.forced()
        starts = self.stops(force=True)
        finished = calls(self.frame, kind="stop", phase="finish")
        self.assertEqual(len(starts), 2)
        self.assertLessEqual(finished[0]["at"], starts[1]["at"])

    async def test_shutdown_never_signals_a_force_manager_or_the_trunk(self) -> None:
        """stuck.shutdown"""
        self.behavior[self.own]["force"]["sleep"] = 0.6
        self.configure()
        await self.look(0)
        await self.look(90)
        pid = (await self.started(1, force=True))[0]["pid"]
        before = time.monotonic()
        self.backend.stopped.set()
        await self.running
        self.assertLess(time.monotonic()-before, 0.5)
        os.kill(pid, 0)
        os.kill(self.trunk.child.pid, 0)
