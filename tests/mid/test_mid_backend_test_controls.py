"""Commented mid-tier selections; see MID_TIER.md before restoring a case."""

# Restore the needed imports and class header only for an explicit testing task.
# import backend.test_controls as _support
# from backend.test_controls import (
#     Any,
#     Params,
#     Path,
#     ROOT,
#     Stopping,
#     WindowFixture,
#     asyncio,
#     sys,
# )


# class Stopping(_support.Stopping):
# TEST-TIER-DISABLED-BEGIN tests/backend/test_controls.py::Stopping.test_shared_windows_stopping_until_real_end_and_exact_result
#     async def test_shared_windows_stopping_until_real_end_and_exact_result(self) -> None:
#         """stop.shared; stop.confirmed-end; stop.no-fabricated-save"""
#         trunk = await Trunk.make(self.frame, chat(1))
#         await trunk.accept(self.db)
#         self.configure(trunk.exchange, sleep=0.15)
#         windows = [await self.open(), await self.open()]
#         for index, (r, w) in enumerate(windows):
#             await self.subscribe(r, w, str(index), "chat", {"chat": chat(1)})
#             await self.event(r, str(index), "exchange")
#         for index, (_, w) in enumerate(windows):
#             await self.send(w, {"type": "call", "id": "stop"+str(index), "method": "exchange.stop", "params": {"exchange": trunk.exchange}})
#         for r, _ in windows:
#             status = await self.until(r, lambda value: value["type"] == "event"
#                 and value.get("event", {}).get("exchange", {}).get("state") == "stopping")
#             self.assertEqual(status["event"]["exchange"]["exchange"], trunk.exchange)
#         results = [await self.until(r, lambda value: value["type"] == "reply") for r, _ in windows]
#         self.assertEqual([reply["result"] for reply in results], [{"ended": "cancelled"}]*2)
#         calls = self.calls()
#         self.assertEqual(len(calls), 1)
#         self.assertEqual(calls[0]["args"], ["--root", self.backend.identity.root, "stop", trunk.exchange])
#         self.assertEqual(calls[0]["pid"], calls[0]["pgid"])
#         self.assertEqual(await self.db.execute("SELECT state FROM exchanges WHERE id=%s", [trunk.exchange]), [("open",)])
#         self.assertIn(trunk.exchange, self.backend.live.stopping)
#         trunk.end("cancelled")
#         r, _ = windows[0]
#         ended = await self.until(r, lambda value: value["type"] == "event" and value.get("event", {}).get("exchange", {}).get("state") == "ending")
#         self.assertEqual(ended["event"]["exchange"]["end"]["state"], "cancelled")
#         self.assertNotIn(trunk.exchange, self.backend.live.stopping)
# TEST-TIER-DISABLED-END tests/backend/test_controls.py::Stopping.test_shared_windows_stopping_until_real_end_and_exact_result

# TEST-TIER-DISABLED-BEGIN tests/backend/test_controls.py::Stopping.test_waits_for_shared_dispatch_and_retained_start_then_stops_once
#     async def test_waits_for_shared_dispatch_and_retained_start_then_stops_once(self) -> None:
#         """stop.wait-start; stop.production-limits"""
#         self.assertEqual((START_WAIT, STOP_WAIT, LIMITS["stop"]), (120, 90, 90))
#         exchange = chat(810)
#         self.configure(exchange, sleep=0.22)
#         self.backend.programs.limits["start"] = 0.03
#         start = asyncio.create_task(self.backend.programs.call("arbol-root", ["start", "--exchange", exchange], kind="start"))
#         await self.wait_call("start")
#         with self.assertRaises(Refused):
#             await start
#         async def dispatch() -> Params:
#             await asyncio.sleep(0.08)
#             return {}
#         pending = asyncio.create_task(dispatch())
#         self.backend.dispatch.entries[exchange] = Entry("private", chat=chat(1), task=pending)
#         self.configure(exchange)
#         result = asyncio.create_task(self.backend.controls.stop({"exchange": exchange}))
#         await asyncio.sleep(0.06)
#         self.assertEqual(self.calls(), [])
#         self.assertFalse(result.done())
#         self.assertEqual(await result, {"ended": "cancelled"})
#         self.assertEqual(len(self.calls()), 1)
#         self.assertTrue(pending.done())
#         self.assertFalse(self.backend.dispatch.active(exchange))
# TEST-TIER-DISABLED-END tests/backend/test_controls.py::Stopping.test_waits_for_shared_dispatch_and_retained_start_then_stops_once

# TEST-TIER-DISABLED-BEGIN tests/backend/test_controls.py::Stopping.test_start_wait_expiration_never_launches_stop_or_kills_start
#     async def test_start_wait_expiration_never_launches_stop_or_kills_start(self) -> None:
#         """stop.start-wait-timeout"""
#         exchange = chat(811)
#         self.configure(exchange, sleep=0.3)
#         self.backend.programs.limits["start"] = 0.02
#         self.backend.controls.start_wait = 0.04
#         start = asyncio.create_task(self.backend.programs.call("arbol-root", ["start", "--exchange", exchange], kind="start"))
#         rows = await self.wait_call("start")
#         with self.assertRaises(Refused):
#             await start
#         pid = rows[0]["pid"]
#         with self.assertRaises(Error) as caught:
#             await self.backend.controls.stop({"exchange": exchange})
#         self.assertEqual(caught.exception.code, "no_answer")
#         self.assertEqual(self.calls(), [])
#         os.kill(pid, 0)
#         self.configure(exchange, ended="none")
#         self.backend.controls.start_wait = 0.5
#         self.assertEqual(await self.backend.controls.stop({"exchange": exchange}), {"ended": "none"})
#         self.assertNotIn(exchange, self.backend.live.stopping)
# TEST-TIER-DISABLED-END tests/backend/test_controls.py::Stopping.test_start_wait_expiration_never_launches_stop_or_kills_start

# TEST-TIER-DISABLED-BEGIN tests/backend/test_controls.py::Stopping.test_cancelled_caller_and_late_manager_never_overlap_repeated_stops
#     async def test_cancelled_caller_and_late_manager_never_overlap_repeated_stops(self) -> None:
#         """stop.shielded; stop.retained-manager; stop.repeat"""
#         exchange = chat(812)
#         self.configure(exchange, sleep=0.25)
#         self.backend.programs.limits["stop"] = 0.08
#         first = asyncio.create_task(self.backend.controls.stop({"exchange": exchange}))
#         rows = await self.wait_call()
#         first.cancel()
#         await asyncio.gather(first, return_exceptions=True)
#         with self.assertRaises(Error):
#             await self.backend.controls.stop({"exchange": exchange})
#         os.kill(rows[0]["pid"], 0)
#         self.assertEqual(len(self.calls()), 1)
#         self.configure(exchange, ended="saved")
#         self.backend.programs.limits["stop"] = 0.5
#         self.assertEqual(await self.backend.controls.stop({"exchange": exchange}), {"ended": "saved"})
#         self.assertEqual(len(self.calls()), 2)
#         self.assertNotIn(("stop", exchange), self.backend.programs.running)
# TEST-TIER-DISABLED-END tests/backend/test_controls.py::Stopping.test_cancelled_caller_and_late_manager_never_overlap_repeated_stops

# TEST-TIER-DISABLED-BEGIN tests/backend/test_controls.py::Stopping.test_all_ended_values_safe_refusals_and_mismatched_results
#     async def test_all_ended_values_safe_refusals_and_mismatched_results(self) -> None:
#         """stop.forwarding; stop.safe-errors; stop.result-identity"""
#         exchange = chat(813)
#         r, w = await self.open()
#         for ended in ("completed", "failed", "cancelled", "interrupted", "saved", "none"):
#             self.configure(exchange, ended=ended)
#             self.assertEqual((await self.call(r, w, "exchange.stop", {"exchange": exchange}))["result"], {"ended": ended})
#         outputs: list[Any] = [{"root": "another", "exchange": exchange, "ended": "none"},
#                        {"root": self.backend.identity.root, "exchange": chat(814), "ended": "none"},
#                        {"root": self.backend.identity.root, "exchange": exchange, "ended": "future"}, []]
#         for output in outputs:
#             self.configure(exchange, output=output)
#             self.assertEqual((await self.call(r, w, "exchange.stop", {"exchange": exchange}))["error"]["code"], "no_answer")
#         self.configure(exchange, output={"error": {"code": "future_refusal", "message": "Try again later."}}, status=1)
#         refusal = (await self.call(r, w, "exchange.stop", {"exchange": exchange}))["error"]
#         self.assertEqual(refusal, {"code": "future_refusal", "source": "root-manager", "message": "Try again later."})
#         self.configure(exchange, output={"error": {"code": "root_unavailable", "message": "Bearer fictional-private-value"}}, status=1)
#         self.assertNotIn("fictional-private-value", json.dumps(await self.call(r, w, "exchange.stop", {"exchange": exchange})))
#         count = len(self.calls())
#         self.assertEqual((await self.call(r, w, "exchange.stop", {"exchange": "../escape"}))["error"]["code"], "invalid_input")
#         self.assertEqual(len(self.calls()), count)
# TEST-TIER-DISABLED-END tests/backend/test_controls.py::Stopping.test_all_ended_values_safe_refusals_and_mismatched_results

# TEST-TIER-DISABLED-BEGIN tests/backend/test_controls.py::Stopping.test_shutdown_does_not_wait_for_or_signal_stop_manager
#     async def test_shutdown_does_not_wait_for_or_signal_stop_manager(self) -> None:
#         """stop.shutdown"""
#         exchange = chat(815)
#         self.configure(exchange, sleep=0.6)
#         task = asyncio.create_task(self.backend.controls.stop({"exchange": exchange}))
#         rows = await self.wait_call()
#         pid = rows[0]["pid"]
#         started = time.monotonic()
#         self.backend.stopped.set()
#         await self.running
#         self.assertLess(time.monotonic()-started, 0.5)
#         await asyncio.gather(task, return_exceptions=True)
#         os.kill(pid, 0)
#         self.assertEqual(len(self.calls()), 1)
# TEST-TIER-DISABLED-END tests/backend/test_controls.py::Stopping.test_shutdown_does_not_wait_for_or_signal_stop_manager


# Original deferred imports (restore at the required scope, never blindly at the tail).
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_controls.py:6
# import json
# TEST-TIER-IMPORTS-END tests/backend/test_controls.py:6

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_controls.py:7
# import os
# TEST-TIER-IMPORTS-END tests/backend/test_controls.py:7

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_controls.py:9
# import time
# TEST-TIER-IMPORTS-END tests/backend/test_controls.py:9

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_controls.py:17
# from arbol_backend.bridge import Error, Params  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_controls.py:17

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_controls.py:18
# from arbol_backend.controls import START_WAIT, STOP_WAIT  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_controls.py:18

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_controls.py:19
# from arbol_backend.dispatch import Entry  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_controls.py:19

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_controls.py:20
# from arbol_backend.model import Refused  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_controls.py:20

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_controls.py:21
# from arbol_backend.process import LIMITS  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_controls.py:21

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_controls.py:22
# from backend.live_support import Trunk  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_controls.py:22

# TEST-TIER-IMPORTS-BEGIN tests/backend/test_controls.py:23
# from backend.test_chat_wire import WindowFixture, chat  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_controls.py:23

raise RuntimeError("Mid-tier tests require an explicitly requested testing task; see MID_TIER.md.")
