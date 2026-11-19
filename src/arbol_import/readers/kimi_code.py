"""Read Kimi Code's saved session wires and identify their raw archive files."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never

from .form import Item, SessionFailure, State, Steer, TextBlock, Trigger, Turn, unknown_record
from .lines import file_records

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


def _discover(home: Path) -> dict[str, _SavedSession]:
    sessions: dict[str, _SavedSession] = {}
    for workspace in _children(home, home / "sessions"):
        for folder in _children(home, workspace):
            match = _SESSION.fullmatch(folder.name)
            if match and _eligible(home, folder, directory=True):
                native_id = match[1].lower()
                sessions.setdefault(native_id, _SavedSession(folder, workspace.name, native_id))
    return sessions


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
    archived: bool | None = None
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


def _state(home: Path, path: Path) -> _State:
    where = path.relative_to(home)
    try:
        if not _eligible(home, path):
            if not path.exists() and not path.is_symlink():
                return _State()
            raise ValueError
        with path.open("rb") as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ValueError
        fork = value.get("forkedFrom")
        if fork is not None and not isinstance(fork, str):
            raise ValueError
    except (OSError, ValueError, RecursionError):
        raise SessionFailure("unreadable_session", f"{where}: could not read the session state.") from None
    archived = value.get("archived")
    return _State(_string(value.get("title")), _string(value.get("cwd")),
                  archived if isinstance(archived, bool) else None, fork, _time(value.get("createdAt")))


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


def _rows(home: Path, path: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    file = path.relative_to(home).as_posix()
    if not _eligible(home, path):
        raise SessionFailure("unreadable_session", f"{file}: no eligible wire.")
    for number, raw in file_records(home, file):
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


def _records(home: Path, path: Path, copied: set[str]) -> Iterator[_Record]:
    for where, row in _rows(home, path):
        if copied.isdisjoint(_record_ids(row)):
            yield _record(where, row)


def _fork_ids(home: Path, session: _SavedSession, state: _State,
              inventory: dict[str, _SavedSession]) -> set[str]:
    if state.forked_from is None:
        return set()
    failure = SessionFailure("unreadable_session", f"{session.state.relative_to(home)}: fork source is unavailable.")
    source = inventory.get(state.forked_from.lower())
    if source is None or source == session:
        raise failure
    ids: set[str] = set()
    try:
        for path in _wires(home, source).values():
            for where, row in _rows(home, path):
                _record(where, row)
                ids.update(_record_ids(row))
    except SessionFailure:
        raise failure from None
    return ids


def _step_number(record: _Record) -> str | None:
    value = record.data.get("step")
    return str(value) if type(value) is int or isinstance(value, str) else None


def _undo(records: list[_Record], count: int) -> None:
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
    records[:] = [record for index, record in enumerate(records) if owners.get(index) not in removed]


def _context_edit(record: _Record, records: list[_Record]) -> None:
    if record.kind == "context.clear":
        records.clear()
    elif record.kind == "context.undo":
        count = record.data.get("count")
        if type(count) is not int or count <= 0:
            record.invalid("context.undo")
        _undo(records, count)


_TRIGGERS: dict[str, Trigger] = {
    "user": "typed",
    "task": "task",
    "skill_activation": "system",
    "system_trigger": "system",
}
_MEDIA_PARTS = frozenset({"image_url", "video_url", "audio_url"})


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
        elif kind not in _MEDIA_PARTS and kind != "think":
            record.invalid(record.kind)
        parts.append(part)
    return parts


def _text(parts: list[dict[str, Any]]) -> str:
    return "".join(part["text"] for part in parts if part["type"] == "text")


def _prompt(record: _Record) -> str:
    return _text(_parts(record.data.get("input"), record))


def _error(value: object) -> str | None:
    return _string(value) or _string(_object(value).get("message"))


@dataclass
class _NativeTurn:
    key: str
    origin: str
    prompt: str
    start: _Record
    last_at: datetime
    end: _Record | None = None
    records: list[_Record] = field(default_factory=list)

    def project(self, cwd: str | None) -> Turn:
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
        return Turn(self.key, _TRIGGERS.get(self.origin, "system"), self.prompt, self.start.time(),
                    self.end.time() if self.end is not None else self.last_at, state, error, kind,
                    cwd, None, None, steers=steers)


@dataclass
class _Lane:
    first_at: datetime | None = None
    version: str | None = None
    turns: dict[str, _NativeTurn] = field(default_factory=dict)
    current: _NativeTurn | None = None
    call_turns: dict[str, _NativeTurn] = field(default_factory=dict)

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
        if kind == "context.clear":
            self.turns.clear()
            self.call_turns.clear()
            self.current = None
            return
        if kind == "turn.prompt":
            origin = _string(_object(data.get("origin")).get("kind"))
            if key is None or not origin:
                record.invalid(kind)
            prompt = _prompt(record)
            turn = _NativeTurn(key, origin, prompt, record, record.time(), records=[record])
            self.current = self.turns[key] = turn
            return

        turn = self.turns.get(key) if key is not None else self.current
        if kind == "tool.result" and (parent := _string(data.get("parentUuid"))):
            turn = self.call_turns.get(parent, turn)
        if kind == "context.undo":
            if turn is None and self.turns:
                turn = next(reversed(self.turns.values()))
            if turn is not None:
                _context_edit(record, turn.records)
                if not any(item.kind == "turn.prompt" for item in turn.records):
                    del self.turns[turn.key]
                    self.call_turns = {uuid: owner for uuid, owner in self.call_turns.items() if owner is not turn}
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


def _content(record: _Record) -> TextBlock | None:
    part = _object(record.data.get("part"))
    _parts([part], record)
    if part["type"] == "text":
        return TextBlock(part["text"], _time(record.data.get("startedAt")) or record.time())
    return None


def _items(turn: _NativeTurn, home: Path, session: _SavedSession, *,
           agent: str | None = None, parent_call: str | None = None) -> Iterator[Item]:
    if agent is None:
        for record in turn.records:
            if record.kind == "content.part" and (item := _content(record)) is not None:
                yield item
