"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_controls as _support
from backend.test_controls import (
    Any,
    Entry,
    Error,
    LIMITS,
    Params,
    Path,
    ROOT,
    Refused,
    START_WAIT,
    STOP_WAIT,
    Stopping,
    Trunk,
    WindowFixture,
    asyncio,
    chat,
    json,
    os,
    sys,
    time,
)


class Stopping(_support.Stopping):


# TEST-TIER-BEGIN tests/backend/test_controls.py::Stopping.test_start_wait_expiration_never_launches_stop_or_kills_start
    async def test_start_wait_expiration_never_launches_stop_or_kills_start(self) -> None:
        """stop.start-wait-timeout"""
        exchange = chat(811)
        self.configure(exchange, sleep=0.3)
        self.backend.programs.limits["start"] = 0.02
        self.backend.controls.start_wait = 0.04
        start = asyncio.create_task(self.backend.programs.call("arbol-root", ["start", "--exchange", exchange], kind="start"))
        rows = await self.wait_call("start")
        with self.assertRaises(Refused):
            await start
        pid = rows[0]["pid"]
        with self.assertRaises(Error) as caught:
            await self.backend.controls.stop({"exchange": exchange})
        self.assertEqual(caught.exception.code, "no_answer")
        self.assertEqual(self.calls(), [])
        os.kill(pid, 0)
        self.configure(exchange, ended="none")
        self.backend.controls.start_wait = 0.5
        self.assertEqual(await self.backend.controls.stop({"exchange": exchange}), {"ended": "none"})
        self.assertNotIn(exchange, self.backend.live.stopping)
# TEST-TIER-END tests/backend/test_controls.py::Stopping.test_start_wait_expiration_never_launches_stop_or_kills_start

# TEST-TIER-BEGIN tests/backend/test_controls.py::Stopping.test_cancelled_caller_and_late_manager_never_overlap_repeated_stops
    async def test_cancelled_caller_and_late_manager_never_overlap_repeated_stops(self) -> None:
        """stop.shielded; stop.retained-manager; stop.repeat"""
        exchange = chat(812)
        self.configure(exchange, sleep=0.25)
        self.backend.programs.limits["stop"] = 0.08
        first = asyncio.create_task(self.backend.controls.stop({"exchange": exchange}))
        rows = await self.wait_call()
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        with self.assertRaises(Error):
            await self.backend.controls.stop({"exchange": exchange})
        os.kill(rows[0]["pid"], 0)
        self.assertEqual(len(self.calls()), 1)
        self.configure(exchange, ended="saved")
        self.backend.programs.limits["stop"] = 0.5
        self.assertEqual(await self.backend.controls.stop({"exchange": exchange}), {"ended": "saved"})
        self.assertEqual(len(self.calls()), 2)
        self.assertNotIn(("stop", exchange), self.backend.programs.running)
# TEST-TIER-END tests/backend/test_controls.py::Stopping.test_cancelled_caller_and_late_manager_never_overlap_repeated_stops
