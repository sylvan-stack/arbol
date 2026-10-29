# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Subscriptions Vigor: the loss of a window and the Vigor of a Subscription, with fixed reports, clock and profile (SGM-1)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_radar.model import Rejected  # noqa: E402


class Records(unittest.TestCase):
    """The records of the Interface, the used-share rules and what the Interface rejects."""

    def rejected(self, field: str, call: Any, *args: Any, **kwargs: Any) -> None:
        with self.assertRaises(Rejected) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.field, field)


class WindowsThatTakePart(unittest.TestCase):
    """Which windows take part in the sum, the store and the gates (SGM-1.2, SGM-D24, SGM-D25)."""


class LossOfAWindow(unittest.TestCase):
    """The loss of one window at its even pace (SGM-1.3)."""


class WorkedExamples(unittest.TestCase):
    """The chapter's worked examples: Claude 0.37, Codex 0.16, Kimi Code 0.47, and 0.39 at 13:20 (SGM-1.1, SGM-1.4)."""


class Weights(unittest.TestCase):
    """The weights and the capped sum (SGM-1.4, SGM-D15)."""


class ExhaustedSubscriptions(unittest.TestCase):
    """The exhausted state (SGM-1.5, SGM-D27); the recovery is computed on predicted windows and is not here."""


class Advisory(unittest.TestCase):
    """Vigor is advisory: the package runs no program, reads no Driver and writes no file (SGM-1.15)."""

    ALLOWED_IMPORTS = {
        "__future__",
        "collections.abc",
        "dataclasses",
        "datetime",
        "math",
        "typing",
        "arbol_radar.model",
    }
    FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "print"}

    # The two modules that reach outside the calculation, each pinned to its one reach (SYL-297): the Drivers through
    # the backend's launcher calls, and the records through the backend's bounded database connection.
    REACHES = {
        "drivers.py": {"arbol_backend.model", "arbol_backend.process"},
        "records.py": {
            "arbol_backend.database",
            "arbol_backend.model",
            "psycopg.types.json",
            "arbol_radar.vigor",
            "uuid",
        },
        # The rollup (SYL-298) reaches the records only for the shape of a loss row in the JSON answer; the command
        # line `arbol vigor` reaches the launchers, the database and standard output, and nothing else.
        "rollup.py": {"arbol_radar.records"},
        "cli.py": {
            "json",
            "arbol_backend.database",
            "arbol_backend.model",
            "arbol_backend.process",
            "arbol_radar.drivers",
            "arbol_radar.learning",
            "arbol_radar.records",
            "arbol_radar.rollup",
            "arbol_radar.tick",
            "arbol_radar.vigor",
        },
        # The tick reaches the Drivers' listing and the records, and nothing else.
        "tick.py": {"arbol_backend.process", "arbol_radar.drivers", "arbol_radar.records"},
        # The learner (SYL-299) reaches the records and the Root's chat tables through the bounded connection.
        "learning.py": {
            "arbol_backend.database",
            "arbol_radar.records",
            "arbol_radar.vigor",
            "itertools",
            "statistics",
        },
    }
    PRINTS = {"cli.py"}  # the one module that answers on standard output



# Archived complete imports; restore needed names in their original scope, not at this file tail.
