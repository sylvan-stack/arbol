# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Actual private connection loss and classified failures keep attention available."""

from __future__ import annotations
import asyncio
import json
import time
from dataclasses import replace
from unittest import mock


import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
import psycopg
from arbol_backend.database import SECONDS, Database  # noqa: E402
from arbol_backend.health import RETRY, Health  # noqa: E402
from arbol_backend.metadata import Attention  # noqa: E402
from arbol_backend.model import Refused  # noqa: E402
from backend.recovery_support import offline, online  # noqa: E402

from backend.test_chat_wire import WindowFixture  # noqa: E402


class Availability(WindowFixture):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


# Archived complete imports; restore needed names in their original scope, not at this file tail.
