"""Read Kimi Code's saved session wires and identify their raw archive files."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
from base64 import b64decode
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
from heapq import merge
from pathlib import Path
from socket import gethostname
from typing import Any, Never
from urllib.parse import unquote, unquote_to_bytes

from .form import (
    LIVE_WINDOW,
    CallLink,
    Failed,
    FileObservations,
    HomeFile,
    Image,
    Item,
    Kind,
    Response,
    Result,
    Session,
    SessionFailure,
    Source,
    State,
    Steer,
    Subagent,
    TextBlock,
    ToolCall,
    Trigger,
    Turn,
    Usage,
    unknown_record,
)
from .lines import file_records, observed_input

_SESSION = re.compile(r"session_([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")


@dataclass(frozen=True)
class _SavedSession:
    folder: Path
    workspace: str
    native_id: str

    @property
    def state(self) -> Path:
        return self.folder / "state.json"

    @property
    def main(self) -> Path:
        return self.folder / "agents/main/wire.jsonl"


def _eligible(home: Path, path: Path, *, directory: bool = False) -> bool:
    # The home itself has already been resolved. Reject aliases beneath it so an allowed
    # filename cannot point to a different session or to credentials or caches.
    try:
        return path.is_relative_to(home) and path.resolve() == path and (path.is_dir() if directory else path.is_file())
    except (OSError, ValueError, RuntimeError):
        return False


def _children(home: Path, directory: Path) -> tuple[Path, ...]:
    if not _eligible(home, directory, directory=True):
        return ()
    try:
        return tuple(sorted(directory.iterdir()))
    except OSError:
        raise SessionFailure("unreadable_session", f"{directory.relative_to(home)}: could not list the directory.") \
            from None


def _discover(home: Path, sessions: dict[str, _SavedSession], *, report_unidentified: bool) -> Iterator[Failed]:
    root = home / "sessions"
    try:
        workspaces = _children(home, root)
    except SessionFailure as failure:
        yield Failed.of(failure, file="sessions")
        return
    for workspace in workspaces:
        try:
            folders = _children(home, workspace)
        except SessionFailure as failure:
            if report_unidentified:
                yield Failed.of(failure, file=workspace.relative_to(home).as_posix())
            continue
        for folder in folders:
            if not folder.name.startswith("session_"):
                continue
            match = _SESSION.fullmatch(folder.name)
            if match is None:
                if report_unidentified and _eligible(home, folder, directory=True):
                    relative = folder.relative_to(home).as_posix()
                    unidentified = SessionFailure("unreadable_session", f"{relative}: invalid session folder identity.")
                    yield Failed.of(unidentified, file=relative)
                continue
            native_id = match[1].lower()
            if _eligible(home, folder, directory=True):
                sessions.setdefault(native_id, _SavedSession(folder, workspace.name, native_id))


def _wires(home: Path, session: _SavedSession) -> dict[str, Path]:
    if not _eligible(home, session.main):
        raise SessionFailure("unreadable_session", f"{session.main.relative_to(home)}: no eligible main wire.")
    wires = {"main": session.main}
    for agent in _children(home, session.folder / "agents"):
        wire = agent / "wire.jsonl"
        if agent.name != "main" and _eligible(home, wire):
            wires[agent.name] = wire
    return wires


@dataclass(frozen=True)
class _State:
    title: str | None = None
    cwd: str | None = None
    forked_from: str | None = None
    created_at: datetime | None = None


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _time(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _state(home: Path, path: Path, observations: FileObservations) -> _State:
    where = path.relative_to(home)
    try:
        if not _eligible(home, path):
            if not path.exists() and not path.is_symlink():
                return _State()
            raise ValueError
        with observed_input(home, where.as_posix(), observations) as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ValueError
        fork = value.get("forkedFrom")
        archived = value.get("archived")
        if fork is not None and not isinstance(fork, str):
            raise ValueError
        if archived is not None and not isinstance(archived, bool):
            raise ValueError
    except (OSError, ValueError, RecursionError):
        raise SessionFailure("unreadable_session", f"{where}: could not read the session state.") from None
    return _State(_string(value.get("title")), _string(value.get("cwd")), fork, _time(value.get("createdAt")))


@dataclass(frozen=True)
class _Record:
    kind: str
    at: datetime | None
    where: str
    data: dict[str, Any]

    def invalid(self, kind: str | None = None) -> Never:
        unknown_record(kind, self.where, conversation=True)
        raise AssertionError("unknown_record must raise for conversation records")

    def time(self) -> datetime:
        if self.at is None:
            self.invalid()
        return self.at


_LOOP_EVENTS = frozenset({"step.begin", "step.end", "content.part", "tool.call", "tool.result"})
_CONVERSATION = frozenset({
    "turn.prompt", "turn.steer", "turn.ended", "context.append_message", "context.append_loop_event",
    "context.undo", "context.clear", "llm.request", "subagent.spawned",
})
_VERSION = re.compile(r"[0-9]{1,4}(?:\.[0-9]{1,4}){0,3}")


def _rows(home: Path, path: Path, observations: FileObservations) -> Iterator[tuple[str, dict[str, Any]]]:
    file = path.relative_to(home).as_posix()
    if not _eligible(home, path):
        raise SessionFailure("unreadable_session", f"{file}: no eligible wire.")
    for number, raw in file_records(home, file, observations):
        where = f"{file}:{number}"
        row = _object(raw)
        if not isinstance(row.get("type"), str):
            unknown_record(None, where, conversation=True)
        yield where, row


def _record(where: str, row: dict[str, Any]) -> _Record:
    kind: str = row["type"]
    at = _time(row.get("created_at") if kind == "metadata" else row.get("time"))
    record = _Record(kind, at, where, row)
    if kind == "metadata":
        version = _string(row.get("protocol_version"))
        minimum = _string(row.get("min_protocol_version", version))
        if at is None or not version or not _VERSION.fullmatch(version) or not minimum or not _VERSION.fullmatch(minimum):
            record.invalid("metadata")
        parts = tuple(map(int, minimum.split(".")))
        if (*parts, 0, 0)[:4] > (1, 5, 0, 0):
            record.invalid("metadata")
    elif kind in _CONVERSATION:
        if at is None:
            record.invalid(kind)
        if kind == "context.append_loop_event":
            event = _object(row.get("event"))
            loop_kind = _string(event.get("type"))
            if loop_kind not in _LOOP_EVENTS:
                record.invalid(kind)
            return _Record(loop_kind, at, where, event)
    return record


def _record_ids(row: dict[str, Any]) -> Iterator[str]:
    if value := _string(row.get("uuid")):
        yield value
    if row.get("type") == "context.append_loop_event":
        if value := _string(_object(row.get("event")).get("uuid")):
            yield value


def _copy_signature(row: dict[str, Any]) -> bytes | None:
    # The native fork copies whole wires. Several structural records, including turn
    # bounds and loop requests, carry time and IDs but have no record UUID.
    if row["type"] not in _CONVERSATION:
        return None
    encoded = json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return sha256(encoded).digest()


@dataclass
class _ForkIndex:
    uuids: set[str] = field(default_factory=set)
    signatures: dict[str, set[bytes]] = field(default_factory=dict)

    def has(self, agent: str, row: dict[str, Any]) -> bool:
        ids = tuple(_record_ids(row))
        if ids:
            return not self.uuids.isdisjoint(ids)
        inherited = self.signatures.get(agent)
        return bool(inherited and _copy_signature(row) in inherited)


def _fork_ids(home: Path, session: _SavedSession, state: _State,
              inventory: dict[str, _SavedSession]) -> _ForkIndex | None:
    if state.forked_from is None:
        return None
    failure = SessionFailure("unreadable_session", f"{session.state.relative_to(home)}: fork source is unavailable.")
    source = inventory.get(state.forked_from.removeprefix("session_").lower())
    if source is None or source == session:
        raise failure
    copied = _ForkIndex()
    observations = FileObservations()
    try:
        for agent, path in _wires(home, source).items():
            signatures = copied.signatures.setdefault(agent, set())
            for where, row in _rows(home, path, observations):
                _record(where, row)
                ids = tuple(_record_ids(row))
                if ids:
                    copied.uuids.update(ids)
                elif (signature := _copy_signature(row)) is not None:
                    signatures.add(signature)
        for path in observations.files:
            observations.record(path, path.stat(follow_symlinks=False))
    except (SessionFailure, OSError, RecursionError):
        raise failure from None
    return copied


def _step_number(record: _Record) -> str | None:
    value = record.data.get("step")
    return str(value) if type(value) is int or isinstance(value, str) else None


def _undo(records: list[_Record], count: int) -> list[_Record]:
    """Remove logical messages along with their loop items, usage and context copies."""
    groups: dict[tuple[str, str], int] = {}
    owners: dict[int, int] = {}
    step_ids: dict[str, int] = {}
    call_ids: dict[str, int] = {}
    results: dict[str, int] = {}
    latest_step = None
    latest_result = None
    for index, record in enumerate(records):
        data = record.data
        kind = record.kind
        group = None
        if kind in {"turn.prompt", "turn.steer"}:
            message_id = _string(data.get("promptId" if kind == "turn.prompt" else "messageId"))
            group = groups.setdefault(("message", message_id or record.where), index)
        elif kind in {"llm.request", "step.begin", "step.end", "content.part", "tool.call"}:
            if kind == "llm.request" and data.get("kind") != "loop":
                continue
            step = _step_number(record)
            if kind == "llm.request" and isinstance(data.get("turnStep"), str):
                step = data["turnStep"].rpartition(".")[2]
            step_id = _string(data.get("stepUuid", data.get("uuid")))
            if step_id is not None:
                group = step_ids.get(step_id)
            if group is None:
                group = groups.setdefault(("step", step or step_id or record.where), index)
            if step_id is not None:
                step_ids[step_id] = group
            latest_step = group
            if kind == "tool.call" and (call_id := _string(data.get("toolCallId"))):
                call_ids[call_id] = group
        elif kind == "tool.result":
            call_id = _string(data.get("toolCallId")) or _string(data.get("parentUuid")) or record.where
            group = results.setdefault(call_id, index)
            latest_result = group
        elif kind == "subagent.spawned":
            group = call_ids.get(_string(data.get("parentToolCallId")) or "")
        elif kind == "context.append_message":
            message = _object(data.get("message"))
            role = message.get("role")
            message_id = _string(message.get("id"))
            if role == "assistant":
                group = latest_step
            elif role == "tool":
                group = results.get(_string(message.get("toolCallId")) or "", latest_result)
            if group is None:
                group = groups.setdefault(("message", message_id or record.where), index)
        if group is not None:
            owners[index] = group
    removed = set(sorted(set(owners.values()))[-count:])
    erased: list[_Record] = []
    kept: list[_Record] = []
    for index, record in enumerate(records):
        (erased if owners.get(index) in removed else kept).append(record)
    records[:] = kept
    return erased


def _context_edit(record: _Record, records: list[_Record]) -> list[_Record]:
    count = record.data.get("count")
    if type(count) is not int or count <= 0:
        record.invalid("context.undo")
    return _undo(records, count)


def _erased_launches(records: Iterable[_Record]) -> Iterator[tuple[str, datetime]]:
    calls: dict[str, datetime] = {}
    for record in records:
        data = record.data
        if record.kind == "tool.call":
            calls[data["toolCallId"]] = record.time()
        elif record.kind == "subagent.spawned":
            call_id = _string(data.get("parentToolCallId"))
            if call_id is not None and call_id in calls:
                yield data["subagentId"], calls[call_id]


_TRIGGERS: dict[str, Trigger] = {
    "user": "typed",
    "task": "task",
    "skill_activation": "system",
    "system_trigger": "system",
}
_MEDIA_PARTS = frozenset({"image_url", "video_url", "audio_url"})
_ARCHIVE_PARTS = frozenset({"think", "function", "tool_call_part"})


def _turn_key(value: object) -> str | None:
    if type(value) is int:
        return str(value)
    return value if isinstance(value, str) and value else None


def _parts(value: object, record: _Record) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        record.invalid(record.kind)
    parts: list[dict[str, Any]] = []
    for raw in value:
        part = _object(raw)
        kind = _string(part.get("type"))
        if kind == "text":
            if not isinstance(part.get("text"), str):
                record.invalid(record.kind)
        elif kind not in _MEDIA_PARTS and kind not in _ARCHIVE_PARTS:
            record.invalid(record.kind)
        parts.append(part)
    return parts


def _text(parts: list[dict[str, Any]]) -> str:
    return "".join(part["text"] for part in parts if part["type"] == "text")


def _prompt(record: _Record) -> str:
    return _text(_parts(record.data.get("input"), record))


def _error(value: object) -> str | None:
    return value if isinstance(value, str) else _string(_object(value).get("message"))


@dataclass
class _NativeTurn:
    key: str
    origin: str
    prompt: str
    start: _Record
    last_at: datetime
    end: _Record | None = None
    records: list[_Record] = field(default_factory=list)

    def project(self, cwd: str | None, counted: set[str]) -> Turn:
        state: State = "interrupted"
        kind = error = None
        if self.end is not None:
            reason: str = self.end.data["reason"]
            match reason:
                case "completed" | "cancelled":
                    state = reason
                case _:
                    state = "failed"
                    kind = reason
                    error = _error(self.end.data.get("error"))
        steers = tuple(Steer(_prompt(record), record.time()) for record in self.records if record.kind == "turn.steer")
        request = next((record.data for record in reversed(self.records)
                        if record.kind == "llm.request" and record.data.get("kind") == "loop"), {})
        model = _string(request.get("model"))
        effort = _string(request.get("thinkingEffort"))
        return Turn(self.key, _TRIGGERS.get(self.origin, "system"), self.prompt, self.start.time(),
                    self.end.time() if self.end is not None else self.last_at, state, error, kind,
                    cwd, model, effort, usage=tuple(_responses(self, counted)), steers=steers)


@dataclass
class _Lane:
    first_at: datetime | None = None
    version: str | None = None
    turns: dict[str, _NativeTurn] = field(default_factory=dict)
    current: _NativeTurn | None = None
    call_turns: dict[str, _NativeTurn] = field(default_factory=dict)
    requests: dict[str, list[_Record]] = field(default_factory=dict)
    native_calls: dict[str, _NativeTurn] = field(default_factory=dict)
    erased_launches: list[tuple[str, datetime]] = field(default_factory=list)

    def append(self, record: _Record) -> None:
        data = record.data
        kind = record.kind
        key = _turn_key(data.get("turnId"))
        turn: _NativeTurn | None
        if self.first_at is None:
            self.first_at = record.at
        if kind == "metadata":
            self.version = self.version or _string(data.get("protocol_version"))
            return
        if (kind not in _CONVERSATION and kind not in _LOOP_EVENTS and kind != "context.apply_compaction"
                and not kind.startswith(("turn.", "prompt.", "subagent."))):
            return
        if kind == "context.clear":
            for cleared in self.turns.values():
                self.erased_launches.extend(_erased_launches(cleared.records))
            self.turns.clear()
            self.call_turns.clear()
            self.requests.clear()
            self.native_calls.clear()
            self.current = None
            return
        if kind == "turn.prompt":
            origin = _string(_object(data.get("origin")).get("kind"))
            if key is None or not origin:
                record.invalid(kind)
            prompt = _prompt(record)
            records = [record, *self.requests.pop(key, [])]
            turn = _NativeTurn(key, origin, prompt, record, record.time(), records=records)
            self.current = self.turns[key] = turn
            return

        if kind == "llm.request":
            request_kind = data.get("kind")
            if request_kind == "compaction":
                if self.current is not None:
                    self.current.last_at = record.time()
                return
            if request_kind != "loop" or not _string(data.get("model")):
                record.invalid(kind)
            key = _request_turn(record)
            fields = ("kind", "model", "thinkingEffort", "turnStep", "step", "stepUuid")
            record = _Record(kind, record.at, record.where, {field: data[field] for field in fields if field in data})
            if key is not None and key not in self.turns:
                self.requests.setdefault(key, []).append(record)
                return
        if kind in {"step.begin", "step.end"}:
            if not _string(data.get("uuid")):
                record.invalid(kind)
            if kind == "step.end":
                _usage(record)
        turn = self.turns.get(key) if key is not None else self.current
        if kind == "tool.result" and (parent := _string(data.get("parentUuid"))):
            turn = self.call_turns.get(parent, turn)
        if kind == "subagent.spawned":
            if not _string(data.get("subagentId")):
                record.invalid(kind)
            call_uuid = _string(data.get("parentToolCallUuid")) or ""
            call_id = _string(data.get("parentToolCallId")) or ""
            turn = self.call_turns.get(call_uuid) or self.native_calls.get(call_id) or turn
        if kind == "context.undo":
            if turn is None and self.turns:
                turn = next(reversed(self.turns.values()))
            if turn is not None:
                erased = _context_edit(record, turn.records)
                self.erased_launches.extend(_erased_launches(erased))
                if not any(item.kind == "turn.prompt" for item in turn.records):
                    del self.turns[turn.key]
                    self.call_turns = {uuid: owner for uuid, owner in self.call_turns.items() if owner is not turn}
                    self.native_calls = {key: owner for key, owner in self.native_calls.items() if owner is not turn}
                    if self.current is turn:
                        self.current = None
                else:
                    turn.last_at = record.time()
            else:
                _context_edit(record, [])
            return

        if kind == "turn.ended":
            if key is None or not _string(data.get("reason")):
                record.invalid(kind)
            if turn is not None and turn.end is None:
                turn.end = record
                if self.current is turn:
                    self.current = None
            return
        if kind in {"tool.call", "tool.result"}:
            _check_tool(record)
        if kind == "content.part":
            _content(record)
        if kind == "turn.steer":
            _prompt(record)
            if turn is None or turn.end is not None:
                return
        if kind == "context.append_message":
            message = _object(data.get("message"))
            role = _string(message.get("role"))
            if role not in {"user", "assistant", "tool", "system", "developer"}:
                record.invalid(kind)
            _parts(message.get("content"), record)
            # The content is a copy. Keep only the evidence needed to group it for undo.
            if _object(message.get("origin")).get("kind") == "compaction_summary":
                return
            record = _Record(kind, record.at, record.where, {"message": {
                "role": role, "id": message.get("id"), "toolCallId": message.get("toolCallId"),
            }})
        if turn is not None:
            if record.at is not None:
                turn.last_at = record.at
            if kind in _LOOP_EVENTS or kind in {"turn.steer", "context.append_message", "llm.request", "subagent.spawned"}:
                turn.records.append(record)
            if kind == "tool.call" and (uuid := _string(data.get("uuid"))):
                self.call_turns[uuid] = turn
                self.native_calls[data['toolCallId']] = turn


def _content(record: _Record) -> TextBlock | None:
    part = _object(record.data.get("part"))
    _parts([part], record)
    if part["type"] == "text":
        return TextBlock(part["text"], _time(record.data.get("startedAt")) or record.time())
    return None


def _items(turn: _NativeTurn, home: Path, session: _SavedSession, observations: FileObservations, *,
           agent: str | None = None, parent: CallLink | None = None) -> Iterator[Item]:
    results = {record.data["parentUuid"]: record for record in turn.records if record.kind == "tool.result"}
    seen: set[str] = set()
    for record in turn.records:
        data = record.data
        if record.kind == "content.part" and agent is None and (item := _content(record)) is not None:
            yield item
        if record.kind != "tool.call" or data["uuid"] in seen:
            continue
        seen.add(data["uuid"])
        result, ok, error = None, True, None
        if linked := results.get(data["uuid"]):
            result, ok, error = _result(home, session, linked, observations)
        yield ToolCall(
            data["toolCallId"], agent, data["name"], data.get("args"), result, ok, error,
            parent.call_id if parent else None, record.time(), parent=parent,
        )


def _check_tool(record: _Record) -> None:
    data = record.data
    if record.kind == "tool.call":
        if not all(_string(data.get(key)) for key in ("uuid", "toolCallId", "name")):
            record.invalid("tool.call")
    elif record.kind == "tool.result":
        result = _object(data.get("result"))
        if not _string(data.get("parentUuid")) or ("isError" in result and type(result["isError"]) is not bool):
            record.invalid("tool.result")
        if not isinstance(result.get("output"), str):
            _parts(result.get("output"), record)


_SPILL_LINE = re.compile(r"(?m)^output_path: ([^\r\n]+)\r?$")


def _spill_name(result: dict[str, Any], text: str) -> str | None:
    if name := _string(_object(result.get("spill")).get("outputPath")):
        return name
    if result.get("truncated") is True or text.startswith(("Tool output exceeded ", "[Per-line truncation occurred;")):
        if found := _SPILL_LINE.search(text):
            return found[1]
    return None


def _spill_path(session: _SavedSession, name: str) -> Path:
    path = Path(name)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "tool-results":
        return session.folder / path
    return session.folder / "tool-results" / path


def _result(
    home: Path, session: _SavedSession, record: _Record, observations: FileObservations,
) -> tuple[Result, bool, str | None]:
    result = _object(record.data["result"])
    output = result["output"]
    parts = [] if isinstance(output, str) else _parts(output, record)
    text = output if isinstance(output, str) else _text(parts)
    if name := _spill_name(result, text):
        path = _spill_path(session, name)
        directory = session.folder / "tool-results"
        if (path.is_relative_to(directory) and _eligible(home, path)
                and not any(_forbidden(part) for part in path.relative_to(directory).parts)):
            try:
                with observed_input(home, path.relative_to(home).as_posix(), observations) as stream:
                    text = stream.read().decode("utf-8")
            except (OSError, UnicodeError):
                raise SessionFailure("unreadable_session", f"{record.where}: could not read the tool result.") from None
    ok = result.get("isError") is not True
    error = None if ok else _error(result.get("error")) or text or _string(result.get("note"))
    fields = {key: value for key, value in result.items() if key not in {"output", "isError"}}
    images = tuple(image for part in parts if (image := _image(home, session, part, observations)) is not None)
    return Result(text, fields or None, images), ok, error


_FILE_ID = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*")
_BLOB_HASH = re.compile(r"[0-9a-fA-F]{64}")


def _file_name(url: str) -> str:
    return unquote(url.removeprefix("kimi-file://").partition("?")[0])


def _upload(
    home: Path, name: str, observations: FileObservations, directory: Path | None = None,
) -> tuple[Path | None, str | None]:
    if not _FILE_ID.fullmatch(name):
        return None, None
    directory = directory or home / "files"
    metadata = directory / "meta" / f"{name}.json"
    if _eligible(home, metadata):
        try:
            with observed_input(home, metadata.relative_to(home).as_posix(), observations) as stream:
                value = _object(json.load(stream))
        except (ValueError, RecursionError):
            value = {}
        key = _string(value.get("key")) or ""
        if (value.get("version") == 1 and _FILE_ID.fullmatch(key)
                and (key == name or key.startswith(f"{name}.")) and not _forbidden(key)):
            saved = directory / key
            if _eligible(home, saved):
                return saved, _string(value.get("mediaType"))
    elif metadata in observations.files:
        raise OSError("Previously read upload metadata is unavailable.")
    try:
        path = next((path for path in _children(home, directory)
                     if (path.name == name or path.name.startswith(f"{name}."))
                     and ".tmp." not in path.name and not _forbidden(path.name)), None)
    except SessionFailure:
        return None, None
    return path, None


def _size(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _image(
    home: Path, session: _SavedSession, part: dict[str, Any], observations: FileObservations,
) -> Image | None:
    if part["type"] != "image_url":
        return None
    native = _object(part.get("imageUrl"))
    metadata = _object(part.get("meta"))
    url = _string(native.get("url")) or ""
    media = None
    size = None
    for evidence in (native, metadata, part):
        media = media or _string(evidence.get("mimeType", evidence.get("mediaType")))
        if size is None:
            size = _size(evidence.get("size", evidence.get("byteLength")))
    path = None
    if url.startswith("data:"):
        header, separator, payload = url.removeprefix("data:").partition(",")
        media = media or header.partition(";")[0]
        if separator and size is None:
            try:
                raw = unquote_to_bytes(payload)
                size = len(b64decode(raw, validate=True)) if header.endswith(";base64") else len(raw)
            except (ValueError, UnicodeError):
                return None
    elif url.startswith("blobref:"):
        blob_media, separator, hash_value = url.removeprefix("blobref:").partition(";")
        media = media or blob_media
        if separator and _BLOB_HASH.fullmatch(hash_value):
            path = session.folder / "blobs" / hash_value
    elif url.startswith("kimi-file://"):
        name = _file_name(url)
        path, mime = _upload(home, name, observations)
        if path is None or not _eligible(home, path):
            path, mime = _upload(home, name, observations, session.folder / "media")
        media = media or mime
    elif not url.startswith("ms://"):
        return None

    if path is not None and _eligible(home, path):
        media = media or mimetypes.guess_file_type(path)[0]
        try:
            info = observations.record(path, path.stat(follow_symlinks=False))
            size = info.size if size is None else size
        except FileNotFoundError:
            if path in observations.files:
                raise
    if media is not None and media.startswith("image/") and size is not None:
        return Image(media, size)
    return None


_USAGE_FIELDS = ("inputOther", "inputCacheRead", "inputCacheCreation", "output")


def _usage(record: _Record) -> Usage | None:
    value = record.data.get("usage")
    if value is None:
        return None
    if not isinstance(value, dict):
        record.invalid("step.end")
    counts = [value.get(field, 0) for field in _USAGE_FIELDS]
    if any(type(count) is not int or count < 0 for count in counts):
        record.invalid("step.end")
    return Usage.native(
        uncached=counts[0], cache_read=counts[1],
        cache_write=counts[2] if "inputCacheCreation" in value else None, output=counts[3],
    )


def _request_turn(record: _Record) -> str | None:
    data = record.data
    if location := _string(data.get("turnStep")):
        turn, _, step = location.rpartition(".")
        if not turn or not step:
            record.invalid("llm.request")
        return turn
    return _turn_key(data.get("turnId"))


def _responses(turn: _NativeTurn, counted: set[str]) -> Iterator[Response]:
    starts: dict[str, datetime] = {}
    for record in turn.records:
        if record.kind == "step.begin":
            starts.setdefault(record.data["uuid"], record.time())
        elif record.kind == "step.end":
            uuid: str = record.data["uuid"]
            if uuid in starts and uuid not in counted and (usage := _usage(record)) is not None:
                counted.add(uuid)
                yield Response(starts[uuid], usage)


@dataclass(frozen=True)
class _Launch:
    parent_agent: str
    parent_turn: _NativeTurn | None
    call_id: str | None
    at: datetime


def _launches(lanes: dict[str, _Lane]) -> dict[str, list[_Launch]]:
    launches: dict[str, list[_Launch]] = {}
    for agent, lane in lanes.items():
        # Preserve evidence of a removed launch so its child cannot reappear as unlinked work.
        for erased_child, at in lane.erased_launches:
            launches.setdefault(erased_child, []).append(_Launch(agent, None, None, at))
        by_uuid = {record.data["uuid"]: (turn, record) for turn in lane.turns.values()
                   for record in turn.records if record.kind == "tool.call"}
        for turn in lane.turns.values():
            calls = {record.data["toolCallId"]: (turn, record)
                     for record in turn.records if record.kind == "tool.call"}
            for record in turn.records:
                if record.kind != "subagent.spawned":
                    continue
                data = record.data
                uuid = _string(data.get("parentToolCallUuid")) or ""
                call_id = _string(data.get("parentToolCallId")) or ""
                parent = by_uuid.get(uuid) or calls.get(call_id)
                if parent is None:
                    continue
                parent_turn, call = parent
                child: str = data["subagentId"]
                launches.setdefault(child, []).append(_Launch(agent, parent_turn, call.data["toolCallId"], call.time()))
    for entries in launches.values():
        entries.sort(key=lambda launch: launch.at)
    return launches


def _turn_at(lane: _Lane, at: datetime) -> _NativeTurn | None:
    for turn in reversed(lane.turns.values()):
        end = turn.end.time() if turn.end is not None else turn.last_at
        if turn.start.time() <= at <= end:
            return turn
    return None


def _route(agent: str, at: datetime, first_at: datetime, main: _Lane,
           launches: dict[str, list[_Launch]]) -> tuple[_NativeTurn | None, CallLink | None]:
    """Find the main turn and the immediate launch call, walking parent lanes."""
    parent = None
    visited = set()
    while agent not in visited:
        visited.add(agent)
        entries = launches.get(agent, [])
        launch = next((entry for entry in reversed(entries) if entry.at <= at), entries[0] if entries else None)
        if launch is None:
            return _turn_at(main, first_at), parent
        if launch.parent_turn is None:
            return None, None
        if parent is None and launch.call_id is not None:
            parent = CallLink(None if launch.parent_agent == "main" else launch.parent_agent, launch.call_id)
        if launch.parent_agent == "main":
            return launch.parent_turn, parent
        agent = launch.parent_agent
        at = first_at = launch.parent_turn.start.time()
    return _turn_at(main, first_at), None


@dataclass
class _ChildWork:
    first_at: datetime
    parent: CallLink | None
    failed: bool = False
    usage: Usage = field(default_factory=Usage)
    items: list[Item] = field(default_factory=list)


def _item_time(item: Item) -> datetime:
    return item.at if isinstance(item, TextBlock) else item.started_at


def _project(
    lanes: dict[str, _Lane], home: Path, session: _SavedSession, cwd: str | None, observations: FileObservations,
) -> Iterator[Turn]:
    main = lanes["main"]
    launches = _launches(lanes)
    children: dict[str, dict[str, _ChildWork]] = {}
    for agent, lane in lanes.items():
        if agent == "main" or lane.first_at is None:
            continue
        counted: set[str] = set()
        native_turns: Iterable[_NativeTurn | None] = lane.turns.values() or (None,)
        for index, turn in enumerate(native_turns):
            at = turn.start.time() if turn is not None else lane.first_at
            first_at = lane.first_at if index == 0 else at
            root, parent = _route(agent, at, first_at, main, launches)
            if root is None:
                continue
            work = children.setdefault(root.key, {}).setdefault(agent, _ChildWork(first_at, parent))
            if turn is not None:
                work.failed = turn.end is not None and turn.end.data["reason"] not in ("cancelled", "completed")
                for response in _responses(turn, counted):
                    work.usage += response.usage
                work.items.extend(_items(turn, home, session, observations, agent=agent, parent=parent))

    counted_main: set[str] = set()
    for turn in main.turns.values():
        root_items = _items(turn, home, session, observations)
        agents = children.get(turn.key, {})
        items = tuple(merge(root_items, *(work.items for work in agents.values()), key=_item_time))
        subagents = tuple(
            Subagent(agent, work.parent.call_id if work.parent else None, work.first_at, work.failed,
                     work.usage, work.parent)
            for agent, work in agents.items()
        )
        yield replace(turn.project(cwd, counted_main), items=items, subagents=subagents)


# Tracked Forester and Arbol evidence gives counts but no exact Kimi installation probe prompts (IMP-D28).
_PROBE_PROMPTS: frozenset[str] = frozenset()


def _kind(lanes: dict[str, _Lane]) -> Kind:
    main = lanes["main"]
    if len(main.turns) == 1:
        turn = next(iter(main.turns.values()))
        if turn.prompt in _PROBE_PROMPTS and not any(
            record.kind == "tool.call"
            for lane in lanes.values()
            for agent_turn in lane.turns.values()
            for record in agent_turn.records
        ):
            return "probe"
    return "owner"


def _origin(session: _SavedSession, main: _Lane) -> dict[str, str]:
    origin = {"workspace": session.workspace}
    if main.turns:
        origin["originKind"] = next(iter(main.turns.values())).origin
    return origin


_ARCHIVE_TREES = ("blobs", "tool-results", "file-history", "tasks", "plans", "media", "media-originals")
_EXCLUDED = frozenset({
    "logs", "locks", "credentials", "oauth", "server.token", "device_id", "server",
    "search-index", "cache", "image-upload-cache",
})
_FILE_REFERENCE = re.compile(r"""kimi-file://[^\s"'<>\])}]+""")


def _forbidden(name: str) -> bool:
    name = name.lower()
    return name in _EXCLUDED or name.startswith("config.toml") or name.endswith((".wal", ".index", ".postings"))


@dataclass
class _RawFiles:
    home: Path
    session: _SavedSession
    observations: FileObservations
    uploads: set[str] = field(default_factory=set)
    outside: set[Path] = field(default_factory=set)

    def escapes(self, path: Path) -> bool:
        try:
            absolute = Path(os.path.abspath(path))
            resolved = path.resolve()
        except (OSError, ValueError, RuntimeError):
            return False
        if absolute.is_relative_to(self.home) and resolved.is_relative_to(self.home):
            return False
        self.outside.add(resolved)
        return True

    def observe(self, row: dict[str, Any]) -> None:
        values: list[object] = [row]
        while values:
            value = values.pop()
            if isinstance(value, dict):
                values.extend(value.values())
            elif isinstance(value, list):
                values.extend(value)
            elif isinstance(value, str) and "kimi-file://" in value:
                self.uploads.update(_file_name(match[0]) for match in _FILE_REFERENCE.finditer(value))

        if row.get("type") == "context.append_loop_event":
            event = _object(row.get("event"))
            if event.get("type") == "tool.result":
                result = _object(event.get("result"))
                output = result.get("output")
                if isinstance(output, list):
                    output = "".join(_string(_object(part).get("text")) or "" for part in output)
                if name := _spill_name(result, _string(output) or ""):
                    self.escapes(_spill_path(self.session, name))

    def archive(self, wires: dict[str, Path]) -> tuple[HomeFile, ...]:
        result: set[Path] = set()
        pending = [self.session.folder / name for name in _ARCHIVE_TREES]
        while pending:
            path = pending.pop()
            if _forbidden(path.name) or self.escapes(path):
                continue
            if _eligible(self.home, path, directory=True):
                pending.extend(_children(self.home, path))
            elif _eligible(self.home, path):
                result.add(path)

        agents = self.session.folder / "agents"
        self.escapes(agents)
        listed = [self.session.state, *(wire for agent, wire in wires.items() if not _forbidden(agent))]
        for path in listed:
            eligible = not self.escapes(path) and _eligible(self.home, path)
            if eligible != (path in self.observations.files):
                raise OSError("A native wire or state file changed during projection.")
            if eligible:
                result.add(path)
        for name in self.uploads:
            named = self.home / "files" / name
            if not self.escapes(named):
                upload, _ = _upload(self.home, name, self.observations)
                if upload is not None and not self.escapes(upload) and _eligible(self.home, upload):
                    result.add(upload)
        files = tuple(self.observations.nominate(self.home, path) for path in sorted(result))
        for path in self.observations.files:
            self.observations.record(path, path.stat(follow_symlinks=False))
        return files


def _claim_is_live(claim: dict[str, Any]) -> bool:
    pid = _size(claim.get("pid"))
    host = _string(claim.get("hostname"))
    started = _time(claim.get("startedAt"))
    if not pid or pid > 2**31 - 1 or not host or started is None:
        return False
    if host != gethostname():
        # The native locker treats a claim from another host as held.
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "stat=", "-o", "lstart="],
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1, check=False,
        )
        if result.returncode != 0:
            return False
        status, date = result.stdout.split(None, 1)
        if status.startswith("Z"):
            return False
        process_started = datetime.strptime(date.strip(), "%a %b %d %H:%M:%S %Y").replace(tzinfo=UTC)
        return process_started <= started
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return True


def _locked(home: Path, session: _SavedSession) -> bool:
    directory = home / "locks" / "sessions"
    for name in (session.folder.name, session.native_id):
        path = directory / f"{name}.lock"
        if _eligible(home, path):
            try:
                with path.open("rb") as stream:
                    claim = _object(json.load(stream))
            except (OSError, ValueError, RecursionError):
                continue
            if _claim_is_live(claim):
                return True
    return False


def read(source: Source) -> Iterator[Session | Failed]:
    """Yield selected sessions or their individual failures. Open native files read-only."""
    try:
        home = source.home.resolve()
    except (OSError, ValueError, RuntimeError):
        failure = SessionFailure("unreadable_session", "sessions: could not resolve the tool home.")
        yield Failed.of(failure, file="sessions")
        return

    inventory: dict[str, _SavedSession] = {}
    yield from _discover(home, inventory, report_unidentified=source.selected is None)
    for session in inventory.values():
        if not source.wants(session.native_id):
            continue
        lanes = {"main": _Lane()}
        observations = FileObservations()
        files = _RawFiles(home, session, observations)
        try:
            state = _state(home, session.state, observations)
            wires = _wires(home, session)
            copied = _fork_ids(home, session, state, inventory)
            main = lanes["main"]
            for agent, path in wires.items():
                lane = lanes.setdefault(agent, _Lane())
                for where, row in _rows(home, path, observations):
                    files.observe(row)
                    if lane.first_at is None:
                        lane.first_at = _time(row.get("created_at") if row["type"] == "metadata" else row.get("time"))
                    if copied is None or not copied.has(agent, row):
                        lane.append(_record(where, row))
            created = main.first_at
            if created is None:
                created = state.created_at or observations.files[session.main].modified_at
            kind = _kind(lanes)
            turns = tuple(_project(lanes, home, session, state.cwd, observations))
            files_to_archive = files.archive(wires)
            live = any(
                observations.files[path].modified_at >= source.clock - LIVE_WINDOW
                for path in wires.values()
            ) or _locked(home, session)
            yield Session("kimi-code", session.native_id, kind, state.title, created, main.version,
                          _origin(session, main), state.cwd, live, turns,
                          files_to_archive, len(files.outside))
        except SessionFailure as session_failure:
            yield Failed.of(session_failure, native_id=session.native_id, kind=_kind(lanes))
        except (OSError, UnicodeError, RecursionError):
            failure = SessionFailure("unreadable_session", f"{session.folder.relative_to(home)}: could not read session.")
            yield Failed.of(failure, native_id=session.native_id, kind=_kind(lanes))
