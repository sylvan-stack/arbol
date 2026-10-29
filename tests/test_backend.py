# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""BKD-0 process/children/database foundation, entirely private."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from backend.support import Cluster, Frame  # noqa: E402

from arbol_backend import database  # noqa: E402
from arbol_backend.model import identity, parse  # noqa: E402


class Process(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = Frame()
        self.addCleanup(self.frame.close)

    def selected(self) -> Any:
        return identity(ROOT, parse(self.frame.options()), home=self.frame.home)


class AsyncFoundation(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.frame = Frame()
        self.addCleanup(self.frame.close)
        self.selected = identity(ROOT, parse(self.frame.options()), home=self.frame.home)


class SQL(unittest.IsolatedAsyncioTestCase):
    cluster: Cluster

    @classmethod
    def setUpClass(cls) -> None:
        cls.cluster = Cluster()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.cluster.close()

    def setUp(self) -> None:
        self.frame = Frame()
        self.addCleanup(self.frame.close)
        self.selected = identity(ROOT, parse(self.frame.options(self.cluster.address)), home=self.frame.home)
        self.db = database.Database(self.selected)

    async def asyncTearDown(self) -> None:
        await self.db.close()



# Archived complete imports; restore needed names in their original scope, not at this file tail.
