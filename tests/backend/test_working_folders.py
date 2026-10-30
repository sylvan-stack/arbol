# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Private real request/SQL receipts qualify stable folders and explicit repository moves."""

from __future__ import annotations
import os
from unittest import mock


import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from backend.dispatch_support import install, starts  # noqa: E402

from arbol_backend.bridge import Params  # noqa: E402
from backend.dispatch_support import install  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class Folders(WindowFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        install(self.frame, self.cluster.address, [{}])
        self.backend.dispatch.retry, self.backend.dispatch.total = 0.1, 2
        self.backend.programs.limits["start"] = 0.5
        self.readonly = self.frame.base / "repos/sylvan-stack/readonly/private repo"
        self.other = self.frame.base / "Other picked folder Ω"
        self.booked = self.frame.base / "repos/sylvan-stack/fox/private repo"
        for path in (self.readonly, self.other, self.booked):
            path.mkdir(parents=True)
        self.route = {"driver": "claude", "subscription": "private", "model": "private-model"}
        self.r, self.w = await self.open()

    async def send_to(self, exchange: int, folder: Path) -> Params:
        payload = {"chat": chat(900), "exchange": chat(exchange), "message": "private folder request",
                   "route": self.route, "workingFolder": str(folder)}
        reply = await self.call(self.r, self.w, "chat.send", payload)
        self.assertIn("result", reply)
        return payload


# Archived complete imports; restore needed names in their original scope, not at this file tail.
