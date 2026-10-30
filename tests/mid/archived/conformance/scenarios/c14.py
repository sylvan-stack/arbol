"""C14: resume or rebuild the caller conversation (DRV-2, DRV-6)."""

from __future__ import annotations

import ctypes
import hashlib
import math
import os
import re
import stat as stat_module
import struct
from typing import Any

from conformance.check import ScenarioError, check, equal, object_, text
from conformance.harness import Scenario, ScenarioHome, fs_error
from conformance.js import UNDEFINED, JSArray, JSObject, get, join, parse, stringify, text_of, truthy
from conformance.scenarios.runs import signed, stream
from conformance.scenarios.stops import method_find, prop, sorted_readdir, strictly_equal
from conformance.scenarios.support import (
    at,
    delay,
    exists,
    index_of,
    item,
    mkdir,
    null_check,
    read_file,
    read_json,
    stat,
    write_file,
)


def to_string(value: Any) -> str:
    """String(value), also the ToString of `+` and of JSON.parse: an object with its own `toString` field, also
    one inside an array, has no primitive value (V8's TypeError)."""
    try:
        return text_of(value)
    except TypeError as error:
        raise ScenarioError(str(error)) from None


def saved_files(folder: str) -> list[str]:
    """Every file under a folder, depth first in readdir order; a missing folder has none."""
    null_check(folder)
    try:
        with os.scandir(folder) as scan:
            entries = sorted(((entry.name, entry.is_dir(follow_symlinks=False), entry.is_file(follow_symlinks=False))
                              for entry in scan), key=lambda entry: os.fsencode(entry[0]))
    except FileNotFoundError:
        return []
    except OSError as error:
        raise fs_error(error, "scandir", folder) from None
    paths: list[str] = []
    for name, directory, regular in entries:
        path = join(folder, name)
        if directory:
            paths.extend(saved_files(path))
        elif regular:
            paths.append(path)
    return paths


def remove_file(path: str, force: bool = False) -> None:
    """rm(path, { force }) without `recursive`: lstat first, as Node does, with Node's texts."""
    null_check(path)
    try:
        result = os.lstat(path)
    except OSError as error:
        if force and isinstance(error, FileNotFoundError):
            return
        raise fs_error(error, "lstat", path) from None
    if stat_module.S_ISDIR(result.st_mode):
        raise ScenarioError(f"Path is a directory: rm returned EISDIR (is a directory) {path}")
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError as error:
        raise fs_error(error, "unlink", path) from None


def creation_ns(path: str) -> int | None:
    """stat's st_birthtimespec in nanoseconds, which Node reads and os.stat gives only as a float: macOS's
    getattrlist(ATTR_CMN_CRTIME), following links as stat does; None where it is not available."""
    try:
        function = ctypes.CDLL(None, use_errno=True).getattrlist
    except (OSError, AttributeError):
        return None
    function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint]
    function.restype = ctypes.c_int
    request = struct.pack("=HHIIIII", 5, 0, 0x200, 0, 0, 0, 0)  # ATTR_BIT_MAP_COUNT, ATTR_CMN_CRTIME
    answer = ctypes.create_string_buffer(64)
    if function(os.fsencode(path), request, answer, len(answer), 0) != 0:
        return None
    _, seconds, nanoseconds = struct.unpack_from("=Iqq", answer.raw)
    return int(seconds) * 1_000_000_000 + int(nanoseconds)


def node_stats(path: str) -> JSObject:
    """The fields of Node's Stats object for a path (stat follows links)."""
    try:
        result = os.stat(path)
    except OSError as error:
        raise fs_error(error, "stat", path) from None

    def milliseconds(nanoseconds: int) -> float:
        return nanoseconds // 1_000_000_000 * 1e3 + nanoseconds % 1_000_000_000 / 1e6

    birth = creation_ns(path)
    if birth is None:
        seconds = math.floor(result.st_birthtime)
        birth = seconds * 1_000_000_000 + round((result.st_birthtime - seconds) * 1e9)
    return JSObject(dev=float(result.st_dev), mode=float(result.st_mode), nlink=float(result.st_nlink),
                    uid=float(result.st_uid), gid=float(result.st_gid), rdev=float(result.st_rdev),
                    blksize=float(result.st_blksize), ino=float(result.st_ino), size=float(result.st_size),
                    blocks=float(result.st_blocks), atimeMs=milliseconds(result.st_atime_ns),
                    mtimeMs=milliseconds(result.st_mtime_ns), ctimeMs=milliseconds(result.st_ctime_ns),
                    birthtimeMs=milliseconds(birth))


def slice_text(value: Any, start: int, end: int | None = None) -> Any:
    """`item.text.slice(start, end)`: UTF-16 units of a string, items of an array, else V8's TypeError."""
    if value is UNDEFINED or value is None:
        raise ScenarioError(f"Cannot read properties of {text_of(value)} (reading 'slice')")
    if isinstance(value, str):
        units = value.encode("utf-16-le", "surrogatepass")
        return units[2 * start: None if end is None else 2 * end].decode("utf-16-le", "surrogatepass")
    if isinstance(value, list):
        return JSArray(value[start:end])
    raise ScenarioError("item.text.slice is not a function")


def json_parse(value: Any) -> Any:
    """JSON.parse(value): a value that is not a string is first made one."""
    return parse(value if isinstance(value, str) else to_string(value))


def inputs(records: list[JSObject]) -> list[JSObject]:
    return [record for record in records if record["stage"] == "input"]


async def run(home: ScenarioHome) -> None:
    subscription_id = await signed(home)
    info = await home.json(["info"])
    state = text("State folder", info.result["stateDirectory"])
    codex = info.result["driver"] == "codex"
    chat_session_id = "opaque/../chat"
    key = hashlib.sha256(chat_session_id.encode("utf-8")).hexdigest()

    def map_path(identifier: str = subscription_id) -> str:
        return join(state, "subscriptions", identifier, "chats", key + ".json")

    async def chat_map() -> JSObject:
        null_check(map_path())  # the first file call on a path from the Driver's state folder
        return object_("Chat map", read_json(map_path()))

    image = JSObject(mediaType="image/png", data="aQ==")
    first_message = JSObject(type="message", role="user", text="history-user-secret", images=JSArray([image]))
    shell = JSObject(type="tool_call", name="shell",
                     input=JSObject(command="printf history-shell-output", cwd="/ignored"), ok=False,
                     result=JSObject(output="history-shell-output", exitCode=2), error="history-error")
    foreign = JSObject(type="tool_call", name="foreign_tool", input=JSObject(value="foreign-input"), ok=True,
                       result=JSObject(value="foreign-value"))
    base = JSObject(subscriptionId=subscription_id, chatSessionId=chat_session_id, workingDirectory=home.home,
                    tools="none", history=JSArray(),
                    input=JSObject(role="user", text="history-user-secret", images=JSArray([image])))
    counter = 0

    async def request_file(request: JSObject) -> str:
        nonlocal counter
        counter += 1
        file = join(home.home, f"request-{counter}.json")
        write_file(file, text_of(stringify(request)))
        return file

    async def invoke(request: JSObject, continuity: str, reason: Any = UNDEFINED, part: str = "plain",
                     outcome: str = "completed") -> JSArray:
        await home.part(part)
        records = stream(await home.call(["run", "--request", await request_file(request)]), outcome)
        started = JSArray(event for event in records if event["type"] == "started")
        equal("One started event", len(started), 1)
        equal("Continuity", started[0]["continuity"], continuity)
        equal("First rebuild reason", started[0]["rebuildReason"], reason)
        return records

    def append(history: list[Any], input_: dict[str, Any], records: list[Any]) -> JSArray:
        return JSArray([*history, JSObject({"type": "message", "role": "user", **input_}),
                        *(JSObject(type="message", role="assistant", text=prop(event, "text")) for event in records
                          if prop(event, "type") == "text" and not truthy(prop(event, "parentCallId")))])

    async def input_seen() -> Any:
        return prop(at(inputs(await home.received()), -1), "checks")

    async def check_native() -> None:
        seen = await input_seen()
        equal("Native shell tool", seen["nativeShellCall"], True)
        equal("Native failed result", seen["nativeShellResult"], "history-shell-output\nexit code: 2\nhistory-error")
        equal("Native error flag", seen["nativeShellFailed"], True)
        equal("Foreign tool and JSON result", seen["nativeForeignCall"], True)
        equal("Earlier images", seen["historyImages"], [image])
        if codex:
            received = await home.received()
            input_ = object_("Codex turn request", prop(at(inputs(received), -1), "request"))
            turn = object_("Codex turn parameters", input_["params"])
            injections = [record for record in received if record["stage"] == "request"
                          and get(record["request"], "method") == "thread/inject_items"
                          and strictly_equal(get(get(record["request"], "params"), "threadId"), turn["threadId"])]
            equal("One Codex native injection", len(injections), 1)
            injection = injections[0]
            last_input = next((index for index in range(len(received) - 1, -1, -1)
                               if received[index]["stage"] == "input"), -1)
            check("Codex native injection precedes turn", index_of(received, injection) < last_input,
                  "thread/inject_items before turn/start", turn)
            items = prop(prop(prop(injection, "request"), "params"), "items")
            call = method_find(items, "items",
                               lambda entry: prop(entry, "type") == "function_call" and prop(entry, "name") == "shell")
            check("Codex shell has a made-up call identifier",
                  isinstance(get(call, "call_id"), str)
                  and re.fullmatch(r"call_[a-zA-Z0-9]{24}", call["call_id"]) is not None,
                  "call_ and 24 letters/digits", call)
            equal("Codex shell arguments", json_parse(prop(call, "arguments")),
                  JSObject(command="printf history-shell-output", cwd="/ignored"))
            equal("Codex shell result follows call", item(items, index_of(items, call) + 1),
                  JSObject(type="function_call_output", call_id=prop(call, "call_id"),
                           output="history-shell-output\nexit code: 2\nhistory-error"))

    def message(words: str) -> JSObject:
        return JSObject(role="user", text=words)

    first = await invoke(base, "fresh")
    initial = await chat_map()
    equal("Map chat identifier", initial["chatSessionId"], chat_session_id)
    equal("Map count", initial["messages"], 2)
    equal("Map filename", sorted_readdir(join(state, "subscriptions", subscription_id, "chats")), [key + ".json"])
    check("Private map", (int(stat(map_path()).mode) & 0o777) == 0o600, "0600", node_stats(map_path()))
    history = append([], base["input"], first)
    next_input = message("second")
    second = await invoke(JSObject({**base, "history": history, "input": next_input}), "resumed")
    equal("Same saved conversation", (await chat_map())["conversation"], initial["conversation"])
    history = append(history, next_input, second)
    changed_prompt = await invoke(
        JSObject({**base, "history": history, "systemPrompt": "changed-system", "input": message("third")}),
        "resumed" if info.result["driver"] == "claude" else "rebuilt",
        UNDEFINED if info.result["driver"] == "claude" else "system_prompt_changed")
    prompt = await input_seen()
    equal("New prompt reached tool", prompt["systemPrompt"], "changed-system")
    if info.result["driver"] == "claude":
        equal("Prompt snapshot disabled", prompt["promptSnapshotOff"], True)
    history = append(history, JSObject(text="third"), changed_prompt)
    edited = JSArray([JSObject({**first_message, "text": "edited-user-secret"}), shell, foreign, *history[1:]])
    rebuilt = await invoke(JSObject({**base, "history": edited, "input": message("after edit")}), "rebuilt",
                           "history_differs")
    await check_native()
    check("New native conversation", not strictly_equal((await chat_map())["conversation"], initial["conversation"]),
          "new identifier", await chat_map())
    history = append(edited, JSObject(text="after edit"), rebuilt)
    # Splitting replies and changing tool records alone leave the message digest unchanged.
    split = JSArray()
    for entry in history:
        if prop(entry, "type") == "message" and prop(entry, "role") == "assistant":
            split.extend([JSObject({**entry, "text": slice_text(prop(entry, "text"), 0, 2)}),
                          JSObject({**entry, "text": slice_text(prop(entry, "text"), 2)})])
        else:
            split.append(entry)
    split_run = await invoke(JSObject({**base, "history": JSArray([*split, JSObject(
        type="tool_call", name="ignored_tool_change", input=JSObject(), ok=True, result="changed-tool-record")]),
        "input": message("split reply")}), "resumed")
    history = append(split, JSObject(text="split reply"), split_run)
    replaced = JSArray(JSObject({**entry, "text": "replaced-reply-secret"}) if index == len(history) - 1 else entry
                       for index, entry in enumerate(history))
    replacement = await invoke(JSObject({**base, "history": replaced, "input": message("replacement")}), "rebuilt",
                               "history_differs")
    await check_native()
    history = append(replaced, JSObject(text="replacement"), replacement)
    other_folder = join(home.home, "other")
    mkdir(other_folder)
    moved = await invoke(JSObject({**base, "history": history, "workingDirectory": other_folder,
                                   "input": message("moved")}), "rebuilt", "working_folder_changed")
    history = append(history, JSObject(text="moved"), moved)
    current = await chat_map()
    tool_home = join(state, "subscriptions", subscription_id, "home")
    projects = join(tool_home, "projects")
    if codex:
        for root in ("sessions", "archived_sessions"):
            for file in saved_files(join(tool_home, root)):
                if file.endswith("-" + to_string(current["conversation"]) + ".jsonl"):
                    remove_file(file)
    else:
        for folder in sorted_readdir(projects):
            remove_file(join(projects, folder, to_string(current["conversation"]) + ".jsonl"), force=True)
    gone = await invoke(JSObject({**base, "history": history, "workingDirectory": other_folder,
                                  "input": message("gone")}), "rebuilt", "conversation_gone")
    history = append(history, JSObject(text="gone"), gone)
    original = await chat_map()
    await home.part("hold")
    held_file = await request_file(JSObject({**base, "history": history, "workingDirectory": other_folder,
                                             "runId": "held-chat", "input": message("held")}))
    held = home.start(["run", "--request", held_file])
    try:
        live = False
        for _ in range(100):
            if any(record["stage"] == "input" and record["part"] == "hold" for record in await home.received()):
                live = True
                break
            await delay(10)
        check("Resume reserved before peer", live, "active held-chat", held.lines)
        equal("Original map kept during run", (await chat_map())["conversation"], original["conversation"])
        peer = await invoke(JSObject({**base, "history": history, "workingDirectory": other_folder,
                                      "input": message("peer")}), "rebuilt", "in_use")
        stream(await held.done)
        history = append(history, JSObject(text="held"), held.lines)
        equal("Last completed writer wins", (await chat_map())["conversation"], original["conversation"])
        equal("Independent peer completed", at(peer, -1)["outcome"], "completed")
    finally:
        await held.dispose()
    failed = await invoke(JSObject({**base, "history": history, "workingDirectory": other_folder,
                                    "input": message("fail")}), "resumed", UNDEFINED, "fail", "failed")
    equal("Failed map removed", not exists(map_path()), True)
    # Failed replies are caller-owned too; their next use has no saved entry.
    history = append(history, JSObject(text="fail"), failed)
    first_again = await invoke(JSObject({**base, "history": history, "workingDirectory": other_folder,
                                         "input": message("again")}), "rebuilt", "first_run")
    history = append(history, JSObject(text="again"), first_again)
    for part in ("refuse", "refuse-stderr"):
        fallback = await invoke(JSObject({**base, "history": history, "workingDirectory": other_folder,
                                          "input": message("fallback")}), "rebuilt", "resume_refused", part)
        equal("One text fallback notice",
              len([event for event in fallback if event["type"] == "notice" and event["code"] == "history_as_text"]), 1)
        equal("Labelled history reaches tool", (await input_seen())["labelledHistory"], True)
        history = append(history, JSObject(text="fallback"), fallback)
    await invoke(JSObject({**base, "history": history, "chatSessionId": UNDEFINED, "input": message("anonymous")}),
                 "rebuilt", "no_chat_session")
    await check_native()
    refused_rebuild = await invoke(JSObject({**base, "history": history, "chatSessionId": UNDEFINED,
                                             "input": message("refused rebuild")}), "rebuilt", "no_chat_session",
                                   "refuse")
    equal("Refused synthetic session uses text",
          len([event for event in refused_rebuild if event["type"] == "notice" and event["code"] == "history_as_text"]),
          1)
    one_off = await invoke(JSObject({**base, "history": history, "workingDirectory": UNDEFINED,
                                     "input": message("one off")}), "rebuilt", "no_chat_session")
    equal("One-off completed", at(one_off, -1)["outcome"], "completed")
    one_off_seen = at(inputs(await home.received()), -1)
    if codex:
        params = prop(prop(one_off_seen, "request"), "params")
        records = await home.received()
        start = at([record for record in records if get(record["request"], "method") == "thread/start"], -1)
        equal("One-off thread is ephemeral", prop(prop(prop(start, "request"), "params"), "ephemeral"), True)
        for root in ("sessions", "archived_sessions"):
            equal("One-off has no saved rollout",
                  any(file.endswith("-" + to_string(prop(params, "threadId")) + ".jsonl")
                      for file in saved_files(join(tool_home, root))), False)
    else:
        one_off_args = prop(one_off_seen, "arguments")
        one_off_id = item(one_off_args, index_of(one_off_args, "--resume") + 1)
        for folder in sorted_readdir(projects):
            equal("One-off synthetic file removed",
                  not exists(join(projects, folder, to_string(one_off_id) + ".jsonl")), True)
    equal("No temporary runs", sorted_readdir(join(state, "tmp")), [])
    await home.part("plain")
    identifier = "other-login"
    await home.json(["subscriptions", "create", "--family", subscription_id, "--label", "Other", "--id", identifier])
    await home.part("success")
    equal("Other account signed in", (await home.call(["subscriptions", "sign-in", identifier]))["status"], 0)
    await invoke(JSObject({**base, "history": history, "subscriptionId": identifier,
                           "input": message("other subscription")}), "rebuilt", "first_run")
    await check_native()
    check("Separate subscription map", truthy(read_file(map_path(identifier))), "map under other account", identifier)
    map_text = read_file(map_path())
    for secret in ("history-user-secret", "edited-user-secret", "history-shell-output", "replaced-reply-secret"):
        check("Map has no message or tool text", secret not in map_text, "identifiers and digests only", map_text)


c14 = Scenario("C14", "Resume or rebuild the caller conversation",
               "continuity, reasons, history, map privacy, competing and failed runs",
               ["DRV-2.11", "DRV-2.12", "DRV-2.13", "DRV-2.34", "DRV-2.35", "DRV-6.11", "DRV-6.12", "DRV-6.14",
                "DRV-6.15"], run)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
