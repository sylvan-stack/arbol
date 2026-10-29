# Test implementations moved to tests/mid/archived/conformance/scenarios/errors.py.
"""C26 to C30: errors, rate limits, retries, run clocks and the latest limit report (DRV-4), and the JavaScript
property reads the scenarios of this file and of `tools` make on Driver data."""

from __future__ import annotations

import math
from typing import Any

from ..check import ScenarioError, object_
from ..harness import Scenario, ScenarioHome
from ..js import (
    UNDEFINED,
    JSArray,
    JSObject,
    get,
    is_number,
    len16,
    parse,
    same_value,
    text_of,
    truthy,
    utf8_length,
)
from .support import at, find

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
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


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
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c26 = Scenario("C26", "Every error mapping row",
               "field precedence, wording fallback, absent result, unknown failures and retry policy",
               ["DRV-4.1", "DRV-4.4"], run_c26)


# --- C27 ---------------------------------------------------------------------------------------------------


async def run_c27(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c27 = Scenario("C27", "Rate limit waits",
               "seconds, minutes, omitted wait and limiting-window reset; no Driver retry", ["DRV-4.5", "DRV-4.6"],
               run_c27)


# --- C28 ---------------------------------------------------------------------------------------------------


async def run_c28(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c28 = Scenario("C28", "Stop rejected retries",
               "first retry ends run and marks the account before any later retry",
               ["DRV-4.7", "DRV-4.8", "DRV-4.12"], run_c28)


# --- C29 ---------------------------------------------------------------------------------------------------


def _is_type(value: Any, kind: str) -> bool:
    """`value.type === kind` for a line a Driver wrote, which may be any JSON value."""
    return bool(prop(value, "type") == kind)


async def run_c29(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c29 = Scenario("C29", "Run clocks and waiting work",
               "start, silent idle, heartbeats, idle off, tool call, background command, question and total while busy",
               ["DRV-4.9", "DRV-4.10", "DRV-4.11", "DRV-3.27", "DRV-3.32"], run_c29)


# --- C30 ---------------------------------------------------------------------------------------------------


def _windows(record: JSObject, field: str) -> JSArray:
    """`record.lastUsage.windows.map(window => window[field])`."""
    windows = array_method(prop(prop(record, "lastUsage"), "windows"), "record.lastUsage.windows", "map")
    return JSArray(prop(window, field) for window in windows)


async def run_c30(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c30 = Scenario("C30", "Latest run limit information",
               "latest report stored at completion and read without a tool invocation; what each window counts",
               ["DRV-4.13", "DRV-1.18", "DRV-1.27"],
               run_c30)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
