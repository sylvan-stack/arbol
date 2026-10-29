# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Private folder boundaries, immutable records and actual clean-UTC process identity."""

from __future__ import annotations
import asyncio
from datetime import UTC, timedelta
from unittest import mock


import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Error  # noqa: E402
from arbol_backend.exchange_files import MAX_RECORD, Folders, living, processes, record  # noqa: E402

from arbol_backend.exchange_files import Folders  # noqa: E402
from arbol_backend.model import identity, parse  # noqa: E402
from backend.support import Frame  # noqa: E402


class Files(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.frame = Frame()
        self.identity = identity(ROOT, parse(self.frame.options()), home=self.frame.home)
        self.reader = Folders(self.identity)
        self.parent = self.frame.root / "exchanges"
        self.parent.mkdir(mode=0o700)
        self.exchange, self.chat = str(uuid4()), str(uuid4())
        self.folder = self.parent / self.exchange
        self.folder.mkdir(mode=0o700)
        self.value: dict[str, Any] = {"rootContract": 1, "root": self.identity.root, "exchange": self.exchange,
            "chat": self.chat, "trunk": "trivial", "build": "0", "route": {}, "workingFolder": str(self.frame.base),
            "process": {"pid": os.getpid(), "startedAt": "2026-10-27T00:00:00Z"},
            "signsOfLife": {"heartbeat": 0, "waitingFor": "driver", "since": "2026-10-27T00:00:00Z"}}
        self.save()
        for name in ("events.jsonl", "control"):
            (self.folder / name).touch(mode=0o600)

    def tearDown(self) -> None:
        self.frame.close()

    def save(self) -> None:
        path = self.folder / "record.json"
        temporary = self.folder / "record.json.new"
        temporary.write_text(json.dumps(self.value))
        temporary.chmod(0o600)
        temporary.replace(path)


# Archived complete imports; restore needed names in their original scope, not at this file tail.
