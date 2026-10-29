# Mid-tier source from conformance/scenarios/runs.py; see MID_TIER.md.
# Shared helpers and refusal entry points remain at the original path.

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/runs.py::run_c10
# async def run_c10(home: ScenarioHome) -> None:
#     identifier = await signed(home)
#     records = stream(await start(home, identifier, "answer", ["--label", "exchange=41"]))
#     equal("First event", records[0]["type"], "started")
#     equal("Fresh conversation", records[0]["continuity"], "fresh")
#     check("Actual model", isinstance(records[0]["model"], str), "model from tool", records[0])
#     for event in records:
#         equal("Echoed labels", event["labels"], {"exchange": "41"})
#     equal("Whole answer despite partial delta", JSArray(event["text"] for event in of_type(records, "text")), ["answer"])
#     info = await home.json(["info"])
#     equal("Build identity", records[0]["driverBuild"], info.result["build"])
#     options = await run_models(home, identifier)
#     await home.settings({"defaultSubscription": identifier,
#                          "subscriptions": {identifier: {"defaultModel": options.model,
#                                                         "defaultEffort": options.effort}}})
#     defaults = stream(await home.call(["run", "answer"]))
#     equal("Default subscription", defaults[0]["subscriptionId"], identifier)
#     equal("Default effort", defaults[0]["effort"], "low")
#     received = at(await calls(home), -1)
#     arguments = prop(received, "arguments")
#     equal("Default model passed",
#           item(arguments, index_of(arguments, "--model") + 1) if includes(arguments, "--input-format")
#           else object_("Thread params", object_("Thread request", received["request"])["params"])["model"],
#           options.model)
#     path = join(home.home, "request.json")
#     write_file(path, text_of(stringify({"subscriptionId": identifier, "tools": "none", "history": [],
#                                         "input": {"role": "user", "text": "file message"},
#                                         "model": options.alternate, "effort": "high",
#                                         "systemPrompt": "Keep this exact.\nSecond line.",
#                                         "labels": {"source": "file"}})))
#     stream(await home.call(["run", "--request", path, "--model", options.model, "--effort", options.effort,
#                             "override"]))
#     input_ = at([record for record in await home.received() if record["stage"] == "input"], -1)
#     request = object_("Input", prop(input_, "checks")["input"])
#     if request["method"] == "turn/start":
#         content = object_("Turn params", request["params"])["input"]
#         check("Text input array", isinstance(content, list), "Codex text input", request)
#         equal("Option replaces message",
#               JSArray(JSObject(type=object_("Text input", value)["type"], text=object_("Text input", value)["text"])
#                       for value in content), [{"type": "text", "text": "override"}])
#     else:
#         equal("Option replaces message", object_("Message", request["message"])["content"],
#               [{"type": "text", "text": "override"}])
#     before = read_file(path)
#     stream(await home.call(["run", "--request", path]))
#     equal("Request unchanged", read_file(path), before)
#     settings = join(home.home, ".arbol", "arbol-" + text_of(info.result["driver"]) + "-driver.json")
#     write_file(settings, "{")
#     refused = stream(await start(home, identifier), "failed")
#     equal("Unreadable settings only final", len(refused), 1)
#     equal("Settings refusal", prop(refused[0]["error"], "code"), "invalid_input")
# TEST-TIER-DISABLED-END conformance/scenarios/runs.py::run_c10

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/runs.py::run_c11
# async def run_c11(home: ScenarioHome) -> None:
#     identifier = await signed(home)
#     records = stream(await start(home, identifier, "answer", ["--tools", "all", "--cwd", home.home]))
#     begun = find_index(records, lambda event, _: event["type"] == "tool_started")
#     ended = find_index(records, lambda event, _: event["type"] == "tool_finished")
#     check("Text before call", find_index(records, lambda event, _: event["type"] == "text") < begun,
#           "text before tool_started", records)
#     check("Text after call",
#           find_index(records, lambda event, index: index > ended and event["type"] == "text") > ended,
#           "text after call", records)
#     equal("Normalized command", prop(item(records, begun), "name"), "shell")
#     input_ = object_("Command input", prop(item(records, begun), "input"))
#     equal("Command input", input_["command"], "printf fixture-output")
#     if "cwd" in input_:
#         equal("Command directory", input_["cwd"], home.home)
#     equal("One matching finish",
#           len([event for event in records if event["type"] == "tool_finished"
#                and strict(event["callId"], prop(item(records, begun), "callId"))]), 1)
#     result = object_("Shell result", prop(item(records, ended), "result"))
#     equal("Shell output", result["output"], "fixture-output")
#     if "exitCode" in result:
#         equal("Shell exit code", result["exitCode"], 0)
# TEST-TIER-DISABLED-END conformance/scenarios/runs.py::run_c11

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/runs.py::run_c12
# async def run_c12(home: ScenarioHome) -> None:
#     records = stream(await start(home, await signed(home)), "failed")
#     equal("Failure code", prop(at(records, -1)["error"], "code"), "vendor_error")
# TEST-TIER-DISABLED-END conformance/scenarios/runs.py::run_c12

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/runs.py::run_c13
# async def run_c13(home: ScenarioHome) -> None:
#     records = stream(await start(home, await signed(home)))
#     usage = JSArray(event["usage"] for event in of_type(records, "usage"))
#     equal("Input totals", JSArray(prop(entry, "inputTokens") for entry in usage), [3, 7, 7])
#     equal("Output totals", JSArray(prop(entry, "outputTokens") for entry in usage), [2, 5, 5])
#     for entry in usage:
#         for field in ("cachedInputTokens", "reasoningTokens", "costUsd"):
#             equal("Unreported " + field, has(entry, field), False)
#     equal("Final usage", at(records, -1)["usage"], at(usage, -1))
# TEST-TIER-DISABLED-END conformance/scenarios/runs.py::run_c13

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/runs.py::run_c18
# async def run_c18(home: ScenarioHome) -> None:
#     identifier = await signed(home)
#     good, bad = await asyncio.gather(start(home, identifier, "hold"), start(home, identifier, "fail"))
#     stream(good)
#     stream(bad, "failed")
#     await home.part("malformed")
#     malformed = await start(home, identifier)
#     stream(malformed, "failed")
#     await home.part("plain")
#     stream(await start(home, identifier))
#     slow = home.start(["run", "--subscription", identifier, "slow"])
#     slow.child.stdout.pause()
#     try:
#         await delay(300)
#         began = now_monotonic()
#         stream(await start(home, identifier))
#         check("Peer completes while output blocked", now_monotonic() - began < 5000, "under 5 seconds",
#               now_monotonic() - began)
#     finally:
#         slow.child.stdout.resume()
#         await slow.dispose()
# TEST-TIER-DISABLED-END conformance/scenarios/runs.py::run_c18

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/runs.py::run_c19
# async def run_c19(home: ScenarioHome) -> None:
#     records = stream(await start(home, await signed(home)))
#     equal("One whole text", len(of_type(records, "text")), 1)
#     equal("No calls", len(of_type(records, "tool_started")), 0)
#     received = at(await calls(home), -1)
#     arguments = prop(received, "arguments")
#     if includes(arguments, "--input-format"):
#         check("Tools off", includes(arguments, "--tools") and item(arguments, index_of(arguments, "--tools") + 1) == "",
#               "empty tool list", received)
#         check("No persistence", includes(arguments, "--no-session-persistence"), "--no-session-persistence", received)
#     else:
#         params = object_("Thread params", object_("Thread request", received["request"])["params"])
#         equal("Read-only sandbox", params["sandbox"], "read-only")
#         equal("No permission escalation", params["approvalPolicy"], "never")
#         equal("No persistence", params["ephemeral"], True)
#         turn = at([record for record in await home.received() if record["stage"] == "input"], -1)
#         equal("Network off", object_("Turn sandbox", object_("Turn params", object_(
#             "Turn request", prop(turn, "request"))["params"])["sandboxPolicy"])["networkAccess"], False)
#     equal("Work folder removed", not exists(received["workingDirectory"]), True)
#     info = await home.json(["info"])
#     equal("No temporary run folders", sorted_entries(join(text_of(info.result["stateDirectory"]), "tmp")), [])
# TEST-TIER-DISABLED-END conformance/scenarios/runs.py::run_c19

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/runs.py::run_c20
# async def run_c20(home: ScenarioHome) -> None:
#     identifier = await signed(home)
#     for part in ("text", "structure"):
#         await home.part(part)
#         records = stream(await start(home, identifier, "answer", ["--tools", "all", "--cwd", home.home]))
#         result = find(records, lambda event: event["type"] == "tool_finished")
#         equal("Cut flag", prop(result, "truncated"), True)
#         value = result["result"]
#         check("Result length", byte_length(value if isinstance(value, str) else stringify(value)) <= 200 * 1024,
#               "at most 200 KiB", result)
#         check("Whole UTF-8 characters", "�" not in text_of(stringify(result["result"])), "valid UTF-8",
#               result["result"])
# TEST-TIER-DISABLED-END conformance/scenarios/runs.py::run_c20

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/runs.py::run_c33
# async def run_c33(home: ScenarioHome) -> None:
#     identifier = await check_run_without_control(home)
#     await home.part("question")
#     unhandled = stream(await start(home, identifier, "answer", ["--tools", "all", "--cwd", home.home]))
#     equal("No caller ask", len(of_type(unhandled, "ask_opened")), 0)
#     response = find(await home.received(), lambda record: record["stage"] == "response")
#     if (await home.json(["info"])).result["driver"] == "codex":
#         refusal = object_("Unsupported question error",
#                           object_("Unsupported question response", prop(response, "request"))["error"])
#         equal("Unhandled Codex question refused", refusal["code"], -32601)
#         check("Decline explains unsupported question", isinstance(refusal["message"], str)
#               and test(r"not supported|unsupported", refusal["message"], re.I), "unsupported question message", refusal)
#     else:
#         def decision() -> Any:
#             return prop(prop(prop(prop(response, "checks"), "input"), "response"), "response")
#         equal("Unhandled ask declined", prop(decision(), "behavior"), "deny")
#         check("Decline explains no caller", test(NOBODY_ANSWERS, text_of(prop(decision(), "message")), re.I),
#               "nobody to answer", response)
#     equal("Question tool not enabled", includes(prop(response, "arguments"), "--permission-prompt-tool"), False)
#     await home.part("plain")
#     active = home.start(["run", "--subscription", identifier, "--run-id", "visible-run", "--control", "hold"])
#     try:
#         active.child.stdin.write("not-json\n")
#         active.send({"type": "answer", "askId": "missing", "answer": {}})
#         listed: Any = JSArray()
#         for _ in range(100):
#             listed = parse((await home.call(["runs", "list"]))["stdout"])
#             if some(listed, lambda entry: prop(entry, "runId") == "visible-run", "listed"):
#                 break
#             await delay(10)
#         check("Active run listed", some(listed, lambda entry: prop(entry, "runId") == "visible-run"
#                                         and strict(entry["subscriptionId"], identifier), "listed"),
#               "visible-run", listed)
#         records = stream(await active.done)
#         equal("Control refusals", len(of_type(records, "control_refused")), 2)
#     finally:
#         await active.dispose()
#     equal("No ended runs listed", parse((await home.call(["runs", "list"]))["stdout"]), [])
#     await home.part("stopping")
#     stoppable = home.start(["run", "--subscription", identifier, "--run-id", "stop-from-peer", "answer"])
#     try:
#         def started() -> bool:
#             return any(prop(event, "type") == "started" for event in stoppable.lines)
#         for _ in range(100):
#             if started():
#                 break
#             await delay(10)
#         check("Run started before peer stop", started(), "started event", stoppable.lines)
#         stopped = await home.call(["runs", "stop", "stop-from-peer"])
#         equal("Peer stop exit", stopped["status"], 0)
#         equal("Peer stop output", stopped["stdout"], "")
#         stream(await stoppable.done, "cancelled")
#         last = at(stoppable.lines, -1)
#         equal("Final emitted before stop returns", get(last, "type") if truthy(last) else last, "finished")
#     finally:
#         await stoppable.dispose()
# TEST-TIER-DISABLED-END conformance/scenarios/runs.py::run_c33

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/runs.py::run_c42
# async def run_c42(home: ScenarioHome) -> None:
#     identifier = await signed(home)
#     records = stream(await start(home, identifier), "failed")
#     final = at(records, -1)
#     equal("Output retained", JSArray(event["text"] for event in of_type(records, "text")), ["answer"])
#     equal("Produced output", final["producedOutput"], True)
#     equal("Unfinished call named", final["unfinishedCalls"], ["fixture-call"])
#     equal("Usage retained", prop(final["usage"], "inputTokens"), 3)
#     equal("Call closed once", len(of_type(records, "tool_finished")), 1)
#     equal("No retry", len(await calls(home)), 1)
# TEST-TIER-DISABLED-END conformance/scenarios/runs.py::run_c42

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/runs.py::run_c43
# async def run_c43(home: ScenarioHome) -> None:
#     path = join(home.home, "blocked-state")
#     write_file(path, "file")
#     records = stream(await home.call(["run", "--state-dir", path, "answer"]), "failed")
#     equal("Only final event", len(records), 1)
#     equal("Internal failure", prop(records[0]["error"], "code"), "internal")
# TEST-TIER-DISABLED-END conformance/scenarios/runs.py::run_c43

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/runs.py:6
# import asyncio
# TEST-TIER-IMPORTS-END conformance/scenarios/runs.py:6

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/runs.py:8
# import re
# TEST-TIER-IMPORTS-END conformance/scenarios/runs.py:8

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/runs.py:14
# from ..js import (
#     UNDEFINED,
#     JSArray,
#     JSObject,
#     get,
#     is_number,
#     join,
#     parse,
#     same_value,
#     stringify,
#     text_of,
#     trim,
#     truthy,
#     utf8_length,
# )
# TEST-TIER-IMPORTS-END conformance/scenarios/runs.py:14

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/runs.py:29
# from .support import (
#     at,
#     date_parse,
#     delay,
#     exists,
#     find,
#     includes,
#     index_of,
#     is_finite,
#     item,
#     now_monotonic,
#     read_file,
#     readdir,
#     test,
#     write_file,
# )
# TEST-TIER-IMPORTS-END conformance/scenarios/runs.py:29

raise RuntimeError("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.")
