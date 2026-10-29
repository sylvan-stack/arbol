# Test implementations moved to tests/mid/archived/conformance/runner.py.
"""Running the scenarios and reporting each one (DRV-5, Interface)."""

from __future__ import annotations

import asyncio
import re
import sys

from .harness import Scenario
from .js import SPACE_CLASS


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
            raise ValueError(
                f"Unknown or unimplemented scenario: {scenario_id}. "
                f"Available: {', '.join(scenario.id for scenario in available)}."
            )
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



async def run_suite(*args: object, **kwargs: object) -> int:
    raise RuntimeError("Required shared mid-tier scenarios are disabled; restore them only for an explicit testing task.")
