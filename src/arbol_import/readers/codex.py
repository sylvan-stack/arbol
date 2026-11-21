"""Read Codex session rollouts for the Arbol importer (IMP-1)."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import stat
from base64 import b64decode
from collections import defaultdict
from collections.abc import Generator, Iterator
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from heapq import heappop, heappush
from pathlib import Path
from struct import Struct, unpack
from tempfile import TemporaryDirectory
from typing import Any, BinaryIO
from urllib.parse import unquote_to_bytes

from .form import (
    LIVE_WINDOW,
    ArchiveFile,
    CallLink,
    ExportedRows,
    Failed,
    FileObservations,
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
from .lines import file_records, lines

type Object = dict[str, Any]

_ROLLOUT = re.compile(r"(?:sessions/[0-9]{4}/[0-9]{2}/[0-9]{2}|archived_sessions)/rollout-[^/]+\.jsonl(?:\.zst)?")
_NATIVE_ID = re.compile(r"[A-Za-z0-9_-]+")
_ORIGIN_FIELDS = ("originator", "source", "thread_source", "cwd")


def _id(value: object) -> str | None:
    return value if isinstance(value, str) and _NATIVE_ID.fullmatch(value) else None


def _time(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            at = datetime.fromisoformat(value)
            if at.utcoffset() is not None:
                return at.astimezone(UTC)
        except (ValueError, OverflowError):
            pass
    return None


def _inside(root: Path, path: Path) -> Path | None:
    try:
        target = path.resolve(strict=True)
        if target.is_relative_to(root):
            return target
    except (OSError, RuntimeError, ValueError):
        pass
    return None


@dataclass
class Rollout:
    relative: str
    mtime_ns: int = 0
    native_id: str | None = None
    parent: str | None = None
    created_at: datetime | None = None
    version: str | None = None
    role: str | None = None
    agent_path: str | None = None
    history_start: int | None = None
    origin: Object = field(default_factory=dict)
    failure: SessionFailure | None = None
    outside: bool = False
    read_path: str | None = None
    observations: FileObservations = field(default_factory=FileObservations)


def _rollout_target(home: Path, relative: str) -> Path:
    try:
        target = (home / relative).resolve(strict=True)
        if (
            target.is_relative_to(home)
            and _ROLLOUT.fullmatch(target.relative_to(home).as_posix())
            and target.name.endswith(".zst") == relative.endswith(".zst")
            and stat.S_ISREG(target.stat().st_mode)
        ):
            return target
    except (OSError, RuntimeError, ValueError):
        pass
    raise SessionFailure("unreadable_session", f"{relative}: the rollout could not be read.")


def _observed_target(home: Path, rollout: Rollout) -> Path:
    target = _rollout_target(home, rollout.relative)
    actual_path = target.relative_to(home).as_posix()
    if rollout.read_path is not None and actual_path != rollout.read_path:
        raise SessionFailure("unreadable_session", f"{rollout.relative}: the rollout target changed.")
    return target


def _records(home: Path, rollout: Rollout) -> Generator[tuple[int, Any]]:
    target = _observed_target(home, rollout)
    try:
        yield from file_records(home, target.relative_to(home).as_posix(), rollout.observations)
    except RecursionError:
        raise SessionFailure("unreadable_session", f"{rollout.relative}: a line could not be decoded.") from None


def _header(rollout: Rollout, row: object, line: int) -> None:
    where = f"{rollout.relative}:{line}"
    if not isinstance(row, dict) or row.get("type") != "session_meta" or not isinstance(row.get("payload"), dict):
        unknown_record("session_meta", where, conversation=True)
        return
    meta: Object = row["payload"]
    rollout.native_id = _id(meta.get("id"))
    rollout.created_at = _time(meta.get("timestamp"))
    source = meta.get("source")
    for name in _ORIGIN_FIELDS:
        value = meta.get(name)
        if isinstance(value, str) or (name == "source" and isinstance(value, dict)):
            rollout.origin[name] = value
    version = meta.get("cli_version")
    rollout.version = version if isinstance(version, str) else None
    agent = source.get("subagent") if isinstance(source, dict) else None
    spawn = agent.get("thread_spawn") if isinstance(agent, dict) else None
    if not isinstance(spawn, dict):
        spawn = {}
    role = meta.get("agent_role", meta.get("agent_type", spawn.get("agent_role", spawn.get("agent_type"))))
    rollout.role = role if isinstance(role, str) else None
    agent_path = meta.get("agent_path", spawn.get("agent_path"))
    rollout.agent_path = agent_path if isinstance(agent_path, str) else None
    parents = [meta.get("parent_thread_id"), spawn.get("parent_thread_id")]
    if meta.get("attached_thread") is True:
        parents.append(meta.get("forked_from_id"))
    parent_ids = {native_id for value in parents if (native_id := _id(value)) is not None}
    rollout.parent = next(iter(parent_ids)) if len(parent_ids) == 1 else None
    cutoff = meta.get("subagent_history_start_ordinal")
    if type(cutoff) is int and cutoff >= 0:
        rollout.history_start = cutoff
    if (
        rollout.native_id is None
        or rollout.created_at is None
        or len(parent_ids) > 1
        or rollout.native_id in parent_ids
        or any(value is not None and _id(value) is None for value in parents)
        or (isinstance(agent, dict) and "thread_spawn" in agent and _id(spawn.get("parent_thread_id")) is None)
        or (source is not None and not isinstance(source, (str, dict)))
        or (cutoff is not None and rollout.history_start is None)
        or any(meta.get(name) is not None and not isinstance(meta[name], str)
               for name in ("originator", "thread_source", "cwd", "cli_version"))
        or (role is not None and rollout.role is None)
        or (agent_path is not None and rollout.agent_path is None)
    ):
        unknown_record("session_meta", where, conversation=True)


def _rollout_paths(home: Path) -> Iterator[Path]:
    yield from sorted(_directory_entries(home, home / "archived_sessions"))
    directories = [home / "sessions"]
    for length in (4, 2, 2):
        directories = [
            child for directory in directories for child in _directory_entries(home, directory)
            if len(child.name) == length and child.name.isascii() and child.name.isdecimal()
        ]
    for directory in sorted(directories):
        yield from sorted(_directory_entries(home, directory))


def _discover(home: Path) -> Iterator[Rollout]:
    for path in _rollout_paths(home):
        relative = path.relative_to(home).as_posix()
        if not _ROLLOUT.fullmatch(relative):
            continue
        rollout = Rollout(relative)
        try:
            target = path.resolve(strict=True)
            if not target.is_relative_to(home):
                rollout.outside = True
                yield rollout
                continue
            if not stat.S_ISREG(target.stat().st_mode):
                continue
            target = _rollout_target(home, relative)
            observation = rollout.observations.record(target, target.stat(follow_symlinks=False))
            rollout.mtime_ns = observation.mtime_ns
            rollout.read_path = target.relative_to(home).as_posix()
            with closing(_records(home, rollout)) as records:
                first = next(records, None)
            if first is None:
                continue
            _header(rollout, first[1], first[0])
        except SessionFailure as failure:
            rollout.failure = failure
        except (OSError, RuntimeError, ValueError):
            rollout.failure = SessionFailure("unreadable_session", f"{relative}: the rollout could not be read.")
        yield rollout


_DB = "state_5.sqlite"
_WAL = _DB + "-wal"
_COPY_ATTEMPTS = 3
_COPY_CHUNK = 1 << 20


@dataclass
class Catalogue:
    threads: dict[str, Object] = field(default_factory=dict)
    edges: list[Object] = field(default_factory=list)
    mtime: datetime | None = None


def _stamp(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _catalogue_file(home: Path, name: str) -> tuple[Path, os.stat_result] | None:
    path = home / name
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    target = _inside(home, path)
    if target is None:
        raise OSError("Catalogue file is unavailable")
    info = target.stat()
    if not stat.S_ISREG(info.st_mode):
        raise OSError("Catalogue file is not regular")
    return target, info


def _catalogue_pair(home: Path) -> dict[str, tuple[Path, os.stat_result]]:
    files = {}
    for name in (_DB, _WAL):
        entry = _catalogue_file(home, name)
        if entry is not None:
            files[name] = entry
    if _DB not in files:
        raise OSError("Catalogue is unavailable")
    return files


def _pair_stamp(files: dict[str, tuple[Path, os.stat_result]]) -> dict[str, tuple[Path, tuple[int, ...]]]:
    return {name: (path, _stamp(info)) for name, (path, info) in files.items()}


def _open_catalogue(path: Path, expected: os.stat_result) -> BinaryIO:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if _stamp(os.fstat(descriptor)) != _stamp(expected):
            raise OSError("Catalogue changed during snapshot")
        stream = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    return stream


def _copy_catalogue(home: Path, private: Path) -> datetime:
    before = _catalogue_pair(home)
    expected = _pair_stamp(before)
    for name, (path, info) in before.items():
        with _open_catalogue(path, info) as original, (private / name).open("xb") as copy:
            shutil.copyfileobj(original, copy, _COPY_CHUNK)
            if _stamp(os.fstat(original.fileno())) != _stamp(info):
                raise OSError("Catalogue changed during snapshot")
    if _pair_stamp(_catalogue_pair(home)) != expected:
        raise OSError("Catalogue changed during snapshot")
    for name, (path, info) in before.items():
        with _open_catalogue(path, info) as original, (private / name).open("rb") as copy:
            while True:
                chunk = copy.read(_COPY_CHUNK)
                if original.read(_COPY_CHUNK) != chunk:
                    raise OSError("Catalogue bytes changed during snapshot")
                if not chunk:
                    break
            if _stamp(os.fstat(original.fileno())) != _stamp(info):
                raise OSError("Catalogue changed during snapshot")
    if _pair_stamp(_catalogue_pair(home)) != expected:
        raise OSError("Catalogue changed during snapshot")
    return datetime.fromtimestamp(before[_DB][1].st_mtime, UTC)


def _wal_checksum(data: bytes, words: Struct, checksum: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    first, second = checksum
    for left, right in words.iter_unpack(data):
        first = (first + left + second) & 0xffffffff
        second = (second + right + first) & 0xffffffff
    return first, second


def _verify_catalogue(private: Path) -> None:
    # SQLite recovery stops at an invalid WAL frame. Verify the active frames
    # ourselves so a corrupt committed overlay cannot silently look like an old DB.
    with (private / _DB).open("rb") as database:
        header = database.read(100)
    if len(header) != 100 or header[:16] != b"SQLite format 3\x00":
        raise ValueError("Invalid catalogue header")
    wal = private / _WAL
    if not wal.exists() or not wal.stat().st_size:
        return
    with wal.open("rb") as stream:
        wal_header = stream.read(32)
        magic = int.from_bytes(wal_header[:4], "big")
        version = int.from_bytes(wal_header[4:8], "big")
        page_size = int.from_bytes(wal_header[8:12], "big")
        db_page_size = int.from_bytes(header[16:18], "big")
        if db_page_size == 1:
            db_page_size = 65536
        if (
            len(wal_header) != 32
            or magic not in (0x377f0682, 0x377f0683)
            or version != 3007000
            or page_size != db_page_size
            or page_size < 512 or page_size > 65536 or page_size & (page_size - 1)
            or header[18:20] != b"\x02\x02"
        ):
            raise ValueError("Invalid catalogue WAL header")
        words = Struct("<II" if magic == 0x377f0682 else ">II")
        checksum = _wal_checksum(wal_header[:24], words)
        if checksum != unpack(">II", wal_header[24:32]):
            raise ValueError("Invalid catalogue WAL checksum")
        while frame := stream.read(24):
            if len(frame) != 24:
                raise ValueError("Incomplete catalogue WAL frame")
            # A WAL reset can leave intact frames from the previous generation.
            if frame[8:12] != wal_header[16:20]:
                break
            page = stream.read(page_size)
            if len(page) != page_size or frame[:4] == b"\0" * 4 or frame[12:16] != wal_header[20:24]:
                raise ValueError("Invalid catalogue WAL frame")
            checksum = _wal_checksum(page, words, _wal_checksum(frame[:8], words, checksum))
            if checksum != unpack(">II", frame[16:24]):
                raise ValueError("Invalid catalogue WAL frame checksum")


def _catalogue_rows(connection: sqlite3.Connection, table: str) -> Iterator[Object]:
    try:
        cursor = connection.execute(f"SELECT * FROM {table}")
        with closing(cursor):
            columns = [column[0] for column in cursor.description]
            for cells in cursor:
                try:
                    yield dict(zip(columns, (cell.decode("utf-8") if isinstance(cell, bytes) else cell
                                             for cell in cells), strict=True))
                except UnicodeError:
                    continue
    except sqlite3.Error:
        return


def _read_catalogue(home: Path, work: Path | None) -> Catalogue:
    if work is None:
        return Catalogue()
    try:
        work = work.resolve(strict=True)
        if work.is_relative_to(home) or not work.is_dir():
            return Catalogue()
    except (OSError, RuntimeError, ValueError):
        return Catalogue()
    for _ in range(_COPY_ATTEMPTS):
        try:
            with TemporaryDirectory(prefix="codex-catalogue-", dir=work) as directory:
                private = Path(directory)
                mtime = _copy_catalogue(home, private)
                _verify_catalogue(private)
                uri = (private / _DB).as_uri() + "?mode=ro"
                with closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
                    connection.text_factory = bytes
                    connection.execute("PRAGMA trusted_schema=OFF")
                    connection.execute("BEGIN")
                    connection.execute("SELECT name FROM sqlite_schema LIMIT 1").fetchone()
                    threads = {key: row for row in _catalogue_rows(connection, "threads")
                               if (key := _id(row.get("id"))) is not None}
                    edges = [row for row in _catalogue_rows(connection, "thread_spawn_edges")
                             if _id(row.get("parent_thread_id")) and _id(row.get("child_thread_id"))]
                return Catalogue(threads, edges, mtime)
        except (OSError, RuntimeError, ValueError, sqlite3.Error):
            continue
    return Catalogue()


def _titles(home: Path) -> dict[str, str]:
    titles: dict[str, str] = {}
    path = _inside(home, home / "session_index.jsonl")
    if path is None:
        return titles
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return titles
        with path.open("rb") as stream:
            for _, raw in lines(stream):
                try:
                    row = json.loads(raw)
                except (ValueError, RecursionError):
                    continue
                if isinstance(row, dict) and (native_id := _id(row.get("id"))) is not None:
                    if isinstance(row.get("thread_name"), str):
                        titles[native_id] = row["thread_name"]
    except OSError:
        pass
    return titles


def _directory_entries(root: Path, path: Path) -> Iterator[Path]:
    directory = _inside(root, path)
    if directory is not None:
        try:
            for child in directory.iterdir():
                yield path / child.name
        except OSError:
            return


def _driver_ids(state: Path | None) -> set[str]:
    found: set[str] = set()
    if state is None:
        return found
    try:
        state = state.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return found
    for subscription in _directory_entries(state, state / "subscriptions"):
        for entry in _directory_entries(state, subscription / "chats"):
            path = _inside(state, entry)
            if path is None or entry.suffix != ".json":
                continue
            try:
                if not stat.S_ISREG(path.stat().st_mode):
                    continue
                data = json.loads(path.read_bytes())
            except (OSError, ValueError, RecursionError):
                continue
            if isinstance(data, dict) and (native_id := _id(data.get("conversation"))) is not None:
                found.add(native_id)
    return found


@dataclass
class Thread:
    native_id: str
    chosen: Rollout
    copies: list[Rollout]
    parent: str | None
    broken: list[Rollout] = field(default_factory=list)


@dataclass
class Inventory:
    roots: list[Thread]
    children: dict[str, list[Thread]]
    unidentified: list[Rollout]
    outside: dict[str, set[str]]

    def family(self, root: Thread) -> Iterator[Thread]:
        pending = [root]
        seen: set[str] = set()
        while pending:
            thread = pending.pop()
            if thread.native_id in seen:
                continue
            seen.add(thread.native_id)
            yield thread
            pending.extend(reversed(self.children.get(thread.native_id, ())))


def _catalogue_path(home: Path, row: Object) -> Path | None:
    name = row.get("rollout_path")
    if not isinstance(name, str) or not name or "\0" in name:
        return None
    try:
        # Keep the lexical path for exact matching and separately check where
        # it resolves. A catalogue entry must never initiate a rollout read.
        return Path(os.path.abspath(home / name))
    except (OSError, ValueError):
        return None


def _copy_preference(home: Path, path: Path | None, rollout: Rollout) -> tuple[int, int, str]:
    found = str(home / rollout.relative)
    rank = 2
    if path is not None:
        wanted = str(path)
        if wanted == found:
            rank = 0
        elif wanted.removesuffix(".zst") == found.removesuffix(".zst"):
            rank = 1
    return rank, -rollout.mtime_ns, rollout.relative


def _inventory(home: Path, catalogue: Catalogue) -> Inventory:
    paths: dict[str, Path] = {}
    path_ids: dict[str, set[str]] = defaultdict(set)
    edges: dict[str, set[str]] = defaultdict(set)
    outside: dict[str, set[str]] = defaultdict(set)
    copies: dict[str, list[Rollout]] = defaultdict(list)
    broken: dict[str, list[Rollout]] = defaultdict(list)
    unidentified: list[Rollout] = []
    for native_id, row in catalogue.threads.items():
        path = _catalogue_path(home, row)
        if path is None:
            continue
        paths[native_id] = path
        path_ids[str(path).removesuffix(".zst")].add(native_id)
        try:
            target = path.resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if not target.is_relative_to(home):
            outside[native_id].add(str(target))
    for edge in catalogue.edges:
        edges[edge["child_thread_id"]].add(edge["parent_thread_id"])
    for rollout in _discover(home):
        matched_id = rollout.native_id
        if matched_id is None:
            matches = path_ids.get(str(home / rollout.relative).removesuffix(".zst"), set())
            if len(matches) == 1:
                matched_id = next(iter(matches))
        if rollout.outside:
            if matched_id is not None:
                try:
                    target = (home / rollout.relative).resolve()
                except (OSError, RuntimeError, ValueError):
                    continue
                outside[matched_id].add(str(target))
        elif rollout.failure is not None:
            if matched_id is None:
                unidentified.append(rollout)
            else:
                broken[matched_id].append(rollout)
        elif matched_id is not None:
            copies[matched_id].append(rollout)

    roots: list[Thread] = []
    children: dict[str, list[Thread]] = defaultdict(list)
    for native_id in sorted(copies.keys() | broken.keys()):
        valid = copies[native_id]
        invalid = broken[native_id]
        chosen = min(valid or invalid, key=lambda rollout: _copy_preference(home, paths.get(native_id), rollout))
        parent = chosen.parent
        if not valid and parent is None:
            evidence = {rollout.parent for rollout in invalid if rollout.parent is not None} | edges[native_id]
            if len(evidence) > 1:
                unidentified.extend(invalid)
                continue
            if evidence:
                parent = next(iter(evidence))
        thread = Thread(native_id, chosen, valid, parent, invalid)
        if parent is None:
            roots.append(thread)
        else:
            children[parent].append(thread)
    return Inventory(roots, children, unidentified, outside)


@dataclass(frozen=True)
class Record:
    kind: str
    at: datetime
    line: int
    ordinal: int | None
    turn_id: str | None
    root_turn_id: str | None
    data: Object


_RESPONSE_ONLY_IN_ARCHIVE = frozenset("""
    agent_message reasoning local_shell_call tool_search_call tool_search_output
    web_search_call image_generation_call compaction compaction_trigger context_compaction
    additional_tools configuration_update ghost_snapshot
    mcp_list_tools mcp_approval_request mcp_approval_response computer_call
    computer_call_output shell_call shell_call_output other
""".split())
_EVENT_ONLY_IN_ARCHIVE = frozenset("""
    error warning auth_recovery_started auth_recovery_completed guardian_warning
    realtime_conversation_started realtime_conversation_realtime realtime_conversation_closed
    realtime_conversation_sdp realtime_conversation_list_voices_response model_reroute
    model_verification turn_moderation_metadata safety_buffering context_compacted
    thread_rolled_back thread_settings_applied token_count agent_message user_message
    agent_reasoning agent_reasoning_raw_content agent_reasoning_section_break session_configured
    environment_connected environment_disconnected thread_goal_updated thread_queue_changed
    mcp_startup_update mcp_startup_complete mcp_tool_call_begin mcp_tool_call_end
    web_search_begin web_search_end image_generation_begin image_generation_end
    exec_command_begin exec_command_output_delta terminal_interaction view_image_tool_call
    exec_approval_request network_approval_resolved request_permissions request_user_input
    dynamic_tool_call_request dynamic_tool_call_response elicitation_request elicitation_abandoned
    apply_patch_approval_request guardian_assessment deprecation_notice stream_error patch_apply_begin
    patch_apply_updated patch_apply_end turn_diff plan_update shutdown_complete entered_review_mode
    exited_review_mode raw_response_item raw_response_completed private_session_event item_started
    hook_started hook_completed agent_message_content_delta plan_delta reasoning_content_delta
    reasoning_raw_content_delta collab_agent_spawn_begin collab_agent_spawn_end
    collab_agent_interaction_begin collab_agent_interaction_end collab_waiting_begin collab_waiting_end
    collab_close_begin collab_close_end collab_resume_begin collab_resume_end sub_agent_activity
""".split())
_ITEM_ONLY_IN_ARCHIVE = frozenset("""
    UserMessage FunctionCallOutput HookPrompt AgentMessage Plan Reasoning DynamicToolCall
    CollabAgentToolCall SubAgentActivity WebSearch ImageView Extension ImageGeneration
    EnteredReviewMode ExitedReviewMode ContextCompaction
""".split())
_WORK_ITEMS = frozenset({"CommandExecution", "McpToolCall", "FileChange"})
_OUTPUT_KINDS = frozenset({"function_call_output", "custom_tool_call_output"})
_CALL_KINDS = frozenset({"function_call", "custom_tool_call"})
_ENDINGS = frozenset({
    "task_complete", "turn_aborted", "task_ended", "turn_ended", "task_failed", "turn_failed",
    "task_cancelled", "turn_cancelled", "task_canceled", "turn_canceled",
    "task_interrupted", "turn_interrupted", "task_finished", "turn_finished",
})


class _Shape(ValueError):
    """A consumed conversation field does not have its native shape."""


def _object(value: object) -> Object:
    if not isinstance(value, dict):
        raise _Shape
    return value


def _optional_string(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise _Shape


def _first_string(*values: object) -> str | None:
    for value in values:
        if text := _optional_string(value):
            return text
    return None


def _string(value: object) -> str:
    if isinstance(value, str):
        return value
    raise _Shape


def _required_id(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    raise _Shape


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is int:
        return value
    raise _Shape


def _unix_time(value: object, scale: int = 1) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Shape
    if value == 0:
        return None
    try:
        return datetime.fromtimestamp(value / scale, UTC)
    except (OSError, OverflowError, ValueError) as error:
        raise _Shape from error


def _response_fields(payload: Object, kind: str, descendant: bool) -> Object:
    if kind == "message":
        role = _string(payload.get("role"))
        content = payload.get("content")
        if role not in ("assistant", "user", "system", "developer", "tool", "function") or not isinstance(content, list):
            raise _Shape
        raw_metadata = payload.get("internal_chat_message_metadata_passthrough")
        metadata = _object(raw_metadata) if raw_metadata is not None else {}
        kinds = metadata.get("content_item_kinds", payload.get("content_item_kinds"))
        if kinds is not None and (not isinstance(kinds, list) or any(not isinstance(name, str) for name in kinds)):
            raise _Shape
        parts = []
        for entry in content:
            part = _object(entry)
            if part.get("type") in ("input_text", "output_text"):
                value = _string(part.get("text"))
                if not descendant and role in ("assistant", "user"):
                    parts.append(value)
            elif part.get("type") not in ("input_image", "input_audio", "output_image"):
                raise _Shape
        return {"role": role, "text": "\n".join(parts) if parts else None, "typed": kinds == ["user.text"]}
    if kind in _CALL_KINDS:
        argument = "input" if kind == "custom_tool_call" else "arguments"
        name = _required_id(payload.get("name"))
        namespace = _optional_string(payload.get("namespace"))
        if argument not in payload:
            raise _Shape
        return {"call_id": _required_id(payload.get("call_id")),
                "name": f"{namespace}::{name}" if namespace else name,
                "input": payload[argument]}
    if kind in _OUTPUT_KINDS:
        output = payload.get("output")
        if not isinstance(output, (str, dict, list)):
            raise _Shape
        if isinstance(output, list):
            for value_part in output:
                part = _object(value_part)
                part_kind = _string(part.get("type"))
                if part_kind in ("text", "input_text", "output_text"):
                    _string(part.get("text"))
                elif part_kind not in ("image", "input_image", "output_image", "input_audio", "encrypted_content"):
                    raise _Shape
        call_id = _optional_string(payload.get("call_id"))
        if kind == "custom_tool_call_output" and not call_id:
            raise _Shape
        return {"call_id": call_id, "result": _tool_result(output) if call_id else None}
    if kind not in _RESPONSE_ONLY_IN_ARCHIVE:
        raise _Shape
    return {}


def _event_fields(payload: Object, kind: str) -> Object:
    if kind == "task_started":
        attribution = _object(payload["turn_attribution"]) if payload.get("turn_attribution") is not None else {}
        return {"trigger": _first_string(attribution.get("turn_trigger"), payload.get("turn_trigger"),
                                         payload.get("trigger"))}
    if kind in _ENDINGS:
        error = payload.get("error")
        if error is not None and not isinstance(error, (dict, str)):
            raise _Shape
        if isinstance(error, dict):
            _optional_string(error.get("message", error.get("text")))
            info = error.get("codex_error_info", error.get("kind", error.get("type")))
            if info is not None and not isinstance(info, (str, dict)):
                raise _Shape
        reason = _optional_string(payload.get("reason"))
        if kind == "turn_aborted" and not reason:
            raise _Shape
        return {"error": error, "reason": reason}
    if kind == "exec_command_end":
        return {"call_id": _optional_string(payload.get("call_id")),
                "exit_code": _optional_int(payload.get("exit_code"))}
    if kind in ("item_started", "item_completed"):
        item = _object(payload.get("item"))
        item_kind = _string(item.get("type"))
        if item_kind in _ITEM_ONLY_IN_ARCHIVE:
            return {}
        if item_kind not in _WORK_ITEMS:
            raise _Shape
        _required_id(item.get("id"))
        _optional_string(item.get("call_id", item.get("callId")))
        if kind == "item_started":
            return {}
        return _completed_work(payload, item, item_kind)
    if kind not in _EVENT_ONLY_IN_ARCHIVE:
        raise _Shape
    return {}


def _usage_fields(payload: Object) -> Object:
    usage = _object(payload.get("usage"))
    counts = {}
    for field_name, alias in (
        ("input_tokens", "input"), ("cached_input_tokens", "cached_input"),
        ("cache_write_input_tokens", "cache_write_input"), ("output_tokens", "output"),
        ("reasoning_output_tokens", "reasoning_output"),
    ):
        count = _optional_int(usage.get(field_name, usage.get(alias)))
        if count is not None and count < 0:
            raise _Shape
        counts[field_name] = count
    if counts["input_tokens"] is None or counts["output_tokens"] is None:
        raise _Shape
    started = payload.get("response_started_at")
    if isinstance(started, str):
        started = _time(started)
        if started is None:
            raise _Shape
    elif started is not None:
        started = _unix_time(started)
    else:
        started = _unix_time(payload.get("response_started_at_ms"), 1000)
    return {"response_id": _required_id(payload.get("response_id")), "usage": counts, "start": started}


def _conversation(rollout: Rollout, line: int, row: Object, kind: str,
                  at: datetime, ordinal: int | None) -> Record:
    payload = _object(row.get("payload"))
    metadata = payload.get("internal_chat_message_metadata_passthrough")
    metadata = _object(metadata) if metadata is not None else {}
    attribution = payload.get("turn_attribution")
    attribution = _object(attribution) if attribution is not None else {}
    turn = _first_string(payload.get("turn_id"), metadata.get("turn_id"), attribution.get("turn_id"),
                         row.get("turn_id"))
    root = _first_string(payload.get("root_turn_id"), attribution.get("root_turn_id"),
                         metadata.get("root_turn_id"), row.get("root_turn_id"))
    if kind == "response_item":
        kind = _string(payload.get("type"))
        data = _response_fields(payload, kind, rollout.parent is not None)
    elif kind == "event_msg":
        kind = _string(payload.get("type"))
        kind = {"turn_started": "task_started", "turn_complete": "task_complete"}.get(kind, kind)
        if kind in _ENDINGS | {"task_started"} and kind != "turn_aborted" and not turn:
            raise _Shape
        data = _event_fields(payload, kind)
    elif kind == "turn_context":
        data = {name: _optional_string(payload.get(name)) for name in ("cwd", "model", "effort")}
    else:
        if not turn:
            raise _Shape
        data = _usage_fields(payload)
    return Record(kind, at, line, ordinal, turn, root, data)


def _body(home: Path, rollout: Rollout) -> Generator[Record]:
    conversation = {"response_item", "event_msg", "turn_context", "token_usage_record"}
    with closing(_records(home, rollout)) as records:
        first = next(records, None)
        if first is None:
            raise SessionFailure("unreadable_session", f"{rollout.relative}: the rollout header disappeared.")
        current = Rollout(rollout.relative)
        _header(current, first[1], first[0])
        if (current.native_id, current.parent, current.history_start) != (
            rollout.native_id, rollout.parent, rollout.history_start
        ):
            raise SessionFailure("unreadable_session", f"{rollout.relative}: the rollout changed while it was read.")
        for line, raw in records:
            where = f"{rollout.relative}:{line}"
            kind: object = None
            try:
                row = _object(raw)
                kind = _string(row.get("type"))
                ordinal = _optional_int(row.get("ordinal"))
                if ordinal is not None and ordinal < 0:
                    raise _Shape
                if rollout.history_start is not None:
                    if ordinal is None:
                        raise _Shape
                    if ordinal < rollout.history_start:
                        continue
                if kind not in conversation:
                    unknown_record(kind, where, conversation=False)
                    continue
                at = _time(row.get("timestamp"))
                if at is None:
                    raise _Shape
                yield _conversation(rollout, line, row, kind, at, ordinal)
            except (_Shape, RecursionError):
                # Report only the known envelope kind. An unknown payload may
                # supply arbitrary strings that must stay out of the report.
                label = kind if isinstance(kind, str) and kind in conversation else None
                unknown_record(label, where, conversation=True)


_SCHEDULED = "automation_heartbeat_scheduled"


def _kind(native_id: str, rollout: Rollout, driver_ids: set[str], starts: list[str | None]) -> Kind:
    originator = rollout.origin.get("originator")
    source = rollout.origin.get("source")
    if native_id in driver_ids or originator == "arbol-codex-driver":
        return "arbol_driver"
    if originator == "hook-probe" or (rollout.role is not None and rollout.role.startswith("probe_")):
        return "probe"
    if originator == "codex_exec" or source == "agent_created_thread" or source == {"custom": "agent_created_thread"}:
        return "agent_launched"
    if starts and all(trigger == _SCHEDULED for trigger in starts):
        return "scheduled"
    return "owner"


@dataclass
class NativeTurn:
    turn_id: str | None
    records: list[Record] = field(default_factory=list)
    start: Record | None = None
    end: Record | None = None
    next_start: datetime | None = None

    @property
    def first_at(self) -> datetime:
        return self.records[0].at

    @property
    def end_at(self) -> datetime:
        if self.end is not None:
            return self.end.at
        if self.next_start is not None:
            return self.next_start
        return self.records[-1].at


def _read_lane(home: Path, rollout: Rollout, starts: list[str | None]) -> list[NativeTurn]:
    turns: dict[str | None, NativeTurn] = {}
    active: NativeTurn | None = None
    with closing(_body(home, rollout)) as records:
        for record in records:
            if record.kind == "task_started":
                starts.append(record.data["trigger"])
                turn = turns.setdefault(record.turn_id, NativeTurn(record.turn_id))
                if active is not None and active is not turn:
                    active.next_start = record.at
                if turn.start is None:
                    turn.start = record
                active = turn if turn.end is None and turn.next_start is None else None
            elif record.turn_id:
                turn = turns.setdefault(record.turn_id, NativeTurn(record.turn_id))
            elif active is not None:
                turn = active
            elif record.kind in _ENDINGS:
                # A legacy abort can close the active turn, if there is one.
                continue
            else:
                turn = turns.setdefault(None, NativeTurn(None))
            turn.records.append(record)
            if record.kind in _ENDINGS and turn.start is not None and turn.end is None and turn.next_start is None:
                turn.end = record
                if active is turn:
                    active = None
    return sorted(turns.values(), key=lambda turn: turn.start.line if turn.start else turn.records[0].line)


def _terminal(end: Record | None) -> tuple[State, str | None, str | None]:
    if end is None:
        return "interrupted", None, None
    native_error = end.data["error"]
    reason = end.data["reason"]
    if end.kind == "task_complete" and native_error is None:
        return "completed", None, None
    if end.kind == "turn_aborted" and reason == "interrupted":
        return "cancelled", None, None
    error_text = native_error if isinstance(native_error, str) else None
    error_kind: str | None = None
    if isinstance(native_error, dict):
        error_text = native_error.get("message", native_error.get("text"))
        info = native_error.get("codex_error_info", native_error.get("kind", native_error.get("type")))
        if isinstance(info, str):
            error_kind = info
        elif isinstance(info, dict) and len(info) == 1:
            error_kind = next(iter(info))
    if end.kind == "turn_aborted":
        error_kind = reason
    elif end.kind != "task_complete":
        error_kind = error_kind or reason or end.kind
    return "failed", error_text, error_kind or end.kind


def _trigger(name: str | None) -> Trigger:
    if name in ("composer", "edit_user_message"):
        return "typed"
    if name == _SCHEDULED:
        return "scheduled"
    return "system"


def _prompt(records: list[Record], trigger: str | None) -> tuple[str, tuple[Steer, ...]]:
    typed: list[Steer] = []
    first_harness: str | None = None
    for record in records:
        if record.kind != "message" or record.data["role"] != "user":
            continue
        text = record.data["text"]
        if record.data["typed"]:
            typed.append(Steer(text or "", record.at))
        elif first_harness is None and text is not None:
            first_harness = text
    if typed:
        return typed[0].text, tuple(typed[1:])
    return (first_harness if first_harness is not None else trigger or ""), ()


def _assistant_text(record: Record) -> TextBlock | None:
    if record.kind == "message" and record.data["role"] == "assistant" and record.data["text"] is not None:
        return TextBlock(record.data["text"], record.at)
    return None


def _inline_image(value: str) -> Image | None:
    if not value.lower().startswith("data:image/"):
        return None
    media, separator, data = value[5:].partition(",")
    if not separator:
        raise _Shape
    media_type, *parameters = media.split(";")
    try:
        raw = unquote_to_bytes(data)
        size = len(b64decode(raw, validate=True)) if any(option.lower() == "base64" for option in parameters) else len(raw)
    except (ValueError, UnicodeError) as error:
        raise _Shape from error
    return Image(media_type, size)


def _without_images(value: Any, images: list[Image]) -> Any:
    if isinstance(value, str):
        image = _inline_image(value)
        if image is not None:
            images.append(image)
            return {"media_type": image.media_type, "size": image.size}
        return value
    if isinstance(value, list):
        return [_without_images(item, images) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") in ("input_image", "output_image", "image"):
        url = value.get("image_url")
        encoded = value.get("data")
        media = value.get("mimeType", value.get("media_type"))
        if isinstance(url, str):
            image = _inline_image(url)
        elif isinstance(encoded, str) and isinstance(media, str) and media.startswith("image/"):
            try:
                image = Image(media, len(b64decode(encoded, validate=True)))
            except (ValueError, UnicodeError) as error:
                raise _Shape from error
        else:
            image = None
        if image is not None:
            images.append(image)
        return {"type": value["type"]}
    if value.get("type") == "encrypted_content":
        return {"type": "encrypted_content"}
    return {key: _without_images(item, images) for key, item in value.items()}


def _json_object_or_list(text: str) -> Object | list[Any] | None:
    if not text.lstrip().startswith(("{", "[")):
        return None
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, (dict, list)) else None


def _result_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part["text"] for part in value
                         if isinstance(part, dict) and isinstance(part.get("text"), str))
    if isinstance(value, dict):
        for name in ("output", "text", "message", "content"):
            part = value.get(name)
            if isinstance(part, (str, list)):
                return _result_text(part)
    return ""


def _tool_result(raw: Any) -> Result:
    images: list[Image] = []
    value = raw
    if isinstance(raw, str):
        decoded = _json_object_or_list(raw)
        if decoded is not None:
            value = decoded
    clean = _without_images(value, images)
    text = _result_text(clean)
    if isinstance(raw, str) and value is not raw and not text:
        text = raw if clean == value else json.dumps(clean, ensure_ascii=True)
    fields = clean if isinstance(clean, dict) else {"content": clean} if isinstance(clean, list) else None
    return Result(text, fields, tuple(images))


def _native_error(result: Result) -> tuple[bool, str | None]:
    fields = result.fields or {}
    error = fields.get("error")
    failed = (
        (error is not None and error is not False)
        or fields.get("type") == "error"
        or fields.get("success") is False
        or fields.get("isError", fields.get("is_error")) is True
    )
    return failed, (_result_text(error) or result.text or None) if failed else None


def _work_link(record: Record, item: Object) -> str | None:
    value = item.get("call_id", item.get("callId")) or record.data.get("call_id")
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True)
class ProjectedCall:
    item: ToolCall
    output_at: datetime | None


def _direct_calls(records: list[Record], agent: str | None) -> dict[int, ProjectedCall]:
    calls: dict[str, Record] = {}
    outputs: dict[tuple[str, str], Record] = {}
    command_codes: dict[str, int] = {}
    for record in records:
        if record.kind in _CALL_KINDS:
            calls.setdefault(record.data["call_id"], record)
        elif record.kind in _OUTPUT_KINDS and record.data["call_id"]:
            outputs.setdefault((record.kind, record.data["call_id"]), record)
        elif record.kind == "exec_command_end":
            if record.data["call_id"] and record.data["exit_code"] is not None:
                command_codes[record.data["call_id"]] = record.data["exit_code"]
        elif record.kind == "item_completed":
            item = record.data.get("item")
            if item is not None and item["type"] == "CommandExecution":
                call_id = _work_link(record, item) or item["id"]
                code = item.get("exit_code", item.get("exitCode"))
                if code is not None:
                    command_codes[call_id] = code

    projected = {}
    for call_id, record in calls.items():
        output = outputs.get((record.kind + "_output", call_id))
        exit_code = command_codes.get(call_id)
        ok, error = False, None
        result = None
        if output is not None:
            result = output.data["result"]
            if result is not None:
                failed, error = _native_error(result)
                if exit_code is not None:
                    result = replace(result, fields={**(result.fields or {}), "exit_code": exit_code})
                ok = exit_code == 0 if exit_code is not None else not failed
                error = None if ok else error or result.text or None
        item = ToolCall(call_id, agent, record.data["name"], record.data["input"], result,
                        ok, error, None, record.at)
        projected[record.line] = ProjectedCall(item, output.at if output is not None else None)
    return projected


def _work_times(record: Record) -> tuple[datetime, datetime]:
    end: datetime = record.data["end"] or record.at
    start: datetime = record.data["start"] or end
    return start, end


def _work_call(record: Record, parent: ToolCall, start: datetime) -> ToolCall:
    item = record.data["item"]
    status = item.get("status")
    result = record.data["result"]
    arguments = record.data["arguments"]
    name = record.data["name"]
    code = record.data["exit_code"]
    failed, error = _native_error(result) if result is not None else (False, None)
    ok = code == 0 if code is not None else not failed and status not in ("failed", "declined", "inProgress",
                                                                          "in_progress", "aborted")
    if not ok and error is None:
        error = _result_text(item.get("error")) or (result.text if result is not None else "") or None
    return ToolCall(
        item["id"], parent.agent, name, arguments, result, ok, None if ok else error, parent.call_id, start,
        parent=CallLink(parent.agent, parent.call_id),
    )


def _completed_work(payload: Object, item: Object, kind: str) -> Object:
    result: Result | None
    arguments: Any
    if kind == "CommandExecution":
        name = "command_execution"
        command = item.get("command")
        if command is not None and (not isinstance(command, list) or any(not isinstance(arg, str) for arg in command)):
            raise _Shape
        _optional_string(item.get("interaction_input"))
        arguments = {field: item[field] for field in ("command", "cwd", "interaction_input") if field in item}
        output = _optional_string(item.get("aggregated_output", item.get("aggregatedOutput")))
        code = _optional_int(item.get("exit_code", item.get("exitCode")))
        fields = {"exit_code": code} if code is not None else None
        result = _tool_result(output) if output is not None else None
        if fields is not None:
            result = replace(result, fields={**(result.fields or {}), **fields}) if result else Result("", fields)
    elif kind == "McpToolCall":
        name = f"{_required_id(item.get('server'))}::{_required_id(item.get('tool'))}"
        arguments = item.get("arguments")
        code = None
        mcp_result = item.get("result")
        if mcp_result is not None and not isinstance(mcp_result, dict):
            raise _Shape
        result = _tool_result(mcp_result) if mcp_result is not None else None
    else:
        name = "file_change"
        changes = _object(item.get("changes"))
        arguments = {
            path: {key: _optional_string(change.get(key)) for key in ("type", "move_path") if key in change}
            for path, entry in changes.items() if (change := _object(entry)) is not None
        }
        code = None
        patch_output = {key: _optional_string(item[key]) for key in ("stdout", "stderr") if key in item}
        output = "\n".join(value for value in patch_output.values() if value)
        result = Result(output, patch_output or None)
    _optional_string(item.get("status"))
    link = _optional_string(payload.get("call_id", payload.get("callId")))
    start = _unix_time(payload.get("started_at_ms"), 1000)
    end = _unix_time(payload.get("completed_at_ms"), 1000)
    return {"item": {"id": item["id"], "type": kind, "status": item.get("status"), "error": item.get("error"),
                     "call_id": item.get("call_id", item.get("callId")), "exit_code": code},
            "call_id": link, "start": start, "end": end, "result": result, "name": name,
            "arguments": arguments, "exit_code": code}


def _code_mode_work(records: list[Record], projected: dict[int, ProjectedCall]) -> dict[int, ProjectedCall]:
    spans = sorted(
        (entry for entry in projected.values()
         if entry.output_at is not None and entry.item.name.rsplit("::", 1)[-1] == "exec"),
        key=lambda entry: entry.item.started_at,
    )
    if not spans:
        return {}
    used_ids = {entry.item.call_id for entry in projected.values()}
    work = []
    for record in records:
        item = record.data.get("item") if record.kind == "item_completed" else None
        if item is None or _work_link(record, item) is not None or item["id"] in used_ids:
            continue
        start, end = _work_times(record)
        if start <= end:
            work.append((start, record.line, end, record))
    result: dict[int, ProjectedCall] = {}
    active: dict[int, tuple[ProjectedCall, datetime]] = {}
    expiry: list[tuple[datetime, int]] = []
    index = 0
    for start, line, end, record in sorted(work):
        while index < len(spans) and spans[index].item.started_at <= start:
            span = spans[index]
            bound = span.output_at
            if bound is not None:
                active[index] = (span, bound)
                heappush(expiry, (bound, index))
            index += 1
        while expiry and expiry[0][0] < start:
            _, expired = heappop(expiry)
            del active[expired]
        matches = [span for span, bound in active.values() if end <= bound]
        native_id = record.data["item"]["id"]
        if len(matches) == 1 and native_id not in used_ids:
            used_ids.add(native_id)
            result[line] = ProjectedCall(_work_call(record, matches[0].item, start), end)
    return result


def _responses(turn: NativeTurn) -> tuple[Response, ...]:
    recorded: dict[str, Response] = {}
    for record in turn.records:
        if record.kind != "token_usage_record" or record.data["response_id"] in recorded:
            continue
        counts = record.data["usage"]
        usage = Usage(
            input_tokens=counts["input_tokens"],
            cached_input_tokens=counts["cached_input_tokens"] or 0,
            cache_write_tokens=counts["cache_write_input_tokens"],
            output_tokens=counts["output_tokens"],
            reasoning_tokens=counts["reasoning_output_tokens"],
        )
        recorded[record.data["response_id"]] = Response(record.data["start"] or record.at, usage)
    return tuple(recorded.values())


def _turn_context(turn: NativeTurn) -> Object:
    return next((record.data for record in reversed(turn.records) if record.kind == "turn_context"), {})


@dataclass
class Lane:
    turns: list[NativeTurn]
    items: dict[int, list[Item]]
    # The root turn hosting each already-projected call in this lane.
    call_turns: dict[str, int] = field(default_factory=dict)


def _project_lane(native_turns: list[NativeTurn], agent: str | None) -> Lane:
    records = sorted((record for turn in native_turns for record in turn.records), key=lambda record: record.line)
    direct = _direct_calls(records, agent)
    work = _code_mode_work(records, direct)
    call_owners = {direct[record.line].item.call_id: index
                   for index, turn in enumerate(native_turns) for record in turn.records if record.line in direct}
    items: dict[int, list[tuple[int, Item]]] = defaultdict(list)
    for index, turn in enumerate(native_turns):
        for record in turn.records:
            if entry := direct.get(record.line):
                items[index].append((record.line, entry.item))
            elif entry := work.get(record.line):
                parent_id = entry.item.parent_call_id
                if parent_id is not None:
                    items[call_owners[parent_id]].append((record.line, entry.item))
            elif agent is None and (block := _assistant_text(record)) is not None:
                items[index].append((record.line, block))
    ordered = {index: [item for _, item in sorted(entries, key=lambda entry: entry[0])]
               for index, entries in items.items()}
    return Lane(native_turns, ordered)


def _identifies_spawn(value: object, native_id: str, agent_path: str | None) -> bool:
    if isinstance(value, str):
        # Some result shapes wrap the spawn object in a structured text part.
        decoded = _json_object_or_list(value)
        return decoded is not None and _identifies_spawn(decoded, native_id, agent_path)
    if isinstance(value, list):
        return any(_identifies_spawn(entry, native_id, agent_path) for entry in value)
    if not isinstance(value, dict):
        return False
    if any(value.get(key) == native_id for key in ("agent_id", "new_agent_id", "agent_thread_id", "child_thread_id", "thread_id")):
        return True
    if agent_path is not None and any(value.get(key) == agent_path for key in ("task_name", "agent_path")):
        return True
    # These native envelopes can contain either structured or textual output.
    return any(_identifies_spawn(value.get(key), native_id, agent_path)
               for key in ("content", "structuredContent", "structured_content", "output", "text"))


def _launch(parent: Lane | None, thread: Thread) -> ToolCall | None:
    if parent is None:
        return None
    candidates = []
    for items in parent.items.values():
        for item in items:
            if not isinstance(item, ToolCall) or not item.ok or item.result is None:
                continue
            name = item.name.rsplit("::", 1)[-1]
            if name not in ("spawn_agent", "spawn_agents", "fork_agent"):
                continue
            if (_identifies_spawn(item.result.fields, thread.native_id, thread.chosen.agent_path)
                    or _identifies_spawn(item.result.text, thread.native_id, thread.chosen.agent_path)):
                candidates.append(item)
    return candidates[0] if len(candidates) == 1 else None


def _root_turn_at(turns: list[NativeTurn], at: datetime) -> int | None:
    indices = [
        index for index, turn in enumerate(turns)
        if turn.start is not None and turn.start.at <= at <= turn.end_at and at != turn.next_start
    ]
    return indices[0] if len(indices) == 1 else None


def _assigned_turn(turn: NativeTurn, root: Lane, root_ids: dict[str, int], launch_turn: int | None) -> int | None:
    native_roots = {record.root_turn_id for record in turn.records if record.root_turn_id}
    if native_roots:
        if len(native_roots) == 1:
            return root_ids.get(next(iter(native_roots)))
        # Conflicting causal IDs cannot justify attaching this work to a turn.
        return None
    if turn.turn_id in root_ids:
        return root_ids[turn.turn_id]
    if launch_turn is not None:
        return launch_turn
    return _root_turn_at(root.turns, turn.first_at)


@dataclass
class AgentWork:
    turns: list[NativeTurn] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)

    def info(self, agent: str, launch: CallLink | None) -> Subagent:
        first = min(self.turns, key=lambda turn: turn.records[0].line).first_at
        native_turns = [turn for turn in self.turns if turn.start is not None]
        last = max(native_turns or self.turns, key=lambda turn: turn.records[-1].line)
        return Subagent(
            agent, launch.call_id if launch else None, first, _terminal(last.end)[0] == "failed", self.usage, launch,
        )


def _agents(root: Lane, descendants: list[tuple[Thread, Lane]], root_id: str
            ) -> dict[int, list[tuple[Subagent, list[ToolCall]]]]:
    root_ids = {turn.turn_id: index for index, turn in enumerate(root.turns)
                if turn.start is not None and turn.turn_id is not None}
    for index in root_ids.values():
        for item in root.items.get(index, ()):
            if isinstance(item, ToolCall):
                root.call_turns[item.call_id] = index
    family = {root_id: root}
    assigned: dict[int, list[tuple[Subagent, list[ToolCall]]]] = defaultdict(list)
    for thread, lane in descendants:
        parent = family.get(thread.parent) if thread.parent else None
        launch = _launch(parent, thread)
        launch_turn = parent.call_turns.get(launch.call_id) if parent is not None and launch is not None else None
        per_turn: dict[int, AgentWork] = defaultdict(AgentWork)
        for index, native_turn in enumerate(lane.turns):
            target = _assigned_turn(native_turn, root, root_ids, launch_turn)
            if target is None:
                continue
            work = per_turn[target]
            work.turns.append(native_turn)
            for response in _responses(native_turn):
                work.usage += response.usage
            link = CallLink(launch.agent, launch.call_id) if launch is not None and launch_turn == target else None
            for item in lane.items.get(index, ()):
                if isinstance(item, ToolCall):
                    lane.call_turns[item.call_id] = target
                    parent_link = item.parent or link
                    work.calls.append(replace(
                        item, parent_call_id=parent_link.call_id if parent_link else None, parent=parent_link,
                    ))
        family[thread.native_id] = lane
        for target, work in per_turn.items():
            link = CallLink(launch.agent, launch.call_id) if launch is not None and launch_turn == target else None
            assigned[target].append((work.info(thread.native_id, link), work.calls))
    return assigned


def _session_metadata(root: Thread, catalogue: Catalogue, titles: dict[str, str]) -> tuple[str | None, str | None]:
    title = catalogue.threads.get(root.native_id, {}).get("title")
    if not isinstance(title, str) or not title:
        title = titles.get(root.native_id)
    cwd = root.chosen.origin.get("cwd")
    return title, cwd if isinstance(cwd, str) else None


# The native catalogue fields describing a session. Other columns and tables
# may contain application settings, account or device identifiers, or caches.
_THREAD_ARCHIVE_FIELDS = frozenset("""
    id rollout_path created_at updated_at source model_provider cwd title tokens_used
    has_user_event archived archived_at git_sha git_branch cli_version first_user_message
    agent_nickname agent_role agent_path model reasoning_effort created_at_ms updated_at_ms
    thread_source preview recency_at history_mode name is_pinned section_id section_order
    originator attached_parent_thread_id
""".split())
_EDGE_ARCHIVE_FIELDS = frozenset({"parent_thread_id", "child_thread_id", "status"})


def _session_archive(home: Path, catalogue: Catalogue, inventory: Inventory, family: list[Thread],
                     clock: datetime) -> tuple[tuple[ArchiveFile, ...], int, bool]:
    native_ids = {thread.native_id for thread in family}
    root = family[0]
    rollouts = {rollout.relative: rollout for thread in family for rollout in thread.copies}
    try:
        files = [
            rollout.observations.nominate(home, home / relative, target=_observed_target(home, rollout))
            for relative, rollout in sorted(rollouts.items())
        ]
        live = any(file.observation is not None and file.observation.modified_at >= clock - LIVE_WINDOW for file in files)
    except (OSError, OverflowError):
        raise SessionFailure("unreadable_session", f"{root.chosen.relative}: rollout times could not be read.") from None
    archive: list[ArchiveFile] = list(files)
    if catalogue.mtime is not None:
        threads = [
            {key: value for key, value in catalogue.threads[native_id].items() if key in _THREAD_ARCHIVE_FIELDS}
            for native_id in sorted(native_ids) if native_id in catalogue.threads
        ]
        edges = [
            {key: value for key, value in edge.items() if key in _EDGE_ARCHIVE_FIELDS}
            for edge in catalogue.edges
            if edge["parent_thread_id"] in native_ids and edge["child_thread_id"] in native_ids
        ]
        edges.sort(key=lambda edge: (edge["parent_thread_id"], edge["child_thread_id"], str(edge.get("status", ""))))
        if threads or edges:
            rows = json.dumps({"threads": threads, "thread_spawn_edges": edges},
                              sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
            archive.append(ExportedRows(f"{_DB}#{root.native_id}.json", rows, catalogue.mtime))
    outside = {path for native_id in native_ids for path in inventory.outside.get(native_id, ())}
    return tuple(archive), len(outside), live


def _assemble_turns(root: Lane, descendants: list[tuple[Thread, Lane]], native_id: str) -> tuple[Turn, ...]:
    agents = _agents(root, descendants, native_id)
    turns = []
    for index, native in enumerate(root.turns):
        start = native.start
        if start is None or native.turn_id is None:
            continue
        trigger = start.data["trigger"]
        prompt, steers = _prompt(native.records, trigger)
        state, error, error_kind = _terminal(native.end)
        context = _turn_context(native)
        items = list(root.items.get(index, ()))
        subagents = []
        for agent, calls in sorted(agents.get(index, ()), key=lambda entry: entry[0].first_record_at):
            subagents.append(agent)
            items.extend(calls)
        turns.append(Turn(
            turn_key=native.turn_id,
            trigger=_trigger(trigger),
            prompt=prompt,
            started_at=start.at,
            ended_at=native.end_at,
            state=state,
            error=error,
            error_kind=error_kind,
            working_folder=context.get("cwd"),
            model=context.get("model"),
            effort=context.get("effort"),
            usage=_responses(native),
            items=tuple(items),
            subagents=tuple(subagents),
            steers=steers,
        ))
    return tuple(turns)


def _read_session(home: Path, source: Source, root: Thread, inventory: Inventory, catalogue: Catalogue,
                  titles: dict[str, str], driver_ids: set[str]) -> Session | Failed:
    starts: list[str | None] = []
    try:
        if not root.copies and root.chosen.failure is not None:
            raise root.chosen.failure
        root_turns = _read_lane(home, root.chosen, starts)
        family = list(inventory.family(root))
        descendants = []
        for thread in family:
            for broken in thread.broken:
                if broken.failure is not None:
                    raise broken.failure
            if thread is not root:
                native = _read_lane(home, thread.chosen, [])
                descendants.append((thread, _project_lane(native, thread.native_id)))
        created_at = root.chosen.created_at
        if created_at is None:
            raise SessionFailure("unknown_format", f"{root.chosen.relative}: the session header has no creation time.")
        title, cwd = _session_metadata(root, catalogue, titles)
        archive, outside, live = _session_archive(home, catalogue, inventory, family, source.clock)
        return Session(
            tool="codex",
            native_id=root.native_id,
            kind=_kind(root.native_id, root.chosen, driver_ids, starts),
            title=title,
            created_at=created_at,
            tool_version=root.chosen.version,
            origin=root.chosen.origin,
            working_folder=cwd,
            live=live,
            turns=_assemble_turns(_project_lane(root_turns, None), descendants, root.native_id),
            archive_files=archive,
            files_not_archived=outside,
        )
    except SessionFailure as failure:
        return Failed.of(failure, native_id=root.native_id, kind=_kind(root.native_id, root.chosen, driver_ids, starts))


def read(source: Source) -> Iterator[Session | Failed]:
    """Yield one supported Codex session or local failure per selected root."""
    try:
        home = source.home.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return
    driver_ids = _driver_ids(source.driver_state)
    catalogue = _read_catalogue(home, source.work)
    titles = _titles(home)
    inventory = _inventory(home, catalogue)
    for root in inventory.roots:
        if source.wants(root.native_id):
            yield _read_session(home, source, root, inventory, catalogue, titles, driver_ids)
    if source.selected is None:
        for broken in inventory.unidentified:
            if broken.failure is not None:
                yield Failed.of(broken.failure, file=broken.relative)
