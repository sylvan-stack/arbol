"""C40: refusals before the vendor tool starts: unsigned Subscriptions and invalid run requests (DRV-1, DRV-2)."""

from __future__ import annotations

from ..check import check, equal, object_
from ..harness import Scenario, ScenarioHome
from ..js import parse, text_of
from .runs import stream


async def check_subscription_refusals(home: ScenarioHome, include_runs: bool = False) -> None:
    reply = await home.call(["subscriptions", "list"])
    equal("List exit status", reply["status"], 0)
    subscriptions = parse(reply["stdout"])
    check("Subscription array", isinstance(subscriptions, list) and len(subscriptions) > 0,
          "a nonempty Subscription array", subscriptions)
    for value in subscriptions:
        subscription = object_("Subscription", value)
        check("Identifier", isinstance(subscription["id"], str), "an identifier", subscription["id"])
        for command in ("models", "check"):
            failure = await home.json(["subscriptions", command, subscription["id"]])
            equal(f"{command} exit status", failure.process["status"], 1)
            equal(f"{command} error", object_("Error", failure.result["error"])["code"], "not_signed_in")
        usage = await home.json(["subscriptions", "usage", subscription["id"]])
        equal("Usage exit status", usage.process["status"], 0)
        equal("Usage outcome", usage.result["outcome"], "needs_sign_in")
        equal("No numeric windows for unsigned usage", usage.result["windows"], [])
        if include_runs:
            run_ = stream(await home.call(["run", "--subscription", text_of(subscription["id"]), "answer"]), "failed")
            equal("Unsigned run one final", len(run_), 1)
            equal("Unsigned run error", object_("Error", run_[0]["error"])["code"], "not_signed_in")
    equal("The vendor tool is never started", await home.received(), [])


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/c40.py::run
# async def run(home: ScenarioHome) -> None:
#     await check_subscription_refusals(home, True)
#     await run_refusals(home)
# TEST-TIER-DISABLED-END conformance/scenarios/c40.py::run
async def run(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c40 = Scenario("C40", "Subscription refusals before starting the tool",
               "unsigned models, check, usage and runs; folders, duplicate ID, models and effort",
               ["DRV-1.11", "DRV-2.2"], run)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/c40.py:8
# from .runs import run_refusals, stream
# TEST-TIER-IMPORTS-END conformance/scenarios/c40.py:8
