"""C9, C25, C35, C36 and C37: tools, permission requests, questions and the owner's own setup (DRV-0, DRV-3)."""

from __future__ import annotations

import base64
import os
import re
import stat
from collections.abc import Callable
from typing import Any

from ..check import ScenarioError, check, equal, object_
from ..harness import Scenario, ScenarioHome, fs_error
from ..js import SPACE_CLASS, JSArray, JSObject, join, stringify, text_of, trim, truthy
from .errors import prop, same, to_string
from .runs import signed, stream
from .support import (
    at,
    delay,
    find,
    index_of,
    mkdir,
    now_monotonic,
    read_file,
    readdir,
    readlink,
    write_file,
)

# --- Helpers -----------------------------------------------------------------------------------------------


async def wait(label: str, condition: Callable[[], bool], timeout: float = 5000) -> None:
    deadline = now_monotonic() + timeout
    while not condition():
        check(label, now_monotonic() < deadline, "arrives before deadline", False)
        await delay(10)


def run_args(home: ScenarioHome, identifier: str) -> list[str]:
    return ["run", "--subscription", identifier, "--tools", "all", "--cwd", home.home, "answer"]


async def is_codex(home: ScenarioHome) -> bool:
    return bool((await home.json(["info"])).result["driver"] == "codex")


def count(items: list[Any], predicate: Callable[[Any], Any]) -> int:
    """`items.filter(predicate).length`."""
    return len([entry for entry in items if predicate(entry)])


def is_type(value: Any, kind: str) -> bool:
    """`value.type === kind` for a line a Driver wrote, which may be any JSON value."""
    return bool(prop(value, "type") == kind)


def begun(records: JSArray, call_id: str) -> Any:
    return find(records, lambda event: event["type"] == "tool_started" and event["callId"] == call_id)


def ended(records: JSArray, call_id: str) -> Any:
    return find(records, lambda event: event["type"] == "tool_finished" and event["callId"] == call_id)


def paired(records: JSArray, call: JSObject) -> int:
    """How many `tool_finished` events carry the call's identifier (`===`)."""
    return count(records, lambda event: event["type"] == "tool_finished" and same(event["callId"], call["callId"]))


def call_index(records: JSArray, ask: JSObject) -> int:
    """`records.findIndex(event => event.type === 'tool_started' && event.callId === ask.ask.callId)`."""
    for index, event in enumerate(records):
        if event["type"] == "tool_started" and same(event["callId"], prop(ask["ask"], "callId")):
            return index
    return -1


def modified(result: os.stat_result) -> float:
    """Node's `mtimeMs`: whole seconds times 1000 plus the nanoseconds over 1e6, each rounded as a double."""
    return result.st_mtime_ns // 1_000_000_000 * 1e3 + result.st_mtime_ns % 1_000_000_000 / 1e6


def stat_result(path: str, follow: bool) -> os.stat_result:
    try:
        return os.stat(path) if follow else os.lstat(path)
    except OSError as error:
        raise fs_error(error, "stat" if follow else "lstat", path) from None


def read_bytes(path: str) -> bytes:
    """readFile(path) without an encoding."""
    try:
        with open(path, "rb") as source:
            return source.read()
    except IsADirectoryError as error:
        raise fs_error(error, "read") from None
    except OSError as error:
        raise fs_error(error, "open", path) from None


BASE64 = {ord(character): value for value, character in
          enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")} | {ord("-"): 62, ord("_"): 63}


def from_base64(text: str) -> bytes:
    """Buffer.from(text, 'base64'): both alphabets, other characters skipped, '=' ends the data, each UTF-16 unit
    read by its low byte, and at most the length Node reserves for the text."""
    data = text.encode("utf-16-le", "surrogatepass")
    units = [data[index] | data[index + 1] << 8 for index in range(0, len(data), 2)]
    size = len(units)
    if size and units[size - 1] == 0x3D:
        size -= 1
    if size > 1 and units[size - 1] == 0x3D:
        size -= 1
    values: list[int] = []
    for unit in units:
        if unit & 0xFF == 0x3D:
            break
        if unit & 0xFF in BASE64:
            values.append(BASE64[unit & 0xFF])
    out = bytearray()
    for start in range(0, len(values), 4):
        group = values[start:start + 4]
        if len(group) >= 2:
            out.append((group[0] << 2 | group[1] >> 4) & 0xFF)
        if len(group) >= 3:
            out.append((group[1] << 4 | group[2] >> 2) & 0xFF)
        if len(group) == 4:
            out.append((group[2] << 6 | group[3]) & 0xFF)
    return bytes(out[:size * 3 >> 2])


def utf16_order(name: str) -> bytes:
    """The sort key of Array.prototype.sort: UTF-16 code units."""
    return name.encode("utf-16-be", "surrogatepass")


# --- Codex paths -------------------------------------------------------------------------------------------


async def codex_permissions(home: ScenarioHome) -> None:
    identifier = await signed(home)
    records = stream(await home.call(run_args(home, identifier)))
    equal("Unexpected request notices",
          count(records, lambda event: event["type"] == "notice" and event["code"] == "unexpected_request"), 7)
    equal("No caller questions",
          count(records, lambda event: event["type"] == "ask_opened" or event["type"] == "ask_closed"), 0)
    responses = [record for record in await home.received() if record["stage"] == "response"]
    equal("Every vendor request answered", len(responses), 7)
    for index in range(len(responses)):
        response = object_("Codex response", responses[index]["request"])
        equal("Response identifier", response["id"], f"fixture-request-{index}")
        if index < 2:
            equal("Approval accepted", response["result"], {"decision": "accept"})
        else:
            equal("Unsupported request rejected", object_("Request error", response["error"])["code"], -32601)
            check("Rejection explains why", isinstance(object_("Request error", response["error"])["message"], str),
                  "message", response)
    await home.part("malformed")
    malformed = stream(await home.call(run_args(home, identifier)), "failed")
    equal("Malformed vendor protocol fails its run", prop(at(malformed, -1)["error"], "code"), "tool_failed")
    await home.part("no-requests")
    stream(await home.call(run_args(home, identifier)))
    equal("No responses in next run",
          count(await home.received(), lambda record: record["stage"] == "response" and record["part"] == "no-requests"),
          0)


async def codex_completed_tools(home: ScenarioHome) -> None:
    identifier = await signed(home)
    for part in ("plain", "collaboration", "nested"):
        await home.part(part)
        records = stream(await home.call(run_args(home, identifier)))
        equal("Refused call reason", prop(ended(records, "refused"), "error"), "Codex refused this command.")
        equal("Refused call failed", prop(ended(records, "refused"), "ok"), False)
        equal("Shell input", prop(begun(records, "refused"), "input"), {"command": "rejected-command", "cwd": home.home})
        equal("Main answer", [event["text"] for event in records
                              if event["type"] == "text" and not truthy(event["parentCallId"])],
              ["main-before", "main-answer"])
        parent = "agent-spawn" if part == "collaboration" else "agent"
        child_events = [event for event in records
                        if event["callId"] == "subcall" or event["text"] == "sub-agent-only"
                        or event["text"] == "child-thinking" or event["type"] == "usage"]
        check("Child event coverage", len(child_events) >= 7,
              "tool start/result/delta, text/delta, reasoning/delta and usage", child_events)
        for event in child_events:
            equal("Sub-agent parent", event["parentCallId"], parent)
        child_notices = [event for event in records if event["type"] == "notice"
                         and (event["code"] == "unexpected_request" or event["message"] == "Fixture child warning.")]
        equal("Child request and warning both carried", len(child_notices), 2)
        for event in child_notices:
            equal("Child notice parent", event["parentCallId"], parent)
        equal("Child elicitation rejected",
              len([record for record in await home.received() if record["part"] == part and record["stage"] == "response"
                   and object_("Response", record["request"])["id"] == "fixture-child-request"]), 1)
        equal("Child tool result", prop(ended(records, "subcall"), "result"), {"output": "child-output", "exitCode": 0})
        if part == "nested":
            equal("Nested spawn parent", prop(begun(records, "nested-agent"), "parentCallId"), "agent")
            for event in [event for event in records
                          if event["callId"] == "nested-call" or event["text"] == "nested-only"]:
                equal("Nested child parent", event["parentCallId"], "nested-agent")
        for event in [event for event in records if event["type"] == "tool_started"]:
            equal("Call paired once", paired(records, event), 1)
        equal("Patch input", prop(begun(records, "patch"), "input"),
              [{"path": join(home.home, "fixture-patch.txt"), "kind": {"type": "add"}, "content": "fixture patch\n"}])
        equal("Patch succeeds", prop(ended(records, "patch"), "ok"), True)
        equal("Web tool name", prop(begun(records, "search"), "name"), "webSearch")
        equal("Web shape retained", object_("Web result", prop(ended(records, "search"), "result"))["action"],
              {"type": "search", "query": "fixture query", "queries": None})
        equal("MCP tool name", prop(begun(records, "mcp"), "name"), "mcpToolCall")
        equal("MCP arguments retained", object_("MCP input", prop(begun(records, "mcp"), "input"))["arguments"],
              {"value": "fixture-value"})
        equal("MCP result retained", prop(ended(records, "mcp"), "result"),
              {"content": [{"type": "text", "text": "fixture-value"}], "structuredContent": {"value": "fixture-value"}})
        equal("MCP failure reason", prop(ended(records, "mcp-failed"), "error"), "Fixture MCP refusal.")
        equal("MCP failure", prop(ended(records, "mcp-failed"), "ok"), False)
        equal("Background result", prop(ended(records, "background"), "result"),
              {"output": "background-output\n", "exitCode": 0})
        check("Final after late child", index_of(records, ended(records, "subcall")) < len(records) - 1,
              "child completes before finished", records)
        check("Final after background", index_of(records, ended(records, "background")) < len(records) - 1,
              "background completes before finished", records)
        received = [record for record in await home.received() if record["part"] == part]
        main_end = find(received, lambda record: record["stage"] == "main-ended")
        equal("Main ends with child active", prop(prop(main_end, "checks"), "childWasActive"), True)
        equal("Main ends with command active", prop(prop(main_end, "checks"), "backgroundWasAlive"), True)
        equal("Child completed", count(received, lambda record: record["stage"] == "child-ended"), 1)
        equal("Background completed", count(received, lambda record: record["stage"] == "background-ended"), 1)
        thread_request = find(received, lambda record: record["stage"] == "request"
                              and object_("Request", record["request"])["method"] == "thread/start")
        thread = object_("Thread params", object_("Thread request", prop(thread_request, "request"))["params"])
        equal("Trusted sandbox", thread["sandbox"], "danger-full-access")
        equal("No approval", thread["approvalPolicy"], "never")
        equal("Single app-server argument",
              prop(find(received, lambda record: record["stage"] == "input"), "arguments"), ["app-server"])
        turn_request = find(received, lambda record: record["stage"] == "input")
        turn = object_("Turn params", object_("Turn request", prop(turn_request, "request"))["params"])
        equal("Turn trusted sandbox", turn["sandboxPolicy"], {"type": "dangerFullAccess"})
        equal("Turn no approval", turn["approvalPolicy"], "never")
        config = read_file(join(to_string(prop(prop(main_end, "checks"), "home")), "config.toml"))
        features = re.search(r"\[features\]" + SPACE_CLASS + r"*([^\[]*)", config)
        if features is None:
            raise ScenarioError("Cannot read properties of null (reading '1')")
        equal("Only memory feature disabled", trim(features.group(1)), "memories = false")
        check("Live web search", 'web_search = "live"' in config, "live web", config)
    await home.part("plain")
    output = await home.call([*run_args(home, identifier), "--output", "text"])
    equal("Text output completed", output["status"], 0)
    equal("Child text excluded", output["stdout"], "main-beforemain-answer")
    await home.part("early-exit")
    failed = stream(await home.call(run_args(home, identifier)), "failed")
    equal("Premature exit refused", prop(at(failed, -1)["error"], "code"), "tool_failed")
    await home.part("unexpected-tool")
    without = stream(await home.call(["run", "--subscription", identifier, "answer"]))
    equal("Unexpected tool in no-tool run reported",
          count(without, lambda event: event["type"] == "tool_started" and event["name"] == "shell"), 1)
    equal("Unexpected tool leaves run completed", at(without, -1)["outcome"], "completed")


# --- C25 ---------------------------------------------------------------------------------------------------


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
async def run_c25(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c25 = Scenario("C25", "Unexpected permission requests",
               "automatic allow, malformed deny, missing identifier fails only its own run", ["DRV-3.22", "DRV-0.7"],
               run_c25)


# --- C35 ---------------------------------------------------------------------------------------------------


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
async def run_c35(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c35 = Scenario("C35", "Tools and completed background work",
               "all tools, refusal reason, shell shape, sub-agent attribution, three result parts and text output; "
               "idle-limit integration covered by C29",
               ["DRV-3.19", "DRV-3.20", "DRV-3.21", "DRV-3.23", "DRV-3.24", "DRV-3.25", "DRV-3.32"], run_c35)


# --- C36 ---------------------------------------------------------------------------------------------------


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
async def run_c36(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c36 = Scenario("C36", "Questions and their answers",
               "concurrent questions, reversed answers, multiple labels, duplicate, invalid and withdrawn answers, "
               "decline and cancellation", ["DRV-3.26", "DRV-3.27", "DRV-3.28", "DRV-3.29"], run_c36)


# --- C9 and C37 --------------------------------------------------------------------------------------------

SKILL = "---\nname: fixture-skill\ndescription: A sentinel skill\n---\nSkill sentinel\n"


def owner_files(home: ScenarioHome, files: list[str]) -> JSArray:
    """Each owner file's text and modification time (`stat` follows links)."""
    snapshot = JSArray()
    for file in files:
        content = read_file(join(home.home, file))
        snapshot.append(JSObject(file=file, content=content, modified=modified(stat_result(join(home.home, file), True))))
    return snapshot


async def owner_scenario(home: ScenarioHome, configured: bool) -> None:
    if await is_codex(home):
        await codex_owner_scenario(home, configured)
        return
    identifier = await signed(home)
    mkdir(join(home.home, ".claude/skills/fixture-skill"), recursive=True)
    mkdir(join(home.home, ".claude/skills/synced/test-account"), recursive=True)
    files = [".claude/CLAUDE.md", ".claude/settings.json", ".claude/skills/fixture-skill/SKILL.md", ".claude.json",
             ".claude/skills/synced/test-account/sentinel"]
    values = ["owner instructions sentinel", '{"ownerSettingsSentinel":true}', SKILL,
              text_of(stringify({"mcpServers": {"fixture": {"command": "fixture-server", "args": ["sentinel"]}},
                                 "ownerStateSentinel": True})), "owner account skill"]
    for index in range(len(files)):
        write_file(join(home.home, files[index]), values[index])
    before = owner_files(home, files)
    stream(await home.call(run_args(home, identifier)))
    seen = find(await home.received(), lambda record: record["stage"] == "input")
    equal("Owner skill path", prop(prop(seen, "checks"), "skills"), join(home.home, ".claude/skills/fixture-skill"))
    equal("Skill reaches tool", prop(prop(seen, "checks"), "skill"), values[2])
    equal("MCP servers reach tool", prop(prop(seen, "checks"), "mcp"),
          {"fixture": {"command": "fixture-server", "args": ["sentinel"]}})
    config_home = to_string(prop(prop(seen, "checks"), "configHome"))
    equal("Skill symlink", readlink(join(config_home, "skills/fixture-skill")),
          join(home.home, ".claude/skills/fixture-skill"))
    equal("Account sync stays private", read_file(join(config_home, "skills/synced/test-account/sentinel")),
          "private account skill")
    for file in ("settings.json", "CLAUDE.md", "plugins", "hooks"):
        equal("Owner " + file + " absent in private home", file in readdir(config_home), False)
    equal("Owner files unchanged", owner_files(home, files), before)
    if configured:
        without = stream(await home.call(["run", "--subscription", identifier, "answer"]))
        equal("No-tool run completes", at(without, -1)["outcome"], "completed")
        no_tools = at([record for record in await home.received() if record["stage"] == "input"], -1)
        equal("No-tool MCP argument omitted", "--mcp-config" in prop(no_tools, "arguments"), False)


def owner_tree(root: str) -> JSArray:
    """Every entry under the folder, depth first, with its time, mode and content; links are not followed."""
    result = JSArray()

    def visit(folder: str) -> None:
        for name in sorted(readdir(folder), key=utf16_order):
            path = join(folder, name)
            metadata = stat_result(path, False)
            content: str | None = readlink(path) if stat.S_ISLNK(metadata.st_mode) else \
                base64.b64encode(read_bytes(path)).decode("ascii") if stat.S_ISREG(metadata.st_mode) else None
            result.append(JSObject(path=path, modified=modified(metadata), mode=float(metadata.st_mode),
                                   content=content))
            if stat.S_ISDIR(metadata.st_mode):
                visit(path)

    visit(root)
    return result


async def codex_owner_scenario(home: ScenarioHome, configured: bool) -> None:
    identifier = await signed(home)
    secret = "fixture-owner-mcp-private-credential-12345"
    header = "fixture-owner-mcp-private-header-67890"
    owner_config = ('[mcp_servers.fixture]\ncommand = "fixture-server"\nargs = ["sentinel"]\nenabled = true\n'
                    'startup_timeout_sec = 12\n[mcp_servers.fixture.env]\nFIXTURE_TOKEN = "' + secret + '"\n'
                    '[mcp_servers.remote]\nurl = "https://example.invalid/mcp"\n[mcp_servers.remote.http_headers]\n'
                    'Authorization = "' + header + '"\n')
    for path in (".codex/skills/sentinel", ".codex/plugins/sentinel", ".codex/hooks/sentinel",
                 ".agents/skills/fixture-skill"):
        mkdir(join(home.home, path), recursive=True)
    files = {
        ".codex/config.toml": 'model = "ownerModelSentinel"\ndeveloper_instructions = "ownerInstructionsSentinel"\n'
                              "[features]\nmemories = true\nshell_tool = false\n" + owner_config,
        ".codex/auth.json": '{"ownerCredentialSentinel":true}', ".codex/AGENTS.md": "Owner instructions sentinel",
        ".codex/skills/sentinel/SKILL.md": "Owner .codex skill is outside this driver scope",
        ".codex/plugins/sentinel/owner.txt": "Owner plugin sentinel",
        ".codex/hooks/sentinel/owner.txt": "Owner hook sentinel",
        ".agents/skills/fixture-skill/SKILL.md": SKILL,
    }
    for file, value in files.items():
        write_file(join(home.home, file), value, 0o600)

    def trees() -> JSArray:
        return JSArray([owner_tree(join(home.home, ".codex")), owner_tree(join(home.home, ".agents"))])

    before = trees()
    reply = await home.call(run_args(home, identifier))
    stream(reply)
    seen = at([record for record in await home.received() if record["stage"] == "input"], -1)
    equal("Owner MCP tables reach tool intact", prop(prop(seen, "checks"), "ownerMcpCorrect"), True)
    equal("MCP config supplied", prop(prop(seen, "checks"), "ownerMcpOmitted"), False)
    equal("Owner skill reaches tool naturally", prop(prop(seen, "checks"), "ownerSkillCorrect"), True)
    equal("Owner skill path", prop(prop(seen, "checks"), "ownerSkillPath"),
          join(home.home, ".agents/skills/fixture-skill/SKILL.md"))
    equal("Only memory feature switched off", prop(prop(seen, "checks"), "onlyMemoryFeature"), True)
    equal("Live web search", prop(prop(seen, "checks"), "liveWebSearch"), True)
    equal("Owner settings excluded", prop(prop(seen, "checks"), "ownerSettingsAbsent"), True)
    private_home = to_string(prop(prop(seen, "checks"), "home"))
    for name in ("AGENTS.md", "plugins", "hooks", "skills"):
        equal("Owner " + name + " not copied", name in readdir(private_home), False)
    private_config = read_file(join(private_home, "config.toml"))
    for marker in (secret, header, "ownerModelSentinel", "ownerInstructionsSentinel", "ownerCredentialSentinel"):
        equal("Owner marker absent in output", marker in reply["stdout"] + reply["stderr"], False)
        equal("Owner marker absent in private config", marker in private_config, False)
        equal("Owner marker absent in fixture ledger", marker in read_file(join(home.tool, "received.jsonl")), False)
        for folder in (private_home, join(home.home, ".arbol")):
            for entry in owner_tree(folder):
                content = object_("Private file snapshot", entry)["content"]
                equal("Owner marker absent in saved files",
                      isinstance(content, str) and marker in from_base64(content).decode("utf-8", "replace"), False)
    equal("Owner trees unchanged", trees(), before)
    if configured:
        without = stream(await home.call(["run", "--subscription", identifier, "answer"]))
        equal("No-tool run completes", at(without, -1)["outcome"], "completed")
        no_tools = at([record for record in await home.received() if record["stage"] == "input"], -1)
        equal("No-tool MCP config omitted", prop(prop(no_tools, "checks"), "ownerMcpOmitted"), True)
        equal("No-tool MCP verified", prop(prop(no_tools, "checks"), "ownerMcpCorrect"), True)
        equal("Owner trees unchanged after no-tool run", trees(), before)


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/tools.py::run_c9
# async def run_c9(home: ScenarioHome) -> None:
#     await owner_scenario(home, False)
# TEST-TIER-DISABLED-END conformance/scenarios/tools.py::run_c9
async def run_c9(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/tools.py::run_c37
# async def run_c37(home: ScenarioHome) -> None:
#     await owner_scenario(home, True)
# TEST-TIER-DISABLED-END conformance/scenarios/tools.py::run_c37
async def run_c37(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c9 = Scenario("C9", "Owner setup stays unchanged",
              "sentinel settings, instructions, skills and MCP list; only skills and MCP paths supplied to the tool",
              ["DRV-0.4"], run_c9)
c37 = Scenario("C37", "Owner skills and MCP servers",
               "owner skill link, MCP configuration argument and private home, including no-tool MCP omission",
               ["DRV-3.31", "DRV-0.4"], run_c37)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
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
