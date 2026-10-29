"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_accounts as _support
from backend.test_accounts import (
    AccountFixture,
    Any,
    Listing,
    MAX_LINE,
    Path,
    ROOT,
    WindowFixture,
    asyncio,
    encode,
    install,
    json,
    subscription,
    sys,
    time,
    usage,
)


class Listing(_support.Listing):


# TEST-TIER-BEGIN tests/backend/test_accounts.py::Listing.test_capacity_is_global_across_concurrent_window_listings
    async def test_capacity_is_global_across_concurrent_window_listings(self) -> None:
        """accounts.global-capacity"""
        self.backend.accounts.capacity = asyncio.Semaphore(2)
        for driver in ("claude", "codex", "pi", "future1", "future2"):
            install(self.frame, driver, {"list": {"sleep": 0.1, "output": [subscription()]}})
        before = len(self.frame.calls())
        tasks = [asyncio.create_task(self.backend.accounts.list({})) for _ in range(3)]
        maximum = 0
        while not all(task.done() for task in tasks):
            maximum = max(maximum, sum(key[0] == "account" and child.process.poll() is None
                for key, child in self.backend.programs.running.items()))
            await asyncio.sleep(0.005)
        results = await asyncio.gather(*tasks)
        self.assertTrue(all(len(result["drivers"]) == 5 for result in results))
        self.assertEqual(maximum, 2)
        self.assertEqual(len(self.driver_calls(after=before)), 5)
# TEST-TIER-END tests/backend/test_accounts.py::Listing.test_capacity_is_global_across_concurrent_window_listings
