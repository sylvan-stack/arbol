"""Project a saved harness session into the importer's database rows (IMP-0)."""

import json
import re
import shlex
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Literal

from .readers.form import CallLink, Kind, Result, Session, State, TextBlock, Tool, ToolCall, Trigger, Turn, Usage

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]
type JsonObject = dict[str, Json]
type ExchangeTrigger = Trigger | Literal["steered"]

_RESULT_LIMIT = 200 * 1024
_SHELL_NAMES = {
    "claude-code": frozenset({"Bash"}),
    "codex": frozenset({"commandExecution", "command_execution", "exec_command"}),
    "mimo": frozenset({"bash"}),
    "pi": frozenset({"bash"}),
}
_SHELL_WRAPPER = re.compile(r"(?:.*/)?(?:sh|bash|zsh|dash|ksh|fish)")
_SHELL_OPTIONS = re.compile(r"-[il]*c[il]*")


@dataclass(frozen=True)
class MessageRow:
    position: int
    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True)
class ToolCallRow:
    position: int
    call_id: str
    parent_call_id: str | None
    name: str
    input: Json
    result: JsonObject | None
    ok: bool
    error: str | None
    truncated: bool = False
    interrupted: bool = False


@dataclass(frozen=True)
class MappedSegment:
    turn_key: str
    trigger: ExchangeTrigger
    accepted_at: datetime
    ended_at: datetime
    state: State
    working_folder: str
    usage: Usage
    messages: tuple[MessageRow, ...]
    calls: tuple[ToolCallRow, ...]
    fallback_count: int


@dataclass(frozen=True)
class MappedSession:
    tool: Tool
    native_id: str
    kind: Kind
    title: str | None
    created_at: datetime
    origin: JsonObject
    segments: tuple[MappedSegment, ...]


class MappingError(ValueError):
    """A content-free per-session mapping refusal."""


@dataclass
class _Call:
    native: ToolCall
    fallback: bool = False
    children: list[_Call] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


type _Work = TextBlock | _Call


@dataclass
class _Segment:
    turn_key: str
    trigger: ExchangeTrigger
    prompt: str
    accepted_at: datetime
    ended_at: datetime
    state: State
    items: list[_Work] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


def stored_text(value: str) -> str:
    return value.replace("\0", "\ufffd").encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def _stored_object[Key](value: Mapping[Key, object]) -> JsonObject:
    result: JsonObject = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise MappingError("A saved object has a non-text key.")
        result[stored_text(key)] = _stored_json(item)
    return result


def _stored_json(value: object) -> Json:
    if isinstance(value, str):
        return stored_text(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    if isinstance(value, Mapping):
        return _stored_object(value)
    if isinstance(value, (list, tuple)):
        return [_stored_json(item) for item in value]
    raise MappingError("A saved value could not be stored as JSON.")


def segment_keys(turn: Turn) -> tuple[str, ...]:
    """Return the native keys even when the caller withholds this turn's rows."""
    return (turn.turn_key, *(f"{turn.turn_key}#{index}" for index in range(1, len(turn.steers) + 1)))


def _item_time(item: _Work) -> datetime:
    return item.at if isinstance(item, TextBlock) else item.native.started_at


def _linked_call(calls: dict[CallLink, list[_Call]], link: CallLink | None) -> _Call | None:
    if link is None or link not in calls:
        return None
    matching = calls[link]
    if len(matching) != 1:
        raise MappingError("A saved parent call is ambiguous.")
    return matching[0]


def _call_tree(turn: Turn) -> tuple[list[_Work], int]:
    work: list[_Work] = []
    calls: dict[CallLink, list[_Call]] = defaultdict(list)
    native_call_count = 0
    for item in turn.items:
        if isinstance(item, ToolCall):
            node = _Call(item)
            calls[CallLink(item.agent, item.call_id)].append(node)
            work.append(node)
            native_call_count += 1
        else:
            work.append(item)

    owners: dict[str, _Call] = {}
    fallbacks: list[_Call] = []
    for actor in turn.subagents:
        if actor.agent_id in owners:
            raise MappingError("A saved turn contains the same subagent twice.")
        launch = _linked_call(calls, actor.launch)
        if launch is None:
            launch = _Call(ToolCall(
                f"subagent/{actor.agent_id}", None, "subagent", {"agent": actor.agent_id}, Result(""),
                not actor.last_turn_failed, None, None, actor.first_record_at,
            ), fallback=True)
            fallbacks.append(launch)
        launch.usage += actor.usage
        owners[actor.agent_id] = launch

    roots: list[_Work] = []
    for branch in work:
        if isinstance(branch, TextBlock):
            roots.append(branch)
            continue
        call = branch.native
        parent = _linked_call(calls, call.parent)
        if parent is None and call.agent is not None:
            parent = owners.get(call.agent)
            if parent is None:
                raise MappingError("A saved call has no recorded subagent.")
        if parent is None:
            roots.append(branch)
        else:
            parent.children.append(branch)
    roots.extend(sorted(fallbacks, key=_item_time))
    return roots, native_call_count + len(fallbacks)


def _split_turn(turn: Turn) -> tuple[list[_Segment], int]:
    steers = sorted(turn.steers, key=lambda steer: steer.at)
    boundaries = [steer.at for steer in steers]
    end_times = [*boundaries, turn.ended_at]
    keys = segment_keys(turn)
    segments = [_Segment(keys[0], turn.trigger, turn.prompt, turn.started_at, end_times[0], turn.state)]
    for index, steer in enumerate(steers, start=1):
        segments[-1].state = "completed"
        segments.append(_Segment(keys[index], "steered", steer.text, steer.at, end_times[index], turn.state))
    roots, call_count = _call_tree(turn)
    for item in roots:
        segments[bisect_right(boundaries, _item_time(item))].items.append(item)
    for response in turn.usage:
        segments[bisect_right(boundaries, response.started_at)].usage += response.usage
    return segments, call_count


def _codex_command(words: list[str]) -> str:
    if len(words) == 3 and _SHELL_WRAPPER.fullmatch(words[0]) and _SHELL_OPTIONS.fullmatch(words[1]):
        return words[2]
    return shlex.join(words)


def _call_input(call: ToolCall, tool: Tool, working_folder: str) -> tuple[str, Json]:
    argument = _stored_json(call.input)
    if call.name in _SHELL_NAMES.get(tool, ()):
        source = argument if isinstance(argument, dict) else {}
        command = source.get("command", argument if isinstance(argument, str) else None)
        if tool == "codex" and isinstance(command, list) and all(isinstance(word, str) for word in command):
            command = _codex_command([word for word in command if isinstance(word, str)])
        cwd = source.get("workdir" if tool == "mimo" else "cwd")
        if not isinstance(cwd, str) and tool in {"pi", "mimo"}:
            cwd = working_folder
        shell_input: JsonObject = {"command": command if isinstance(command, str) else None}
        if isinstance(cwd, str):
            shell_input["cwd"] = cwd
        return "shell", shell_input
    name = "apply_patch" if tool == "codex" and call.name in {"fileChange", "file_change"} else call.name
    return stored_text(name), {"input": argument} if isinstance(argument, str) else argument


def _json_size(value: Json) -> int:
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def _output_prefix(output: str, budget: int) -> str:
    # The two quotes are already accounted for in the empty result's size.
    low, high = 0, min(len(output), budget)
    while low < high:
        pivot = (low + high + 1) // 2
        if _json_size(output[:pivot]) - 2 <= budget:
            low = pivot
        else:
            high = pivot - 1
    return output[:low]


def _bounded_result(result: Result) -> tuple[JsonObject, bool]:
    fields = _stored_object(result.fields or {})
    fields.pop("output", None)
    if result.images:
        fields["images"] = [
            {"mediaType": stored_text(image.media_type), "size": image.size} for image in result.images
        ]
    output = stored_text(result.text)
    value = {**fields, "output": output}
    if _json_size(value) <= _RESULT_LIMIT:
        return value, False
    value["output"] = ""
    budget = _RESULT_LIMIT - _json_size(value)
    if budget < 0:
        value = {"output": ""}
        budget = _RESULT_LIMIT - _json_size(value)
        for key, field_value in fields.items():
            # A singleton object's braces take the same two bytes as the new comma and space.
            size = _json_size({key: field_value})
            if size <= budget:
                value[key] = field_value
                budget -= size
    value["output"] = _output_prefix(output, budget)
    return value, True


def _call_row(call: ToolCall, position: int, identifier: str, parent: str | None, *,
              tool: Tool, working_folder: str) -> ToolCallRow:
    name, argument = _call_input(call, tool, working_folder)
    if call.result is None:
        return ToolCallRow(
            position, identifier, parent, name, argument, None, False,
            "The session ended before the tool call finished.", call.truncated, interrupted=True,
        )
    contents, cut = _bounded_result(call.result)
    error = stored_text(call.error)[:2000] if not call.ok and call.error is not None else None
    return ToolCallRow(
        position, identifier, parent, name, argument, contents, call.ok, error, cut or call.truncated,
    )


def _map_turn(turn: Turn, working_folder: str, session: Session) -> Iterator[MappedSegment]:
    segments, call_count = _split_turn(turn)
    visited = 0
    for segment in segments:
        messages = [MessageRow(0, "user", stored_text(segment.prompt))]
        calls: list[ToolCallRow] = []
        seen_ids: set[str] = set()
        fallback_count = 0
        pending: list[tuple[_Work, str | None]] = [(item, None) for item in reversed(segment.items)]
        while pending:
            item, parent = pending.pop()
            position = len(messages) + len(calls)
            if isinstance(item, TextBlock):
                messages.append(MessageRow(position, "assistant", stored_text(item.text)))
                continue
            call = item.native
            identifier = stored_text(
                call.call_id if parent is None else f"{call.agent or session.native_id}/{call.call_id}"
            )
            if identifier in seen_ids:
                raise MappingError("Saved calls have duplicate IDs in an Exchange.")
            seen_ids.add(identifier)
            calls.append(_call_row(call, position, identifier, parent, tool=session.tool, working_folder=working_folder))
            visited += 1
            fallback_count += item.fallback
            segment.usage += item.usage
            pending.extend((child, identifier) for child in reversed(sorted(item.children, key=_item_time)))
        yield MappedSegment(
            segment.turn_key, segment.trigger, segment.accepted_at, segment.ended_at,
            segment.state, working_folder, segment.usage, tuple(messages), tuple(calls), fallback_count,
        )
    if visited != call_count:
        raise MappingError("Saved tool calls have circular parent links.")


def map_session(session: Session, owner_home: Path) -> MappedSession:
    """Keep native identity and row order independent of allocation and persistence."""
    title = stored_text(session.title or "").strip()[:240] or None
    fallback_folder = session.working_folder or str(owner_home)
    try:
        origin = _stored_object(session.origin)
        segments = tuple(
            segment for turn in session.turns
            for segment in _map_turn(turn, stored_text(turn.working_folder or fallback_folder), session)
        )
    except RecursionError:
        raise MappingError("A saved object is nested too deeply.") from None
    return MappedSession(session.tool, session.native_id, session.kind, title, session.created_at, origin, segments)
