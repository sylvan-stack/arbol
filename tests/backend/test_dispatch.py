# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Real private child processes qualify shared send, timing, uncertainty and replacement."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Params  # noqa: E402
from arbol_backend.drafts import save_params  # noqa: E402
from backend.dispatch_support import install, starts  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class Sending(WindowFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        install(self.frame, self.cluster.address, [{}])
        self.backend.dispatch.retry, self.backend.dispatch.total = 0.1, 2.0
        self.backend.programs.limits["start"] = 0.5

    def payload(self, *, exchange: int = 800, id: int = 1) -> Params:
        return {"chat": chat(id), "exchange": chat(exchange), "message": "send me",
                "route": {"driver": "claude", "subscription": "private", "model": "model"},
                "workingFolder": str(self.frame.base)}

    async def with_draft(self, params: Params, *, folder: bool = False) -> Params:
        key = {"folder": params["workingFolder"]} if folder else {"chat": params["chat"]}
        saved = await self.backend.drafts.save(await save_params({**key, "text": params["message"], "baseRevision": None}))
        return {**params, "draft": {"revision": saved["revision"], **({"folder": key["folder"]} if folder else {})}}

    async def execute(self, params: Params) -> Params:
        return await self.backend.dispatch.send(await self.backend.dispatch.send_params(params))

    async def wait_starts(self, count: int = 1) -> list[dict[str, Any]]:
        async with asyncio.timeout(3):
            while len(rows := starts(self.frame)) < count:
                await asyncio.sleep(0.01)
        return rows


# Archived complete imports; restore needed names in their original scope, not at this file tail.
