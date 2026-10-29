# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Private request-file namespace, modes, races and narrowly scoped startup cleanup."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.model import identity, parse  # noqa: E402
from arbol_backend.requests import Requests  # noqa: E402
from backend.support import Frame  # noqa: E402


class Files(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = Frame()
        self.files = Requests(identity(ROOT, parse(self.frame.options()), home=self.frame.home))
        self.exchange = str(uuid4())
        self.request = {"chat": str(uuid4()), "message": "exact\n🙂", "route": {"model": "m"},
                        "workingFolder": str(self.frame.base)}

    def tearDown(self) -> None:
        self.frame.close()


# Archived complete imports; restore needed names in their original scope, not at this file tail.
