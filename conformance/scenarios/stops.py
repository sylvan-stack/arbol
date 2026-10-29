# Test implementations moved to tests/mid/archived/conformance/scenarios/stops.py.
"""C15, C16, C17 and C38: stopping runs, ending process groups and recovering a killed Driver (DRV-0, DRV-1,
DRV-2, DRV-6), and `wait_for`, the deadline poll other scenarios use. Also the JavaScript readings C14 shares:
`prop`, `strictly_equal`, `method_find` and `sorted_readdir`."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

from ..check import ScenarioError, check
from ..harness import Scenario, ScenarioHome
from ..js import (
    UNDEFINED,
    JSArray,
    get,
    is_number,
    same_value,
    text_of,
)
from .support import (
    alive,
    at,
    delay,
    find,
    is_integer,
    now_monotonic,
    null_check,
    readdir,
)

# --- JavaScript readings --------------------------------------------------------------------------------


def prop(value: Any, key: str) -> Any:
    """`value.key` without optional chaining: V8's TypeError text on undefined and null, else `get`."""
    if value is UNDEFINED or value is None:
        raise ScenarioError(f"Cannot read properties of {text_of(value)} (reading '{key}')")
    return get(value, key)


def strictly_equal(a: Any, b: Any) -> bool:
    """`a === b`: numbers by value (-0 is 0, NaN is not NaN), objects and arrays by identity."""
    if is_number(a) and is_number(b):
        return float(a) == float(b)
    if isinstance(a, dict | list) or isinstance(b, dict | list):
        return a is b
    return same_value(a, b)


def method_find(value: Any, expression: str, predicate: Callable[[Any], Any]) -> Any:
    """`<expression>.find(predicate)` on a value that may not be an array, with V8's TypeError texts."""
    if value is UNDEFINED or value is None:
        raise ScenarioError(f"Cannot read properties of {text_of(value)} (reading 'find')")
    if not isinstance(value, list):
        raise ScenarioError(f"{expression}.find is not a function")
    return find(value, predicate)


def sorted_readdir(path: str) -> JSArray:
    """readdir(path): libuv's scandir sorts the names by their bytes."""
    null_check(path)
    return JSArray(sorted(readdir(path), key=os.fsencode))


def alive_pid(pid: Any) -> bool:
    """process.kill(pid, 0) succeeds; a pid that is not an int32 throws, which counts as not alive."""
    return is_integer(pid) and -2**31 <= float(pid) < 2**31 and alive(int(pid))


async def wait_for(check_name: str, predicate: Callable[[], Awaitable[bool]], timeout: float = 5000) -> None:
    deadline = now_monotonic() + timeout
    while not await predicate():
        check(check_name, now_monotonic() < deadline, "within deadline", timeout)
        await delay(10)


def at_once(function: Callable[[], bool]) -> Callable[[], Awaitable[bool]]:
    """An `async () => ...` predicate whose body awaits nothing."""
    async def predicate() -> bool:
        return function()
    return predicate


def some_line(lines: JSArray, predicate: Callable[[Any], bool]) -> Callable[[], Awaitable[bool]]:
    """`async () => lines.some(predicate)` on an interaction's live lines."""
    return at_once(lambda: any(predicate(event) for event in lines))


async def input_(home: ScenarioHome, part: str, after: int = 0) -> Any:
    async def accepted() -> bool:
        return any(record["stage"] == "input" and record["part"] == part for record in (await home.received())[after:])
    await wait_for("Tool accepts message", accepted)
    return at([record for record in (await home.received())[after:]
               if record["stage"] == "input" and record["part"] == part], -1)


async def gone(pid: Any) -> None:
    if is_number(pid):
        await wait_for("Background process ended", at_once(lambda: not alive_pid(pid)))


# --- Scenarios ------------------------------------------------------------------------------------------


async def run_c15(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c16(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c17(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c38(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c15 = Scenario("C15", "Stop closes partial output, calls, questions and sub-agents",
               "interrupt, cancellation ordering, 2/15 second limits, ignored interrupt and peer isolation",
               ["DRV-2.3", "DRV-2.8", "DRV-2.16", "DRV-2.17", "DRV-2.19", "DRV-2.21", "DRV-2.25"], run_c15)
c16 = Scenario("C16", "Stopping ended or unknown runs succeeds", "idempotent runs stop", ["DRV-2.18"], run_c16)
c17 = Scenario("C17", "Every end path clears shell process groups",
               "normal result, hanging exit, SIGINT, SIGTERM, input EOF, broken event pipe",
               ["DRV-0.10", "DRV-2.19", "DRV-2.26"], run_c17)
c38 = Scenario("C38", "Recover a killed Driver and protect durable state",
               "orphan tool and shell groups, resumed map removal, concurrent recovery, format, empty state and "
               "concurrent subscription creation; sign-in independence covered by C6",
               ["DRV-6.1", "DRV-6.3", "DRV-6.10", "DRV-0.9", "DRV-1.10"], run_c38)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
