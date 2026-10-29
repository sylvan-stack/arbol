# Test implementations moved to tests/mid/archived/conformance/scenarios/c31.py.
"""C31: missing and old vendor tools (DRV-0, DRV-4)."""

from __future__ import annotations

from ..harness import Scenario, ScenarioHome


async def run(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c31 = Scenario("C31", "Missing and old vendor tools", "missing and old", ["DRV-0.6", "DRV-4.14"], run)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
