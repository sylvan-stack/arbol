
# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/c31.py::run
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: Run.
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/c31.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END
