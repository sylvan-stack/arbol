# Test implementations moved to tests/mid/archived/conformance/scenarios/c1.py.
"""C1: local Subscription records (DRV-1)."""

from __future__ import annotations

from ..harness import Scenario, ScenarioHome


async def run(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c1 = Scenario("C1", "Local Subscription records", "families, create, list, relabel and removal",
              ["DRV-1.1 (families, create, list and relabel)", "DRV-1.14 (list)", "DRV-1.15",
               "DRV-1.23 (create and update)"], run)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
