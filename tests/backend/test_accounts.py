"""Actual private launcher children qualify independent, shared account listing."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from backend.account_support import install, subscription, usage  # noqa: E402
from backend.test_chat_wire import WindowFixture  # noqa: E402


class AccountFixture(WindowFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        for driver in ("claude", "codex", "pi"):
            install(self.frame, driver, {"list": {"output": [subscription(lastUsage=usage())]}})

    def driver_calls(self, *, after: int = 0) -> list[dict[str, Any]]:
        return [row for row in self.frame.calls()[after:] if row["program"].endswith("-driver")]


class Listing(AccountFixture):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.
# TEST-TIER-DISABLED-BEGIN tests/backend/test_accounts.py::Listing.test_listing_finds_new_launchers_and_only_runs_subscription_list
#     async def test_listing_finds_new_launchers_and_only_runs_subscription_list(self) -> None:
#         """accounts.launcher-inventory; accounts.list-only; accounts.driver-records"""
#         install(self.frame, "future", {"list": {"output": [subscription("future-one", state="signed_out")]}})
#         invalid = self.frame.bin / "arbol-ignored-driver"
#         invalid.write_text("not executable")
#         invalid.chmod(0o600)
#         before = len(self.frame.calls())
#         r, w = await self.open()
#         rows = (await self.call(r, w, "accounts.list"))["result"]["drivers"]
#         self.assertEqual([row["driver"] for row in rows], ["claude", "codex", "future", "pi"])
#         self.assertEqual(rows[2]["subscriptions"][0]["state"], "signed_out")
#         self.assertEqual(rows[0]["subscriptions"][0]["lastUsage"]["windows"][0]["usedPercent"], 37)
#         self.assertEqual(len(self.driver_calls(after=before)), 4)
#         self.assertTrue(all(row["args"] == ["subscriptions", "list"] for row in self.driver_calls(after=before)))
#         (self.frame.bin / "arbol-future-driver").unlink()
#         self.assertNotIn("future", [row["driver"] for row in (await self.call(r, w, "accounts.list"))["result"]["drivers"]])
# TEST-TIER-DISABLED-END tests/backend/test_accounts.py::Listing.test_listing_finds_new_launchers_and_only_runs_subscription_list

# TEST-TIER-DISABLED-BEGIN tests/backend/test_accounts.py::Listing.test_bad_private_partial_or_failed_driver_is_isolated_beside_valid_ones
#     async def test_bad_private_partial_or_failed_driver_is_isolated_beside_valid_ones(self) -> None:
#         """accounts.driver-isolation; accounts.safe-refusal; accounts.no-raw-fields"""
#         r, w = await self.open()
#         for option in ({"output": [subscription(), subscription()]}, {"output": [{"id": "minimal-only"}]},
#                        {"status": 1, "output": {"error": {"code": "future_refusal", "message": "Bearer fictional-bearer"}}},
#                        {"raw": '[{"id":"private","id":"other"}]'}, {"raw": '[NaN]'}):
#             install(self.frame, "codex", {"list": option})
#             rows = {row["driver"]: row for row in (await self.call(r, w, "accounts.list"))["result"]["drivers"]}
#             self.assertIn("subscriptions", rows["claude"])
#             self.assertIn("subscriptions", rows["pi"])
#             self.assertEqual(rows["codex"]["error"]["source"], "driver")
#             self.assertNotIn("fictional-bearer", json.dumps(rows))
# TEST-TIER-DISABLED-END tests/backend/test_accounts.py::Listing.test_bad_private_partial_or_failed_driver_is_isolated_beside_valid_ones

# TEST-TIER-DISABLED-BEGIN tests/backend/test_accounts.py::Listing.test_three_windows_share_each_driver_read_then_a_later_request_is_fresh
#     async def test_three_windows_share_each_driver_read_then_a_later_request_is_fresh(self) -> None:
#         """accounts.shared-list; accounts.fresh-list; accounts.no-vendor-poll"""
#         for driver in ("claude", "codex", "pi"):
#             install(self.frame, driver, {"list": {"sleep": 0.12, "output": [subscription()]}})
#         clients = [await self.open() for _ in range(3)]
#         before = len(self.frame.calls())
#         result = await asyncio.gather(*(self.call(r, w, "accounts.list") for r, w in clients))
#         self.assertTrue(all(row["result"] == result[0]["result"] for row in result))
#         self.assertEqual(len(self.driver_calls(after=before)), 3)
#         await self.call(*clients[0], "accounts.list")
#         self.assertEqual(len(self.driver_calls(after=before)), 6)
# TEST-TIER-DISABLED-END tests/backend/test_accounts.py::Listing.test_three_windows_share_each_driver_read_then_a_later_request_is_fresh

# TEST-TIER-DISABLED-BEGIN tests/backend/test_accounts.py::Listing.test_cancelled_listing_does_not_cancel_another_window_read
#     async def test_cancelled_listing_does_not_cancel_another_window_read(self) -> None:
#         """accounts.caller-shield; accounts.cancel-isolation"""
#         install(self.frame, "claude", {"list": {"sleep": 0.2, "output": [subscription()]}})
#         first = asyncio.create_task(self.backend.accounts.list({}))
#         async with asyncio.timeout(1):
#             while "claude" not in self.backend.accounts.raws:
#                 await asyncio.sleep(0.01)
#         second = asyncio.create_task(self.backend.accounts.list({}))
#         await asyncio.sleep(0.02)
#         first.cancel()
#         await asyncio.gather(first, return_exceptions=True)
#         result = await second
#         self.assertIn("subscriptions", result["drivers"][0])
#         self.assertEqual(len([row for row in self.driver_calls() if row["program"] == "arbol-claude-driver"]), 2)  # Startup + shared request.
# TEST-TIER-DISABLED-END tests/backend/test_accounts.py::Listing.test_cancelled_listing_does_not_cancel_another_window_read

# TEST-TIER-DISABLED-BEGIN tests/backend/test_accounts.py::Listing.test_account_deadline_keeps_other_topics_and_fast_drivers_available
#     async def test_account_deadline_keeps_other_topics_and_fast_drivers_available(self) -> None:
#         """accounts.total-bound; accounts.topic-isolation"""
#         self.backend.accounts.total = 0.15
#         install(self.frame, "codex", {"list": {"sleep": 2, "output": [subscription()]}})
#         r, w = await self.open()
#         r2, w2 = await self.open()
#         task = asyncio.create_task(self.call(r, w, "accounts.list"))
#         before = time.monotonic()
#         self.assertIn("result", await self.call(r2, w2, "subscriptions.check"))
#         self.assertLess(time.monotonic()-before, 0.1)
#         reply = await task
#         self.assertLess(time.monotonic()-before, 0.5)
#         rows = {row["driver"]: row for row in reply["result"]["drivers"]}
#         self.assertIn("subscriptions", rows["claude"])
#         self.assertIn("subscriptions", rows["pi"])
#         self.assertEqual(rows["codex"]["error"]["code"], "no_answer")
# TEST-TIER-DISABLED-END tests/backend/test_accounts.py::Listing.test_account_deadline_keeps_other_topics_and_fast_drivers_available

# TEST-TIER-DISABLED-BEGIN tests/backend/test_accounts.py::Listing.test_capacity_is_global_across_concurrent_window_listings
#     async def test_capacity_is_global_across_concurrent_window_listings(self) -> None:
#         """accounts.global-capacity"""
#         self.backend.accounts.capacity = asyncio.Semaphore(2)
#         for driver in ("claude", "codex", "pi", "future1", "future2"):
#             install(self.frame, driver, {"list": {"sleep": 0.1, "output": [subscription()]}})
#         before = len(self.frame.calls())
#         tasks = [asyncio.create_task(self.backend.accounts.list({})) for _ in range(3)]
#         maximum = 0
#         while not all(task.done() for task in tasks):
#             maximum = max(maximum, sum(key[0] == "account" and child.process.poll() is None
#                 for key, child in self.backend.programs.running.items()))
#             await asyncio.sleep(0.005)
#         results = await asyncio.gather(*tasks)
#         self.assertTrue(all(len(result["drivers"]) == 5 for result in results))
#         self.assertEqual(maximum, 2)
#         self.assertEqual(len(self.driver_calls(after=before)), 5)
# TEST-TIER-DISABLED-END tests/backend/test_accounts.py::Listing.test_capacity_is_global_across_concurrent_window_listings

# TEST-TIER-DISABLED-BEGIN tests/backend/test_accounts.py::Listing.test_oversized_combined_public_reply_keeps_every_driver_and_small_results
#     async def test_oversized_combined_public_reply_keeps_every_driver_and_small_results(self) -> None:
#         """accounts.reply-bound; accounts.oversized-driver-isolation"""
#         payload = subscription(settings={"field"+str(n): "p"*6000 for n in range(160)})
#         for index in range(19):
#             install(self.frame, "future"+str(index), {"list": {"output": [payload]}})
#         result = await self.backend.accounts.list({})
#         self.assertEqual(len(result["drivers"]), 22)
#         self.assertLessEqual(len(encode(result)), MAX_LINE-4096)
#         rows = {row["driver"]: row for row in result["drivers"]}
#         for driver in ("claude", "codex", "pi"):
#             self.assertIn("subscriptions", rows[driver])
#         self.assertTrue(any("error" in row for row in result["drivers"]))
# TEST-TIER-DISABLED-END tests/backend/test_accounts.py::Listing.test_oversized_combined_public_reply_keeps_every_driver_and_small_results

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_accounts.py:5
# import asyncio
# TEST-TIER-IMPORTS-END tests/backend/test_accounts.py:5
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_accounts.py:6
# import json
# TEST-TIER-IMPORTS-END tests/backend/test_accounts.py:6
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_accounts.py:8
# import time
# TEST-TIER-IMPORTS-END tests/backend/test_accounts.py:8
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_accounts.py:16
# from arbol_backend.bridge import MAX_LINE, encode  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_accounts.py:16
