"""Commented mid-tier selections; see MID_TIER.md before restoring a case."""

# Restore the needed imports and class header only for an explicit testing task.
# import backend.test_settling as _support
# from backend.test_settling import (
#     Params,
#     Path,
#     ROOT,
#     STANDIN,
#     Settles,
#     WindowFixture,
#     asyncio,
#     chat,
#     now,
#     shlex,
#     sys,
# )


# class Settles(_support.Settles):
# TEST-TIER-DISABLED-BEGIN tests/backend/test_settling.py::Settles.test_startup_and_requests_coalesce_one_further_pass
#     async def test_startup_and_requests_coalesce_one_further_pass(self) -> None:
#         """settle.startup; settle.coalescing; settle.production-limit"""
#         self.assertEqual(len(self.initial), 1)
#         # Startup discovery and the own-Root watcher can perform successive completed looks.
#         self.assertGreaterEqual(len(self.calls("list")), 1)
#         self.assertEqual(LIMITS["settle"], 120)
#         self.configure(settle_sleep=0.15)
#         for _ in range(20):
#             self.backend.settling.request()
#         await self.count(2)
#         for _ in range(20):
#             self.backend.settling.request()
#         await self.done()
#         self.assertEqual(len(self.calls()), 3)  # startup, current pass, exactly one further pass
#         self.assertTrue(all(row["pid"] == row["pgid"] for row in self.calls()))
#         self.assertTrue(all(row["args"] == ["--root", self.backend.identity.root, "settle"] for row in self.calls()))
# TEST-TIER-DISABLED-END tests/backend/test_settling.py::Settles.test_startup_and_requests_coalesce_one_further_pass

# TEST-TIER-DISABLED-BEGIN tests/backend/test_settling.py::Settles.test_database_failure_runs_no_settle_and_waits_for_a_new_reason
#     async def test_database_failure_runs_no_settle_and_waits_for_a_new_reason(self) -> None:
#         """settle.database-gate; settle.no-timer-retry"""
#         before = len(self.calls())
#         with mock.patch.object(self.backend.database, "execute", side_effect=Refused("database_unavailable", "Private DB offline.")):
#             self.backend.settling.request()
#             await self.done()
#             await asyncio.sleep(0.12)
#             self.assertEqual(len(self.calls()), before)
#         await asyncio.sleep(0.1)
#         self.assertEqual(len(self.calls()), before)
#         self.backend.settling.request()
#         await self.done()
#         self.assertEqual(len(self.calls()), before+1)
# TEST-TIER-DISABLED-END tests/backend/test_settling.py::Settles.test_database_failure_runs_no_settle_and_waits_for_a_new_reason

# TEST-TIER-DISABLED-BEGIN tests/backend/test_settling.py::Settles.test_timeout_retains_manager_and_new_reason_waits_for_actual_exit
#     async def test_timeout_retains_manager_and_new_reason_waits_for_actual_exit(self) -> None:
#         """settle.retained-manager; settle.no-overlap"""
#         self.configure(settle_sleep=0.3)
#         self.backend.programs.limits["settle"] = 0.06
#         self.backend.settling.request()
#         rows = await self.count(2)
#         await self.done()
#         pid = rows[-1]["pid"]
#         os.kill(pid, 0)
#         await asyncio.sleep(0.04)
#         self.assertEqual(len(self.calls()), 2)
#         self.configure()
#         self.backend.programs.limits["settle"] = 0.5
#         self.backend.settling.request()
#         await asyncio.sleep(0.06)
#         self.assertEqual(len(self.calls()), 2)
#         await self.done()
#         self.assertEqual(len(self.calls()), 3)
#         self.assertNotIn(("settle", self.backend.identity.root), self.backend.programs.running)
# TEST-TIER-DISABLED-END tests/backend/test_settling.py::Settles.test_timeout_retains_manager_and_new_reason_waits_for_actual_exit

# TEST-TIER-DISABLED-BEGIN tests/backend/test_settling.py::Settles.test_only_valid_own_root_eligible_listings_request_settle
#     async def test_only_valid_own_root_eligible_listings_request_settle(self) -> None:
#         """settle.listing-reasons; settle.own-root"""
#         initial = len(self.calls())
#         for index, state in enumerate(("unaccepted", "unsaved", "interrupted"), 1):
#             self.configure(rows=[self.row(state)])
#             self.backend.settling.request_listing()
#             assert self.backend.settling.look
#             await self.backend.settling.look
#             await self.done()
#             self.assertEqual(len(self.calls()), initial+index)
#         for rows, root in (([self.row("running")], None), ([self.row("future")], None),
#                            ([self.row("interrupted")], "another"), ([{"state": "interrupted"}], None)):
#             self.configure(rows=rows, root=root)
#             self.backend.settling.request_listing()
#             assert self.backend.settling.look
#             await self.backend.settling.look
#         self.assertEqual(len(self.calls()), initial+3)
#         hex_row = {**self.row("interrupted"), "build": "af"}
#         value = {"root": self.backend.identity.root, "exchanges": [hex_row], "unreadable": []}
#         self.assertEqual(listing(value, self.backend.identity.root), [hex_row])
#         for invalid in (None, {**value, "unreadable": ["../escape"]}, {**value, "exchanges": [{**self.row("interrupted"), "root": "another"}]}):
#             with self.assertRaises(Error):
#                 listing(invalid, self.backend.identity.root)
# TEST-TIER-DISABLED-END tests/backend/test_settling.py::Settles.test_only_valid_own_root_eligible_listings_request_settle

# TEST-TIER-DISABLED-BEGIN tests/backend/test_settling.py::Settles.test_listings_do_not_overlap_and_pending_look_runs_once
#     async def test_listings_do_not_overlap_and_pending_look_runs_once(self) -> None:
#         """settle.shared-listing"""
#         before = len(self.calls("list"))
#         self.configure(list_sleep=0.15)
#         for _ in range(20):
#             self.backend.settling.request_listing()
#         await self.count(before+1, "list")
#         for _ in range(20):
#             self.backend.settling.request_listing()
#         assert self.backend.settling.look
#         await self.backend.settling.look
#         self.assertEqual(len(self.calls("list")), before+2)
# TEST-TIER-DISABLED-END tests/backend/test_settling.py::Settles.test_listings_do_not_overlap_and_pending_look_runs_once

# TEST-TIER-DISABLED-BEGIN tests/backend/test_settling.py::Settles.test_dead_folder_stays_gone_until_real_committed_rows_are_saved
#     async def test_dead_folder_stays_gone_until_real_committed_rows_are_saved(self) -> None:
#         """settle.dead-observation; settle.gone-until-saved"""
#         trunk = await Trunk.make(self.frame, chat(1))
#         await trunk.accept(self.db)
#         trunk.event("text", text="unsaved answer")
#         trunk.die()
#         row = self.row("interrupted")
#         row["exchange"] = trunk.exchange
#         self.configure(rows=[row], settle_sleep=0.4)
#         before = len(self.calls())
#         r, w = await self.open()
#         await self.subscribe(r, w, "chat", "chat", {"chat": chat(1)})
#         gone = await self.event(r, "chat", "exchange")
#         self.assertEqual(gone["exchange"]["state"], "gone")
#         await self.count(before+1)
#         self.assertEqual(await self.db.execute("SELECT state FROM exchanges WHERE id=%s", [trunk.exchange]), [("open",)])
#         await trunk.save(self.db, state="interrupted", answer="saved interrupted answer")
#         saved = await self.event(r, "chat", "saved")
#         self.assertEqual(saved["exchange"]["state"], "interrupted")
#         self.assertEqual(saved["exchange"]["items"][-1]["text"], "saved interrupted answer")
# TEST-TIER-DISABLED-END tests/backend/test_settling.py::Settles.test_dead_folder_stays_gone_until_real_committed_rows_are_saved

# TEST-TIER-DISABLED-BEGIN tests/backend/test_settling.py::Settles.test_failure_does_not_retry_and_shutdown_keeps_actual_mutation_alive
#     async def test_failure_does_not_retry_and_shutdown_keeps_actual_mutation_alive(self) -> None:
#         """settle.failure; settle.shutdown"""
#         self.configure(status=1)
#         self.backend.settling.request()
#         await self.done()
#         before = len(self.calls())
#         await asyncio.sleep(0.12)
#         self.assertEqual(len(self.calls()), before)
#         self.configure(settle_sleep=0.6)
#         self.backend.settling.request()
#         pid = (await self.count(before+1))[-1]["pid"]
#         started = time.monotonic()
#         self.backend.stopped.set()
#         await self.running
#         self.assertLess(time.monotonic()-started, 0.5)
#         os.kill(pid, 0)
# TEST-TIER-DISABLED-END tests/backend/test_settling.py::Settles.test_failure_does_not_retry_and_shutdown_keeps_actual_mutation_alive


# Original deferred imports (restore at the required scope, never blindly at the tail).
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_settling.py:6
# import os
# TEST-TIER-IMPORTS-END tests/backend/test_settling.py:6

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_settling.py:9
# import time
# TEST-TIER-IMPORTS-END tests/backend/test_settling.py:9

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_settling.py:11
# from unittest import mock
# TEST-TIER-IMPORTS-END tests/backend/test_settling.py:11

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_settling.py:17
# from arbol_backend.bridge import Error, Params  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_settling.py:17

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_settling.py:18
# from arbol_backend.model import Refused  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_settling.py:18

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_settling.py:19
# from arbol_backend.process import LIMITS  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_settling.py:19

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_settling.py:20
# from arbol_backend.settling import listing  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_settling.py:20

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_settling.py:21
# from backend.live_support import Trunk, now  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_settling.py:21

raise RuntimeError("Mid-tier tests require an explicitly requested testing task; see MID_TIER.md.")
