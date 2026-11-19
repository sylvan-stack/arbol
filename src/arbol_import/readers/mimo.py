"""Read saved Mimo sessions from a private copy of their SQLite database (IMP-1)."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import stat
from collections import defaultdict
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import NoReturn

from .form import Kind, SessionFailure, Source, State, TextBlock, unknown_record

_DATABASE = "mimocode.db"
_DATABASE_FILES = (_DATABASE, f"{_DATABASE}-wal", f"{_DATABASE}-shm")
_COPY_ATTEMPTS = 3


def _unreadable(record_type: str) -> SessionFailure:
    return SessionFailure("unreadable_session", f"{_DATABASE}: could not read the {record_type}.")


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _database_files(home_fd: int) -> dict[str, os.stat_result]:
    files = {}
    for name in _DATABASE_FILES:
        try:
            info = os.stat(name, dir_fd=home_fd, follow_symlinks=False)
        except FileNotFoundError:
            if name == _DATABASE:
                raise
            continue
        if not stat.S_ISREG(info.st_mode):
            raise _unreadable("database set")
        files[name] = info
    return files


def _copy_database(home: Path, destination: Path) -> datetime:
    home_fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        files = _database_files(home_fd)
        expected = {name: _signature(info) for name, info in files.items()}
        for name, signature in expected.items():
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=home_fd)
            with os.fdopen(fd, "rb") as original:
                if _signature(os.fstat(fd)) != signature:
                    raise _unreadable("database set")
                copy_fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(copy_fd, "wb") as copy:
                    shutil.copyfileobj(original, copy)
                    if copy.tell() != files[name].st_size:
                        raise _unreadable("database set")
                if _signature(os.fstat(fd)) != signature:
                    raise _unreadable("database set")
        current = {name: _signature(info) for name, info in _database_files(home_fd).items()}
        if current != expected or not os.path.samestat(os.fstat(home_fd), home.stat()):
            raise _unreadable("database set")
        return datetime.fromtimestamp(files[_DATABASE].st_mtime, UTC)
    finally:
        os.close(home_fd)


@contextmanager
def _snapshot(source: Source, home: Path) -> Iterator[tuple[sqlite3.Connection, datetime]]:
    if source.work is None:
        raise _unreadable("database set")
    work = source.work.resolve()
    if work.is_relative_to(home):
        raise _unreadable("database set")
    work.mkdir(parents=True, exist_ok=True)

    for _ in range(_COPY_ATTEMPTS):
        with TemporaryDirectory(prefix="mimo-", dir=work) as temporary:
            private = Path(temporary)
            try:
                mtime = _copy_database(home, private)
                connection = sqlite3.connect(f"{(private / _DATABASE).as_uri()}?mode=ro", uri=True)
            except (OSError, OverflowError, ValueError, sqlite3.Error, SessionFailure):
                continue
            with closing(connection):
                connection.row_factory = sqlite3.Row
                yield connection, mtime
                return
    raise _unreadable("database set")


def _session_ids(database: sqlite3.Connection, source: Source) -> Iterator[str]:
    for row in database.execute("SELECT id FROM session WHERE parent_id IS NULL ORDER BY time_created, id"):
        native_id = row["id"]
        if not isinstance(native_id, str) or not native_id:
            raise _unreadable("session")
        if source.wants(native_id):
            yield native_id


def _session_row(database: sqlite3.Connection, native_id: str) -> sqlite3.Row:
    row = database.execute(
        "SELECT * FROM session WHERE id = ? AND parent_id IS NULL", (native_id,)
    ).fetchone()
    if not isinstance(row, sqlite3.Row):
        raise _unreadable("session")
    return row


def _message_rows(database: sqlite3.Connection, native_id: str) -> Iterator[sqlite3.Row]:
    yield from database.execute(
        "SELECT * FROM message WHERE session_id = ? ORDER BY time_created, id", (native_id,)
    )


def _part_rows(database: sqlite3.Connection, native_id: str) -> Iterator[sqlite3.Row]:
    yield from database.execute(
        "SELECT * FROM part WHERE session_id = ? ORDER BY id", (native_id,)
    )


def _actor_names(database: sqlite3.Connection, native_id: str) -> Iterator[sqlite3.Row]:
    registry = database.execute(
        "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'actor_registry'"
    ).fetchone()
    if registry is not None:
        yield from database.execute(
            "SELECT actor_id, agent FROM actor_registry WHERE session_id = ? ORDER BY actor_id", (native_id,)
        )


type _Object = dict[str, object]

_PART_TYPES = frozenset({
    "text", "subtask", "reasoning", "file", "tool", "step-start", "step-finish",
    "snapshot", "patch", "agent", "retry", "checkpoint", "compaction",
})


@dataclass
class _KindFacts:
    title: str | None = None
    directory: str | None = None
    completed_history: bool = False
    probe_actor: bool = False


@dataclass(frozen=True)
class _SessionInfo:
    title: str
    directory: str
    version: str
    title_source: str
    slug: str
    created: datetime
    updated: datetime


@dataclass(frozen=True)
class _Part:
    id: str
    kind: str
    data: _Object
    created: datetime
    synthetic: bool
    started: datetime
    last_saved: datetime


@dataclass(frozen=True)
class _Message:
    id: str
    lane: str
    role: str
    parent: str | None
    created: datetime
    data: _Object
    parts: tuple[_Part, ...]
    completed: datetime | None
    finish: str | None
    error_kind: str | None
    error_text: str | None
    model: str | None
    summary: bool


def _unknown(record: str) -> NoReturn:
    unknown_record(record, _DATABASE, conversation=True)
    raise AssertionError("unknown_record must raise for a conversation record")


def _string(value: object, record: str) -> str:
    if not isinstance(value, str):
        _unknown(record)
    return value


def _optional_string(value: object, record: str) -> str | None:
    return None if value is None else _string(value, record)


def _id(value: object, record: str) -> str:
    text = _string(value, record)
    if not text:
        _unknown(record)
    return text


def _object(value: object, record: str) -> _Object:
    if not isinstance(value, dict):
        _unknown(record)
    # JSON object keys are strings.
    return value


def _optional_object(value: object, record: str) -> _Object:
    return {} if value is None else _object(value, record)


def _invalid_constant(_: str) -> NoReturn:
    raise ValueError("Non-JSON number")


def _data(row: sqlite3.Row, record: str) -> _Object:
    value = row["data"]
    if not isinstance(value, str):
        raise _unreadable(record)
    try:
        decoded = json.loads(value, parse_constant=_invalid_constant)
    except (ValueError, RecursionError):
        raise _unreadable(record) from None
    return _object(decoded, record)


def _time(value: object, record: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _unknown(record)
    try:
        return datetime.fromtimestamp(value / 1000, UTC)
    except (OSError, OverflowError, ValueError):
        _unknown(record)


def _optional_time(value: object, record: str) -> datetime | None:
    return None if value is None else _time(value, record)


def _session_info(row: sqlite3.Row, facts: _KindFacts) -> _SessionInfo:
    facts.title = _string(row["title"], "session")
    facts.directory = _string(row["directory"], "session")
    return _SessionInfo(
        facts.title, facts.directory, _string(row["version"], "session"), _string(row["title_source"], "session"),
        _string(row["slug"], "session"), _time(row["time_created"], "session"), _time(row["time_updated"], "session"),
    )


def _part(row: sqlite3.Row, facts: _KindFacts) -> _Part:
    data = _data(row, "part")
    kind = _string(data.get("type"), "part")
    if kind not in _PART_TYPES:
        _unknown("part")
    synthetic = data.get("synthetic", False)
    if not isinstance(synthetic, bool):
        _unknown("part")
    if kind == "text":
        _string(data.get("text"), "part")
    elif kind == "file":
        _string(data.get("mime"), "part")
        _string(data.get("url"), "part")
    created = _time(row["time_created"], "part")
    timing = _optional_object(data.get("time"), "part")
    started = _optional_time(timing.get("start"), "part") or created
    ended = _optional_time(timing.get("end"), "part") or started
    part = _Part(_id(row["id"], "part"), kind, data, created, synthetic, started, max(created, started, ended))
    metadata = _optional_object(data.get("metadata"), "part")
    state = _object(data.get("state"), "part") if kind == "tool" else {}
    state_metadata = _optional_object(state.get("metadata"), "part")
    if "arbolCompletedHistory" in metadata or "arbolCompletedHistory" in state_metadata:
        facts.completed_history = True
    return part


def _message(row: sqlite3.Row, parts: list[sqlite3.Row], facts: _KindFacts) -> _Message:
    data = _data(row, "message")
    role = _string(data.get("role"), "message")
    if role not in ("user", "assistant"):
        _unknown("message")
    parent = _id(data.get("parentID"), "message") if role == "assistant" else None
    lane = _id(row["agent_id"], "message")
    created = _time(row["time_created"], "message")
    message_id = _id(row["id"], "message")
    message_time = _optional_object(data.get("time"), "message")
    _optional_time(message_time.get("created"), "message")
    completed = _optional_time(message_time.get("completed"), "message")
    finish = _optional_string(data.get("finish"), "message")
    error_kind, error_text = _message_error(data.get("error"))
    model = _assistant_model(data) if role == "assistant" else None
    summary = data.get("summary", False) if role == "assistant" else False
    if not isinstance(summary, bool):
        _unknown("message")
    name = data.get("agent")
    if lane != "main" and isinstance(name, str) and name.startswith("probe-"):
        facts.probe_actor = True
    return _Message(
        message_id, lane, role, parent, created, data, tuple(_part(part, facts) for part in parts),
        completed, finish, error_kind, error_text, model, summary,
    )


def _read_messages(
    database: sqlite3.Connection, native_id: str, part_rows: list[sqlite3.Row], facts: _KindFacts,
) -> tuple[list[_Message], list[sqlite3.Row]]:
    parts: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in part_rows:
        parts[_id(row["message_id"], "part")].append(row)
    messages = []
    message_rows = []
    for row in _message_rows(database, native_id):
        messages.append(_message(row, parts.get(_id(row["id"], "message"), []), facts))
        message_rows.append(row)
    return messages, message_rows


_DRIVER_TITLES = re.compile(r"Arbol run [0-9A-Fa-f]{32}|Arbol completed history|arbol-source-[0-9A-Fa-f]+:.*", re.S)
_DRIVER_ID = re.compile(r"ses_[0-9a-f]{26}")


def _kind(native_id: str, facts: _KindFacts) -> Kind:
    if (
        _DRIVER_ID.fullmatch(native_id)
        or facts.completed_history
        or facts.title == f"Cancelled {native_id}"
        or (facts.title is not None and _DRIVER_TITLES.fullmatch(facts.title))
    ):
        return "arbol_driver"
    if facts.probe_actor or (facts.directory is not None and _claude_scratchpad(facts.directory)):
        return "probe"
    return "owner"


def _claude_scratchpad(directory: str) -> bool:
    parts = Path(directory).parts
    for index, component in enumerate(parts):
        if (component == ".claude" or re.fullmatch(r"claude-\d+", component)) and "scratchpad" in parts[index + 1:]:
            return True
    return False


def _read_actor_facts(database: sqlite3.Connection, native_id: str, facts: _KindFacts) -> None:
    if _kind(native_id, facts) != "owner":
        return
    for row in _actor_names(database, native_id):
        lane = _id(row["actor_id"], "actor registry")
        name = _string(row["agent"], "actor registry")
        if lane != "main" and name.startswith("probe-"):
            facts.probe_actor = True
            return


_USER_INPUT = frozenset({"text", "file", "agent", "subtask"})


@dataclass
class _Turn:
    user: _Message
    assistants: list[_Message] = field(default_factory=list)


def _synthetic_user(message: _Message) -> bool:
    synthetic = any(part.synthetic or part.kind == "compaction" for part in message.parts)
    real_input = any(part.kind in _USER_INPUT and not part.synthetic for part in message.parts)
    return synthetic and not real_input


def _prompt(user: _Message) -> str:
    return "\n".join(
        _string(part.data.get("text"), "part")
        for part in user.parts
        if part.kind == "text" and not part.synthetic
    )


def _main_turns(messages: list[_Message]) -> tuple[list[_Turn], dict[str, _Turn]]:
    turns = []
    owner_by_message: dict[str, _Turn] = {}
    current = None
    for message in messages:
        if message.lane != "main" or message.role != "user":
            continue
        if not _synthetic_user(message):
            current = _Turn(message)
            turns.append(current)
        if current is not None:
            owner_by_message[message.id] = current

    owner_by_assistant = {}
    for message in messages:
        if message.lane != "main" or message.parent is None:
            continue
        owner = owner_by_message.get(message.parent)
        if owner is not None:
            owner.assistants.append(message)
            owner_by_assistant[message.id] = owner
    return turns, owner_by_assistant


def _message_error(value: object) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    error = _object(value, "message")
    details = _optional_object(error.get("data"), "message")
    return _id(error.get("name"), "message"), _optional_string(details.get("message"), "message")


def _assistant_model(data: _Object) -> str | None:
    provider = _optional_string(data.get("providerID"), "message")
    model = _optional_string(data.get("modelID"), "message")
    return f"{provider}/{model}" if provider and model else None


def _turn_end(turn: _Turn) -> datetime:
    if turn.assistants and (completed := turn.assistants[-1].completed) is not None:
        return completed
    messages = [turn.user, *turn.assistants]
    return max(
        max(message.created, *(part.last_saved for part in message.parts))
        if message.parts else message.created
        for message in messages
    )


def _state(assistant: _Message | None) -> tuple[State, str | None, str | None]:
    if assistant is not None:
        if assistant.error_kind is not None:
            return "failed", assistant.error_text, assistant.error_kind
        if assistant.finish == "stop":
            return "completed", None, None
    return "interrupted", None, None


def _text_block(message: _Message, part: _Part) -> TextBlock | None:
    if part.kind == "text" and not part.synthetic and not message.summary:
        return TextBlock(_string(part.data.get("text"), "part"), part.started)
    return None
