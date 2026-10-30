# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""The check frame's own support: the private PostgreSQL starts in a session without a locale."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))


def without_locale() -> dict[str, str]:
    """This process's environment with `LANG` and every `LC_*` variable removed, as a session of the app has it."""
    return {name: value for name, value in os.environ.items() if name != "LANG" and not name.startswith("LC_")}


class Locale(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


class Restart(unittest.IsolatedAsyncioTestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


# Archived complete imports; restore needed names in their original scope, not at this file tail.
