# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Actual private launcher children qualify independent, shared account listing."""

from __future__ import annotations
import asyncio
import json
import time


import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import MAX_LINE, encode  # noqa: E402

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


# Archived complete imports; restore needed names in their original scope, not at this file tail.
