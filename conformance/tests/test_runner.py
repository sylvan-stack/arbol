# Test implementations moved to tests/mid/archived/conformance/tests/test_runner.py.
"""The suite's own checks (runner.*), with a synthetic second Driver instead of a real one (DRV-5).

    uv run --no-sync python -B -m unittest discover -s conformance/tests -t .
"""

from __future__ import annotations

import dataclasses
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from conformance.harness import Scenario  # noqa: E402
from conformance.runner import select_scenarios as registry_scenarios  # noqa: E402
from conformance.scenarios.c32 import check_driver_info  # noqa: E402

FAKE = str(ROOT / "conformance/tests/fake_driver.py")
CLI = str(ROOT / "conformance/bin/arbol-conformance.py")
COMMAND = [sys.executable, FAKE]


def select_scenarios(ids: str) -> list[Scenario]:
    """The synthetic second Driver exercises runner mechanics and identity, not inference."""
    return [dataclasses.replace(scenario, scope="info only for runner self-tests", run=check_driver_info)
            if scenario.id == "C32" else scenario for scenario in registry_scenarios(ids)]


def gone(path: str) -> bool:
    return not os.path.lexists(path)


class Runner(unittest.IsolatedAsyncioTestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.











if __name__ == "__main__":
    unittest.main()

# Archived complete imports; restore needed names in their original scope, not at this file tail.
