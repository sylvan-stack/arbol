"""Running the scenarios and reporting each one (DRV-5, Interface)."""

from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import Callable

from .harness import Scenario
from .js import SPACE_CLASS
from .process import Abort


def scenarios() -> list[Scenario]:
    from .scenarios import SCENARIOS
    return list(SCENARIOS)


def select_scenarios(only: str | None = None) -> list[Scenario]:
    available = scenarios()
    if only is None:
        return available
    ids = [item for item in re.split(f"(?:{SPACE_CLASS}|,)+", only) if item]
    if not ids:
        raise ValueError("Give --only at least one scenario identifier.")
    for scenario_id in ids:
        if not any(scenario.id == scenario_id for scenario in available):
            raise ValueError(f"Unknown or unimplemented scenario: {scenario_id}. "
                             f"Available: {', '.join(scenario.id for scenario in available)}.")
    return [scenario for scenario in available if scenario.id in ids]


def _stdout(line: str) -> None:
    from .cli import write
    write(sys.stdout, line + "\n")


async def _signals() -> None:
    """Runs the handler of a SIGINT or SIGTERM that came while the runner worked without yielding. Node awaited its
    file operations (resolving the Driver, removing a home), so its event loop had run the handler before the
    runner looked at the abort; asyncio needs one turn to read the signal and the next to run its handler."""
    for _ in range(3):
        await asyncio.sleep(0)


# TEST-TIER-DISABLED-BEGIN conformance/runner.py::run_suite
# async def run_suite(command: list[str], selected: list[Scenario], *, timeout_ms: float | None = None,
#                     signal_: Abort | None = None, write: Callable[[str], None] | None = None) -> int:
#     write = write or _stdout
#     passed = 0
#     if signal_ is not None:
#         await _signals()
#     native_pi = False
#     discovery = await ScenarioHome.create("identity", command, min(timeout_ms or 15000, 1500), signal_)
#     try:
#         await discovery.part("missing", missing=True)
#         identity = await discovery.json(["info"])
#         native_pi = identity.result.get("driver") == "pi"
#     except Exception:
#         # The selected scenarios report malformed/unavailable Drivers themselves.
#         pass
#     finally:
#         await discovery.dispose()
#     for scenario in selected:
#         fixture: ScenarioHome | None = None
#         scope = scenario.scope
#         try:
#             if signal_ is not None:
#                 signal_.throw_if_aborted()
#             fixture = await ScenarioHome.create(scenario.id, command, timeout_ms, signal_)
#             if native_pi:
#                 from .scenarios.pi import SCOPES, prepare, run
#                 scope = SCOPES.get(scenario.id, "unimplemented Pi variant")
#                 await prepare(fixture)
#                 await run(fixture)
#             else:
#                 await scenario.run(fixture)
#             await fixture.dispose()
#             fixture = None
#             write(f"PASS {scenario.id} — {scenario.title} ({scope})")
#             passed += 1
#         except Exception as error:
#             write(f"FAIL {scenario.id} — {scenario.title} ({scope})")
#             write(f"  {message_of(error)}")
#             if isinstance(error, Mismatch):
#                 write(f"  Expected: {inspect(error.expected)}")
#                 write(f"  Received: {inspect(error.actual, 2048)}")
#         finally:
#             if fixture is not None:
#                 await fixture.dispose()
#         if signal_ is not None:
#             await _signals()
#             if signal_.aborted:
#                 break
#     write(f"{passed}/{len(selected)} scenarios passed.")
#     if signal_ is not None and signal_.aborted:
#         return 2
#     return 0 if passed == len(selected) else 1
# TEST-TIER-DISABLED-END conformance/runner.py::run_suite
async def run_suite(command: list[str], selected: list[Scenario], *, timeout_ms: float | None = None,
                    signal_: Abort | None = None, write: Callable[[str], None] | None = None) -> int:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN conformance/runner.py:10
# from .check import Mismatch, message_of
# TEST-TIER-IMPORTS-END conformance/runner.py:10
# TEST-TIER-IMPORTS-BEGIN conformance/runner.py:11
# from .harness import Scenario, ScenarioHome
# TEST-TIER-IMPORTS-END conformance/runner.py:11
# TEST-TIER-IMPORTS-BEGIN conformance/runner.py:12
# from .inspect import inspect
# TEST-TIER-IMPORTS-END conformance/runner.py:12
