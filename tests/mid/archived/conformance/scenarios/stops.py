"""C15, C16, C17 and C38: stopping runs, ending process groups and recovering a killed Driver (DRV-0, DRV-1,
DRV-2, DRV-6), and `wait_for`, the deadline poll other scenarios use. Also the JavaScript readings C14 shares:
`prop`, `strictly_equal`, `method_find` and `sorted_readdir`."""

from __future__ import annotations
import asyncio
import hashlib

from ..check import ScenarioError, check, equal, object_, text
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
    truthy,
)
from .runs import signed, stream
from .support import (
    alive,
    at,
    delay,
    exists,
    find,
    is_integer,
    now_monotonic,
    null_check,
    read_file,
    readdir,
    write_file,
)


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
    identifier = await signed(home)
    home.env["ARBOL_TEST_TIME_SCALE"] = "1"
    for part in ("text", "tool", "question", "subagent", "stubborn"):
        if part == "question" and (await home.json(["info"])).result["driver"] == "codex":
            continue
        await home.part(part)
        active = home.start(["run", "--subscription", identifier, "--tools", "all", "--cwd", home.home, "--control",
                             "answer"])
        try:
            seen = await input_(home, part)
            await wait_for("Partial output arrives",
                           some_line(active.lines, lambda event: prop(event, "type") == "text_delta"))
            if part == "question":
                await wait_for("Question is open",
                               some_line(active.lines, lambda event: prop(event, "type") == "ask_opened"))
            if part == "subagent":
                await wait_for("Sub-agent is working",
                               some_line(active.lines, lambda event: truthy(prop(event, "parentCallId"))))

                async def ticking() -> bool:
                    return any(record["stage"] == "subagent-tick" for record in await home.received())
                await wait_for("Sub-agent records active work", ticking)
            start = now_monotonic()
            active.send({"type": "stop"})
            records = stream(await active.done, "cancelled")
            elapsed = now_monotonic() - start
            check("Stop finishes within fifteen seconds", elapsed < 15000, "< 15 seconds", elapsed)
            check("Tool asked to interrupt",
                  any(record["stage"] == "interrupt" and record["part"] == part for record in await home.received()),
                  "interrupt request", await home.received())
            if part == "stubborn":
                check("Escalation after two seconds", elapsed >= 1900 and elapsed < 5000, "about two seconds", elapsed)
            equal("Earlier delta preserved", prop(find(records, lambda event: event["type"] == "text_delta"), "text"),
                  "partial")
            equal("Output reported", at(records, -1)["producedOutput"], True)
            for call in [event for event in records if event["type"] == "tool_started"]:
                equal("Every call closed once", len([event for event in records if event["type"] == "tool_finished"
                                                     and strictly_equal(event["callId"], call["callId"])]), 1)
            if part == "tool":
                equal("Running call interrupted",
                      prop(find(records, lambda event: event["type"] == "tool_finished"), "interrupted"), True)
            if part == "question":
                equal("Question withdrawn", prop(find(records, lambda event: event["type"] == "ask_closed"), "reason"),
                      "withdrawn")
            await gone(prop(seen, "checks")["backgroundPid"])
            await gone(prop(seen, "checks")["toolPid"])
            before = len([record for record in await home.received() if record["stage"] == "subagent-tick"])
            await delay(100)
            equal("No sub-agent activity after final",
                  len([record for record in await home.received() if record["stage"] == "subagent-tick"]), before)
        finally:
            await active.dispose()
    await home.part("hold")
    held = home.start(["run", "--subscription", identifier, "--control", "answer"])
    try:
        await input_(home, "hold")
        await home.part("plain")
        stream(await home.call(["run", "--subscription", identifier, "peer"]))
        held.send({"type": "stop"})
        stream(await held.done, "cancelled")
    finally:
        await held.dispose()
    early = home.start(["run", "--subscription", identifier, "--control", "answer"])
    try:
        early.send({"type": "stop"})
        stream(await early.done, "cancelled")
    finally:
        await early.dispose()




async def run_c17(home: ScenarioHome) -> None:
    identifier = await signed(home)
    for path in ("normal", "linger", "SIGINT", "SIGTERM", "input", "output"):
        part = "background" if path == "normal" else "linger" if path == "linger" else "hold"
        await home.part(part)
        after = len(await home.received())
        active = home.start(["run", "--subscription", identifier, "--tools", "all", "--cwd", home.home, "--control",
                             "answer"])
        try:
            seen = await input_(home, part, after)
            pid = prop(seen, "checks")["backgroundPid"]
            check("Background child was alive", is_number(pid) and prop(seen, "checks")["backgroundWasAlive"] is True,
                  "live background process before final", pid)
            if path in ("SIGINT", "SIGTERM"):
                active.child.kill(path)
            if path == "input":
                active.child.stdin.end()
            if path == "output":
                active.child.stdout.destroy()
                active.child.kill("SIGCONT")
            # Closing a pipe is observed when the next event is written.
            if path == "output":
                active.send({"type": "unrecognized"})
            reply = await active.done
            if path != "output":
                stream(reply, "completed" if path in ("normal", "linger") else "cancelled")
            else:
                equal("Broken output cancels", reply["status"], 2)
            await gone(pid)
            await gone(prop(seen, "checks")["toolPid"])
        finally:
            await active.dispose()


async def run_c38(home: ScenarioHome) -> None:
    identifier = await signed(home)
    info = await home.json(["info"])
    state = text("State directory", info.result["stateDirectory"])
    key = hashlib.sha256(b"recovery-chat").hexdigest()
    map_path = join(state, "subscriptions", identifier, "chats", key + ".json")
    request = JSObject(subscriptionId=identifier, tools="all", workingDirectory=home.home,
                       chatSessionId="recovery-chat", history=JSArray(), input=JSObject(role="user", text="answer"))
    file = join(home.home, "request.json")
    write_file(file, text_of(stringify(request)))
    await home.part("plain")
    first = stream(await home.call(["run", "--request", file]))
    request["history"] = JSArray([JSObject(type="message", role="user", text="answer"),
                                  *(JSObject(type="message", role="assistant", text=event["text"])
                                    for event in first if event["type"] == "text")])
    write_file(file, text_of(stringify(JSObject({**request, "runId": "killed-run"}))))
    await home.part("hold")
    active = home.start(["run", "--request", file])
    try:
        seen = await input_(home, "hold")
        await wait_for("Native resume began", some_line(
            active.lines, lambda event: prop(event, "type") == "started" and prop(event, "continuity") == "resumed"))
        active.child.kill("SIGKILL")
        await active.done
        replies = await asyncio.gather(home.call(["runs", "list"]), home.call(["runs", "list"]))
        for reply in replies:
            equal("Recovery succeeded", reply["status"], 0)
            equal("No orphan run listed", parse(reply["stdout"]), [])
        await gone(prop(seen, "checks")["toolPid"])
        await gone(prop(seen, "checks")["backgroundPid"])
        equal("Run folder gone", not exists(join(state, "tmp", "killed-run")), True)
        equal("Continued map gone", not exists(map_path), True)
        equal("Run record gone", not exists(join(state, "runs", "killed-run.json")), True)
    finally:
        await active.dispose()
    created = await asyncio.gather(*(home.json(["subscriptions", "create", "--family", identifier, "--label", label])
                                     for label in ("One", "Two")))
    for created_reply in created:
        equal("Concurrent change succeeds", created_reply.process["status"], 0)
    check("Distinct creations kept", not strictly_equal(created[0].result["id"], created[1].result["id"]),
          "different identifiers", JSArray(created_reply.result["id"] for created_reply in created))
    listed = parse((await home.call(["subscriptions", "list"]))["stdout"])

    def listed_with(wanted: Any) -> Any:
        return method_find(listed, "listed", lambda entry: strictly_equal(prop(entry, "id"), wanted))
    for created_reply in created:
        equal("Both creations persisted", get(listed_with(created_reply.result["id"]), "label"),
              created_reply.result["label"])
    empty = join(home.home, "empty-state")
    equal("Empty state works", (await home.call(["info", "--state-dir", empty]))["status"], 0)
    write_file(join(empty, "format"), "999\n")
    newer = await home.json(["info", "--state-dir", empty])
    equal("Newer format refused", newer.process["status"], 1)
    equal("Format refusal", object_("Error", newer.result["error"])["code"], "state_newer")
    equal("Newer format unchanged", read_file(join(empty, "format")), "999\n")
    equal("No recovered scratch files", sorted_readdir(join(state, "tmp")), [])


c15 = Scenario("C15", "Stop closes partial output, calls, questions and sub-agents",
               "interrupt, cancellation ordering, 2/15 second limits, ignored interrupt and peer isolation",
               ["DRV-2.3", "DRV-2.8", "DRV-2.16", "DRV-2.17", "DRV-2.19", "DRV-2.21", "DRV-2.25"], run_c15)
c17 = Scenario("C17", "Every end path clears shell process groups",
               "normal result, hanging exit, SIGINT, SIGTERM, input EOF, broken event pipe",
               ["DRV-0.10", "DRV-2.19", "DRV-2.26"], run_c17)
c38 = Scenario("C38", "Recover a killed Driver and protect durable state",
               "orphan tool and shell groups, resumed map removal, concurrent recovery, format, empty state and "
               "concurrent subscription creation; sign-in independence covered by C6",
               ["DRV-6.1", "DRV-6.3", "DRV-6.10", "DRV-0.9", "DRV-1.10"], run_c38)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
