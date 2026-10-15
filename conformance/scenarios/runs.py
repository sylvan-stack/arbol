"""C10 to C13, C18 to C20, C33, C42 and C43: runs, from the request to the final event (DRV-2), and the
helpers other scenarios use: `events`, `stream`, `signed`, `check_run_without_control` and `run_refusals`."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Callable
from typing import Any, NamedTuple

from ..check import ScenarioError, check, equal, object_, text
from ..harness import Scenario, ScenarioHome
from ..js import (
    UNDEFINED,
    JSArray,
    JSObject,
    get,
    is_number,
    join,
    parse,
    same_value,
    stringify,
    text_of,
    trim,
    truthy,
    utf8_length,
)
from .support import (
    at,
    date_parse,
    delay,
    exists,
    find,
    includes,
    index_of,
    is_finite,
    item,
    now_monotonic,
    read_file,
    readdir,
    test,
    write_file,
)


def events(reply: JSObject) -> JSArray:
    return JSArray(object_("Run event", parse(line)) for line in trim(reply["stdout"]).split("\n") if line)


def stream(reply: JSObject, outcome: str = "completed") -> JSArray:
    records = events(reply)
    check("Nonempty event stream", len(records) > 0, "at least a final event", reply)
    for index, event in enumerate(records):
        equal("Gapless sequence", event["seq"], index + 1)
        equal("Run identifier", event["runId"], records[0]["runId"])
        check("Timestamp", isinstance(event["at"], str) and is_finite(date_parse(event["at"])), "UTC timestamp", event)
    equal("One final event", len([event for event in records if event["type"] == "finished"]), 1)
    equal("Last event", at(records, -1)["type"], "finished")
    equal("Outcome", at(records, -1)["outcome"], outcome)
    equal("Outcome exit status", reply["status"], 0 if outcome == "completed" else 1 if outcome == "failed" else 2)
    return records


async def signed(home: ScenarioHome) -> str:
    home.env["ARBOL_TEST_TIME_SCALE"] = "10"
    await home.part("success")
    families: Any = parse((await home.call(["subscriptions", "families"]))["stdout"])
    if families is None or families is UNDEFINED:
        raise ScenarioError(f"Cannot read properties of {text_of(families)} (reading 'find')")
    if not isinstance(families, list):
        raise ScenarioError("families.find is not a function")

    def vendor_login(family: Any) -> bool:
        if family is None or family is UNDEFINED:
            raise ScenarioError(f"Cannot read properties of {text_of(family)} (reading 'auth')")
        return bool(get(family, "auth") == "vendor_login")

    identifier = text("Vendor login family", get(find(families, vendor_login), "id"))
    result = await home.call(["subscriptions", "sign-in", identifier])
    equal("Sign-in exit", result["status"], 0)
    await home.part("plain")
    return identifier


# --- What the TypeScript read without a guard: V8's own texts where it would have thrown ------------------


def prop(value: Any, key: str) -> Any:
    """`value.key`: V8's TypeError text for undefined and null, else the property as JavaScript reads it."""
    if value is UNDEFINED or value is None:
        raise ScenarioError(f"Cannot read properties of {text_of(value)} (reading '{key}')")
    return get(value, key)


def has(value: Any, key: str) -> bool:
    """`key in value` for the field names used here: an own key of an object; never one of an array."""
    if isinstance(value, dict):
        return key in value
    if isinstance(value, list):
        return False
    raise ScenarioError(f"Cannot use 'in' operator to search for '{key}' in {text_of(value)}")


def some(value: Any, predicate: Callable[[Any], bool], source: str) -> bool:
    """`value.some(predicate)` on a parsed JSON value; `source` is the expression V8 names when it is no array."""
    if value is UNDEFINED or value is None:
        raise ScenarioError(f"Cannot read properties of {text_of(value)} (reading 'some')")
    if not isinstance(value, list):
        raise ScenarioError(f"{source}.some is not a function")
    return any(predicate(entry) for entry in value)


def strict(a: Any, b: Any) -> bool:
    """`a === b`: numbers by value (-0 is 0, NaN is nothing), objects and arrays by identity."""
    if is_number(a) and is_number(b):
        return float(a) == float(b)
    if isinstance(a, dict | list) or isinstance(b, dict | list):
        return a is b
    return same_value(a, b)


def find_index(items: list[Any], predicate: Callable[[Any, int], bool]) -> int:
    """Array.prototype.findIndex: -1 when nothing matches."""
    for index, entry in enumerate(items):
        if predicate(entry, index):
            return index
    return -1


def byte_length(value: Any) -> int:
    """Buffer.byteLength for a string; Node's TypeError for undefined, the only other value that reaches it."""
    if not isinstance(value, str):
        raise ScenarioError('The "string" argument must be of type string or an instance of Buffer or ArrayBuffer. '
                            f"Received {text_of(value)}")
    return utf8_length(value)


def sorted_entries(path: str) -> JSArray:
    """readdir(path): the names in byte order, as libuv's scandir sorts them."""
    return JSArray(sorted(readdir(path), key=os.fsencode))


def of_type(records: list[Any], kind: str) -> JSArray:
    return JSArray(event for event in records if event["type"] == kind)


# --- Runs ----------------------------------------------------------------------------------------------------


async def start(home: ScenarioHome, identifier: str, message: str = "answer", extra: list[str] | None = None) -> JSObject:
    return await home.call(["run", "--subscription", identifier, *(extra or []), message])


async def calls(home: ScenarioHome) -> JSArray:
    return JSArray(record for record in await home.received()
                   if includes(record["arguments"], "--input-format") and record["stage"] != "input"
                   or record["stage"] == "request"
                   and object_("Codex request", record["request"])["method"] == "thread/start")


class RunOptions(NamedTuple):
    model: str
    alternate: str
    effort: str


async def run_models(home: ScenarioHome, identifier: str) -> RunOptions:
    catalog = await home.json(["subscriptions", "models", identifier])
    check("Run catalog", isinstance(catalog.result["models"], list), "model array", catalog.result)
    models = JSArray(object_("Run model", model) for model in catalog.result["models"])
    primary = find(models, lambda model: isinstance(model["efforts"], list) and includes(model["efforts"], "low"))
    check("Low effort model", truthy(primary), "a model advertising low effort", models)
    alternate = find(models, lambda model: not strict(model["id"], primary["id"]) and isinstance(model["efforts"], list)
                     and includes(model["efforts"], "high"))
    check("Alternate high effort model", truthy(alternate), "a second model advertising high effort", models)
    return RunOptions(text("Run model ID", primary["id"]), text("Alternate model ID", alternate["id"]), "low")


async def run_c10(home: ScenarioHome) -> None:
    identifier = await signed(home)
    records = stream(await start(home, identifier, "answer", ["--label", "exchange=41"]))
    equal("First event", records[0]["type"], "started")
    equal("Fresh conversation", records[0]["continuity"], "fresh")
    check("Actual model", isinstance(records[0]["model"], str), "model from tool", records[0])
    for event in records:
        equal("Echoed labels", event["labels"], {"exchange": "41"})
    equal("Whole answer despite partial delta", JSArray(event["text"] for event in of_type(records, "text")), ["answer"])
    info = await home.json(["info"])
    equal("Build identity", records[0]["driverBuild"], info.result["build"])
    options = await run_models(home, identifier)
    await home.settings({"defaultSubscription": identifier,
                         "subscriptions": {identifier: {"defaultModel": options.model,
                                                        "defaultEffort": options.effort}}})
    defaults = stream(await home.call(["run", "answer"]))
    equal("Default subscription", defaults[0]["subscriptionId"], identifier)
    equal("Default effort", defaults[0]["effort"], "low")
    received = at(await calls(home), -1)
    arguments = prop(received, "arguments")
    equal("Default model passed",
          item(arguments, index_of(arguments, "--model") + 1) if includes(arguments, "--input-format")
          else object_("Thread params", object_("Thread request", received["request"])["params"])["model"],
          options.model)
    path = join(home.home, "request.json")
    write_file(path, text_of(stringify({"subscriptionId": identifier, "tools": "none", "history": [],
                                        "input": {"role": "user", "text": "file message"},
                                        "model": options.alternate, "effort": "high",
                                        "systemPrompt": "Keep this exact.\nSecond line.",
                                        "labels": {"source": "file"}})))
    stream(await home.call(["run", "--request", path, "--model", options.model, "--effort", options.effort,
                            "override"]))
    input_ = at([record for record in await home.received() if record["stage"] == "input"], -1)
    request = object_("Input", prop(input_, "checks")["input"])
    if request["method"] == "turn/start":
        content = object_("Turn params", request["params"])["input"]
        check("Text input array", isinstance(content, list), "Codex text input", request)
        equal("Option replaces message",
              JSArray(JSObject(type=object_("Text input", value)["type"], text=object_("Text input", value)["text"])
                      for value in content), [{"type": "text", "text": "override"}])
    else:
        equal("Option replaces message", object_("Message", request["message"])["content"],
              [{"type": "text", "text": "override"}])
    before = read_file(path)
    stream(await home.call(["run", "--request", path]))
    equal("Request unchanged", read_file(path), before)
    settings = join(home.home, ".arbol", "arbol-" + text_of(info.result["driver"]) + "-driver.json")
    write_file(settings, "{")
    refused = stream(await start(home, identifier), "failed")
    equal("Unreadable settings only final", len(refused), 1)
    equal("Settings refusal", prop(refused[0]["error"], "code"), "invalid_input")


c10 = Scenario("C10", "Fresh run and request defaults",
               "fresh runs, whole blocks, options, defaults and unreadable settings; history covered by C14",
               ["DRV-2.1", "DRV-2.3", "DRV-2.4", "DRV-0.2", "DRV-0.16"], run_c10)


async def run_c11(home: ScenarioHome) -> None:
    identifier = await signed(home)
    records = stream(await start(home, identifier, "answer", ["--tools", "all", "--cwd", home.home]))
    begun = find_index(records, lambda event, _: event["type"] == "tool_started")
    ended = find_index(records, lambda event, _: event["type"] == "tool_finished")
    check("Text before call", find_index(records, lambda event, _: event["type"] == "text") < begun,
          "text before tool_started", records)
    check("Text after call",
          find_index(records, lambda event, index: index > ended and event["type"] == "text") > ended,
          "text after call", records)
    equal("Normalized command", prop(item(records, begun), "name"), "shell")
    input_ = object_("Command input", prop(item(records, begun), "input"))
    equal("Command input", input_["command"], "printf fixture-output")
    if "cwd" in input_:
        equal("Command directory", input_["cwd"], home.home)
    equal("One matching finish",
          len([event for event in records if event["type"] == "tool_finished"
               and strict(event["callId"], prop(item(records, begun), "callId"))]), 1)
    result = object_("Shell result", prop(item(records, ended), "result"))
    equal("Shell output", result["output"], "fixture-output")
    if "exitCode" in result:
        equal("Shell exit code", result["exitCode"], 0)


c11 = Scenario("C11", "Text before and after a shell call",
               "live block ordering and call pairing; history mapping covered by C14",
               ["DRV-2.5", "DRV-2.6", "DRV-3.19 (events)"], run_c11)


async def run_c12(home: ScenarioHome) -> None:
    records = stream(await start(home, await signed(home)), "failed")
    equal("Failure code", prop(at(records, -1)["error"], "code"), "vendor_error")


c12 = Scenario("C12", "Error flag under a success subtype", "vendor error result", ["DRV-2.7"], run_c12)


async def run_c13(home: ScenarioHome) -> None:
    records = stream(await start(home, await signed(home)))
    usage = JSArray(event["usage"] for event in of_type(records, "usage"))
    equal("Input totals", JSArray(prop(entry, "inputTokens") for entry in usage), [3, 7, 7])
    equal("Output totals", JSArray(prop(entry, "outputTokens") for entry in usage), [2, 5, 5])
    for entry in usage:
        for field in ("cachedInputTokens", "reasoningTokens", "costUsd"):
            equal("Unreported " + field, has(entry, field), False)
    equal("Final usage", at(records, -1)["usage"], at(usage, -1))


c13 = Scenario("C13", "Usage totals and absent values", "intermediate request sums replaced by result totals",
               ["DRV-2.15"], run_c13)


async def run_c18(home: ScenarioHome) -> None:
    identifier = await signed(home)
    good, bad = await asyncio.gather(start(home, identifier, "hold"), start(home, identifier, "fail"))
    stream(good)
    stream(bad, "failed")
    await home.part("malformed")
    malformed = await start(home, identifier)
    stream(malformed, "failed")
    await home.part("plain")
    stream(await start(home, identifier))
    slow = home.start(["run", "--subscription", identifier, "slow"])
    slow.child.stdout.pause()
    try:
        await delay(300)
        began = now_monotonic()
        stream(await start(home, identifier))
        check("Peer completes while output blocked", now_monotonic() - began < 5000, "under 5 seconds",
              now_monotonic() - began)
    finally:
        slow.child.stdout.resume()
        await slow.dispose()


c18 = Scenario("C18", "Concurrent runs stay independent", "failed and malformed peers, slow consumer",
               ["DRV-2.21", "CLD-0.5"], run_c18)


async def run_c19(home: ScenarioHome) -> None:
    records = stream(await start(home, await signed(home)))
    equal("One whole text", len(of_type(records, "text")), 1)
    equal("No calls", len(of_type(records, "tool_started")), 0)
    received = at(await calls(home), -1)
    arguments = prop(received, "arguments")
    if includes(arguments, "--input-format"):
        check("Tools off", includes(arguments, "--tools") and item(arguments, index_of(arguments, "--tools") + 1) == "",
              "empty tool list", received)
        check("No persistence", includes(arguments, "--no-session-persistence"), "--no-session-persistence", received)
    else:
        params = object_("Thread params", object_("Thread request", received["request"])["params"])
        equal("Read-only sandbox", params["sandbox"], "read-only")
        equal("No permission escalation", params["approvalPolicy"], "never")
        equal("No persistence", params["ephemeral"], True)
        turn = at([record for record in await home.received() if record["stage"] == "input"], -1)
        equal("Network off", object_("Turn sandbox", object_("Turn params", object_(
            "Turn request", prop(turn, "request"))["params"])["sandboxPolicy"])["networkAccess"], False)
    equal("Work folder removed", not exists(received["workingDirectory"]), True)
    info = await home.json(["info"])
    equal("No temporary run folders", sorted_entries(join(text_of(info.result["stateDirectory"]), "tmp")), [])


c19 = Scenario("C19", "No tools and no leftover work folder", "no tools, no session persistence, fresh scratch cleanup",
               ["DRV-2.20"], run_c19)


async def run_c20(home: ScenarioHome) -> None:
    identifier = await signed(home)
    for part in ("text", "structure"):
        await home.part(part)
        records = stream(await start(home, identifier, "answer", ["--tools", "all", "--cwd", home.home]))
        result = find(records, lambda event: event["type"] == "tool_finished")
        equal("Cut flag", prop(result, "truncated"), True)
        value = result["result"]
        check("Result length", byte_length(value if isinstance(value, str) else stringify(value)) <= 200 * 1024,
              "at most 200 KiB", result)
        check("Whole UTF-8 characters", "�" not in text_of(stringify(result["result"])), "valid UTF-8",
              result["result"])


c20 = Scenario("C20", "Large tool results are cut", "text and structure, UTF-8 boundary", ["DRV-2.22"], run_c20)


async def check_run_without_control(home: ScenarioHome) -> str:
    identifier = await signed(home)
    stream(await start(home, identifier))
    request = home.start(["run", "--request", "-"])
    try:
        request.send({"subscriptionId": identifier, "history": [], "tools": "none",
                      "input": {"role": "user", "text": "stdin"}})
        request.child.stdin.end()
        stream(await request.done)
    finally:
        await request.dispose()
    return identifier


NOBODY_ANSWERS = r"nobody[^\n\r  ]*answer"  # /nobody.*answer/i: JavaScript's dot, ASCII case only


async def run_c33(home: ScenarioHome) -> None:
    identifier = await check_run_without_control(home)
    await home.part("question")
    unhandled = stream(await start(home, identifier, "answer", ["--tools", "all", "--cwd", home.home]))
    equal("No caller ask", len(of_type(unhandled, "ask_opened")), 0)
    response = find(await home.received(), lambda record: record["stage"] == "response")
    if (await home.json(["info"])).result["driver"] == "codex":
        refusal = object_("Unsupported question error",
                          object_("Unsupported question response", prop(response, "request"))["error"])
        equal("Unhandled Codex question refused", refusal["code"], -32601)
        check("Decline explains unsupported question", isinstance(refusal["message"], str)
              and test(r"not supported|unsupported", refusal["message"], re.I), "unsupported question message", refusal)
    else:
        def decision() -> Any:
            return prop(prop(prop(prop(response, "checks"), "input"), "response"), "response")
        equal("Unhandled ask declined", prop(decision(), "behavior"), "deny")
        check("Decline explains no caller", test(NOBODY_ANSWERS, text_of(prop(decision(), "message")), re.I),
              "nobody to answer", response)
    equal("Question tool not enabled", includes(prop(response, "arguments"), "--permission-prompt-tool"), False)
    await home.part("plain")
    active = home.start(["run", "--subscription", identifier, "--run-id", "visible-run", "--control", "hold"])
    try:
        active.child.stdin.write("not-json\n")
        active.send({"type": "answer", "askId": "missing", "answer": {}})
        listed: Any = JSArray()
        for _ in range(100):
            listed = parse((await home.call(["runs", "list"]))["stdout"])
            if some(listed, lambda entry: prop(entry, "runId") == "visible-run", "listed"):
                break
            await delay(10)
        check("Active run listed", some(listed, lambda entry: prop(entry, "runId") == "visible-run"
                                        and strict(entry["subscriptionId"], identifier), "listed"),
              "visible-run", listed)
        records = stream(await active.done)
        equal("Control refusals", len(of_type(records, "control_refused")), 2)
    finally:
        await active.dispose()
    equal("No ended runs listed", parse((await home.call(["runs", "list"]))["stdout"]), [])
    await home.part("stopping")
    stoppable = home.start(["run", "--subscription", identifier, "--run-id", "stop-from-peer", "answer"])
    try:
        def started() -> bool:
            return any(prop(event, "type") == "started" for event in stoppable.lines)
        for _ in range(100):
            if started():
                break
            await delay(10)
        check("Run started before peer stop", started(), "started event", stoppable.lines)
        stopped = await home.call(["runs", "stop", "stop-from-peer"])
        equal("Peer stop exit", stopped["status"], 0)
        equal("Peer stop output", stopped["stdout"], "")
        stream(await stoppable.done, "cancelled")
        last = at(stoppable.lines, -1)
        equal("Final emitted before stop returns", get(last, "type") if truthy(last) else last, "finished")
    finally:
        await stoppable.dispose()


c33 = Scenario("C33", "Run input and active records",
               "no control and unhandled question, stdin request, malformed control, runs list and runs stop",
               ["DRV-2.25", "DRV-2.26", "DRV-2.27", "DRV-2.28", "DRV-3.30", "DRV-6.7", "DRV-6.8"], run_c33)


async def run_c42(home: ScenarioHome) -> None:
    identifier = await signed(home)
    records = stream(await start(home, identifier), "failed")
    final = at(records, -1)
    equal("Output retained", JSArray(event["text"] for event in of_type(records, "text")), ["answer"])
    equal("Produced output", final["producedOutput"], True)
    equal("Unfinished call named", final["unfinishedCalls"], ["fixture-call"])
    equal("Usage retained", prop(final["usage"], "inputTokens"), 3)
    equal("Call closed once", len(of_type(records, "tool_finished")), 1)
    equal("No retry", len(await calls(home)), 1)


c42 = Scenario("C42", "Failure preserves output and unfinished calls",
               "unexpected exit with output and known usage; no retry", ["DRV-2.8", "DRV-2.9", "DRV-2.10"], run_c42)


async def run_c43(home: ScenarioHome) -> None:
    path = join(home.home, "blocked-state")
    write_file(path, "file")
    records = stream(await home.call(["run", "--state-dir", path, "answer"]), "failed")
    equal("Only final event", len(records), 1)
    equal("Internal failure", prop(records[0]["error"], "code"), "internal")


c43 = Scenario("C43", "State failure has one final event", "state path is an unwritable regular file", ["DRV-4.15"],
               run_c43)


async def run_refusals(home: ScenarioHome) -> None:
    identifier = await signed(home)
    options = await run_models(home, identifier)
    for args in (["--cwd", join(home.home, "gone")], ["--model", "unknown-model"],
                 ["--model", options.model, "--effort", "unsupported-effort"], ["--service-tier", "unsupported-tier"]):
        records = stream(await start(home, identifier, "answer", args), "failed")
        equal("Only final refusal", len(records), 1)
        equal("Invalid request", prop(records[0]["error"], "code"), "invalid_input")
    await home.part("dropped-effort")
    stream(await start(home, identifier, "answer", ["--model", options.model, "--effort", options.effort]), "failed")
    await home.part("plain")
    first = home.start(["run", "--subscription", identifier, "--run-id", "same-id", "hold"])
    try:
        for _ in range(100):
            if some(parse((await home.call(["runs", "list"]))["stdout"]),
                    lambda entry: prop(entry, "runId") == "same-id", "JSON.parse(...)"):
                break
            await delay(10)
        refused = stream(await start(home, identifier, "answer", ["--run-id", "same-id"]), "failed")
        equal("Duplicate identifier", prop(refused[0]["error"], "code"), "in_use")
        stream(await first.done)
    finally:
        await first.dispose()
    inputs = [record for record in await home.received() if record["stage"] == "input"]
    equal("Only accepted run reached inference", len(inputs), 1)
