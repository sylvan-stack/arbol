"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_chat_foundation as _support
from backend.test_chat_foundation import (
    Attention,
    Catalogues,
    Cluster,
    Database,
    Error,
    Frame,
    Inputs,
    Params,
    Path,
    Programs,
    ROOT,
    Refused,
    Schema,
    View,
    Views,
    asyncio,
    identity,
    inspect,
    integer,
    mock,
    os,
    parse,
    save_paste,
    stat,
    sys,
    text,
    unittest,
)


class Views(_support.Views):
# TEST-TIER-BEGIN tests/backend/test_chat_foundation.py::Views.test_invalidation_rejects_an_older_snapshot_and_reads_coalesce
    async def test_invalidation_rejects_an_older_snapshot_and_reads_coalesce(self) -> None:
        """chats.view-generation"""
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0
        state = 1
        async def load(params: Params) -> Params:
            nonlocal calls
            calls += 1
            captured = state
            entered.set()
            await release.wait()
            return {"kind": "snapshot", "state": captured}
        published: list[Params] = []
        view = View(load, lambda old, new, params: published.append(new))
        self.addAsyncCleanup(view.close)
        first = asyncio.create_task(view.snapshot({"chat": "a"}))
        await entered.wait()
        second = asyncio.create_task(view.snapshot({"chat": "a"}))
        state = 2
        view.invalidate({"chat": "a"})
        release.set()
        one, two = await asyncio.gather(first, second)
        self.assertEqual((one.event["state"], two.event["state"], calls), (2, 2, 2))
        self.assertEqual(published, [{"kind": "snapshot", "state": 2}])
        view.forget_unwatched()
        self.assertFalse(view.states)
        self.assertFalse(view.inflight)
        self.assertFalse(view.generations)
# TEST-TIER-END tests/backend/test_chat_foundation.py::Views.test_invalidation_rejects_an_older_snapshot_and_reads_coalesce
