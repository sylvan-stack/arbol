"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_space_watch as _support
from backend.test_space_watch import (
    Any,
    LocalDisk,
    Trunk,
    asyncio,
    chat,
    mock,
    signal,
    until,
)


class Watching(_support.Watching):


# TEST-TIER-BEGIN tests/backend/test_space_watch.py::Watching.test_shutdown_cancels_measurement_utility_and_watcher_but_keeps_a_live_producer
    async def test_shutdown_cancels_measurement_utility_and_watcher_but_keeps_a_live_producer(self) -> None:
        """measurement.shutdown; measurement.utility-reaped; measurement.no-trunk-signal"""
        service = self.backend.measurements
        producer = await Trunk.make(self.frame, chat(1))
        program = self.frame.bin / "space-du"
        program.write_text("#!/bin/sh\nexec /bin/sleep 30\n")
        program.chmod(0o700)
        service.disk = LocalDisk(program=str(program))
        children: list[asyncio.subprocess.Process] = []
        create = asyncio.create_subprocess_exec
        async def captured(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
            child = await create(*args, **kwargs)
            if args[0] == str(program):
                children.append(child)
            return child
        with mock.patch("arbol_backend.storage.asyncio.create_subprocess_exec", side_effect=captured):
            caller = asyncio.create_task(service.measure({}))
            await until(lambda: bool(children))
            await asyncio.wait_for(service.close(), 0.5)
            with self.assertRaises(asyncio.CancelledError):
                await caller
        self.assertEqual(children[0].returncode, -signal.SIGKILL)
        self.assertIsNone(producer.child.poll())
        assert service.watcher
        self.assertTrue(service.watcher.done())
# TEST-TIER-END tests/backend/test_space_watch.py::Watching.test_shutdown_cancels_measurement_utility_and_watcher_but_keeps_a_live_producer

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_space_watch.py::Watching.test_thresholds_reach_two_windows_and_late_snapshot_preserving_since_until_confirmed_clear
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: measurement.thresholds; measurement.space-windows; measurement.urgent; measurement.warning-clear
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_space_watch.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_thresholds_reach_two_windows_and_late_snapshot_preserving_since_until_confirmed_clear(self) -> None:
#         """measurement.thresholds; measurement.space-windows; measurement.urgent; measurement.warning-clear"""
#         clients = [await self.open(), await self.open()]
#         for r, w in clients:
#             await self.subscribe(r, w, "attention", "attention")
#         disk = self.backend.measurements.disk
#         since = None
#         for free, warning in ((int(8.6*GIB), "low"), (2*GIB-1, "urgent"), (2*GIB, "low"), (10*GIB-1, "low")):
#             with mock.patch.object(disk, "get", return_value={"freeBytes": free, "dataFolderBytes": int(3.5*GIB)}):
#                 report = (await self.call(*clients[0], "health.measure"))["result"]
#             self.assertEqual(report["warning"], warning)
#             for r, _ in clients:
#                 item = (await self.event(r, "attention", "opened"))["item"]
#                 self.assertEqual(item["id"], "space_low")
#                 self.assertEqual(item["severity"], "urgent" if warning == "urgent" else "warning")
#                 self.assertIn("3.5 GiB", item["message"])
#                 self.assertIn(self.frame.record["name"], item["message"])
#                 if since is None:
#                     since = item["since"]
#                     self.assertIn("8.6 GiB", item["message"])
#                 self.assertEqual(item["since"], since)
#         r, w = await self.open()
#         self.assertEqual((await self.subscribe(r, w, "late", "attention"))["items"][0]["since"], since)
#         with mock.patch.object(disk, "get", return_value={"freeBytes": 10*GIB, "dataFolderBytes": GIB}):
#             report = await self.backend.measurements.measure({})
#         self.assertNotIn("warning", report)
#         for r, _ in clients:
#             self.assertEqual((await self.event(r, "attention", "closed"))["id"], "space_low")
#         self.assertNotIn("space_low", self.backend.chats.attention.items)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_space_watch.py::Watching.test_missing_sizes_are_honest_and_unknown_free_space_never_clears_an_earlier_warning
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: measurement.partial-attention; measurement.no-false-clear
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_space_watch.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_missing_sizes_are_honest_and_unknown_free_space_never_clears_an_earlier_warning(self) -> None:
#         """measurement.partial-attention; measurement.no-false-clear"""
#         original = Session.execute
#         async def missing(session: Session, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
#             return [] if sql.startswith("SELECT pg_database_size") else await original(session, sql, params)
#         with mock.patch.object(Session, "execute", missing), mock.patch.object(self.backend.measurements.disk, "get", return_value={"freeBytes": GIB}):
#             report = await self.backend.measurements.measure({})
#         self.assertEqual(report["warning"], "urgent")
#         item = self.backend.chats.attention.items["space_low"]
#         self.assertIn("Data folder size is unavailable", item["message"])
#         self.assertIn("Database sizes are unavailable", item["message"])
#         with mock.patch.object(self.backend.measurements.disk, "get", return_value={"diskProblem": "Private unavailable fixture"}):
#             report = await self.backend.measurements.measure({})
#         self.assertNotIn("warning", report)
#         self.assertNotIn("freeBytes", report)
#         self.assertEqual(self.backend.chats.attention.items["space_low"], item)
#         with mock.patch.object(self.backend.measurements.disk, "get", return_value={"freeBytes": 11*GIB}):
#             await self.backend.measurements.measure({})
#         self.assertNotIn("space_low", self.backend.chats.attention.items)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_space_watch.py::Watching.test_injected_awake_300_schedule_excludes_sleep_and_wall_clock_and_requests_do_not_postpone_it
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: measurement.awake-300; measurement.sleep-excluded; measurement.wall-clock; measurement.request-keeps-schedule
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_space_watch.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_injected_awake_300_schedule_excludes_sleep_and_wall_clock_and_requests_do_not_postpone_it(self) -> None:
#         """measurement.awake-300; measurement.sleep-excluded; measurement.wall-clock; measurement.request-keeps-schedule"""
#         self.assertEqual(INTERVAL, 300)
#         clock = Clock()
#         service = Measurements(self.backend.health, self.backend.roots, Registry(), clock=clock, poll=0.005)
#         calls: list[float] = []
#         async def collect() -> Params:
#             calls.append(clock())
#             return {"measuredAt": "2026-10-27T12:00:00.000Z", "server": {"ok": True}, "roots": []}
#         try:
#             with mock.patch.object(service, "collect", collect):
#                 service.start()
#                 await until(lambda: len(calls) == 1)
#                 with mock.patch("time.time", return_value=10000000000):
#                     await asyncio.sleep(0.025)  # A Mac-sleep/wall-clock jump advances no injected awake time.
#                 self.assertEqual(calls, [0])
#                 clock.value = 299
#                 await asyncio.sleep(0.025)
#                 self.assertEqual(calls, [0])
#                 await service.measure({})
#                 self.assertEqual(calls, [0, 299])
#                 clock.value = 300
#                 await until(lambda: len(calls) == 3)
#                 clock.value = 3600
#                 await until(lambda: len(calls) == 4)
#                 await asyncio.sleep(0.025)
#                 self.assertEqual(calls, [0, 299, 300, 3600])
#         finally:
#             await service.close()
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_space_watch.py::Watching.test_actual_database_return_refreshes_space_without_delaying_return_snapshots
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: measurement.return-refresh; measurement.return-snapshot-isolation; measurement.callback-composition
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_space_watch.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_actual_database_return_refreshes_space_without_delaying_return_snapshots(self) -> None:
#         """measurement.return-refresh; measurement.return-snapshot-isolation; measurement.callback-composition"""
#         clients = [await self.open(), await self.open()]
#         for r, w in clients:
#             await self.subscribe(r, w, "attention", "attention")
#             await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
#         service = self.backend.measurements
#         with mock.patch.object(service.disk, "get", return_value={"freeBytes": GIB, "dataFolderBytes": 3*GIB}):
#             await service.measure({})
#         for r, _ in clients:
#             await self.event(r, "attention", "opened")
#         since = self.backend.chats.attention.items["space_low"]["since"]
#         await offline(self.cluster)
#         await self.backend.health.probe()
#         await service.measure({})
#         self.assertEqual(self.backend.chats.attention.items["space_low"]["since"], since)
#         entered, release = asyncio.Event(), asyncio.Event()
#         async def delayed(*args: Any) -> Params:
#             entered.set()
#             await release.wait()
#             return {"freeBytes": 12*GIB, "dataFolderBytes": 3*GIB}
#         with mock.patch.object(service.disk, "get", delayed):
#             await online(self.cluster)
#             await self.backend.health.probe()
#             await asyncio.wait_for(entered.wait(), 2)
#             await asyncio.gather(*list(self.backend.health.recoveries))
#             self.assertIsNotNone(service.task)
#             assert service.task
#             self.assertFalse(service.task.done())
#             for r, _ in clients:
#                 self.assertEqual((await self.event(r, "attention", "closed"))["id"], "database_unreachable")
#                 self.assertEqual((await self.event(r, "chat", "snapshot"))["chat"]["chat"], chat(1))
#             release.set()
#             await service.task
#         for r, _ in clients:
#             self.assertEqual((await self.event(r, "attention", "closed"))["id"], "space_low")
#         self.assertFalse(self.backend.database.away)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_space_watch.py::Watching.test_measurement_started_before_an_outage_gets_one_fresh_pass_after_return
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: measurement.return-after-old-read; measurement.return-epoch; measurement.return-coalescing
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_space_watch.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_measurement_started_before_an_outage_gets_one_fresh_pass_after_return(self) -> None:
#         """measurement.return-after-old-read; measurement.return-epoch; measurement.return-coalescing"""
#         service = self.backend.measurements
#         entered, release, sizes_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
#         original = Session.execute
#         async def observed(session: Session, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
#             rows = await original(session, sql, params)
#             if sql.startswith("SELECT pg_database_size"):
#                 sizes_done.set()
#             return rows
#         calls = 0
#         async def disk(*args: Any) -> Params:
#             nonlocal calls
#             calls += 1
#             if calls == 1:
#                 entered.set()
#                 await release.wait()
#                 return {"freeBytes": GIB, "dataFolderBytes": 3*GIB}
#             return {"freeBytes": 12*GIB, "dataFolderBytes": 3*GIB}
#         with mock.patch.object(service.disk, "get", disk), mock.patch.object(Session, "execute", observed):
#             old = asyncio.create_task(service.measure({}))
#             await asyncio.wait_for(entered.wait(), 2)
#             await asyncio.wait_for(sizes_done.wait(), 2)
#             previous = service.task
#             await offline(self.cluster)
#             await self.backend.health.probe()
#             await online(self.cluster)
#             await self.backend.health.probe()
#             await until(lambda: service.return_waiter is not None)
#             waiter = service.return_waiter
#             release.set()
#             self.assertEqual((await old)["warning"], "urgent")
#             assert waiter
#             await waiter
#             self.assertIsNot(service.task, previous)
#             assert service.task
#             report = await service.task
#             self.assertEqual(report["freeBytes"], 12*GIB)
#             self.assertNotIn("warning", report)
#             self.assertNotIn("space_low", self.backend.chats.attention.items)
#             self.assertEqual(calls, 2)
# LOW-TIER-SOURCE-END
# LOW-TIER-END
