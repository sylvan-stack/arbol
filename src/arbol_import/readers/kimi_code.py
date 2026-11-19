"""Read Kimi Code's saved session wires and identify their raw archive files."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never

from .form import SessionFailure, unknown_record
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
