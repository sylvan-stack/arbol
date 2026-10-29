# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Real bounded private managers qualify shared stop ownership and uncertain outcomes."""

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
from backend.test_chat_wire import WindowFixture  # noqa: E402


class Stopping(WindowFixture):
    def configure(self, exchange: str, *, ended: str = "cancelled", sleep: float = 0, **extra: Any) -> None:
        self.frame.behavior["arbol-root"] = {"sleep": sleep,
            "output": {"root": self.backend.identity.root, "exchange": exchange, "ended": ended, "forced": False}, **extra}
        self.frame.configure()

    def calls(self, kind: str = "stop") -> list[Params]:
        return [row for row in self.frame.calls() if row["program"] == "arbol-root" and row["args"][2] == kind]

    async def wait_call(self, kind: str = "stop", count: int = 1) -> list[Params]:
        async with asyncio.timeout(2):
            while len(rows := self.calls(kind)) < count:
                await asyncio.sleep(0.01)
        return rows


# Archived complete imports; restore needed names in their original scope, not at this file tail.
