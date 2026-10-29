# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Public family metadata remains useful without becoming a credential channel."""

from __future__ import annotations
import json
from typing import Any


import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.account_data import Public  # noqa: E402
from arbol_backend.bridge import Error  # noqa: E402
from backend.account_support import models, subscription, usage  # noqa: E402


class Projection(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


# Archived complete imports; restore needed names in their original scope, not at this file tail.
