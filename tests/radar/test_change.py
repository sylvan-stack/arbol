# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Subscriptions Vigor: predicted windows, the next change, stale and unknown, with fixed reports, clock and profile (SGM-1)."""

from __future__ import annotations

__all__ = [
    "CLAUDE", "CODEX", "FIRST_PROFILE", "FIVE_HOURS", "KIMI", "MONDAY", "Path", "PredictedWindows", "Profile",
    "RESET", "ROOT", "Rejected", "Stale", "TheNextChange", "Unknown", "Weight", "Window", "ZAI", "at", "by_label",
    "claude", "codex", "compute", "kimi", "next_change", "predict", "report", "stale_after", "sys", "timedelta",
    "unittest", "unknown_reason", "window",
]


import sys
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_radar.model import FIRST_PROFILE, Profile, Rejected, Weight, Window, stale_after  # noqa: E402
from arbol_radar.vigor import compute, next_change, predict, unknown_reason  # noqa: E402
from radar.support import (  # noqa: E402
    CLAUDE,
    CODEX,
    KIMI,
    MONDAY,
    ZAI,
    at,
    by_label,
    claude,
    codex,
    kimi,
    report,
    window,
)

RESET = MONDAY + timedelta(hours=3, minutes=20)  # the worked example's five-hour reset, 13:20
FIVE_HOURS = timedelta(hours=5)


class PredictedWindows(unittest.TestCase):
    """A fresh window after a reset without a newer report (SGM-1.7, SGM-D20)."""


class TheNextChange(unittest.TestCase):
    """The earliest reset among the windows and the Vigor at that moment on the predicted windows (SGM-1.6, SGM-D16)."""


class Stale(unittest.TestCase):
    """A result on a report older than the shortest window that is summed or can exhaust the Subscription (SGM-1.8)."""


class Unknown(unittest.TestCase):
    """A result that cannot be computed is unknown with its reason, never zero (SGM-1.9, SGM-D19)."""


# Archived complete imports; restore needed names in their original scope, not at this file tail.
