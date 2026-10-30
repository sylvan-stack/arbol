# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""BKD-D36 public readonly bootstrap and first-prompt snapshot input."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from backend.test_chat_wire import WindowFixture  # noqa: E402


class Bootstrap(WindowFixture):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


# Archived complete imports; restore needed names in their original scope, not at this file tail.
