# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Bounded file replay, exact cutoffs and oversized metadata without retained payloads."""

from __future__ import annotations
import asyncio
import tracemalloc


import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
from arbol_backend.bridge import MAX_LINE  # noqa: E402
from arbol_backend.event_file import CHUNK, Envelope, Scanner, completed, meta, metadata, superseded  # noqa: E402

from arbol_backend.event_file import Scanner, completed, superseded  # noqa: E402


def event(n: int, kind: str, **fields: Any) -> bytes:
    return (json.dumps({"n": n, "event": {"runId": "r", "seq": n, "at": "2026-10-27T00:00:00Z",
        "type": kind, **fields}}, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


class Files(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.file = tempfile.TemporaryFile()
        self.fd = self.file.fileno()

    def tearDown(self) -> None:
        self.file.close()

    def append(self, data: bytes) -> None:
        os.lseek(self.fd, 0, os.SEEK_END)
        os.write(self.fd, data)


# Archived complete imports; restore needed names in their original scope, not at this file tail.
