"""The suite's own checks (runner.*), with a synthetic second Driver instead of a real one (DRV-5).

    uv run --no-sync python -B -m unittest discover -s conformance/tests -t .
"""

from __future__ import annotations
import asyncio
import json
import shutil
import stat
import tempfile
from typing import Any


import dataclasses
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from conformance.command import command_words, resolve_command, shell_quote  # noqa: E402
from conformance.harness import Scenario, ScenarioHome  # noqa: E402
from conformance.process import Abort, invoke  # noqa: E402
from conformance.runner import run_suite  # noqa: E402

from conformance.harness import Scenario  # noqa: E402

FAKE = str(ROOT / "conformance/tests/fake_driver.py")
CLI = str(ROOT / "conformance/bin/arbol-conformance.py")
COMMAND = [sys.executable, FAKE]




def gone(path: str) -> bool:
    return not os.path.lexists(path)


class Runner(unittest.IsolatedAsyncioTestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


    async def test_runner_timeout(self) -> None:
        """runner.timeout ends the Driver and its child before removing the scenario home."""
        state: dict[str, Any] = {"path": "", "pids": []}

        async def run(home: ScenarioHome) -> None:
            state["path"] = home.home
            outcome = asyncio.ensure_future(home.call(["info"]))
            for _ in range(100):
                try:
                    state["pids"] = json.loads(Path(home.home, "pids.json").read_text())
                    break
                except (OSError, ValueError):
                    await asyncio.sleep(0.01)
            await outcome
            self.fail("The hanging Driver unexpectedly completed.")

        reports: list[str] = []
        selected = [Scenario("hang", "hanging Driver", "runner self-test", [], run)]
        self.assertEqual(await run_suite([*COMMAND, "--fixture=hang"], selected, timeout_ms=1500,
                                         write=reports.append), 1)
        self.assertRegex("\n".join(reports), r"timed out[\s\S]*Expected:.*1500")
        self.assertEqual(len(state["pids"]), 2)
        for pid in state["pids"]:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        self.assertTrue(gone(state["path"]))


if __name__ == "__main__":
    unittest.main()

# Archived complete imports; restore needed names in their original scope, not at this file tail.
