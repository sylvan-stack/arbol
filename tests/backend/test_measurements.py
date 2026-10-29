# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Private PostgreSQL and actual disk tools qualify partial, own-connection measurement."""

from __future__ import annotations
import asyncio
import json
import os
import shlex
import signal
import time
from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from unittest import mock


import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Registry  # noqa: E402
from arbol_backend.database import Database, Session  # noqa: E402
from arbol_backend.health import Health  # noqa: E402
from arbol_backend.measurements import Measurements  # noqa: E402
from arbol_backend.metadata import Attention  # noqa: E402
from arbol_backend.process import Programs  # noqa: E402
from arbol_backend.storage import LocalDisk  # noqa: E402
from backend.recovery_support import offline  # noqa: E402

from backend.test_chat_wire import WindowFixture  # noqa: E402


class Storage(WindowFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        if self.backend.discovery.task:
            await self.backend.discovery.task
        if self.backend.roots.inflight:
            await self.backend.roots.inflight

    def catalogue(self, *other: tuple[str, str]) -> None:
        self.frame.behavior["arbol-roots"]["output"] = [{**self.frame.record, "current": True},
            *[{"root": root, "name": "Private "+root, "status": "working", "current": False, "database": database}
              for root, database in other]]
        self.frame.configure()


# Archived complete imports; restore needed names in their original scope, not at this file tail.
