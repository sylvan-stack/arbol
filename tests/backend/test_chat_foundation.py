# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Private boundaries shared by the chat read/update implementation (BKD-D30)."""

from __future__ import annotations

__all__ = [
    "Attention", "Catalogues", "Cluster", "Database", "Error", "Frame", "Inputs", "Params", "Path", "Programs",
    "ROOT", "Refused", "Schema", "View", "Views", "asyncio", "identity", "inspect", "integer", "mock", "os",
    "parse", "save_paste", "stat", "sys", "text", "unittest",
]
import asyncio
import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Error, Params  # noqa: E402
from arbol_backend.database import Database  # noqa: E402
from arbol_backend.metadata import Attention, inspect  # noqa: E402
from arbol_backend.model import Refused, identity, parse  # noqa: E402
from arbol_backend.process import Programs  # noqa: E402
from arbol_backend.validation import Catalogues, integer, save_paste, text  # noqa: E402
from arbol_backend.views import View  # noqa: E402
from backend.support import Cluster, Frame  # noqa: E402


class Views(unittest.IsolatedAsyncioTestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


class Inputs(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.frame = Frame()
        self.selected = identity(ROOT, parse(self.frame.options()), home=self.frame.home)
        self.programs = Programs(self.selected)
        for driver in ("claude", "codex", "pi"):
            self.frame.behavior["arbol-" + driver + "-driver"] = {"output": [{"id": "private", "key": "private-secret"}]}
        self.frame.configure()
        self.catalogues = Catalogues(self.selected, self.programs)
        self.catalogues.start()
        assert self.catalogues.task
        await self.catalogues.task

    async def asyncTearDown(self) -> None:
        await self.catalogues.close()
        self.programs.close()
        self.frame.close()


class Schema(unittest.IsolatedAsyncioTestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


# Archived complete imports; restore needed names in their original scope, not at this file tail.
