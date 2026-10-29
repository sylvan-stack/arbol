# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Private boundaries shared by the chat read/update implementation (BKD-D30)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.model import identity, parse  # noqa: E402
from arbol_backend.process import Programs  # noqa: E402
from arbol_backend.validation import Catalogues  # noqa: E402
from backend.support import Frame  # noqa: E402


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
