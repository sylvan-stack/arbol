"""The suite's own checks (runner.*), with a synthetic second Driver instead of a real one (DRV-5).

    uv run --no-sync python -B -m unittest discover -s conformance/tests -t .
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from conformance.harness import Scenario, ScenarioHome  # noqa: E402
from conformance.runner import run_suite  # noqa: E402

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

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/archived/conformance/tests/test_runner.py::Runner.test_runner_shared_scenarios
# Reason: Runner self-check repeats straightforward parsing/selection/status behavior or synthetic wrapper coverage; retained timeout checks actual descendant cleanup, the consequential integration risk. Case reviewed: runner.shared-scenarios checks a second Driver protocol without Driver imports.
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/tests/test_runner.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_runner_shared_scenarios(self) -> None:
#         """runner.shared-scenarios checks a second Driver protocol without Driver imports."""
#         reports: list[str] = []
#         self.assertEqual(await run_suite(COMMAND, select_scenarios("C1,C31,C32"), write=reports.append), 0)
#         text = "\n".join(reports)
#         self.assertRegex(text, r"PASS C31")
#         self.assertRegex(text, r"PASS C32.*info only")
#         self.assertRegex(text, r"PASS C1.*removal")
#         self.assertEqual(reports[-1], "3/3 scenarios passed.")
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/tests/test_runner.py::Runner.test_runner_isolation
# Reason: Runner self-check repeats straightforward parsing/selection/status behavior or synthetic wrapper coverage; retained timeout checks actual descendant cleanup, the consequential integration risk. Case reviewed: runner.isolation gives each scenario a clean home, settings, time scale and working folder.
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/tests/test_runner.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_runner_isolation(self) -> None:
#         """runner.isolation gives each scenario a clean home, settings, time scale and working folder."""
#         homes: list[str] = []
#
#         def wrap(scenario: Scenario) -> Scenario:
#             async def run(fixture: ScenarioHome) -> None:
#                 homes.append(fixture.home)
#                 self.assertEqual(stat.S_IMODE(os.stat(fixture.home).st_mode), 0o700)
#                 self.assertEqual(fixture.env["ARBOL_TEST_TIME_SCALE"], "100")
#                 self.assertEqual(fixture.env["HOME"], fixture.home)
#                 self.assertEqual(fixture.env["TMPDIR"], fixture.home)
#                 for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "NODE_OPTIONS"):
#                     self.assertNotIn(key, fixture.env)
#                 for name in ("claude", "codex"):
#                     settings = json.loads(Path(fixture.home, ".arbol", f"arbol-{name}-driver.json").read_text())
#                     self.assertEqual(settings["toolPath"], fixture.tool_path)
#                 self.assertEqual(await fixture.received(), [])
#                 await scenario.run(fixture)
#                 record = (await fixture.received())[0]
#                 self.assertEqual(record["workingDirectory"], fixture.home)
#                 self.assertIn("ARBOL_TEST_TIME_SCALE", record["environment"])
#                 self.assertNotIn("NODE_OPTIONS", record["environment"])
#             return dataclasses.replace(scenario, run=run)
#
#         selected = [wrap(scenario) for scenario in select_scenarios("C31,C32")]
#         self.assertEqual(await run_suite(COMMAND, selected, write=lambda line: None), 0)
#         self.assertNotEqual(homes[0], homes[1])
#         for home in homes:
#             self.assertTrue(gone(home))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/tests/test_runner.py::Runner.test_runner_failure
# Reason: Runner self-check repeats straightforward parsing/selection/status behavior or synthetic wrapper coverage; retained timeout checks actual descendant cleanup, the consequential integration risk. Case reviewed: runner.failure reports expected and received, continues, and cleans both homes.
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/tests/test_runner.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_runner_failure(self) -> None:
#         """runner.failure reports expected and received, continues, and cleans both homes."""
#         homes: list[str] = []
#         reports: list[str] = []
#
#         def wrap(scenario: Scenario) -> Scenario:
#             async def run(home: ScenarioHome) -> None:
#                 homes.append(home.home)
#                 await scenario.run(home)
#             return dataclasses.replace(scenario, run=run)
#
#         selected = [wrap(scenario) for scenario in select_scenarios("C31,C32")]
#         self.assertEqual(await run_suite([*COMMAND, "--fixture=wrong"], selected, write=reports.append), 1)
#         self.assertRegex("\n".join(reports),
#                          r"PASS C31[\s\S]*FAIL C32[\s\S]*Contract version[\s\S]*Expected: 1[\s\S]*Received: 99")
#         self.assertEqual(reports[-1], "1/2 scenarios passed.")
#         for home in homes:
#             self.assertTrue(gone(home))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/tests/test_runner.py::Runner.test_runner_invalid_json
# Reason: Runner self-check repeats straightforward parsing/selection/status behavior or synthetic wrapper coverage; retained timeout checks actual descendant cleanup, the consequential integration risk. Case reviewed: runner.invalid-json and exit statuses cannot pass as valid info.
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/tests/test_runner.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_runner_invalid_json(self) -> None:
#         """runner.invalid-json and exit statuses cannot pass as valid info."""
#         for mode in ("bad-json", "wrong-exit"):
#             reports: list[str] = []
#             self.assertEqual(await run_suite([*COMMAND, f"--fixture={mode}"], select_scenarios("C32"),
#                                              write=reports.append), 1)
#             self.assertRegex("\n".join(reports), r"FAIL C32[\s\S]*Expected:[\s\S]*Received:")
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/tests/test_runner.py::Runner.test_runner_commands
# Reason: Runner self-check repeats straightforward parsing/selection/status behavior or synthetic wrapper coverage; retained timeout checks actual descendant cleanup, the consequential integration risk. Case reviewed: runner.commands handles spaces and single quotes without a shell.
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/tests/test_runner.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_runner_commands(self) -> None:
#         """runner.commands handles spaces and single quotes without a shell."""
#         self.assertEqual(command_words("node 'a b' \"c d\" '' e\\ f"), ["node", "a b", "c d", "", "e f"])
#         self.assertEqual(command_words('node "$(never-execute)" ";"'), ["node", "$(never-execute)", ";"])
#         for invalid in ("", "'unclosed", "node \\"):
#             with self.assertRaises(ValueError):
#                 command_words(invalid)
#         temp = tempfile.mkdtemp(prefix="suite's path ")
#         self.addCleanup(shutil.rmtree, temp, True)
#         filename = os.path.join(temp, "fake Driver's program.py")
#         shutil.copyfile(FAKE, filename)
#         command = resolve_command(f"{shell_quote(sys.executable)} {shell_quote(filename)}")
#         self.assertEqual(await run_suite(command, select_scenarios("C1,C31,C32"), write=lambda line: None), 0)
#         program = os.path.basename(sys.executable)
#         self.assertEqual(resolve_command(f"{program} conformance/tests/fake_driver.py", str(ROOT),
#                                          os.path.dirname(sys.executable)), COMMAND)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/tests/test_runner.py::Runner.test_runner_output
# Reason: Runner self-check repeats straightforward parsing/selection/status behavior or synthetic wrapper coverage; retained timeout checks actual descendant cleanup, the consequential integration risk. Case reviewed: runner.output preserves Unicode split across pipe chunks.
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/tests/test_runner.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_runner_output(self) -> None:
#         """runner.output preserves Unicode split across pipe chunks."""
#         script = ("import sys, time\nsys.stdout.buffer.write(b'\\xc3'); sys.stdout.flush(); time.sleep(0.025)\n"
#                   "sys.stdout.buffer.write(b'\\xb1'); sys.stdout.flush()")
#         result = await invoke([sys.executable, "-c", script], [], cwd=str(ROOT), env={}, timeout_ms=1500)
#         self.assertEqual(result["status"], 0)
#         self.assertEqual(result["stdout"], "ñ")
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/tests/test_runner.py::Runner.test_runner_cancellation
# Reason: Runner self-check repeats straightforward parsing/selection/status behavior or synthetic wrapper coverage; retained timeout checks actual descendant cleanup, the consequential integration risk. Case reviewed: runner.cancellation stops the active invocation and removes its home.
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/tests/test_runner.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_runner_cancellation(self) -> None:
#         """runner.cancellation stops the active invocation and removes its home."""
#         controller = Abort()
#         state = {"path": ""}
#
#         async def run(home: ScenarioHome) -> None:
#             state["path"] = home.home
#             pending = asyncio.ensure_future(home.call(["info"]))
#             timer = asyncio.get_running_loop().call_later(0.1, controller.abort)
#             try:
#                 await pending
#             finally:
#                 timer.cancel()
#
#         reports: list[str] = []
#         selected = [Scenario("cancel", "cancelled Driver", "runner self-test", [], run)]
#         self.assertEqual(await run_suite([*COMMAND, "--fixture=hang"], selected, signal_=controller,
#                                          write=reports.append), 2)
#         self.assertRegex("\n".join(reports), r"Driver invocation was stopped")
#         self.assertTrue(gone(state["path"]))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/tests/test_runner.py::Runner.test_runner_selection
# Reason: Runner self-check repeats straightforward parsing/selection/status behavior or synthetic wrapper coverage; retained timeout checks actual descendant cleanup, the consequential integration risk. Case reviewed: runner.selection runs only requested, known scenarios.
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/tests/test_runner.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_runner_selection(self) -> None:
#         """runner.selection runs only requested, known scenarios."""
#         self.assertEqual([scenario.id for scenario in select_scenarios("C32")], ["C32"])
#         self.assertEqual([scenario.id for scenario in select_scenarios("C32,C31 C31")], ["C31", "C32"])
#         self.assertEqual([scenario.id for scenario in select_scenarios("C1,C40")], ["C1", "C40"])
#         for ids in ("", "C21", "C31,C99"):
#             with self.assertRaises(ValueError):
#                 select_scenarios(ids)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/tests/test_runner.py::Runner.test_runner_cli
# Reason: Runner self-check repeats straightforward parsing/selection/status behavior or synthetic wrapper coverage; retained timeout checks actual descendant cleanup, the consequential integration risk. Case reviewed: runner.cli exposes the program, selection and meaningful failure statuses.
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/tests/test_runner.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_runner_cli(self) -> None:
#         """runner.cli exposes the program, selection and meaningful failure statuses."""
#         driver = " ".join(shell_quote(word) for word in [*COMMAND, "--fixture=wrong"])
#         options: dict[str, Any] = {"cwd": str(ROOT), "env": {"PATH": os.environ.get("PATH", "")}, "timeout_ms": 15000}
#         program = [sys.executable, "-I", CLI]
#         passed = await invoke(program, ["--driver", driver, "--only=C31"], **options)
#         self.assertEqual(passed["status"], 0)
#         self.assertRegex(passed["stdout"], r"1/1 scenarios passed")
#         self.assertNotRegex(passed["stdout"], r"C32")
#         failed = await invoke(program, ["--driver", driver, "--only", "C32"], **options)
#         self.assertEqual(failed["status"], 1)
#         self.assertRegex(failed["stdout"], r"FAIL C32[\s\S]*Expected: 1[\s\S]*Received: 99")
#         for args in ([], ["--driver", driver, "--only", "C21"], ["--driver", "missing-driver"], ["--unknown"],
#                      ["--driver", driver, "--driver", driver]):
#             refused = await invoke(program, args, **options)
#             self.assertEqual(refused["status"], 2, args)
#             self.assertRegex(refused["stderr"], r"Usage: arbol-conformance")
#             self.assertEqual(refused["stdout"], "")
# LOW-TIER-SOURCE-END
# LOW-TIER-END
