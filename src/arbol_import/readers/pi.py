"""Read saved Pi SessionManager v3 sessions and their archive references (IMP-1)."""

from __future__ import annotations

import base64
import binascii
import os
import re
import stat
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

from .form import Image, Item, Kind, Result, SessionFailure, Source, State, TextBlock, ToolCall, Turn, unknown_record
from .lines import file_records

_NATIVE_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
_ENTRY_TYPES = (
    "message", "thinking_level_change", "model_change", "usage", "compaction", "branch_summary",
    "custom", "custom_message", "context_edit", "label", "session_info",
)
_ARCHIVE_ROLES = ("system", "custom", "bashExecution", "branchSummary", "compactionSummary")
_SPILL_LOG = re.compile(r"pi-(?:bash|powershell|output)-[0-9a-f]{16}\.log")
_EXCLUDED_NAMES = frozenset({
    ".cache", ".env", ".git", ".ssh", "auth", "cache", "caches", "config", "credentials", "device-id",
    "device_id", "logs", "secrets", "tokens",
})
_HOME_STATE_DIRS = frozenset({"bin", "extensions", "install", "plugins", "prompts", "skills", "themes", "tools"})


def _iso_time(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            at = datetime.fromisoformat(value)
            if at.utcoffset() is not None:
                return at.astimezone(UTC)
        except (ValueError, OverflowError):
            pass
    return None


def _unreadable(file: str) -> SessionFailure:
    return SessionFailure("unreadable_session", f"{file}: the file could not be read.")


def _session_name(path: Path) -> bool:
    prefix, separator, suffix = path.stem.partition("_")
    return path.suffix == ".jsonl" and bool(prefix and separator and suffix)


def _session_layout(relative: Path) -> bool:
    return len(relative.parts) == 3 and relative.parts[0] == "sessions" and _session_name(relative)


def _eligible_path(relative: Path) -> bool:
    if relative.parts and relative.parts[0].casefold() in _HOME_STATE_DIRS:
        return False
    for part in relative.parts:
        name = part.casefold()
        if name in _EXCLUDED_NAMES or name.startswith((
            ".env.", "auth.", "config.", "credentials.", "device-id.", "device_id.", "settings.", "settings-backup-",
        )):
            return False
        if name.startswith("models") and ".json" in name:
            return False
        # Pi's shell tools save full tool output with a .log suffix as well.
        if name.endswith((".cache", ".index", ".log", ".token", ".wal")) and not _SPILL_LOG.fullmatch(name):
            return False
    return True


def _children(home: Path, directory: Path) -> list[Path]:
    file = directory.relative_to(home).as_posix()
    try:
        resolved = directory.resolve()
        if not resolved.is_relative_to(home / "sessions"):
            raise _unreadable(file)
        if not _eligible_path(directory.relative_to(home)) or not _eligible_path(resolved.relative_to(home)):
            return []
        if stat.S_ISDIR(resolved.stat().st_mode):
            return sorted(resolved.iterdir())
    except FileNotFoundError:
        pass
    except (OSError, RuntimeError, ValueError):
        raise _unreadable(file) from None
    return []


def _session_path(home: Path, path: Path) -> Path:
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(home)
        if (_session_layout(relative)
                and _eligible_path(path.relative_to(home)) and _eligible_path(relative)
                and stat.S_ISREG(resolved.stat().st_mode)):
            return resolved
    except (OSError, RuntimeError, ValueError):
        pass
    raise _unreadable(path.relative_to(home).as_posix())


def _session_records(home: Path, file: str) -> Generator[tuple[int, Any]]:
    yield from file_records(home, file)


@dataclass(frozen=True)
class _Header:
    native_id: str
    created_at: datetime
    cwd: str


def _header(row: Any, file: str, line: int) -> _Header:
    if isinstance(row, dict) and row.get("type") == "session" and type(row.get("version")) is int:
        native_id = row.get("id")
        at = _iso_time(row.get("timestamp"))
        cwd = row.get("cwd")
        if row["version"] == 3 and isinstance(native_id, str) and _NATIVE_ID.fullmatch(native_id):
            if at is not None and isinstance(cwd, str):
                return _Header(native_id, at, cwd)
    unknown_record("session", f"{file}:{line}", conversation=True)
    raise AssertionError("A malformed session header must fail.")


def _selected_header(rows: Iterator[tuple[int, Any]], file: str, source: Source) -> _Header | None:
    first = next(rows, None)
    if first is None:
        return None
    line, row = first
    header = _header(row, file, line)
    return header if source.wants(header.native_id) else None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True)
class _Entry:
    file: str
    line: int
    row: dict[str, Any]

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}"

    @property
    def native_id(self) -> str | None:
        return _string(self.row.get("id"))

    @property
    def at(self) -> datetime | None:
        return _iso_time(self.row.get("timestamp"))

    @property
    def has_parent(self) -> bool:
        return "parentId" in self.row and (
            self.row["parentId"] is None or _string(self.row["parentId"]) is not None
        )

    def bad(self, record_type: str) -> NoReturn:
        unknown_record(record_type, self.where, conversation=True)
        raise AssertionError("A malformed Pi conversation record must fail.")


@dataclass
class _Scan:
    file: str
    entries: list[_Entry] = field(default_factory=list)
    kind: Kind = "owner"
    title: str | None = None

    def add(self, line: int, row: Any) -> None:
        if not isinstance(row, dict):
            return
        entry = _Entry(self.file, line, row)
        self.entries.append(entry)
        if (line == 2 and row.get("type") == "custom" and row.get("customType") == "arbol-history-import"
                and entry.native_id is not None and entry.has_parent and entry.at is not None):
            self.kind = "arbol_driver"
        if row.get("type") == "session_info":
            name = _string(row.get("name"))
            self.title = name if name and name.strip() else None


def _active_path(entries: list[_Entry]) -> list[_Entry]:
    by_id: dict[str, _Entry] = {}
    duplicate_ids: set[str] = set()
    leaf = None
    for entry in entries:
        entry_type = entry.row.get("type")
        native_id = entry.native_id
        if entry_type not in _ENTRY_TYPES and not (
            isinstance(entry_type, str) and entry_type != "session" and native_id is not None and entry.has_parent
        ):
            unknown_record(entry_type, entry.where, conversation=False)
            continue
        if native_id is not None:
            if native_id in by_id:
                duplicate_ids.add(native_id)
            by_id[native_id] = entry
        leaf = entry

    # On reload, Pi treats the last entry as the leaf, even when it belongs to a newer branch from an older parent.
    path = []
    current = leaf
    while current is not None:
        if current.native_id is None or current.native_id in duplicate_ids or not current.has_parent:
            current.bad("session-entry")
        path.append(current)
        parent_id = current.row["parentId"]
        if parent_id is None:
            break
        parent = by_id.get(parent_id)
        # Append-only ancestry goes backwards in file order, which also rules out cycles.
        if parent is None or parent.line >= current.line:
            current.bad("session-entry")
        current = parent
    return path[::-1]


def _active_messages(entries: list[_Entry]) -> Iterator[tuple[_Entry, dict[str, Any]]]:
    for entry in _active_path(entries):
        record_type = entry.row.get("type")
        if record_type != "message":
            unknown_record(record_type, entry.where, conversation=False)
            continue
        message = entry.row.get("message")
        if not isinstance(message, dict):
            entry.bad("message")
        role = message.get("role")
        if role in _ARCHIVE_ROLES:
            continue
        if role not in ("user", "assistant", "toolResult") or entry.at is None:
            entry.bad("message")
        yield entry, message


type _Message = tuple[_Entry, dict[str, Any]]


def _entry_time(entry: _Entry) -> datetime:
    at = entry.at
    if at is None:
        entry.bad("message")
    return at


def _native_time(entry: _Entry, record: dict[str, Any]) -> datetime:
    if "timestamp" not in record:
        return _entry_time(entry)
    stamp = record["timestamp"]
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        try:
            return datetime.fromtimestamp(stamp / 1000, UTC)
        except (OSError, OverflowError, ValueError):
            pass
    entry.bad("message-timestamp")


def _parts(entry: _Entry, content: object, allowed: tuple[str, ...]) -> Iterator[dict[str, Any]]:
    if not isinstance(content, list):
        entry.bad("message-content")
    for part in content:
        if not isinstance(part, dict) or part.get("type") not in allowed:
            entry.bad("message-part")
        if part["type"] == "text" and not isinstance(part.get("text"), str):
            entry.bad("text")
        yield part


def _prompt(entry: _Entry, message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts = _parts(entry, content, ("text", "image"))
    return "\n".join(part["text"] for part in parts if part["type"] == "text")


def _turn_messages(messages: Iterator[_Message]) -> Iterator[list[_Message]]:
    turn: list[_Message] = []
    for entry, message in messages:
        if message["role"] == "user":
            if turn:
                yield turn
            turn = [(entry, message)]
        elif turn:
            turn.append((entry, message))
    if turn:
        yield turn


def _ending(assistant: _Message | None) -> tuple[State, str | None, str | None]:
    if assistant is None:
        return "interrupted", None, None
    entry, message = assistant
    reason = _string(message.get("stopReason"))
    if reason is None:
        entry.bad("assistant-stop")
    if reason == "stop":
        return "completed", None, None
    if reason == "aborted":
        return "cancelled", None, None
    if reason == "toolUse":
        return "interrupted", None, None
    if reason == "error":
        return "failed", _string(message.get("errorMessage")), None
    return "failed", None, reason


def _turn_end(last: _Message, state: State) -> datetime:
    entry, message = last
    if message["role"] == "toolResult":
        return _native_time(entry, message)
    if message["role"] == "assistant" and state != "interrupted" and "durationMs" in message:
        duration = message["durationMs"]
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
            try:
                return _native_time(entry, message) + timedelta(milliseconds=duration)
            except (OverflowError, ValueError):
                pass
        entry.bad("assistant-duration")
    return _entry_time(entry)


def _turn(home: Path, rows: list[_Message], cwd: str) -> Turn:
    start, user = rows[0]
    turn_key = start.native_id
    assert turn_key is not None  # The active path validated it.
    last_assistant = next((row for row in reversed(rows) if row[1]["role"] == "assistant"), None)
    state, error, error_kind = _ending(last_assistant)
    return Turn(
        turn_key=turn_key,
        trigger="typed",
        prompt=_prompt(start, user),
        started_at=_native_time(start, user),
        ended_at=_turn_end(rows[-1], state),
        state=state,
        error=error,
        error_kind=error_kind,
        working_folder=cwd,
        model=None,
        effort=None,
        items=tuple(_items(home, rows)),
    )


def _image(entry: _Entry, part: dict[str, Any]) -> Image:
    media_type = _string(part.get("mimeType"))
    data = part.get("data")
    if media_type is None or not isinstance(data, str):
        entry.bad("image")
    try:
        return Image(media_type, len(base64.b64decode(data, validate=True)))
    except (binascii.Error, ValueError):
        entry.bad("image")


def _without_image_bytes(value: Any) -> Any:
    if isinstance(value, list):
        return [_without_image_bytes(item) for item in value]
    if isinstance(value, dict):
        image = value.get("type") == "image" and isinstance(value.get("mimeType"), str)
        return {key: _without_image_bytes(item) for key, item in value.items() if not (image and key == "data")}
    return value


def _spill_failure(entry: _Entry) -> SessionFailure:
    return SessionFailure("unreadable_session", f"{entry.where}: the spilled tool result could not be read.")


def _spill_path(home: Path, entry: _Entry, message: dict[str, Any]) -> Path | None:
    details = message.get("details")
    name = _string(details.get("fullOutputPath")) if isinstance(details, dict) else None
    if name is None or "\0" in name:
        return None
    path = home / name
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError, ValueError):
        normalized = Path(os.path.abspath(path))
        if not normalized.is_relative_to(home):
            return normalized
        raise _spill_failure(entry) from None
    if resolved.is_relative_to(home):
        if path.is_relative_to(home) and not _eligible_path(path.relative_to(home)):
            return None
        relative = resolved.relative_to(home)
        if _session_layout(relative) or not _eligible_path(relative):
            return None
    return resolved


def _full_output(home: Path, entry: _Entry, message: dict[str, Any], inline: str) -> str:
    path = _spill_path(home, entry, message)
    if path is None or not path.is_relative_to(home):
        return inline
    try:
        if stat.S_ISREG(path.stat().st_mode):
            return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError):
        raise _spill_failure(entry) from None
    return inline


def _result(home: Path, entry: _Entry, message: dict[str, Any]) -> tuple[Result, str | None, bool]:
    content = message.get("content")
    parts = list(_parts(entry, content, ("text", "image")))
    output = "\n".join(part["text"] for part in parts if part["type"] == "text")
    images = tuple(_image(entry, part) for part in parts if part["type"] == "image")
    is_error = message.get("isError", False)
    if not isinstance(is_error, bool):
        entry.bad("tool-result")
    details = message.get("details")
    truncated = False
    if isinstance(details, dict):
        truncation = details.get("truncation")
        truncated = truncation is True or (isinstance(truncation, dict) and truncation.get("truncated") is True)
        fields = {key: value for key, value in details.items() if key not in ("truncation", "fullOutputPath")}
    else:
        fields = {"details": details} if details is not None else {}
    full_output = _full_output(home, entry, message, output)
    return Result(full_output, _without_image_bytes(fields) or None, images), output if is_error else None, truncated


def _results(rows: list[_Message]) -> dict[str, _Message]:
    results: dict[str, _Message] = {}
    for entry, message in rows:
        if message["role"] != "toolResult":
            continue
        call_id = _string(message.get("toolCallId"))
        if call_id is None or call_id in results:
            entry.bad("tool-result")
        _native_time(entry, message)
        results[call_id] = (entry, message)
    return results


def _items(home: Path, rows: list[_Message]) -> Iterator[Item]:
    results = _results(rows)
    calls: set[str] = set()
    for entry, message in rows:
        if message["role"] != "assistant":
            continue
        for part in _parts(entry, message.get("content"), ("text", "thinking", "toolCall")):
            if part["type"] == "text":
                yield TextBlock(part["text"], _entry_time(entry))
            if part["type"] != "toolCall":
                continue
            call_id = _string(part.get("id"))
            name = _string(part.get("name"))
            arguments = part.get("arguments")
            if call_id is None or call_id in calls or name is None or not isinstance(arguments, dict):
                entry.bad("tool-call")
            calls.add(call_id)
            saved = results.get(call_id)
            result, error, truncated = _result(home, *saved) if saved is not None else (None, None, False)
            yield ToolCall(
                call_id=call_id,
                agent=None,
                name=name,
                input=arguments,
                result=result,
                ok=result is not None and error is None,
                error=error,
                parent_call_id=None,
                started_at=_native_time(entry, part),
                truncated=truncated,
            )
