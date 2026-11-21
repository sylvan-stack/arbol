"""Read saved Mimo sessions from a private copy of their SQLite database (IMP-1)."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import sqlite3
import stat
from collections import defaultdict
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import NoReturn
from urllib.parse import unquote, urlsplit

from .form import (
    LIVE_WINDOW,
    ArchiveFile,
    CallLink,
    ExportedRows,
    Failed,
    FileObservation,
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
    Subagent,
    TextBlock,
    ToolCall,
    Turn,
    Usage,
    unknown_record,
)

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


def _work_directory(path: Path, home: Path) -> Path:
    work = path.resolve()
    home_info = home.stat()
    missing = []
    for directory in (work, *work.parents):
        try:
            info = directory.stat()
        except FileNotFoundError:
            missing.append(directory)
            continue
        # Identity catches case-equivalent paths on case-insensitive volumes.
        if not stat.S_ISDIR(info.st_mode) or os.path.samestat(home_info, info):
            raise _unreadable("database set")
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=True)
    return work


@contextmanager
def _snapshot(source: Source, home: Path) -> Iterator[tuple[sqlite3.Connection, datetime]]:
    if source.work is None:
        raise _unreadable("database set")
    work = _work_directory(source.work, home)

    for _ in range(_COPY_ATTEMPTS):
        with TemporaryDirectory(prefix="mimo-", dir=work) as temporary:
            private = Path(temporary)
            try:
                mtime = _copy_database(home, private)
                connection = sqlite3.connect(f"{(private / _DATABASE).as_uri()}?mode=ro", uri=True)
            except (OSError, OverflowError, ValueError, sqlite3.Error, SessionFailure):
                continue
            with closing(connection):
                connection.execute("PRAGMA trusted_schema=OFF")
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
    tool: ToolCall | None
    launched_actor: str | None


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
    usage: Usage


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
    state = _object(data.get("state"), "part") if kind == "tool" else {}
    record = state if kind == "tool" else data
    timing = _optional_object(record.get("time"), "part")
    started = _optional_time(timing.get("start"), "part") or created
    ended = _optional_time(timing.get("updated" if kind == "retry" else "end"), "part") or started
    metadata = _optional_object(data.get("metadata"), "part")
    state_metadata = _optional_object(state.get("metadata"), "part")
    call = _tool_call(data, state, state_metadata, started) if kind == "tool" else None
    launched_actor = None
    if (
        call is not None and call.name == "actor"
        and call.input.get("action") in (None, "run", "spawn")
        and state_metadata.get("sessionId") in (None, row["session_id"])
    ):
        launched_actor = _optional_string(state_metadata.get("actorId"), "part")
    part = _Part(
        _id(row["id"], "part"), kind, data, created, synthetic, started,
        max(created, started, ended), call, launched_actor,
    )
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
    usage = _usage(data.get("tokens")) if role == "assistant" else Usage()
    name = data.get("agent")
    if lane != "main" and isinstance(name, str) and name.startswith("probe-"):
        facts.probe_actor = True
    return _Message(
        message_id, lane, role, parent, created, data, tuple(_part(part, facts) for part in parts),
        completed, finish, error_kind, error_text, model, summary, usage,
    )


def _read_messages(
    database: sqlite3.Connection, native_id: str, part_rows: list[sqlite3.Row], facts: _KindFacts,
) -> tuple[list[_Message], list[sqlite3.Row]]:
    parts: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in part_rows:
        owner = row["message_id"]
        if isinstance(owner, str):
            parts[owner].append(row)
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
    last_saved = max(max(message.created, message.completed or message.created) for message in messages)
    return max(last_saved, max((part.last_saved for message in messages for part in message.parts), default=last_saved))


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


def _attachments(value: object) -> Iterator[_Object]:
    if value is None:
        return
    if not isinstance(value, list):
        _unknown("part")
    for raw in value:
        attachment = _object(raw, "part")
        _string(attachment.get("mime"), "part")
        _string(attachment.get("url"), "part")
        yield attachment


def _inline_image(attachment: _Object) -> Image | None:
    media_type = _string(attachment.get("mime"), "part")
    url = _string(attachment.get("url"), "part")
    if not media_type.lower().startswith("image/") or url[:5].lower() != "data:":
        return None
    header, comma, payload = url.partition(",")
    if not comma or header[5:].lower() != f"{media_type};base64".lower():
        return None
    try:
        return Image(media_type, len(base64.b64decode(payload, validate=True)))
    except (binascii.Error, ValueError):
        _unknown("part")


def _tool_call(data: _Object, state: _Object, metadata: _Object, started: datetime) -> ToolCall:
    call_id = _id(data.get("callID"), "part")
    name = _id(data.get("tool"), "part")
    arguments = _object(state.get("input"), "part")
    status = state.get("status")
    if status not in ("pending", "running", "completed", "error"):
        _unknown("part")

    result = None
    error = None
    if status in ("completed", "error"):
        if status == "completed":
            output = _string(state.get("output"), "part")
        else:
            error = _string(state.get("error"), "part")
            partial = metadata.get("output")
            output = partial if isinstance(partial, str) else error
        images = tuple(
            image for attachment in _attachments(state.get("attachments"))
            if (image := _inline_image(attachment)) is not None
        )
        fields = {key: value for key, value in metadata.items() if key not in {"attachments", "images", "output"}}
        if name == "bash" and type(fields.get("exit")) is int:
            fields["exitCode"] = fields.pop("exit")
        result = Result(output, fields or None, images)
    return ToolCall(call_id, None, name, arguments, result, status == "completed", error, None, started)


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        _unknown("message")
    return value


def _usage(value: object) -> Usage:
    tokens = _optional_object(value, "message")
    cache = _optional_object(tokens.get("cache"), "message")
    reasoning = tokens.get("reasoning")
    return Usage.native(
        uncached=_count(tokens.get("input", 0)),
        cache_read=_count(cache.get("read", 0)),
        cache_write=_count(cache["write"]) if "write" in cache else None,
        output=_count(tokens.get("output", 0)),
        reasoning=None if reasoning is None else _count(reasoning),
    )


def _responses(turn: _Turn) -> tuple[Response, ...]:
    return tuple(Response(message.created, message.usage) for message in turn.assistants)


@dataclass(frozen=True)
class _Launch:
    message: _Message
    call_id: str

    def link(self) -> CallLink:
        return CallLink(None if self.message.lane == "main" else self.message.lane, self.call_id)


@dataclass(frozen=True)
class _Actor:
    lane: str
    messages: list[_Message]
    launch: _Launch | None


def _message_order(message: _Message) -> tuple[datetime, str]:
    return message.created, message.id


def _actor_owners(
    messages: list[_Message], turns: list[_Turn], by_assistant: dict[str, _Turn],
) -> dict[str, list[_Actor]]:
    lanes: dict[str, list[_Message]] = defaultdict(list)
    launches: dict[str, _Launch] = {}
    for message in messages:
        if message.lane != "main":
            lanes[message.lane].append(message)
        if message.role == "assistant":
            for part in message.parts:
                if part.launched_actor and part.tool is not None:
                    launches.setdefault(part.launched_actor, _Launch(message, part.tool.call_id))

    windows = [(turn, _turn_end(turn)) for turn in reversed(turns)]
    owners: dict[str, _Turn | None] = {}
    assigned: dict[str, list[_Actor]] = defaultdict(list)
    for lane, records in lanes.items():
        current = lane
        visited: set[str] = set()
        # Resolve nested launches through their caller lane. A link to an archived
        # launch (or a cycle in saved links) cannot give the actor a projected turn.
        while current not in visited and current not in owners:
            visited.add(current)
            launch = launches.get(current)
            if launch is None:
                first = lanes[current][0]
                owners[current] = next(
                    (
                        turn for turn, end in windows
                        if _message_order(turn.user) <= _message_order(first) and first.created <= end
                    ),
                    None,
                )
                break
            if launch.message.lane == "main":
                owners[current] = by_assistant.get(launch.message.id)
                break
            current = launch.message.lane
        owner = owners.get(current)
        for resolved in visited:
            owners[resolved] = owner
        if owner is not None:
            assigned[owner.user.id].append(_Actor(lane, records, launches.get(lane)))
    return assigned


def _items(turn: _Turn, actors: list[_Actor]) -> Iterator[Item]:
    work: list[tuple[_Message, _Launch | None]] = [(message, None) for message in turn.assistants]
    for actor in actors:
        work.extend((message, actor.launch) for message in actor.messages if message.role == "assistant")

    for message, launch in sorted(work, key=lambda record: _message_order(record[0])):
        for part in message.parts:
            if part.tool is not None:
                if message.lane == "main":
                    yield part.tool
                else:
                    yield replace(
                        part.tool, agent=message.lane, parent_call_id=launch.call_id if launch else None,
                        parent=launch.link() if launch else None,
                    )
            elif message.lane == "main" and (text := _text_block(message, part)) is not None:
                yield text


def _subagent(actor: _Actor) -> Subagent:
    usage = Usage()
    last_user = None
    for message in actor.messages:
        if message.role == "user":
            last_user = message.id
        else:
            usage += message.usage
    last_assistant = next(
        (message for message in reversed(actor.messages) if message.parent is not None and message.parent == last_user),
        None,
    )
    state, _, _ = _state(last_assistant)
    return Subagent(
        actor.lane, actor.launch.call_id if actor.launch else None, actor.messages[0].created, state == "failed",
        usage, actor.launch.link() if actor.launch else None,
    )


def _diff_paths(diffs: object) -> Iterator[str]:
    if isinstance(diffs, list):
        for diff in diffs:
            if isinstance(diff, dict) and isinstance(name := diff.get("file"), str):
                yield name


def _file_urls(file: _Object) -> Iterator[str]:
    if isinstance(url := file.get("url"), str) and url[:5].lower() == "file:":
        yield url
    source = file.get("source")
    if isinstance(source, dict):
        if source.get("type") in ("file", "symbol") and isinstance(name := source.get("path"), str):
            yield name
        if isinstance(uri := source.get("uri"), str) and uri[:5].lower() == "file:":
            yield uri


def _part_files(part: _Part) -> Iterator[str]:
    if part.kind == "file":
        if part.data.get("mime") != "application/x-directory":
            yield from _file_urls(part.data)
    elif part.kind == "patch":
        files = part.data.get("files")
        if isinstance(files, list):
            yield from (path for path in files if isinstance(path, str))
    elif part.kind == "tool":
        state = _object(part.data.get("state"), "part")
        metadata = _optional_object(state.get("metadata"), "part")
        if isinstance(path := metadata.get("outputPath"), str):
            yield path
        if part.tool is not None and part.tool.result is not None:
            for attachment in _attachments(state.get("attachments")):
                if attachment.get("mime") != "application/x-directory":
                    yield from _file_urls(attachment)


def _outside_reference(home: Path, directory: Path, name: str) -> str | None:
    if not name or "\x00" in name:
        return None
    if name[:5].lower() == "file:":
        try:
            url = urlsplit(name)
        except ValueError:
            return None
        if url.netloc.lower() not in ("", "localhost"):
            return url._replace(query="", fragment="").geturl()
        name = unquote(url.path)
        if not name or "\x00" in name:
            return None
    path = directory / name
    if not path.is_absolute():
        return None
    try:
        reference = path.resolve()
    except (OSError, RuntimeError, ValueError):
        reference = Path(os.path.abspath(path))
    return str(reference) if not reference.is_relative_to(home) else None


def _outside_files(
    home: Path, directory: Path, session: sqlite3.Row, messages: list[_Message],
) -> set[str]:
    outside: set[str] = set()
    for message in messages:
        summary = message.data.get("summary")
        if isinstance(summary, dict):
            outside.update(
                path for name in _diff_paths(summary.get("diffs"))
                if (path := _outside_reference(home, directory, name)) is not None
            )
        for part in message.parts:
            outside.update(
                path for name in _part_files(part) if (path := _outside_reference(home, directory, name)) is not None
            )
    if "summary_diffs" in session.keys() and isinstance(raw_diffs := session["summary_diffs"], str):
        try:
            diffs = json.loads(raw_diffs)
        except (ValueError, RecursionError):
            return outside
        outside.update(
            path for name in _diff_paths(diffs) if (path := _outside_reference(home, directory, name)) is not None
        )
    return outside


def _archive(
    home: Path, native_id: str, mtime: datetime, directory: str, session: sqlite3.Row,
    messages: list[_Message], message_rows: list[sqlite3.Row], part_rows: list[sqlite3.Row],
) -> tuple[tuple[ArchiveFile, ...], int]:
    if native_id in (".", "..") or any(char in native_id for char in ("/", "\\", "\x00")):
        _unknown("session")

    data = {
        "session": dict(session),
        "message": [dict(row) for row in message_rows],
        "part": [dict(row) for row in part_rows],
    }
    content = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    exported = ExportedRows(f"{_DATABASE}#{native_id}.json", content, mtime)

    outside = _outside_files(home, Path(directory), session, messages)
    relative = Path("storage", "session_diff", f"{native_id}.json")
    candidate = home / relative
    try:
        info = candidate.lstat()
    except FileNotFoundError:
        return (exported,), len(outside)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(home):
        outside.add(str(resolved))
    # The listed diff must not alias an in-home credential or another session's file.
    if resolved == candidate and stat.S_ISREG(info.st_mode):
        observed = FileObservation.from_stat(info)
        if FileObservation.from_stat(candidate.lstat()) != observed:
            raise OSError("A native session diff changed during archive nomination.")
        return (exported, HomeFile(relative.as_posix(), observation=observed)), len(outside)
    return (exported,), len(outside)


def _turns(messages: list[_Message], directory: str) -> Iterator[Turn]:
    turns, by_assistant = _main_turns(messages)
    actors_by_turn = _actor_owners(messages, turns, by_assistant)
    for turn in turns:
        last = turn.assistants[-1] if turn.assistants else None
        state, error, error_kind = _state(last)
        actors = actors_by_turn.get(turn.user.id, [])
        yield Turn(
            turn_key=turn.user.id, trigger="typed", prompt=_prompt(turn.user), started_at=turn.user.created,
            ended_at=_turn_end(turn), state=state, error=error, error_kind=error_kind, working_folder=directory,
            model=turn.assistants[0].model if turn.assistants else None, effort=None,
            usage=_responses(turn), items=tuple(_items(turn, actors)),
            subagents=tuple(_subagent(actor) for actor in actors),
        )


def _read_session(
    database: sqlite3.Connection, home: Path, source: Source, native_id: str, mtime: datetime,
) -> Session | Failed:
    facts = _KindFacts()
    record = "session"
    try:
        row = _session_row(database, native_id)
        info = _session_info(row, facts)
        record = "actor registry"
        _read_actor_facts(database, native_id, facts)
        record = "part"
        part_rows = list(_part_rows(database, native_id))
        record = "message"
        messages, message_rows = _read_messages(database, native_id, part_rows, facts)
        record = "session archive"
        archive, outside = _archive(home, native_id, mtime, info.directory, row, messages, message_rows, part_rows)
        return Session(
            tool="mimo", native_id=native_id, kind=_kind(native_id, facts), title=info.title,
            created_at=info.created, tool_version=info.version, working_folder=info.directory,
            origin={"directory": info.directory, "title_source": info.title_source, "slug": info.slug},
            live=info.updated >= source.clock - LIVE_WINDOW,
            turns=tuple(_turns(messages, info.directory)), archive_files=archive, files_not_archived=outside,
        )
    except SessionFailure as failure:
        return Failed.of(failure, native_id=native_id, kind=_kind(native_id, facts))
    except (sqlite3.Error, OSError, IndexError, RuntimeError, TypeError, ValueError, OverflowError):
        return Failed.of(_unreadable(record), native_id=native_id, kind=_kind(native_id, facts))


def read(source: Source) -> Iterator[Session | Failed]:
    """Yield selected top-level sessions while the private database set is open."""
    try:
        home = source.home.resolve(strict=True)
        with _snapshot(source, home) as (database, mtime):
            for native_id in _session_ids(database, source):
                yield _read_session(database, home, source, native_id, mtime)
    except SessionFailure as failure:
        yield Failed.of(failure, file=_DATABASE)
    except (sqlite3.Error, OSError, RuntimeError, ValueError):
        yield Failed.of(_unreadable("database set"), file=_DATABASE)
