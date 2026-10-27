"""Actual private managers qualify Root isolation, bounded fan-out and routed mutations."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import MAX_LINE, Error, Params  # noqa: E402
from arbol_backend.chat_data import encoded  # noqa: E402
from arbol_backend.controls import stop_params  # noqa: E402
from arbol_backend.discovery import TOTAL  # noqa: E402
from arbol_backend.listings import CAPACITY  # noqa: E402
from arbol_backend.metadata import now  # noqa: E402
from arbol_backend.model import Refused  # noqa: E402
from backend.discovery_support import calls, configure, install  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class AcrossRoots(WindowFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        assert self.backend.discovery.task and self.backend.settling.look and self.backend.settling.worker
        await self.backend.discovery.task
        await self.backend.settling.look
        await self.backend.settling.worker
        self.own = self.backend.identity.root
        self.behavior: dict[str, Any] = {}
        install(self.frame, self.behavior)
        self.catalogue([self.own, "t2"])

    def catalogue(self, roots: list[str]) -> None:
        self.frame.behavior["arbol-roots"]["output"] = [{"root": root, "name": "Private "+root,
            "status": "working", "current": root == self.own} for root in roots]
        self.frame.configure()

    def row(self, root: str, *, state: str = "running", exchange: str | None = None) -> Params:
        return {"root": root, "exchange": exchange or chat(910), "chat": chat(1), "state": state,
            "trunk": "trivial", "build": "af", "process": {"pid": 4242, "startedAt": now(), "alive": state == "running"},
            "signsOfLife": {"heartbeat": 7, "waitingFor": "future-wait", "since": now()}}

    def listed(self, root: str, rows: list[Params] | None = None, unreadable: list[str] | None = None) -> Params:
        return {"root": root, "rootBuild": "1", "rootPackageVersion": "1.0.0", "exchanges": rows or [], "unreadable": unreadable or []}

    def configure(self) -> None:
        configure(self.frame, self.behavior)

    async def count(self, n: int, *, kind: str = "list", root: str | None = None) -> list[Params]:
        async with asyncio.timeout(3):
            while len(rows := calls(self.frame, kind=kind, root=root)) < n:
                await asyncio.sleep(0.01)
        return rows

    async def test_three_windows_share_one_fresh_discovery_and_only_public_listing_metadata(self) -> None:
        """discovery.shared; discovery.metadata-only; discovery.root-manager-route"""
        self.assertEqual((CAPACITY, TOTAL), (8, 25))
        own, other = self.row(self.own), self.row("t2", state="future-state")
        other.update(message="hidden transcript", password="fictional-private-value", future={"secret": "private"})
        self.behavior = {self.own: {"list": {"sleep": 0.12, "output": self.listed(self.own, [own])}},
            "t2": {"list": {"sleep": 0.12, "output": self.listed("t2", [other])}}}
        self.configure()
        clients = [await self.open() for _ in range(3)]
        replies = await asyncio.gather(*(self.call(r, w, "roots.list") for r, w in clients))
        self.assertTrue(all(reply["result"] == replies[0]["result"] for reply in replies))
        rows = replies[0]["result"]["roots"]
        self.assertEqual([row["root"]["root"] for row in rows], [self.own, "t2"])
        self.assertEqual(rows[1]["exchanges"][0]["state"], "future-state")
        self.assertEqual(rows[1]["exchanges"][0]["signsOfLife"]["waitingFor"], "future-wait")
        self.assertNotIn("hidden transcript", json.dumps(replies))
        self.assertNotIn("fictional-private-value", json.dumps(replies))
        self.assertEqual(len(calls(self.frame, kind="list", root=self.own)), 1)
        self.assertEqual(len(calls(self.frame, kind="list", root="t2")), 1)
        self.assertTrue(all(row["args"][:3] == ["--root", row["root"], "list"] for row in calls(self.frame)))
        self.assertEqual((self.backend.database.parameters or {})["dbname"], "arbol_test")
        self.assertFalse((self.frame.home / "Library/Application Support/Arbol/roots/t2").exists())

    async def test_failing_mismatched_partial_and_unknown_refusal_roots_do_not_hide_others(self) -> None:
        """discovery.root-error-isolation; discovery.partial; discovery.safe-refusal"""
        self.catalogue([self.own, "t2", "t3"])
        self.behavior = {self.own: {"list": {"output": self.listed(self.own, [self.row(self.own)], [chat(911)])}},
            "t2": {"list": {"output": self.listed("another", [self.row("another")])}},
            "t3": {"list": {"status": 1, "output": {"error": {"code": "future_refusal", "message": "Try later."}}}}}
        self.configure()
        result = await self.backend.discovery.get({})
        rows = {entry["root"]["root"]: entry for entry in result["roots"]}
        self.assertEqual(len(rows[self.own]["exchanges"]), 1)
        self.assertEqual(rows[self.own]["error"]["code"], "no_answer")
        self.assertEqual(rows["t2"]["error"]["code"], "no_answer")
        self.assertEqual(rows["t3"]["error"], {"code": "future_refusal", "source": "root-manager", "message": "Try later."})
        self.behavior["t3"]["list"]["output"]["error"]["message"] = "Authorization Bearer fictional-private-value"
        self.configure()
        self.assertNotIn("fictional-private-value", json.dumps(await self.backend.discovery.get({})))
        duplicate = self.row("t2")
        for invalid in (self.listed("t2", [duplicate, duplicate]), self.listed("t2", [duplicate], [duplicate["exchange"]])):
            with self.assertRaises(Error):
                self.backend.listings.checked(invalid, "t2")

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

    async def test_unknown_deleted_invalid_or_wrong_root_stop_never_falls_back_to_current(self) -> None:
        """discovery.deleted-root; discovery.validate-root-before-effects; discovery.stop-result-root"""
        exchange = chat(913)
        self.catalogue([self.own])
        with self.assertRaises(Error) as caught:
            await self.backend.controls.stop(await stop_params({"exchange": exchange, "root": "t2"}))
        self.assertEqual(caught.exception.code, "unknown_root")
        self.assertEqual(calls(self.frame, kind="stop"), [])
        for root in ("../escape", "a;command", True, None, ""):
            with self.assertRaises(Error):
                await stop_params({"exchange": exchange, "root": root})
        for program, kind, args in (("arbol-root", "start", ["start", "--exchange", exchange]),
                                    ("arbol-roots", "list", ["list"]),
                                    ("arbol-claude-driver", "account", ["subscriptions", "list"])):
            with self.assertRaises(Refused):
                await self.backend.programs.call(program, args, kind=kind, root="t2")
        self.assertEqual(calls(self.frame), [])
        self.catalogue([self.own, "t2"])
        self.behavior = {"t2": {"stop": {"output": {"root": self.own, "exchange": exchange, "ended": "none"}}}}
        self.configure()
        with self.assertRaises(Error) as caught:
            await self.backend.controls.stop(await stop_params({"exchange": exchange, "root": "t2"}))
        self.assertEqual(caught.exception.code, "no_answer")
        self.assertEqual([row["root"] for row in calls(self.frame, kind="stop")], ["t2"])

    async def test_eligible_listings_settle_each_explicit_root_once_and_defer_when_own_database_is_away(self) -> None:
        """discovery.settle-root; discovery.settle-coalescing; discovery.settle-database-gate"""
        self.behavior = {root: {"list": {"output": self.listed(root, [self.row(root, state="interrupted")])},
            "settle": {"sleep": 0.15}} for root in (self.own, "t2")}
        self.configure()
        await self.backend.discovery.get({})
        await self.count(2, kind="settle")
        for _ in range(10):
            self.backend.settling.request(self.own)
            self.backend.settling.request("t2")
        await asyncio.gather(*(queue.task for queue in self.backend.settling.queues.values() if queue.task is not None))
        self.assertEqual(len(calls(self.frame, kind="settle", root=self.own)), 2)
        self.assertEqual(len(calls(self.frame, kind="settle", root="t2")), 2)
        before = len(calls(self.frame, kind="settle"))
        self.backend.health.failed("Private test database is unavailable.")
        self.backend.settling.request(self.own)
        self.backend.settling.request("t2")
        await asyncio.gather(*(queue.task for queue in self.backend.settling.queues.values() if queue.task is not None))
        self.assertEqual(len(calls(self.frame, kind="settle")), before)
        await self.backend.health.probe()

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

    async def test_cancelled_caller_joins_shared_listing_and_total_budget_preserves_all_root_records(self) -> None:
        """discovery.caller-shield; discovery.shared-look; discovery.total-bound; discovery.capacity"""
        self.behavior = {self.own: {"list": {"sleep": 0.12}}}
        self.configure()
        caller = asyncio.create_task(self.backend.discovery.get({}))
        await self.count(1, root=self.own)
        self.backend.settling.request_listing()
        caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)
        await self.backend.discovery.get({})
        assert self.backend.settling.look
        await self.backend.settling.look
        self.assertEqual(len(calls(self.frame, kind="list", root=self.own)), 1)
        roots = [self.own]+["r"+str(n) for n in range(11)]
        self.catalogue(roots)
        self.behavior = {root: {"list": {"sleep": 0.35}} for root in roots}
        self.configure()
        self.backend.discovery.total = 0.15
        before = time.monotonic()
        result = await self.backend.discovery.get({})
        self.assertLess(time.monotonic()-before, 0.5)
        self.assertEqual([entry["root"]["root"] for entry in result["roots"]], roots)
        self.assertTrue(any("error" in entry for entry in result["roots"]))
        await asyncio.gather(*self.backend.listings.tasks.values())
        events = calls(self.frame)+calls(self.frame, phase="finish")
        active: set[int] = set()
        peak = 0
        for row in sorted(events, key=lambda row: row["at"]):
            if row["phase"] == "start":
                active.add(row["pid"])
                peak = max(peak, len(active))
            else:
                active.discard(row["pid"])
        self.assertLessEqual(peak, 8)

    async def test_oversized_combined_reply_keeps_small_roots_and_fits_complete_bridge_frame(self) -> None:
        """discovery.reply-bound; discovery.oversized-root-isolation"""
        roots = [self.own]+["r"+str(n) for n in range(18)]+["last"]
        self.catalogue(roots)
        self.behavior = {root: {"list": {"output": self.listed(root, [self.row(root)]), "stateBytes": 900000}}
            for root in roots[:-1]}
        self.configure()
        r, w = await self.open()
        result = await self.call(r, w, "roots.list")
        self.assertLessEqual(len(encoded(result))+1, MAX_LINE)
        entries = result["result"]["roots"]
        self.assertEqual(len(entries), len(roots))
        self.assertTrue(any("error" in entry for entry in entries[:-1]))
        self.assertNotIn("error", entries[-1])
        self.assertEqual(entries[-1]["root"]["root"], "last")
