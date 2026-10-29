# Mid-tier source from conformance/scenarios/stops.py; see MID_TIER.md.
# Shared helpers and refusal entry points remain at the original path.

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/stops.py::run_c15
# async def run_c15(home: ScenarioHome) -> None:
#     identifier = await signed(home)
#     home.env["ARBOL_TEST_TIME_SCALE"] = "1"
#     for part in ("text", "tool", "question", "subagent", "stubborn"):
#         if part == "question" and (await home.json(["info"])).result["driver"] == "codex":
#             continue
#         await home.part(part)
#         active = home.start(["run", "--subscription", identifier, "--tools", "all", "--cwd", home.home, "--control",
#                              "answer"])
#         try:
#             seen = await input_(home, part)
#             await wait_for("Partial output arrives",
#                            some_line(active.lines, lambda event: prop(event, "type") == "text_delta"))
#             if part == "question":
#                 await wait_for("Question is open",
#                                some_line(active.lines, lambda event: prop(event, "type") == "ask_opened"))
#             if part == "subagent":
#                 await wait_for("Sub-agent is working",
#                                some_line(active.lines, lambda event: truthy(prop(event, "parentCallId"))))
#
#                 async def ticking() -> bool:
#                     return any(record["stage"] == "subagent-tick" for record in await home.received())
#                 await wait_for("Sub-agent records active work", ticking)
#             start = now_monotonic()
#             active.send({"type": "stop"})
#             records = stream(await active.done, "cancelled")
#             elapsed = now_monotonic() - start
#             check("Stop finishes within fifteen seconds", elapsed < 15000, "< 15 seconds", elapsed)
#             check("Tool asked to interrupt",
#                   any(record["stage"] == "interrupt" and record["part"] == part for record in await home.received()),
#                   "interrupt request", await home.received())
#             if part == "stubborn":
#                 check("Escalation after two seconds", elapsed >= 1900 and elapsed < 5000, "about two seconds", elapsed)
#             equal("Earlier delta preserved", prop(find(records, lambda event: event["type"] == "text_delta"), "text"),
#                   "partial")
#             equal("Output reported", at(records, -1)["producedOutput"], True)
#             for call in [event for event in records if event["type"] == "tool_started"]:
#                 equal("Every call closed once", len([event for event in records if event["type"] == "tool_finished"
#                                                      and strictly_equal(event["callId"], call["callId"])]), 1)
#             if part == "tool":
#                 equal("Running call interrupted",
#                       prop(find(records, lambda event: event["type"] == "tool_finished"), "interrupted"), True)
#             if part == "question":
#                 equal("Question withdrawn", prop(find(records, lambda event: event["type"] == "ask_closed"), "reason"),
#                       "withdrawn")
#             await gone(prop(seen, "checks")["backgroundPid"])
#             await gone(prop(seen, "checks")["toolPid"])
#             before = len([record for record in await home.received() if record["stage"] == "subagent-tick"])
#             await delay(100)
#             equal("No sub-agent activity after final",
#                   len([record for record in await home.received() if record["stage"] == "subagent-tick"]), before)
#         finally:
#             await active.dispose()
#     await home.part("hold")
#     held = home.start(["run", "--subscription", identifier, "--control", "answer"])
#     try:
#         await input_(home, "hold")
#         await home.part("plain")
#         stream(await home.call(["run", "--subscription", identifier, "peer"]))
#         held.send({"type": "stop"})
#         stream(await held.done, "cancelled")
#     finally:
#         await held.dispose()
#     early = home.start(["run", "--subscription", identifier, "--control", "answer"])
#     try:
#         early.send({"type": "stop"})
#         stream(await early.done, "cancelled")
#     finally:
#         await early.dispose()
# TEST-TIER-DISABLED-END conformance/scenarios/stops.py::run_c15

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/stops.py::run_c16
# async def run_c16(home: ScenarioHome) -> None:
#     identifier = await signed(home)
#     stream(await home.call(["run", "--subscription", identifier, "--run-id", "ended", "answer"]))
#     for run in ("ended", "unknown"):
#         reply = await home.call(["runs", "stop", run])
#         equal("Successful stop", reply["status"], 0)
#         equal("No output", reply["stdout"], "")
# TEST-TIER-DISABLED-END conformance/scenarios/stops.py::run_c16

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/stops.py::run_c17
# async def run_c17(home: ScenarioHome) -> None:
#     identifier = await signed(home)
#     for path in ("normal", "linger", "SIGINT", "SIGTERM", "input", "output"):
#         part = "background" if path == "normal" else "linger" if path == "linger" else "hold"
#         await home.part(part)
#         after = len(await home.received())
#         active = home.start(["run", "--subscription", identifier, "--tools", "all", "--cwd", home.home, "--control",
#                              "answer"])
#         try:
#             seen = await input_(home, part, after)
#             pid = prop(seen, "checks")["backgroundPid"]
#             check("Background child was alive", is_number(pid) and prop(seen, "checks")["backgroundWasAlive"] is True,
#                   "live background process before final", pid)
#             if path in ("SIGINT", "SIGTERM"):
#                 active.child.kill(path)
#             if path == "input":
#                 active.child.stdin.end()
#             if path == "output":
#                 active.child.stdout.destroy()
#                 active.child.kill("SIGCONT")
#             # Closing a pipe is observed when the next event is written.
#             if path == "output":
#                 active.send({"type": "unrecognized"})
#             reply = await active.done
#             if path != "output":
#                 stream(reply, "completed" if path in ("normal", "linger") else "cancelled")
#             else:
#                 equal("Broken output cancels", reply["status"], 2)
#             await gone(pid)
#             await gone(prop(seen, "checks")["toolPid"])
#         finally:
#             await active.dispose()
# TEST-TIER-DISABLED-END conformance/scenarios/stops.py::run_c17

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/stops.py::run_c38
# async def run_c38(home: ScenarioHome) -> None:
#     identifier = await signed(home)
#     info = await home.json(["info"])
#     state = text("State directory", info.result["stateDirectory"])
#     key = hashlib.sha256(b"recovery-chat").hexdigest()
#     map_path = join(state, "subscriptions", identifier, "chats", key + ".json")
#     request = JSObject(subscriptionId=identifier, tools="all", workingDirectory=home.home,
#                        chatSessionId="recovery-chat", history=JSArray(), input=JSObject(role="user", text="answer"))
#     file = join(home.home, "request.json")
#     write_file(file, text_of(stringify(request)))
#     await home.part("plain")
#     first = stream(await home.call(["run", "--request", file]))
#     request["history"] = JSArray([JSObject(type="message", role="user", text="answer"),
#                                   *(JSObject(type="message", role="assistant", text=event["text"])
#                                     for event in first if event["type"] == "text")])
#     write_file(file, text_of(stringify(JSObject({**request, "runId": "killed-run"}))))
#     await home.part("hold")
#     active = home.start(["run", "--request", file])
#     try:
#         seen = await input_(home, "hold")
#         await wait_for("Native resume began", some_line(
#             active.lines, lambda event: prop(event, "type") == "started" and prop(event, "continuity") == "resumed"))
#         active.child.kill("SIGKILL")
#         await active.done
#         replies = await asyncio.gather(home.call(["runs", "list"]), home.call(["runs", "list"]))
#         for reply in replies:
#             equal("Recovery succeeded", reply["status"], 0)
#             equal("No orphan run listed", parse(reply["stdout"]), [])
#         await gone(prop(seen, "checks")["toolPid"])
#         await gone(prop(seen, "checks")["backgroundPid"])
#         equal("Run folder gone", not exists(join(state, "tmp", "killed-run")), True)
#         equal("Continued map gone", not exists(map_path), True)
#         equal("Run record gone", not exists(join(state, "runs", "killed-run.json")), True)
#     finally:
#         await active.dispose()
#     created = await asyncio.gather(*(home.json(["subscriptions", "create", "--family", identifier, "--label", label])
#                                      for label in ("One", "Two")))
#     for created_reply in created:
#         equal("Concurrent change succeeds", created_reply.process["status"], 0)
#     check("Distinct creations kept", not strictly_equal(created[0].result["id"], created[1].result["id"]),
#           "different identifiers", JSArray(created_reply.result["id"] for created_reply in created))
#     listed = parse((await home.call(["subscriptions", "list"]))["stdout"])
#
#     def listed_with(wanted: Any) -> Any:
#         return method_find(listed, "listed", lambda entry: strictly_equal(prop(entry, "id"), wanted))
#     for created_reply in created:
#         equal("Both creations persisted", get(listed_with(created_reply.result["id"]), "label"),
#               created_reply.result["label"])
#     empty = join(home.home, "empty-state")
#     equal("Empty state works", (await home.call(["info", "--state-dir", empty]))["status"], 0)
#     write_file(join(empty, "format"), "999\n")
#     newer = await home.json(["info", "--state-dir", empty])
#     equal("Newer format refused", newer.process["status"], 1)
#     equal("Format refusal", object_("Error", newer.result["error"])["code"], "state_newer")
#     equal("Newer format unchanged", read_file(join(empty, "format")), "999\n")
#     equal("No recovered scratch files", sorted_readdir(join(state, "tmp")), [])
# TEST-TIER-DISABLED-END conformance/scenarios/stops.py::run_c38

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/stops.py:7
# import asyncio
# TEST-TIER-IMPORTS-END conformance/scenarios/stops.py:7

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/stops.py:8
# import hashlib
# TEST-TIER-IMPORTS-END conformance/scenarios/stops.py:8

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/stops.py:13
# from ..check import ScenarioError, check, equal, object_, text
# TEST-TIER-IMPORTS-END conformance/scenarios/stops.py:13

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/stops.py:15
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
#     truthy,
# )
# TEST-TIER-IMPORTS-END conformance/scenarios/stops.py:15

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/stops.py:28
# from .runs import signed, stream
# TEST-TIER-IMPORTS-END conformance/scenarios/stops.py:28

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/stops.py:29
# from .support import (
#     alive,
#     at,
#     delay,
#     exists,
#     find,
#     is_integer,
#     now_monotonic,
#     null_check,
#     read_file,
#     readdir,
#     write_file,
# )
# TEST-TIER-IMPORTS-END conformance/scenarios/stops.py:29

raise RuntimeError("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.")
