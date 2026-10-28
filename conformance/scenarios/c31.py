"""C31: missing and old vendor tools (DRV-0, DRV-4)."""

from __future__ import annotations

from ..harness import Scenario, ScenarioHome


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/c31.py::run
# async def run(home: ScenarioHome) -> None:
#     for part in ("missing", "old"):
#         await home.part(part, part == "missing")
#         reply = await home.json(["info"])
#         equal(f"{part}: info exit status", reply.process["status"], 0)
#         _, tool, name = inspect_info(reply.result)
#         equal(f"{part}: tool support", tool["supported"], False)
#         needed = text("Needed tool version", tool["oldestSupported"])
#         if part == "missing":
#             equal("Missing tool path is absent", tool["path"], UNDEFINED)
#             equal("Missing tool version is absent", tool["version"], UNDEFINED)
#         else:
#             equal("Old tool path", tool["path"], home.tool_path)
#             found = text("Old tool version", tool["version"])
#             check("Old version is below the support boundary", version_order(found, needed) < 0,
#                   f"a version below {needed}", found)
#         failure = await home.json(["dev", "probe"])
#         equal(f"{part}: refused operation exit status", failure.process["status"], 1)
#         error = object_(f"{part}: typed error", failure.result["error"])
#         equal(f"{part}: error code", error["code"], "tool_missing" if part == "missing" else "tool_unsupported")
#         equal(f"{part}: retryable", error["retryable"], False)
#         detail = object_(f"{part}: error detail", error["detail"])
#         equal(f"{part}: needed version in error", detail["neededVersion"], needed)
#         if part == "old":
#             equal("Found version in error", detail["toolVersion"], tool["version"])
#         message = text(f"{part}: error message", error["message"])
#         for word in [name, needed, *([tool["version"]] if part == "old" else [])]:
#             check(f"{part}: error names tool and versions", isinstance(word, str) and word in message,
#                   f"a message containing {word}", message)
#         if part == "missing":
#             equal("Missing tool was never started", await home.received(), [])
#         else:
#             await version_records(home, "old")
#             for record in await home.received():
#                 equal("Old version matches the stand-in", tool["version"], record["toolVersion"])
# TEST-TIER-DISABLED-END conformance/scenarios/c31.py::run
async def run(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c31 = Scenario("C31", "Missing and old vendor tools", "missing and old", ["DRV-0.6", "DRV-4.14"], run)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/c31.py:5
# from ..check import check, equal, object_, text
# TEST-TIER-IMPORTS-END conformance/scenarios/c31.py:5
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/c31.py:7
# from ..js import UNDEFINED
# TEST-TIER-IMPORTS-END conformance/scenarios/c31.py:7
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/c31.py:8
# from .info import inspect_info, version_order, version_records
# TEST-TIER-IMPORTS-END conformance/scenarios/c31.py:8
