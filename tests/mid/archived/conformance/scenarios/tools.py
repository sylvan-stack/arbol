# Mid-tier source from conformance/scenarios/tools.py; see MID_TIER.md.
# Shared helpers and refusal entry points remain at the original path.

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/tools.py::run_c25
# async def run_c25(home: ScenarioHome) -> None:
#     if await is_codex(home):
#         await codex_permissions(home)
#         return
#     identifier = await signed(home)
#     records = stream(await home.call(run_args(home, identifier)))
#     equal("Permission notices",
#           count(records, lambda event: event["type"] == "notice" and event["code"] == "permission_answered"), 2)
#     equal("No ask", count(records, lambda event: event["type"] == "ask_opened"), 0)
#     responses = [record for record in await home.received() if record["stage"] == "response"]
#
#     def answer(n: int) -> JSObject:
#         return object_("Response", object_("Envelope", prop(prop(item(responses, n), "checks"), "input"))["response"])
#
#     equal("Permission allowed", object_("Allow", answer(0)["response"]),
#           {"behavior": "allow", "updatedInput": {"file_path": "fixture", "content": "value"}})
#     equal("Permission declined", object_("Deny", answer(1)["response"])["behavior"], "deny")
#     check("Deny has reason", isinstance(object_("Deny", answer(1)["response"])["message"], str), "message", answer(1))
#     await home.part("missing-id")
#     failed = stream(await home.call(run_args(home, identifier)), "failed")
#     equal("Malformed protocol fails", prop(at(failed, -1)["error"], "code"), "tool_unsupported")
#     await home.part("plain")
#     stream(await home.call(run_args(home, identifier)))
# TEST-TIER-DISABLED-END conformance/scenarios/tools.py::run_c25

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/tools.py::run_c35
# async def run_c35(home: ScenarioHome) -> None:
#     if await is_codex(home):
#         await codex_completed_tools(home)
#         return
#     identifier = await signed(home)
#     records = stream(await home.call(run_args(home, identifier)))
#     equal("Refused call reason", prop(ended(records, "refused"), "error"), "Claude refused this command.")
#     equal("Refused call failed", prop(ended(records, "refused"), "ok"), False)
#     equal("Shell input", prop(begun(records, "refused"), "input"), {"command": "rejected-command", "cwd": home.home})
#     equal("Main answer",
#           [event["text"] for event in records if event["type"] == "text" and not truthy(event["parentCallId"])],
#           ["main-before", "main-after-agent", "main-after-command"])
#     for event in [event for event in records if event["callId"] == "subcall" or event["text"] == "sub-agent-only"]:
#         equal("Sub-agent parent", event["parentCallId"], "agent")
#     for event in [event for event in records if event["type"] == "tool_started"]:
#         equal("Call paired", paired(records, event), 1)
#     input_ = find(await home.received(), lambda record: record["stage"] == "input")
#     for option in ("--tools", "--allowedTools", "--disallowedTools", "--setting-sources", "--strict-mcp-config"):
#         equal("No restrictive " + option, option in prop(input_, "arguments"), False)
#     arguments = prop(input_, "arguments")
#     equal("Trusted mode", item(arguments, index_of(arguments, "--permission-mode") + 1), "bypassPermissions")
#     equal("Memory disabled", prop(prop(input_, "checks"), "memoryOff"), True)
#     equal("Background completed",
#           count(await home.received(), lambda record: record["stage"] == "background-ended"), 1)
#     output = await home.call([*run_args(home, identifier), "--output", "text"])
#     equal("Text output completed", output["status"], 0)
#     equal("Sub-agent excluded", output["stdout"], "main-beforemain-after-agentmain-after-command")
#     await home.part("early-exit")
#     failed = stream(await home.call(run_args(home, identifier)), "failed")
#     equal("Premature exit refused", prop(at(failed, -1)["error"], "code"), "tool_failed")
# TEST-TIER-DISABLED-END conformance/scenarios/tools.py::run_c35

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/tools.py::run_c36
# async def run_c36(home: ScenarioHome) -> None:
#     identifier = await signed(home)
#     info = await home.json(["info"])
#     if info.result["driver"] == "codex":
#         records = stream(await home.call(run_args(home, identifier)))
#         equal("Codex carries no questions",
#               count(records, lambda event: event["type"] == "ask_opened" or event["type"] == "ask_closed"), 0)
#         equal("Every unsupported question gives notice",
#               count(records, lambda event: event["type"] == "notice" and event["code"] == "unexpected_request"), 2)
#         responses = [record for record in await home.received() if record["stage"] == "response"]
#         equal("Both questions settled", len(responses), 2)
#         for response in responses:
#             error = object_("Unsupported question error",
#                             object_("Question response", response["request"])["error"])
#             equal("Codex question refusal", error["code"], -32601)
#             check("Question refusal explains why",
#                   isinstance(error["message"], str) and test(r"not supported|unsupported", error["message"], re.I),
#                   "unsupported question message", error)
#         return
#     active = home.start([*run_args(home, identifier), "--control"])
#     try:
#         await wait("Three questions open",
#                    lambda: count(active.lines, lambda event: is_type(event, "ask_opened")) == 3)
#         await delay(150)
#         equal("No question timeout", count(active.lines, lambda event: is_type(event, "finished")), 0)
#
#         def answers(ask_id: str, choices: Any) -> None:
#             active.send({"type": "answer", "askId": ask_id, "answer": {"type": "answers", "answers": choices}})
#
#         invalid: list[dict[str, list[str]]] = [{}, {"Choose first": ["Green"]}, {"Choose first": ["Blue", "Red"]},
#                                                {"Choose first": []}, {"Choose first": ["Blue"], "extra": ["Red"]}]
#         for choices in invalid:
#             answers("first", choices)
#         answers("withdrawn", {"Choose withdrawn": ["Blue"]})
#         answers("unknown", {})
#         answers("second", {"Choose second": ["Blue", "Blue"]})
#         await wait("All invalid answers refused",
#                    lambda: count(active.lines, lambda event: is_type(event, "control_refused")) == 8)
#         answers("second", {"Choose second": ["Red", "Blue"]})
#         await wait("Second answered", lambda: any(is_type(event, "ask_closed") and prop(event, "askId") == "second"
#                                                   for event in active.lines))
#         active.send({"type": "answer", "askId": "second", "answer": {}})
#         answers("first", {"Choose first": ["Blue"]})
#         records = stream(await active.done)
#         equal("Refusal codes",
#               [prop(event["error"], "code") for event in records if event["type"] == "control_refused"],
#               ["invalid_input", "invalid_input", "invalid_input", "invalid_input", "invalid_input", "not_found",
#                "not_found", "invalid_input"])
#         equal("Answered order", [event["askId"] for event in records
#                                  if event["type"] == "ask_closed" and event["reason"] == "answered"],
#               ["second", "first"])
#         for ask in [event for event in records if event["type"] == "ask_opened"]:
#             check("Call starts before ask", call_index(records, ask) < index_of(records, ask),
#                   "tool_started before ask_opened", records)
#             equal("Ask closes once", len([event for event in records
#                                           if event["type"] == "ask_closed" and same(event["askId"], ask["askId"])]), 1)
#         responses = [record for record in await home.received() if record["stage"] == "response"]
#         equal("Exactly two delivered answers", len(responses), 2)
#         mapped = prop(prop(prop(prop(responses[0]["checks"]["input"], "response"), "response"), "updatedInput"),
#                       "answers")
#         equal("Multiple choices mapped", mapped, {"Choose second": "Red, Blue"})
#     finally:
#         await active.dispose()
#     await home.part("decline")
#     declined = home.start([*run_args(home, identifier), "--control"])
#     try:
#         await wait("Decline question opens", lambda: any(is_type(event, "ask_opened") for event in declined.lines))
#         declined.send({"type": "answer", "askId": "decline", "answer": {"type": "decline"}})
#         records = stream(await declined.done, "cancelled")
#         equal("Decline closes question",
#               prop(find(records, lambda event: event["type"] == "ask_closed"), "reason"), "answered")
#         response = at([record for record in await home.received() if record["stage"] == "response"], -1)
#         equal("Decline interrupts",
#               prop(prop(prop(prop(prop(response, "checks"), "input"), "response"), "response"), "interrupt"), True)
#     finally:
#         await declined.dispose()
# TEST-TIER-DISABLED-END conformance/scenarios/tools.py::run_c36

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/tools.py::run_c9
# async def run_c9(home: ScenarioHome) -> None:
#     await owner_scenario(home, False)
# TEST-TIER-DISABLED-END conformance/scenarios/tools.py::run_c9

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/tools.py::run_c37
# async def run_c37(home: ScenarioHome) -> None:
#     await owner_scenario(home, True)
# TEST-TIER-DISABLED-END conformance/scenarios/tools.py::run_c37

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/tools.py:17
# from .support import (
#     at,
#     delay,
#     find,
#     index_of,
#     item,
#     mkdir,
#     now_monotonic,
#     read_file,
#     readdir,
#     readlink,
#     test,
#     write_file,
# )
# TEST-TIER-IMPORTS-END conformance/scenarios/tools.py:17

raise RuntimeError("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.")
