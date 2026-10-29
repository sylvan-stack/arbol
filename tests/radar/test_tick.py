# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""The recompute tick of Subscriptions Vigor (SGM-1.14, SGM-D30), on a database of the check's own with stand-in Drivers.

Every three minutes while the backend runs: every Driver listed, every newer report recorded, every Subscription
recalculated and recorded, a passed reset taking effect at that tick and never earlier, no faster schedule, and a Root
without the tables left alone. Vigor stays advisory: nothing of the package writes a route, a binding or a request file.
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timedelta


import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.model import Refused  # noqa: E402
from arbol_radar.drivers import LIST  # noqa: E402
from arbol_radar.model import FIRST_PROFILE, Profile, Rejected, Weight  # noqa: E402
from arbol_radar.tick import Tick, Ticker, tick  # noqa: E402
from radar.fixture import LAYOUT, LISTING, RecordFixture, drivers, record, usage  # noqa: E402
from radar.support import CLAUDE, CODEX, KIMI, MONDAY, ZAI, at, claude  # noqa: E402

from arbol_backend.process import Programs  # noqa: E402
from radar.fixture import LISTING, RecordFixture, drivers  # noqa: E402


def listing(**replies: dict[str, Any]) -> dict[str, Any]:
    """The stand-in Drivers' `list` replies: the worked examples' listing, with a Driver's reply replaced."""
    return {name: {"list": replies.get(name, config)} for name, config in LISTING.items()}


class Clock:
    """An injected clock: the moments the ticker reads, one per wake."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class TheTick(RecordFixture):
    """One tick: list, record what is newer, recalculate every Subscription (SGM-1.14)."""

    def programs(self, behavior: dict[str, Any]) -> Programs:
        drivers(self.frame, behavior)
        return Programs(self.selected)

    def commands(self) -> list[list[str]]:
        return [call["args"] for call in self.frame.calls()]


class TheBackend(RecordFixture):
    """The backend's loop ticks while it runs: at its first wake, then every three minutes; without the tables it runs on."""

    def backend(self) -> subprocess.Popen[bytes]:
        child = self.frame.start(args=self.frame.options(self.cluster.address))
        self.assertTrue(self.frame.line(child)["ready"])
        return child

    @staticmethod
    def stop(child: subprocess.Popen[bytes]) -> None:
        assert child.stdin is not None
        child.stdin.close()  # the end of its standard input stops the backend, as the Swift App would
        child.communicate(timeout=10)


# Archived complete imports; restore needed names in their original scope, not at this file tail.
