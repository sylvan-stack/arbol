"""C26 to C30: errors, rate limits, retries, run clocks and the latest limit report (DRV-4), and the JavaScript
property reads the scenarios of this file and of `tools` make on Driver data."""

from __future__ import annotations

import math
from typing import Any

from ..check import ScenarioError, check, equal, object_
from ..harness import Scenario, ScenarioHome
from ..js import (
    UNDEFINED,
    JSArray,
    JSObject,
    get,
    is_number,
    join,
    len16,
    parse,
    same_value,
    stringify,
    text_of,
    truthy,
    utf8_length,
)
from .runs import events as parse_events
from .runs import signed, stream
from .support import at, delay, exists, find, is_integer, item, now_monotonic, write_file

# --- JavaScript's reads, with V8's errors ----------------------------------------------------------------


def prop(value: Any, key: str | int) -> Any:
    """`value.key` or `value[index]`: V8's TypeError on null and undefined, `undefined` where JavaScript gives it."""
    if value is UNDEFINED or value is None:
        kind = "undefined" if value is UNDEFINED else "null"
        raise ScenarioError(f"Cannot read properties of {kind} (reading '{key}')")
    if isinstance(value, str) and isinstance(key, int):
        units = value.encode("utf-16-le", "surrogatepass")
        return units[2 * key:2 * key + 2].decode("utf-16-le", "surrogatepass") if 0 <= key < len16(value) else UNDEFINED
    return get(value, key)


def same(a: Any, b: Any) -> bool:
    """`a === b`: numbers by value, objects and arrays by identity."""
    if is_number(a) and is_number(b):
        return float(a) == float(b)
    if isinstance(a, dict | list) or isinstance(b, dict | list):
        return a is b
    return same_value(a, b)


def array_method(value: Any, expression: str, method: str) -> list[Any]:
    """The array a method such as `expression.map(...)` is called on, or V8's TypeError for what is not one."""
    if value is UNDEFINED or value is None:
        prop(value, method)
    if not isinstance(value, list):
        raise ScenarioError(f"{expression}.{method} is not a function")
    return value


def to_string(value: Any) -> str:
    """String(value), a template literal or a computed key on a JSON value. An object with its own `toString`
    field (never a function in JSON) has no primitive value, and V8 refuses it."""
    try:
        return text_of(value)
    except TypeError as error:
        raise ScenarioError(str(error)) from None


def _described(value: Any) -> str:
    """How Node's ERR_INVALID_ARG_TYPE names a value that is not a string (determineSpecificType)."""
    if value is UNDEFINED:
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return f"type boolean ({'true' if value else 'false'})"
    if is_number(value):
        number = float(value)
        return "type number (-0)" if number == 0 and math.copysign(1.0, number) < 0 else f"type number ({text_of(number)})"
    if isinstance(value, list):
        return "an instance of Array"
    # `value.constructor && 'name' in value.constructor`: an own `constructor` field of the JSON object stands in for
    # Object; without a name, util.inspect at depth -1 prints the object as [Object].
    if "constructor" not in value:
        return "an instance of Object"
    constructor = value["constructor"]
    if not truthy(constructor):
        return "[Object]"
    if not isinstance(constructor, dict | list):
        raise ScenarioError(f"Cannot use 'in' operator to search for 'name' in {text_of(constructor)}")
    if isinstance(constructor, dict) and "name" in constructor:
        return f"an instance of {to_string(constructor['name'])}"
    return "[Object]"


def byte_length(value: Any) -> int:
    """Buffer.byteLength(value), with Node's error for a value that is not a string."""
    if not isinstance(value, str):
        raise ScenarioError('The "string" argument must be of type string or an instance of Buffer or ArrayBuffer. '
                            f"Received {_described(value)}")
    return utf8_length(value)


# --- What the error scenarios share ------------------------------------------------------------------------


async def run(home: ScenarioHome, identifier: str) -> JSObject:
    return await home.call(["run", "--subscription", identifier, "answer"])


async def subscription(home: ScenarioHome, identifier: str) -> JSObject:
    listed = array_method(parse((await home.call(["subscriptions", "list"]))["stdout"]), "JSON.parse(...)", "find")
    return object_("Subscription", find(listed, lambda value: same(prop(value, "id"), identifier)))


async def inputs(home: ScenarioHome) -> list[JSObject]:
    return [record for record in await home.received() if record["stage"] == "input"]


async def codex(home: ScenarioHome) -> bool:
    return bool((await home.json(["info"])).result["driver"] == "codex")


def limit_reads(records: list[JSObject]) -> list[JSObject]:
    return [record for record in records if record["stage"] == "request"
            and object_("Vendor request", record["request"])["method"] == "account/rateLimits/read"]


def last_error(records: JSArray) -> Any:
    """`records.at(-1).error`: the stream's final event is always there."""
    return at(records, -1)["error"]


# --- C26 ---------------------------------------------------------------------------------------------------


def _codex_rows() -> list[tuple[str, str]]:
    return [
        ("unauthorized", "credential_rejected"), ("usageLimitExceeded", "rate_limited"),
        ("rateLimitExceeded", "rate_limited"), ("contextWindowExceeded", "context_exceeded"),
        *[(part, "vendor_unavailable") for part in ("serverOverloaded", "internalServerError", "flexUnavailable")],
        *[(part + "-" + status, code)
          for part in ("httpConnectionFailed", "responseStreamConnectionFailed", "responseStreamDisconnected",
                       "responseTooManyFailedAttempts")
          for status, code in (("401", "credential_rejected"), ("403", "credential_rejected"),
                               ("500", "vendor_unavailable"), ("none", "vendor_unavailable"), ("400", "vendor_error"))],
        *[(part, "vendor_error")
          for part in ("cyberPolicy", "misalignmentPolicyViolation", "tooManyDenials", "badRequest",
                       "sessionBudgetExceeded")],
        *[(part, "tool_failed") for part in ("sandboxError", "threadRollbackFailed", "activeTurnNotSteerable")],
        ("model", "invalid_input"), ("effort", "invalid_input"), ("tool-newer", "tool_unsupported"),
        ("wording-rate", "rate_limited"), ("wording-auth", "credential_rejected"),
        ("missing-class-rate", "rate_limited"), ("missing-class-auth", "credential_rejected"),
        ("unknown-class", "vendor_error"), ("unknown", "vendor_error"), ("bare-fragments", "vendor_error"),
        ("exit", "tool_failed"),
    ]


CLAUDE_ROWS = [
    ("authentication", "credential_rejected"), ("401", "credential_rejected"), ("403", "credential_rejected"),
    ("model", "invalid_input"), ("404", "invalid_input"), ("rate", "rate_limited"), ("429", "rate_limited"),
    ("server", "vendor_unavailable"), ("503", "vendor_unavailable"), ("context", "context_exceeded"),
    ("400", "vendor_error"), ("418", "vendor_error"), ("other-code", "vendor_error"), ("turns", "limit_reached"),
    ("missing", "tool_missing"), ("argument", "tool_unsupported"), ("exit", "tool_failed"),
    ("wording-rate", "rate_limited"), ("wording-auth", "credential_rejected"), ("unknown", "vendor_error"),
]


async def run_c26(home: ScenarioHome) -> None:
    is_codex = await codex(home)
    rows = _codex_rows() if is_codex else CLAUDE_ROWS
    for part, code in rows:
        identifier = await signed(home)
        await home.part(part)
        before = len(await inputs(home))
        error = last_error(stream(await run(home, identifier), "failed"))
        equal("Code for " + part, prop(error, "code"), code)
        equal("Retryable " + part, prop(error, "retryable"), code in ("rate_limited", "vendor_unavailable"))
        wording = (part.startswith("wording") or part.startswith("missing-class") or part == "tool-newer"
                   or part == "bare-fragments" or part == "unknown" or part == "argument")
        equal("Classification basis " + part, prop(prop(error, "detail"), "basis"), "wording" if wording else "fields")
        equal("No Driver retry " + part, len(await inputs(home)) - before, 1)
        if code == "credential_rejected":
            record = await subscription(home, identifier)
            equal("Attention state", record["state"], "needs_attention")
            equal("Stored problem", record["problem"], error)
        if part in ("missing", "argument", "exit"):
            check("Exit detail", is_integer(prop(prop(error, "detail"), "toolExit")), "tool exit code", error)
            check("Bounded excerpt", byte_length(prop(prop(error, "detail"), "excerpt")) <= 1024, "<= 1 KiB", error)
    if is_codex:
        identifier = await signed(home)
        await home.part("old-handshake")
        error = last_error(stream(await run(home, identifier), "failed"))
        equal("Handshake version rejected", prop(error, "code"), "tool_unsupported")
        equal("Handshake found version", prop(prop(error, "detail"), "toolVersion"), "0.159.1")
        equal("Handshake needed version", prop(prop(error, "detail"), "neededVersion"), "0.159.2")
        equal("Old handshake starts no turn",
              len([record for record in await inputs(home) if record["part"] == "old-handshake"]), 0)


c26 = Scenario("C26", "Every error mapping row",
               "field precedence, wording fallback, absent result, unknown failures and retry policy",
               ["DRV-4.1", "DRV-4.4"], run_c26)


# --- C27 ---------------------------------------------------------------------------------------------------


async def run_c27(home: ScenarioHome) -> None:
    is_codex = await codex(home)
    identifier = await signed(home)
    waits: list[tuple[str, Any]] = [("seconds", 8), ("minutes", 300), ("none", UNDEFINED), ("reset", "reset")]
    for part, wait in waits:
        await home.part(part)
        before = len(await inputs(home))
        before_reads = len(limit_reads(await home.received()))
        error = last_error(stream(await run(home, identifier), "failed"))
        equal("Rate limit", prop(error, "code"), "rate_limited")
        if wait == "reset":
            check("Reset wait", is_number(prop(error, "retryAfterSeconds")) and prop(error, "retryAfterSeconds") > 0,
                  "positive vendor reset wait", error)
        else:
            equal("Named wait " + part, prop(error, "retryAfterSeconds"), wait)
        equal("Still signed in", (await subscription(home, identifier))["state"], "signed_in")
        equal("No Driver retry", len(await inputs(home)) - before, 1)
        if is_codex:
            equal("One post-limit read", len(limit_reads(await home.received())) - before_reads, 1)


c27 = Scenario("C27", "Rate limit waits",
               "seconds, minutes, omitted wait and limiting-window reset; no Driver retry", ["DRV-4.5", "DRV-4.6"],
               run_c27)


# --- C28 ---------------------------------------------------------------------------------------------------


async def run_c28(home: ScenarioHome) -> None:
    is_codex = await codex(home)
    identifier = await signed(home)
    records = stream(await run(home, identifier), "failed")
    equal("Credential refusal", prop(last_error(records), "code"), "credential_rejected")
    notice = "retrying" if is_codex else "api_retry"
    equal("One retry notice",
          len([event for event in records if event["type"] == "notice" and event["code"] == notice]), 1)
    equal("No second retry", len([record for record in await home.received() if record["stage"] == "second-retry"]),
          0)
    equal("Cleanup requested", len([record for record in await home.received() if record["stage"] == "interrupt"]), 1)
    if is_codex:
        equal("Codex has no retry-count setting",
              prop(prop(item(await inputs(home), 0), "checks"), "retryBoundSupported"), False)
    else:
        equal("Retry bound", prop(prop(item(await inputs(home), 0), "checks"), "maxRetries"), "3")
    equal("Account marked", (await subscription(home, identifier))["state"], "needs_attention")
    if is_codex:
        equal("Stored retry problem", (await subscription(home, identifier))["problem"], last_error(records))


c28 = Scenario("C28", "Stop rejected retries",
               "first retry ends run and marks the account before any later retry",
               ["DRV-4.7", "DRV-4.8", "DRV-4.12"], run_c28)


# --- C29 ---------------------------------------------------------------------------------------------------


def _is_type(value: Any, kind: str) -> bool:
    """`value.type === kind` for a line a Driver wrote, which may be any JSON value."""
    return bool(prop(value, "type") == kind)


async def run_c29(home: ScenarioHome) -> None:
    is_codex = await codex(home)
    identifier = await signed(home)
    home.env["ARBOL_TEST_TIME_SCALE"] = "100"
    info = await home.json(["info"])
    root = to_string(info.result["stateDirectory"])
    # Codex explicitly refuses caller questions (C25); it cannot open one for an idle-clock check.
    for part in ["start", "idle", "call", "background", "heartbeat", "idle-off", "total",
                 *([] if is_codex else ["question"])]:
        await home.part(part)
        # Only the start part tests the fixed 60-second start limit. The others get 6 seconds to start, so that a busy
        # machine starting the stand-in cannot reach that limit; request limits are not scaled.
        home.env["ARBOL_TEST_TIME_SCALE"] = "100" if part == "start" else "10"
        run_id = "clock-" + part
        limits = JSObject({"idleSeconds": 0 if part == "idle-off" else 0.15,
                           **({"totalSeconds": 0.3} if part == "total" else {})})
        request = JSObject(subscriptionId=identifier, runId=run_id, tools="all", history=JSArray(),
                           workingDirectory=home.home, input=JSObject(role="user", text="answer"), limits=limits)
        file = join(home.home, "request.json")
        write_file(file, text_of(stringify(request)))
        if part == "question":
            active = home.start(["run", "--request", file, "--control"])
            try:
                deadline = now_monotonic() + 5000
                while not any(_is_type(event, "ask_opened") for event in active.lines):
                    check("Question opens", now_monotonic() < deadline, "before deadline", active.lines)
                    await delay(10)
                await delay(450)
                equal("No idle timeout for question", any(_is_type(event, "finished") for event in active.lines), False)
                ask = find(active.lines, lambda event: _is_type(event, "ask_opened"))
                ask_id = prop(ask, "askId")
                question = to_string(prop(prop(prop(prop(ask, "ask"), "questions"), 0), "id"))
                active.send(JSObject(type="answer", askId=ask_id,
                                     answer=JSObject(type="answers", answers=JSObject({question: JSArray(["Blue"])}))))
                reply = await active.done
            finally:
                await active.dispose()
        else:
            reply = await home.call(["run", "--request", file])
        limit = part in ("start", "idle", "total")
        outcome = "failed" if limit else "completed"
        check("Clock outcome " + part, get(at(parse_events(reply), -1), "outcome") == outcome, outcome, reply)
        records = stream(reply, outcome)
        if limit:
            equal("Limit code", prop(last_error(records), "code"), "limit_reached")
            equal("Named limit", prop(prop(last_error(records), "detail"), "limit"), part)
        for call in [event for event in records if event["type"] == "tool_started"]:
            finished = [event for event in records
                        if event["type"] == "tool_finished" and same(event["callId"], call["callId"])]
            equal("Call closed once", len(finished), 1)
            if is_codex and part in ("call", "background"):
                equal("Busy command completes", finished[0]["ok"], True)
            if is_codex and part == "total":
                equal("Total limit interrupts busy command", finished[0]["interrupted"], True)
        equal("Scratch removed", not exists(join(root, "tmp", run_id)), True)
        equal("Run record removed", not exists(join(root, "runs", run_id + ".json")), True)


c29 = Scenario("C29", "Run clocks and waiting work",
               "start, silent idle, heartbeats, idle off, tool call, background command, question and total while busy",
               ["DRV-4.9", "DRV-4.10", "DRV-4.11", "DRV-3.27", "DRV-3.32"], run_c29)


# --- C30 ---------------------------------------------------------------------------------------------------


def _windows(record: JSObject, field: str) -> JSArray:
    """`record.lastUsage.windows.map(window => window[field])`."""
    windows = array_method(prop(prop(record, "lastUsage"), "windows"), "record.lastUsage.windows", "map")
    return JSArray(prop(window, field) for window in windows)


async def run_c30(home: ScenarioHome) -> None:
    is_codex = await codex(home)
    identifier = await signed(home)
    if is_codex:
        equal("Seed rich usage", (await home.json(["subscriptions", "usage", identifier])).result["outcome"], "ok")
    before_run_reads = len(limit_reads(await home.received()))
    stream(await run(home, identifier))
    record = await subscription(home, identifier)
    equal("Usage outcome", prop(record["lastUsage"], "outcome"), "ok")
    equal("Latest shares", _windows(record, "usedPercent"), [25, 100])
    equal("Window durations", _windows(record, "windowMinutes"), [300, 10080])
    equal("Exhausted window", _windows(record, "limitReached"), [False, True])
    if is_codex:
        equal("Normal run does not poll limits", len(limit_reads(await home.received())), before_run_reads)
        equal("Sparse update keeps reached reason", prop(prop(record["lastUsage"], "extra"), "rateLimitReachedType"),
              "rate_limit_reached")
        equal("Sparse update keeps false value", prop(prop(record["lastUsage"], "extra"), "spendControlReached"), False)
    before = len(await home.received())
    # Codex's explicit usage command refreshes account limits; list exposes its stored report.
    cached = (await subscription(home, identifier))["lastUsage"] if is_codex else \
        (await home.json(["subscriptions", "usage", identifier])).result
    equal("Cached report", cached, record["lastUsage"])
    equal("No tool for cached usage", len(await home.received()), before)


c30 = Scenario("C30", "Latest run limit information",
               "latest report stored at completion and read without a tool invocation", ["DRV-4.13", "DRV-1.18"],
               run_c30)
