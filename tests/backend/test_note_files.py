# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Private note publication survives each crash boundary without replacing other files."""

from __future__ import annotations
import json
import os
from unittest import mock
from uuid import uuid4


import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Error, Params  # noqa: E402
from arbol_backend.note_files import MAX_NOTE, NoteFiles  # noqa: E402

from arbol_backend.bridge import Params  # noqa: E402
from arbol_backend.model import identity, parse  # noqa: E402
from arbol_backend.note_files import NoteFiles  # noqa: E402
from backend.support import Frame  # noqa: E402
from backend.test_chat_wire import chat  # noqa: E402


class Files(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = Frame()
        self.addCleanup(self.frame.close)
        self.files = NoteFiles(identity(ROOT, parse(self.frame.options()), home=self.frame.home))
        self.value: Params = {"root": self.frame.record["root"], "exchange": chat(900), "chat": chat(1),
            "kind": "ended_stuck", "at": "2026-10-27T01:02:03.000Z"}
        self.path = self.frame.root / "notes" / (chat(900)+".json")


# Archived complete imports; restore needed names in their original scope, not at this file tail.
