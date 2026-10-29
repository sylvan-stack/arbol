# Test implementations moved to tests/mid/archived/conformance/scenarios/runs.py.
"""C10 to C13, C18 to C20, C33, C42 and C43: runs, from the request to the final event (DRV-2), and the
helpers other scenarios use: `events`, `stream`, `signed`, `check_run_without_control` and `run_refusals`."""

from __future__ import annotations

import os
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
    text_of,
    trim,
    truthy,
    utf8_length,
)
from .support import (
    at,
    date_parse,
    delay,
    find,
    includes,
    is_finite,
    readdir,
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
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c10 = Scenario("C10", "Fresh run and request defaults",
               "fresh runs, whole blocks, options, defaults and unreadable settings; history covered by C14",
               ["DRV-2.1", "DRV-2.3", "DRV-2.4", "DRV-0.2", "DRV-0.16"], run_c10)


async def run_c11(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c11 = Scenario("C11", "Text before and after a shell call",
               "live block ordering and call pairing; history mapping covered by C14",
               ["DRV-2.5", "DRV-2.6", "DRV-3.19 (events)"], run_c11)


async def run_c12(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c12 = Scenario("C12", "Error flag under a success subtype", "vendor error result", ["DRV-2.7"], run_c12)


async def run_c13(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c13 = Scenario("C13", "Usage totals and absent values", "intermediate request sums replaced by result totals",
               ["DRV-2.15"], run_c13)


async def run_c18(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c18 = Scenario("C18", "Concurrent runs stay independent", "failed and malformed peers, slow consumer",
               ["DRV-2.21", "CLD-0.5"], run_c18)


async def run_c19(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c19 = Scenario("C19", "No tools and no leftover work folder", "no tools, no session persistence, fresh scratch cleanup",
               ["DRV-2.20"], run_c19)


async def run_c20(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


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
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c33 = Scenario("C33", "Run input and active records",
               "no control and unhandled question, stdin request, malformed control, runs list and runs stop",
               ["DRV-2.25", "DRV-2.26", "DRV-2.27", "DRV-2.28", "DRV-3.30", "DRV-6.7", "DRV-6.8"], run_c33)


async def run_c42(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c42 = Scenario("C42", "Failure preserves output and unfinished calls",
               "unexpected exit with output and known usage; no retry", ["DRV-2.8", "DRV-2.9", "DRV-2.10"], run_c42)


async def run_c43(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


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

# Archived complete imports; restore needed names in their original scope, not at this file tail.
