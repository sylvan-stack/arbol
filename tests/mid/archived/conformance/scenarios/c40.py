# Mid-tier source from conformance/scenarios/c40.py; see MID_TIER.md.
# Shared helpers and refusal entry points remain at the original path.

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/c40.py::run
# async def run(home: ScenarioHome) -> None:
#     await check_subscription_refusals(home, True)
#     await run_refusals(home)
# TEST-TIER-DISABLED-END conformance/scenarios/c40.py::run

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/c40.py:8
# from .runs import run_refusals, stream
# TEST-TIER-IMPORTS-END conformance/scenarios/c40.py:8

raise RuntimeError("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.")
