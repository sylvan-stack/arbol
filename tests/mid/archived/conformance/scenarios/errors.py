# Mid-tier source from conformance/scenarios/errors.py; see MID_TIER.md.
# Shared helpers and refusal entry points remain at the original path.

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/errors.py::run
# async def run(home: ScenarioHome, identifier: str) -> JSObject:
#     return await home.call(["run", "--subscription", identifier, "answer"])
# TEST-TIER-DISABLED-END conformance/scenarios/errors.py::run

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/errors.py::run_c26
# async def run_c26(home: ScenarioHome) -> None:
#     is_codex = await codex(home)
#     rows = _codex_rows() if is_codex else CLAUDE_ROWS
#     for part, code in rows:
#         identifier = await signed(home)
#         await home.part(part)
#         before = len(await inputs(home))
#         error = last_error(stream(await run(home, identifier), "failed"))
#         equal("Code for " + part, prop(error, "code"), code)
#         equal("Retryable " + part, prop(error, "retryable"), code in ("rate_limited", "vendor_unavailable"))
#         wording = (part.startswith("wording") or part.startswith("missing-class") or part == "tool-newer"
#                    or part == "bare-fragments" or part == "unknown" or part == "argument")
#         equal("Classification basis " + part, prop(prop(error, "detail"), "basis"), "wording" if wording else "fields")
#         equal("No Driver retry " + part, len(await inputs(home)) - before, 1)
#         if code == "credential_rejected":
#             record = await subscription(home, identifier)
#             equal("Attention state", record["state"], "needs_attention")
#             equal("Stored problem", record["problem"], error)
#         if part in ("missing", "argument", "exit"):
#             check("Exit detail", is_integer(prop(prop(error, "detail"), "toolExit")), "tool exit code", error)
#             check("Bounded excerpt", byte_length(prop(prop(error, "detail"), "excerpt")) <= 1024, "<= 1 KiB", error)
#     if is_codex:
#         identifier = await signed(home)
#         await home.part("old-handshake")
#         error = last_error(stream(await run(home, identifier), "failed"))
#         equal("Handshake version rejected", prop(error, "code"), "tool_unsupported")
#         equal("Handshake found version", prop(prop(error, "detail"), "toolVersion"), "0.159.1")
#         equal("Handshake needed version", prop(prop(error, "detail"), "neededVersion"), "0.159.2")
#         equal("Old handshake starts no turn",
#               len([record for record in await inputs(home) if record["part"] == "old-handshake"]), 0)
# TEST-TIER-DISABLED-END conformance/scenarios/errors.py::run_c26

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/errors.py::run_c27
# async def run_c27(home: ScenarioHome) -> None:
#     is_codex = await codex(home)
#     identifier = await signed(home)
#     waits: list[tuple[str, Any]] = [("seconds", 8), ("minutes", 300), ("none", UNDEFINED), ("reset", "reset")]
#     for part, wait in waits:
#         await home.part(part)
#         before = len(await inputs(home))
#         before_reads = len(limit_reads(await home.received()))
#         error = last_error(stream(await run(home, identifier), "failed"))
#         equal("Rate limit", prop(error, "code"), "rate_limited")
#         if wait == "reset":
#             check("Reset wait", is_number(prop(error, "retryAfterSeconds")) and prop(error, "retryAfterSeconds") > 0,
#                   "positive vendor reset wait", error)
#         else:
#             equal("Named wait " + part, prop(error, "retryAfterSeconds"), wait)
#         equal("Still signed in", (await subscription(home, identifier))["state"], "signed_in")
#         equal("No Driver retry", len(await inputs(home)) - before, 1)
#         if is_codex:
#             equal("One post-limit read", len(limit_reads(await home.received())) - before_reads, 1)
# TEST-TIER-DISABLED-END conformance/scenarios/errors.py::run_c27

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/errors.py::run_c28
# async def run_c28(home: ScenarioHome) -> None:
#     is_codex = await codex(home)
#     identifier = await signed(home)
#     records = stream(await run(home, identifier), "failed")
#     equal("Credential refusal", prop(last_error(records), "code"), "credential_rejected")
#     notice = "retrying" if is_codex else "api_retry"
#     equal("One retry notice",
#           len([event for event in records if event["type"] == "notice" and event["code"] == notice]), 1)
#     equal("No second retry", len([record for record in await home.received() if record["stage"] == "second-retry"]),
#           0)
#     equal("Cleanup requested", len([record for record in await home.received() if record["stage"] == "interrupt"]), 1)
#     if is_codex:
#         equal("Codex has no retry-count setting",
#               prop(prop(item(await inputs(home), 0), "checks"), "retryBoundSupported"), False)
#     else:
#         equal("Retry bound", prop(prop(item(await inputs(home), 0), "checks"), "maxRetries"), "3")
#     equal("Account marked", (await subscription(home, identifier))["state"], "needs_attention")
#     if is_codex:
#         equal("Stored retry problem", (await subscription(home, identifier))["problem"], last_error(records))
# TEST-TIER-DISABLED-END conformance/scenarios/errors.py::run_c28

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/errors.py::run_c29
# async def run_c29(home: ScenarioHome) -> None:
#     is_codex = await codex(home)
#     identifier = await signed(home)
#     home.env["ARBOL_TEST_TIME_SCALE"] = "100"
#     info = await home.json(["info"])
#     root = to_string(info.result["stateDirectory"])
#     # Codex explicitly refuses caller questions (C25); it cannot open one for an idle-clock check.
#     for part in ["start", "idle", "call", "background", "heartbeat", "idle-off", "total",
#                  *([] if is_codex else ["question"])]:
#         await home.part(part)
#         # Only the start part tests the fixed 60-second start limit. The others get 6 seconds to start, so that a busy
#         # machine starting the stand-in cannot reach that limit; request limits are not scaled.
#         home.env["ARBOL_TEST_TIME_SCALE"] = "100" if part == "start" else "10"
#         run_id = "clock-" + part
#         limits = JSObject({"idleSeconds": 0 if part == "idle-off" else 0.15,
#                            **({"totalSeconds": 0.3} if part == "total" else {})})
#         request = JSObject(subscriptionId=identifier, runId=run_id, tools="all", history=JSArray(),
#                            workingDirectory=home.home, input=JSObject(role="user", text="answer"), limits=limits)
#         file = join(home.home, "request.json")
#         write_file(file, text_of(stringify(request)))
#         if part == "question":
#             active = home.start(["run", "--request", file, "--control"])
#             try:
#                 deadline = now_monotonic() + 5000
#                 while not any(_is_type(event, "ask_opened") for event in active.lines):
#                     check("Question opens", now_monotonic() < deadline, "before deadline", active.lines)
#                     await delay(10)
#                 await delay(450)
#                 equal("No idle timeout for question", any(_is_type(event, "finished") for event in active.lines), False)
#                 ask = find(active.lines, lambda event: _is_type(event, "ask_opened"))
#                 ask_id = prop(ask, "askId")
#                 question = to_string(prop(prop(prop(prop(ask, "ask"), "questions"), 0), "id"))
#                 active.send(JSObject(type="answer", askId=ask_id,
#                                      answer=JSObject(type="answers", answers=JSObject({question: JSArray(["Blue"])}))))
#                 reply = await active.done
#             finally:
#                 await active.dispose()
#         else:
#             reply = await home.call(["run", "--request", file])
#         limit = part in ("start", "idle", "total")
#         outcome = "failed" if limit else "completed"
#         check("Clock outcome " + part, get(at(parse_events(reply), -1), "outcome") == outcome, outcome, reply)
#         records = stream(reply, outcome)
#         if limit:
#             equal("Limit code", prop(last_error(records), "code"), "limit_reached")
#             equal("Named limit", prop(prop(last_error(records), "detail"), "limit"), part)
#         for call in [event for event in records if event["type"] == "tool_started"]:
#             finished = [event for event in records
#                         if event["type"] == "tool_finished" and same(event["callId"], call["callId"])]
#             equal("Call closed once", len(finished), 1)
#             if is_codex and part in ("call", "background"):
#                 equal("Busy command completes", finished[0]["ok"], True)
#             if is_codex and part == "total":
#                 equal("Total limit interrupts busy command", finished[0]["interrupted"], True)
#         equal("Scratch removed", not exists(join(root, "tmp", run_id)), True)
#         equal("Run record removed", not exists(join(root, "runs", run_id + ".json")), True)
# TEST-TIER-DISABLED-END conformance/scenarios/errors.py::run_c29

# TEST-TIER-DISABLED-BEGIN conformance/scenarios/errors.py::run_c30
# async def run_c30(home: ScenarioHome) -> None:
#     is_codex = await codex(home)
#     identifier = await signed(home)
#     if is_codex:
#         equal("Seed rich usage", (await home.json(["subscriptions", "usage", identifier])).result["outcome"], "ok")
#     before_run_reads = len(limit_reads(await home.received()))
#     stream(await run(home, identifier))
#     record = await subscription(home, identifier)
#     equal("Usage outcome", prop(record["lastUsage"], "outcome"), "ok")
#     equal("Latest shares", _windows(record, "usedPercent"), [25, 100])
#     equal("Window durations", _windows(record, "windowMinutes"), [300, 10080])
#     equal("Exhausted window", _windows(record, "limitReached"), [False, True])
#     check_resources("record.lastUsage.windows", prop(prop(record, "lastUsage"), "windows"))
#     if is_codex:
#         equal("Normal run does not poll limits", len(limit_reads(await home.received())), before_run_reads)
#         equal("Sparse update keeps reached reason", prop(prop(record["lastUsage"], "extra"), "rateLimitReachedType"),
#               "rate_limit_reached")
#         equal("Sparse update keeps false value", prop(prop(record["lastUsage"], "extra"), "spendControlReached"), False)
#     before = len(await home.received())
#     # Codex's explicit usage command refreshes account limits; list exposes its stored report.
#     cached = (await subscription(home, identifier))["lastUsage"] if is_codex else \
#         (await home.json(["subscriptions", "usage", identifier])).result
#     equal("Cached report", cached, record["lastUsage"])
#     equal("No tool for cached usage", len(await home.received()), before)
# TEST-TIER-DISABLED-END conformance/scenarios/errors.py::run_c30

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/errors.py:9
# from ..check import ScenarioError, check, equal, object_
# TEST-TIER-IMPORTS-END conformance/scenarios/errors.py:9

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/errors.py:11
# from ..js import (
#     UNDEFINED,
#     JSArray,
#     JSObject,
#     get,
#     is_number,
#     join,
#     len16,
#     parse,
#     same_value,
#     stringify,
#     text_of,
#     truthy,
#     utf8_length,
# )
# TEST-TIER-IMPORTS-END conformance/scenarios/errors.py:11

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/errors.py:26
# from .runs import events as parse_events
# TEST-TIER-IMPORTS-END conformance/scenarios/errors.py:26

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/errors.py:27
# from .runs import signed, stream
# TEST-TIER-IMPORTS-END conformance/scenarios/errors.py:27

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/errors.py:28
# from .subscriptions import check_resources
# TEST-TIER-IMPORTS-END conformance/scenarios/errors.py:28

# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/errors.py:29
# from .support import at, delay, exists, find, is_integer, item, now_monotonic, write_file
# TEST-TIER-IMPORTS-END conformance/scenarios/errors.py:29

raise RuntimeError("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.")
