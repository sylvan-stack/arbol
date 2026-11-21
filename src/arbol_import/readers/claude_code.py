"""Read saved Claude Code sessions and their archive files (IMP-1)."""

from __future__ import annotations

import base64
import binascii
import json
import re
import stat
from collections.abc import Generator, Iterable, Iterator, Sequence
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

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


@dataclass(frozen=True)
class SessionFile:
    path: Path

    @property
    def native_id(self) -> str:
        return self.path.stem

    @property
    def directory(self) -> Path:
        return self.path.with_suffix("")


def _inside(root: Path, path: Path) -> Path | None:
    resolved = path.resolve()
    return resolved if resolved.is_relative_to(root) else None


def _unreadable(home: Path, path: Path) -> SessionFailure:
    return SessionFailure("unreadable_session", f"{path.relative_to(home)}: could not be read.")


def _regular(home: Path, path: Path) -> Path:
    try:
        resolved = _inside(home, path)
        if resolved is not None and stat.S_ISREG(resolved.stat().st_mode):
            return resolved
    except (OSError, RuntimeError, ValueError):
        pass
    raise _unreadable(home, path)


def _discover(home: Path) -> Iterator[SessionFile | Failed]:
    projects = home / "projects"
    try:
        if _inside(home, projects) is None:
            raise _unreadable(home, projects)
        folders = sorted(projects.iterdir())
    except FileNotFoundError:
        return
    except (OSError, RuntimeError, SessionFailure):
        yield Failed.of(_unreadable(home, projects), file="projects")
        return
    for folder in folders:
        try:
            if _inside(home, folder) is None:
                raise _unreadable(home, folder)
            if not stat.S_ISDIR(folder.stat().st_mode):
                continue
            paths = sorted(folder.iterdir())
        except (OSError, RuntimeError, SessionFailure):
            yield Failed.of(_unreadable(home, folder), file=folder.relative_to(home).as_posix())
            continue
        yield from (SessionFile(path) for path in paths if path.suffix == ".jsonl")


_NATIVE_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)


def _map_entries(root: Path, directory: Path) -> Iterator[Path]:
    try:
        if _inside(root, directory) is not None:
            yield from directory.iterdir()
    except (OSError, RuntimeError):
        pass


def _driver_ids(state: Path | None) -> set[str]:
    if state is None:
        return set()
    try:
        root = state.resolve()
    except (OSError, RuntimeError):
        return set()

    native_ids = set()
    for subscription in _map_entries(root, root / "subscriptions"):
        for entry in _map_entries(root, subscription / "chats"):
            if entry.suffix != ".json":
                continue
            try:
                value = json.loads(_regular(root, entry).read_bytes())
            except (OSError, ValueError, RecursionError, SessionFailure):
                continue
            conversation = value.get("conversation") if isinstance(value, dict) else None
            if isinstance(conversation, str) and _NATIVE_ID.fullmatch(conversation):
                native_ids.add(conversation)
    return native_ids


def _time(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.utcoffset() is not None:
                return parsed.astimezone(UTC)
        except (ValueError, OverflowError):
            pass
    return None


@dataclass(frozen=True)
class OrderedFile:
    file: SessionFile
    at: datetime
    mtime: datetime | None
    lookahead_failure: SessionFailure | None = None
    failure_line: int = 1


def _data_file(home: Path, path: Path) -> Path:
    resolved = _regular(home, path)
    try:
        if (
            resolved.parent == path.parent.resolve()
            and resolved.suffix == path.suffix
            and _archive_name(resolved.relative_to(home))
        ):
            return resolved
    except (OSError, RuntimeError, ValueError):
        pass
    raise _unreadable(home, path)


def _bind_input(home: Path, path: Path, target: Path, observations: FileObservations) -> str:
    info = target.stat(follow_symlinks=False)
    observations.record(path, info)
    observations.record(target, info)
    return target.relative_to(home).as_posix()


def _read_records(home: Path, path: Path, observations: FileObservations) -> Generator[tuple[int, Any]]:
    resolved = _data_file(home, path)
    yield from file_records(home, _bind_input(home, path, resolved, observations), observations)


def _record_time(row: dict[str, Any]) -> datetime | None:
    at = _time(row.get("timestamp"))
    if at is None and row.get("type") == "file-history-snapshot":
        snapshot = row.get("snapshot")
        if isinstance(snapshot, dict):
            return _time(snapshot.get("timestamp"))
    return at


def _order_file(home: Path, file: SessionFile, observations: FileObservations) -> OrderedFile:
    modified = None
    number = 0
    try:
        target = _data_file(home, file.path)
        _bind_input(home, file.path, target, observations)
        modified = observations.files[target].modified_at
        stream = _read_records(home, file.path, observations)
        try:
            for line, row in stream:
                number = line
                at = _record_time(row) if isinstance(row, dict) else None
                if at is not None:
                    return OrderedFile(file, at, modified)
        finally:
            stream.close()
    except (OSError, OverflowError, RecursionError, SessionFailure) as error:
        failure = error if isinstance(error, SessionFailure) else _unreadable(home, file.path)
        return OrderedFile(file, modified or datetime.min.replace(tzinfo=UTC), modified, failure, number + 1)
    assert modified is not None
    return OrderedFile(file, modified, modified)


@dataclass(frozen=True)
class Record:
    file: SessionFile
    position: tuple[int, int]
    row: dict[str, Any]
    at: datetime | None
    duplicate: bool
    stream_path: Path | None = None
    results: dict[str, NativeResult] = field(default_factory=dict)

    def where(self, home: Path) -> str:
        return f"{(self.stream_path or self.file.path).relative_to(home)}:{self.position[1]}"


@dataclass
class SessionRecords:
    files: list[OrderedFile] = field(default_factory=list)
    rows: list[Record] = field(default_factory=list)
    failure: SessionFailure | None = None
    created_at: datetime | None = None


def _ordered_rows(home: Path, ordered: OrderedFile, observations: FileObservations) -> Generator[tuple[int, Any]]:
    with closing(_read_records(home, ordered.file.path, observations)) as records:
        for number, raw in records:
            if ordered.lookahead_failure is not None and number >= ordered.failure_line:
                raise ordered.lookahead_failure
            yield number, raw
    if ordered.lookahead_failure is not None:
        raise ordered.lookahead_failure


def _context_files(files: list[SessionFile], selected: frozenset[str] | None) -> Iterable[SessionFile]:
    if selected is None:
        return files
    by_project: dict[Path, list[SessionFile]] = {}
    by_id: dict[str, list[SessionFile]] = {}
    for file in files:
        by_project.setdefault(file.path.parent, []).append(file)
        by_id.setdefault(file.native_id, []).append(file)

    # A continued UUID can cross IDs in a project, and copies of the same
    # session can cross projects. Include both links when a selection is given.
    pending = [file for native_id in selected for file in by_id.get(native_id, ())]
    related: set[SessionFile] = set()
    while pending:
        file = pending.pop()
        if file in related:
            continue
        related.add(file)
        pending.extend(by_project.pop(file.path.parent, []))
        pending.extend(by_id.pop(file.native_id, []))
    return related


def _ordered_sessions(
    home: Path, source: Source, observations: FileObservations,
) -> Iterator[Failed | tuple[str, SessionRecords]]:
    discovered: list[SessionFile] = []
    for file in _discover(home):
        if isinstance(file, Failed):
            yield file
        else:
            discovered.append(file)
    files = sorted(
        (_order_file(home, file, observations) for file in _context_files(discovered, source.selected)),
        key=lambda ordered: (ordered.at, ordered.file.path),
    )

    remaining: dict[str, int] = {}
    for ordered in files:
        native_id = ordered.file.native_id
        remaining[native_id] = remaining.get(native_id, 0) + 1

    projects: dict[Path, set[str]] = {}
    previous_copies: dict[str, set[str]] = {}
    sessions: dict[str, SessionRecords] = {}

    # Context IDs go through the same scan even when they won't be yielded.
    for rank, ordered in enumerate(files):
        file = ordered.file
        native_id = file.native_id
        session = sessions.setdefault(native_id, SessionRecords())
        session.files.append(ordered)
        project_uuids = projects.setdefault(file.path.parent, set())
        session_uuids = previous_copies.setdefault(native_id, set())
        seen_here: set[str] = set()
        if session.failure is None:
            try:
                for number, raw in _ordered_rows(home, ordered, observations):
                    uuid = raw.get("uuid") if isinstance(raw, dict) else None
                    duplicate = isinstance(uuid, str) and (uuid in project_uuids or uuid in session_uuids)
                    row = _validated(home, file, (rank, number), raw, duplicate, observations)
                    if session.created_at is None and isinstance(raw, dict):
                        session.created_at = row.at if row is not None else _record_time(raw)
                    if row is None:
                        continue
                    if isinstance(uuid, str):
                        seen_here.add(uuid)
                    if source.wants(native_id):
                        session.rows.append(row)
            except SessionFailure as error:
                session.failure = error
            except (OSError, RecursionError):
                session.failure = _unreadable(home, file.path)
        project_uuids.update(seen_here)
        session_uuids.update(seen_here)
        remaining[native_id] -= 1
        if remaining[native_id] == 0:
            previous_copies.pop(native_id)
            finished = sessions.pop(native_id)
            if source.wants(native_id):
                yield native_id, finished


_USAGE_FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
_MESSAGE_TYPES = ("user", "assistant")
_ARCHIVE_BLOCKS = (
    "thinking", "redacted_thinking", "document", "search_result", "tool_reference", "container_upload",
    "server_tool_use", "web_search_tool_result", "web_fetch_tool_result", "code_execution_tool_result",
    "bash_code_execution_tool_result", "text_editor_code_execution_tool_result", "mcp_tool_use", "mcp_tool_result",
    "compaction",
)
_METADATA_TYPES = (
    "summary", "system", "progress", "queue-operation", "bridge-session", "relocated", "custom-title", "ai-title",
    "file-history-snapshot", "file-history-delta",
)


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _bad_record(home: Path, record: Record) -> NoReturn:
    # Record types from unrecognised envelopes can contain arbitrary native text.
    kind = record.row.get("type")
    known = kind if kind in (*_MESSAGE_TYPES, *_METADATA_TYPES, "attachment") else None
    unknown_record(known, record.where(home), conversation=True)
    raise AssertionError("An unknown conversation record must fail.")


def _check_content(home: Path, record: Record, content: object, allowed: tuple[str, ...]) -> None:
    if isinstance(content, str):
        return
    if not isinstance(content, list):
        _bad_record(home, record)
    for block in content:
        if not isinstance(block, dict) or block.get("type") not in allowed:
            _bad_record(home, record)
        kind = block["type"]
        if kind == "text" and not isinstance(block.get("text"), str):
            _bad_record(home, record)
        if kind == "tool_use" and (
            not _string(block.get("id")) or not _string(block.get("name")) or "input" not in block
        ):
            _bad_record(home, record)
        if kind == "tool_result":
            if not _string(block.get("tool_use_id")) or type(block.get("is_error", False)) is not bool:
                _bad_record(home, record)
            _check_content(home, record, block.get("content", ""), ("text", "image", *_ARCHIVE_BLOCKS))


def _validate_message(home: Path, record: Record) -> None:
    row = record.row
    kind = row["type"]
    message = _object(row.get("message"))
    if not message or message.get("role", kind) != kind or record.at is None:
        _bad_record(home, record)
    native_block = "tool_result" if kind == "user" else "tool_use"
    _check_content(home, record, message.get("content"), ("text", "image", native_block, *_ARCHIVE_BLOCKS))
    for name in ("uuid", "version", "cwd", "entrypoint", "permissionMode", "turnOrigin", "effort", "error"):
        if row.get(name) is not None and not isinstance(row[name], str):
            _bad_record(home, record)
    for name in ("isMeta", "isCompactSummary", "isApiErrorMessage"):
        if row.get(name) is not None and type(row[name]) is not bool:
            _bad_record(home, record)
    if kind == "user" and _user_prompt(record) is not None and not _string(row.get("uuid")):
        _bad_record(home, record)
    if kind == "assistant":
        for name in ("id", "model", "stop_reason"):
            if message.get(name) is not None and not isinstance(message[name], str):
                _bad_record(home, record)
        usage = message.get("usage")
        if usage is not None and (
            not isinstance(usage, dict) or any(
                value is not None and (type(value) is not int or value < 0)
                for value in (usage.get(name) for name in _USAGE_FIELDS)
            )
        ):
            _bad_record(home, record)


def _validated(
    home: Path, file: SessionFile, position: tuple[int, int], raw: object, duplicate: bool,
    observations: FileObservations, *, stream_path: Path | None = None,
) -> Record | None:
    row = _object(raw)
    kind = row.get("type")
    record = Record(file, position, row, _record_time(row), duplicate, stream_path)
    if kind in _MESSAGE_TYPES:
        _validate_message(home, record)
        if kind == "user":
            results = _native_results(home, record, observations)
            if results and not duplicate:
                record = replace(record, results=results)
    elif kind == "attachment":
        attachment = _object(row.get("attachment"))
        if not _string(attachment.get("type")):
            _bad_record(home, record)
        if attachment["type"] == "queued_command":
            if record.at is None:
                _bad_record(home, record)
            _check_content(home, record, attachment.get("prompt"), ("text", "image"))
    elif kind not in _METADATA_TYPES:
        conversation = any(key in row for key in ("message", "attachment", "turnId", "role", "content"))
        conversation = conversation or not isinstance(raw, dict) or kind in ("message", "turn", "result", "stream_event")
        unknown_record(None, record.where(home), conversation=conversation)
        return None
    return record


# Exact first prompts from the Claude Driver live checks (archived dev.py),
# the recorded continuity probe, and Arbol's C14 and C44 conformance sources.
_PROBE_PROMPTS = frozenset({
    "Answer with the single word: ready",
    "Use AskUserQuestion to ask Ready? with options Ready and Later. Then use Bash to run printf ready. Finish with ready.",
    "Start one Haiku sub-agent in the background. Tell it to run printf ready and return ready. Wait for it and finish with ready.",
    "Remember the word willow. Answer only ready.",
    "What word did I give you? Answer only that word.",
    "Use Bash to run sleep 8 then printf ready.",
    "Remember probe.",
    "history-user-secret",
    "answer",
})
_INTERRUPTED = "[Request interrupted by user"
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_COMMAND_WRAPPER = re.compile(
    r"<(command-name|command-message|command-args|local-command-stdout)>.*?</\1>", re.DOTALL
)


def _blocks(content: object) -> list[dict[str, Any]]:
    return [_object(part) for part in content] if isinstance(content, list) else []


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(block["text"] for block in _blocks(content) if block.get("type") == "text")


def _message(row: Record) -> dict[str, Any]:
    return _object(row.row.get("message"))


def _interruption(record: Record) -> bool:
    return record.row.get("type") == "user" and _REMINDER.sub(
        "", _text(_message(record).get("content"))
    ).lstrip().startswith(_INTERRUPTED)


def _user_prompt(record: Record) -> str | None:
    row = record.row
    if row.get("type") != "user" or row.get("isMeta") or row.get("isCompactSummary"):
        return None
    content = _message(record).get("content")
    blocks = _blocks(content)
    if row.get("toolUseResult") is not None or any(block.get("type") == "tool_result" for block in blocks):
        return None
    text = _text(content)
    prompt = _REMINDER.sub("", text)
    if prompt.lstrip().startswith(_INTERRUPTED):
        return None
    if text.strip() and not _COMMAND_WRAPPER.sub("", prompt).strip():
        if not any(block.get("type") == "image" for block in blocks):
            return None
    return prompt


def _first_field(records: Sequence[Record], name: str) -> str | None:
    return next((value for record in records if (value := _string(record.row.get(name))) is not None), None)


def _kind(native_id: str, driver_ids: set[str], records: Sequence[Record]) -> Kind:
    if native_id in driver_ids or any(record.row.get("version") == "synthetic-arbol" for record in records):
        return "arbol_driver"
    if _first_field(records, "entrypoint") != "sdk-cli":
        return "owner"
    if records[0].file.path.parent.name.startswith("-private-tmp-") and not any(
        record.row.get("type") == "bridge-session" for record in records
    ):
        first_prompt = next((prompt for row in records if (prompt := _user_prompt(row)) is not None), None)
        if first_prompt in _PROBE_PROMPTS:
            return "probe"
    return "agent_launched"


@dataclass(frozen=True)
class TurnRecords:
    prompt: str
    rows: list[Record]


def _turn_records(records: Iterable[Record]) -> Iterator[TurnRecords]:
    current = None
    for record in records:
        if record.duplicate:
            continue
        prompt = _user_prompt(record)
        if prompt is not None:
            if current is not None:
                yield current
            current = TurnRecords(prompt, [])
        if current is not None:
            current.rows.append(record)
    if current is not None:
        yield current


def _at(record: Record) -> datetime:
    assert record.at is not None
    return record.at


def _trigger(row: Record) -> Trigger:
    origin = row.row.get("turnOrigin")
    if origin == "task_notification":
        return "task"
    if origin in ("sdk", "peer", "host_synthetic"):
        return "system"
    return "typed" if origin in (None, "human") else "system"


@dataclass(frozen=True)
class Ending:
    at: datetime
    state: State
    error: str | None = None
    kind: str | None = None


def _ending(rows: Sequence[Record]) -> Ending | None:
    marker = next((row for row in reversed(rows) if _interruption(row)), None)
    if marker is not None:
        return Ending(_at(marker), "cancelled")
    assistant = next((row for row in reversed(rows) if row.row.get("type") == "assistant"), None)
    if assistant is None:
        return None
    message = _message(assistant)
    if assistant.row.get("isApiErrorMessage"):
        return Ending(
            _at(assistant), "failed", _text(message.get("content")), _string(assistant.row.get("error"))
        )
    reason = _string(message.get("stop_reason"))
    if reason == "end_turn":
        return Ending(_at(assistant), "completed")
    if reason is not None and reason != "tool_use":
        return Ending(_at(assistant), "failed", kind=reason)
    return None


def _steers(rows: Iterable[Record]) -> Iterator[Steer]:
    for row in rows:
        if row.row.get("type") != "attachment":
            continue
        attachment = _object(row.row.get("attachment"))
        if attachment.get("type") == "queued_command":
            yield Steer(_REMINDER.sub("", _text(attachment.get("prompt"))), _at(row))


def _turn(
    group: TurnRecords,
    results: dict[str, NativeResult],
    responses: dict[tuple[int, int], Response],
) -> Turn:
    rows = group.rows
    start = rows[0]
    assistant = next((record for record in rows if record.row.get("type") == "assistant"), None)
    ending = _ending(rows)
    if ending is None:
        ending = Ending(next(row.at for row in reversed(rows) if row.at is not None), "interrupted")
    return Turn(
        turn_key=start.row["uuid"],
        trigger=_trigger(start),
        prompt=group.prompt,
        started_at=_at(start),
        ended_at=ending.at,
        state=ending.state,
        error=ending.error,
        error_kind=ending.kind,
        working_folder=_string(start.row.get("cwd")),
        model=_string(_message(assistant).get("model")) if assistant is not None else None,
        effort=_string(assistant.row.get("effort")) if assistant is not None else None,
        usage=tuple(responses[row.position] for row in rows if row.position in responses),
        items=tuple(_items(rows, results)),
        steers=tuple(_steers(rows)),
    )


@dataclass(frozen=True)
class NativeResult:
    output: Result
    ok: bool


_SPILLED = re.compile(r"\A<persisted-output>.*?Full output saved to:[ \t]*([^\r\n<]+)", re.DOTALL)


def _spill_path(record: Record, text: str) -> Path | None:
    match = _SPILLED.match(text[:4096])
    if match is None:
        return None
    path = Path(match[1].strip())
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "tool-results":
        return record.file.directory / path
    return record.file.directory / "tool-results" / path


def _spill_result(
    home: Path, record: Record, text: str, observations: FileObservations,
) -> tuple[str, tuple[Image, ...]]:
    path = _spill_path(record, text)
    if path is None:
        return text, ()
    folder = record.file.directory / "tool-results"
    try:
        resolved = _inside(home, path)
        if (
            resolved is None or not resolved.is_relative_to(folder)
            or not _archive_name(path.relative_to(home)) or not _archive_name(resolved.relative_to(home))
        ):
            return text, ()
        with observed_input(home, _bind_input(home, path, resolved, observations), observations) as stream:
            saved = stream.read().decode("utf-8")
        content = json.loads(saved) if resolved.suffix == ".json" else None
    except (OSError, RuntimeError, ValueError, SessionFailure):
        raise SessionFailure("unreadable_session", f"{record.where(home)}: the tool result could not be read.") from None
    # Claude can spill an array of native content blocks as JSON.
    if isinstance(content, list) and any(isinstance(part, dict) and "type" in part for part in content):
        _check_content(home, record, content, ("text", "image", *_ARCHIVE_BLOCKS))
        return _text(content), _result_images(home, record, content)
    return saved, ()


def _result_image(home: Path, record: Record, part: dict[str, Any]) -> Image:
    source = _object(part.get("source"))
    media_type = _string(source.get("media_type"))
    data = _string(source.get("data"))
    if source.get("type") != "base64" or not media_type or data is None:
        _bad_record(home, record)
    try:
        return Image(media_type, len(base64.b64decode(data, validate=True)))
    except (binascii.Error, ValueError):
        _bad_record(home, record)


def _result_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [_result_fields(part) for part in value]
    if isinstance(value, dict):
        kind = _string(value.get("type")) or ""
        omitted = ("data",) if kind == "base64" else ()
        if kind == "image" or kind.startswith("image/") or "media_type" in value or "mediaType" in value:
            omitted = (*omitted, "base64")
        return {key: _result_fields(part) for key, part in value.items() if key not in omitted}
    return value


def _result_blocks(record: Record) -> Iterator[dict[str, Any]]:
    if record.row.get("type") == "user":
        yield from (
            block for block in _blocks(_message(record).get("content")) if block.get("type") == "tool_result"
        )


def _result_texts(content: object) -> Iterator[str]:
    if isinstance(content, str):
        yield content
    else:
        yield from (part["text"] for part in _blocks(content) if part.get("type") == "text")


def _result_images(home: Path, record: Record, content: object) -> tuple[Image, ...]:
    return tuple(_result_image(home, record, part) for part in _blocks(content) if part.get("type") == "image")


def _native_results(home: Path, record: Record, observations: FileObservations) -> dict[str, NativeResult]:
    results = {}
    native_fields = _object(record.row.get("toolUseResult"))
    for block in _result_blocks(record):
        content = block.get("content", "")
        images = list(_result_images(home, record, content))
        if record.duplicate:
            continue
        texts = []
        for part in _result_texts(content):
            output_text, output_images = _spill_result(home, record, part, observations)
            texts.append(output_text)
            images.extend(output_images)
        extras = {
            key: value for key, value in block.items() if key not in ("type", "tool_use_id", "is_error", "content")
        }
        output = Result("\n".join(texts), _result_fields({**native_fields, **extras}) or None, tuple(images))
        results[block["tool_use_id"]] = NativeResult(output, not block.get("is_error", False))
    return results

def _results(rows: Iterable[Record]) -> dict[str, NativeResult]:
    results: dict[str, NativeResult] = {}
    for record in rows:
        results.update(record.results)
    return results


def _items(
    rows: Iterable[Record], results: dict[str, NativeResult], *,
    agent: str | None = None,
) -> Iterator[Item]:
    for record in rows:
        if record.duplicate or record.row.get("type") != "assistant":
            continue
        content = _message(record).get("content")
        if isinstance(content, str):
            if agent is None:
                yield TextBlock(content, _at(record))
            continue
        for block in _blocks(content):
            if block.get("type") == "text" and agent is None:
                yield TextBlock(block["text"], _at(record))
            if block.get("type") == "tool_use":
                native = results.get(block["id"])
                yield ToolCall(
                    call_id=block["id"],
                    agent=agent,
                    name=block["name"],
                    input=block["input"],
                    result=native.output if native is not None else None,
                    ok=native.ok if native is not None else False,
                    error=native.output.text if native is not None and not native.ok else None,
                    parent_call_id=None,
                    started_at=_at(record),
                )


def _responses(rows: Iterable[Record]) -> dict[tuple[int, int], Response]:
    responses = {}
    seen: set[str] = set()
    for record in rows:
        if record.duplicate or record.row.get("type") != "assistant":
            continue
        message = _message(record)
        identifier = _string(message.get("id"))
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        usage = _object(message.get("usage"))
        responses[record.position] = Response(
            _at(record),
            Usage.native(
                uncached=usage.get("input_tokens") or 0,
                cache_read=usage.get("cache_read_input_tokens") or 0,
                cache_write=usage.get("cache_creation_input_tokens"),
                output=usage.get("output_tokens") or 0,
            ),
        )
    return responses


def _children(home: Path, directory: Path) -> list[Path]:
    try:
        return sorted(directory.iterdir()) if _inside(home, directory) is not None else []
    except FileNotFoundError:
        return []
    except (OSError, RuntimeError, ValueError):
        raise _unreadable(home, directory) from None


def _present(home: Path, path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        raise _unreadable(home, path) from None
    return True


def _json_file(home: Path, path: Path, observations: FileObservations) -> Any:
    try:
        target = _data_file(home, path)
        with observed_input(home, _bind_input(home, path, target, observations), observations) as stream:
            return json.load(stream)
    except (OSError, ValueError, RecursionError):
        raise _unreadable(home, path) from None


def _agent_link(home: Path, path: Path, observations: FileObservations) -> str | None:
    meta = path.with_suffix(".meta.json")
    if not _present(home, meta):
        return None
    value = _json_file(home, meta, observations)
    if not isinstance(value, dict) or (
        value.get("toolUseId") is not None and not _string(value["toolUseId"])
    ):
        unknown_record(None, meta.relative_to(home).as_posix(), conversation=True)
    return _string(value.get("toolUseId"))


def _agent_files(home: Path, file: SessionFile) -> Iterator[tuple[Path, str | None]]:
    root = file.directory / "subagents"
    for path in _children(home, root):
        if path.name.startswith("agent-") and path.suffix == ".jsonl":
            yield path, None
    for workflow in _children(home, root / "workflows"):
        if workflow.name.startswith("wf_"):
            for path in _children(home, workflow):
                if path.name.startswith("agent-") and path.suffix == ".jsonl":
                    yield path, workflow.name


@dataclass
class AgentLog:
    native_id: str
    workflow_id: str | None
    launch_id: str | None
    rows: list[Record] = field(default_factory=list)

    @property
    def first_at(self) -> datetime | None:
        return next((row.at for row in self.rows if row.at is not None and not row.duplicate), None)


def _agent_logs(home: Path, files: Sequence[OrderedFile], observations: FileObservations) -> dict[str, AgentLog]:
    inputs = [
        (_order_file(home, SessionFile(path), observations), top.file, workflow)
        for top in files for path, workflow in _agent_files(home, top.file)
    ]
    inputs.sort(key=lambda entry: (entry[0].at, entry[0].file.path))
    logs: dict[str, AgentLog] = {}
    seen: dict[str, set[str]] = {}
    for rank, (ordered, owner, workflow) in enumerate(inputs):
        path = ordered.file.path
        native_id = path.stem.removeprefix("agent-")
        launch = _agent_link(home, path, observations)
        log = logs.setdefault(native_id, AgentLog(native_id, workflow, launch))
        if log.launch_id is None:
            log.launch_id = launch
        if log.workflow_id is None:
            log.workflow_id = workflow
        earlier = seen.setdefault(native_id, set())
        current: set[str] = set()
        try:
            for number, raw in _ordered_rows(home, ordered, observations):
                uuid = _string(raw.get("uuid")) if isinstance(raw, dict) else None
                row = _validated(home, owner, (rank, number), raw, uuid in earlier, observations, stream_path=path)
                if row is not None:
                    log.rows.append(row)
                    if uuid is not None:
                        current.add(uuid)
        except (OSError, RecursionError):
            raise _unreadable(home, path) from None
        earlier.update(current)
    return logs


@dataclass(frozen=True)
class Launch:
    call_id: str
    turn: int | None
    agent: str | None


_WORKFLOW_RUN = re.compile(r"^Run ID: (wf_[\w-]+)\s*$", re.MULTILINE)


def _launches(
    turns: Sequence[Turn], agent_items: dict[str, tuple[Item, ...]],
) -> tuple[dict[str, Launch], dict[str, Launch]]:
    calls: dict[str, Launch] = {}
    named: dict[str, Launch] = {}

    def add(items: Iterable[Item], turn: int | None, agent: str | None) -> None:
        for item in items:
            if not isinstance(item, ToolCall) or item.name not in ("Agent", "Task", "Workflow"):
                continue
            launch = Launch(item.call_id, turn, agent)
            calls.setdefault(launch.call_id, launch)
            if item.result is None:
                continue
            fields = item.result.fields or {}
            if item.name == "Workflow":
                run = _WORKFLOW_RUN.search(item.result.text)
                identifier = _string(fields.get("runId")) or _string(fields.get("workflowRunId"))
                if run is not None:
                    identifier = run[1]
            else:
                identifier = _string(fields.get("agentId"))
            if identifier is not None:
                named.setdefault(identifier, launch)

    for index, turn in enumerate(turns):
        add(turn.items, index, None)
    for agent_id, items in agent_items.items():
        add(items, None, agent_id)
    return calls, named


def _locate_turn(turns: Sequence[Turn], at: datetime | None) -> int | None:
    if at is None:
        return None
    return next((
        index for index in range(len(turns) - 1, -1, -1)
        if turns[index].started_at <= at <= turns[index].ended_at
    ), None)


def _placements(
    turns: Sequence[Turn], logs: dict[str, AgentLog], agent_items: dict[str, tuple[Item, ...]],
) -> Iterator[tuple[int, AgentLog, CallLink | None]]:
    calls, named = _launches(turns, agent_items)
    parents = {
        agent_id: calls.get(log.launch_id or "") or named.get(agent_id) or named.get(log.workflow_id or "")
        for agent_id, log in logs.items()
    }
    for agent_id, log in logs.items():
        root = agent_id
        link = parents[root]
        seen = {root}
        launch = link
        while launch is not None and launch.agent is not None and launch.agent not in seen:
            root = launch.agent
            seen.add(root)
            launch = parents[root]
        if launch is None:
            turn_index = _locate_turn(turns, logs[root].first_at)
        elif launch.agent is None:
            turn_index = launch.turn
        else:
            # A circular native link has no usable launch ancestry.
            link = None
            turn_index = _locate_turn(turns, log.first_at)
        if turn_index is not None and log.first_at is not None:
            yield turn_index, log, CallLink(link.agent, link.call_id) if link is not None else None


def _subagent(log: AgentLog, launch: CallLink | None) -> Subagent:
    first = log.first_at
    assert first is not None
    rows = [record for record in log.rows if not record.duplicate]
    last_turn = rows
    for group in _turn_records(rows):
        last_turn = group.rows
    ending = _ending(last_turn)
    usage = sum((response.usage for response in _responses(rows).values()), Usage())
    return Subagent(
        log.native_id, launch.call_id if launch else None, first, ending is not None and ending.state == "failed",
        usage, launch,
    )


def _project_turns(rows: Sequence[Record], agents: dict[str, AgentLog]) -> tuple[Turn, ...]:
    results = _results(rows)
    responses = _responses(rows)
    turns = [_turn(group, results, responses) for group in _turn_records(rows)]
    agent_items = {
        agent_id: tuple(_items(log.rows, _results(log.rows), agent=agent_id))
        for agent_id, log in agents.items()
    }
    nested: list[list[Item]] = [[] for _ in turns]
    subagents: list[list[Subagent]] = [[] for _ in turns]
    for index, log, launch in _placements(turns, agents, agent_items):
        subagents[index].append(_subagent(log, launch))
        nested[index].extend(
            replace(item, parent_call_id=launch.call_id if launch else None, parent=launch)
            for item in agent_items[log.native_id] if isinstance(item, ToolCall)
        )
    return tuple(
        replace(turn, items=(*turn.items, *nested[index]), subagents=tuple(subagents[index]))
        for index, turn in enumerate(turns)
    )


_EXCLUDED = frozenset({
    ".credentials.json", "credentials", "credentials.json", "oauth", "oauth.json", "auth",
    "auth.json", "mcp-auth.json", "server.token", "token", "tokens", "device_id", "device-id",
    "installation_id", "config", "configuration", "settings", "cache", "caches", "debug", "logs",
    "log", "memory", "search-index", "__pycache__", ".git", ".env",
})


def _archive_name(relative: Path) -> bool:
    for part in relative.parts:
        name = part.casefold()
        if (
            name in _EXCLUDED or name.startswith((".env.", "settings.", "config."))
            or name.endswith((".log", ".token", ".wal", ".index", ".postings"))
        ):
            return False
    return True


@dataclass
class ArchiveFiles:
    home: Path
    observations: FileObservations
    regular: dict[Path, HomeFile] = field(default_factory=dict)
    outside: set[Path] = field(default_factory=set)

    def resolve(self, path: Path) -> Path | None:
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError, ValueError):
            if path.is_relative_to(self.home):
                raise _unreadable(self.home, path) from None
            self.outside.add(path)
            return None
        if not resolved.is_relative_to(self.home):
            self.outside.add(resolved)
            return None
        if not path.is_relative_to(self.home):
            return None
        if _archive_name(path.relative_to(self.home)) and _archive_name(resolved.relative_to(self.home)):
            return resolved
        return None

    def include(self, path: Path, boundary: Path) -> None:
        resolved = self.resolve(path)
        if resolved is None or not resolved.is_relative_to(boundary):
            return
        try:
            if stat.S_ISREG(resolved.stat(follow_symlinks=False).st_mode):
                _bind_input(self.home, path, resolved, self.observations)
                self.regular[path] = self.observations.nominate(self.home, path, target=resolved)
            elif resolved in self.observations.files or path in self.observations.files:
                raise _unreadable(self.home, path)
        except FileNotFoundError:
            if resolved in self.observations.files or path in self.observations.files:
                raise _unreadable(self.home, path) from None
        except OSError:
            raise _unreadable(self.home, path) from None

    def session_tree(self, directory: Path) -> None:
        root = self.resolve(directory)
        if root is None or root != directory:
            return

        def walk_error(error: OSError) -> None:
            if not isinstance(error, FileNotFoundError):
                raise _unreadable(self.home, directory) from None

        for parent, folders, files in directory.walk(on_error=walk_error):
            folders[:] = [name for name in folders if _archive_name(Path(name))]
            for name in files:
                self.include(parent / name, directory)


def _backup_names(record: Record) -> Iterator[str]:
    kind = record.row.get("type")
    if kind == "file-history-snapshot":
        snapshot = _object(record.row.get("snapshot"))
        backups = _object(snapshot.get("trackedFileBackups"))
        for backup in backups.values():
            if name := _string(_object(backup).get("backupFileName")):
                yield name
    elif kind == "file-history-delta":
        if name := _string(_object(record.row.get("backup")).get("backupFileName")):
            yield name


def _history_path(home: Path, record: Record, name: str) -> Path:
    path = Path(name)
    if path.is_absolute():
        return path
    if path.parts[0] == "file-history":
        return home / path
    native_id = _string(record.row.get("sessionId"))
    if not native_id or Path(native_id).name != native_id or native_id in (".", ".."):
        native_id = record.file.native_id
    return home / "file-history" / native_id / path


def _archive_refs(archive: ArchiveFiles, rows: Iterable[Record]) -> None:
    for record in rows:
        for name in _backup_names(record):
            if "\x00" not in name and Path(name).parts:
                archive.include(_history_path(archive.home, record, name), archive.home / "file-history")
        for block in _result_blocks(record):
            for text in _result_texts(block.get("content", "")):
                path = _spill_path(record, text)
                if path is not None:
                    archive.include(path, record.file.directory / "tool-results")


def _archive(
    home: Path, clock: datetime, session: SessionRecords, agents: dict[str, AgentLog], observations: FileObservations,
) -> tuple[tuple[HomeFile, ...], bool, int]:
    archive = ArchiveFiles(home, observations)
    for top in session.files:
        archive.include(top.file.path, top.file.path.parent)
        archive.session_tree(top.file.directory)
    _archive_refs(archive, session.rows)
    for agent in agents.values():
        _archive_refs(archive, agent.rows)
    files = tuple(archive.regular[path] for path in sorted(archive.regular))
    live = any(file.observation is not None and file.observation.modified_at >= clock - LIVE_WINDOW for file in files)
    return files, live, len(archive.outside)


def _last_title(rows: Sequence[Record], record_type: str, field_name: str) -> str | None:
    for record in reversed(rows):
        if record.row.get("type") == record_type:
            title = _string(record.row.get(field_name))
            if title is not None:
                return title
    return None


def _title(home: Path, session: SessionRecords, observations: FileObservations) -> str | None:
    title = _last_title(session.rows, "custom-title", "customTitle")
    if title is not None:
        return title
    for top in reversed(session.files):
        path = top.file.directory / "custom-title.json"
        if not _present(home, path):
            continue
        value = _json_file(home, path, observations)
        title = _string(value) if isinstance(value, str) else _string(_object(value).get("customTitle"))
        if title is None:
            unknown_record("custom-title", path.relative_to(home).as_posix(), conversation=True)
        return title
    return _last_title(session.rows, "ai-title", "aiTitle")


def _session(
    home: Path, source: Source, native_id: str, kind: Kind, session: SessionRecords, observations: FileObservations,
) -> Session:
    rows = session.rows
    title = _title(home, session, observations)
    agents = _agent_logs(home, session.files, observations)
    files, live, outside = _archive(home, source.clock, session, agents, observations)
    first_prompt = next((row for row in rows if _user_prompt(row) is not None), None)
    created_at = session.created_at
    if created_at is None:
        created_at = min(top.mtime for top in session.files if top.mtime is not None)
    origin = {
        name: value for name in ("entrypoint", "permissionMode", "turnOrigin")
        if (value := _first_field(rows, name)) is not None
    }
    if rows:
        origin["folder"] = rows[0].file.path.parent.name
    return Session(
        tool="claude-code",
        native_id=native_id,
        kind=kind,
        title=title,
        created_at=created_at,
        tool_version=_string(first_prompt.row.get("version")) if first_prompt is not None else None,
        origin=origin,
        working_folder=_string(first_prompt.row.get("cwd")) if first_prompt is not None else None,
        live=live,
        turns=_project_turns(rows, agents),
        archive_files=files,
        files_not_archived=outside,
    )


def read(source: Source) -> Iterator[Session | Failed]:
    """Yield one Claude Code reader result per selected native session."""
    try:
        home = source.home.resolve()
    except (OSError, RuntimeError, ValueError):
        yield Failed.of(SessionFailure("unreadable_session", "projects: could not be read."), file="projects")
        return

    driver_ids = _driver_ids(source.driver_state)
    observations = FileObservations()
    for discovered in _ordered_sessions(home, source, observations):
        if isinstance(discovered, Failed):
            yield discovered
            continue
        native_id, session = discovered
        kind = _kind(native_id, driver_ids, session.rows)
        try:
            # The scanner stopped before the offending row. A later sidecar
            # failure retains the prefix already accepted from the main logs.
            if session.failure is not None:
                raise session.failure
            yield _session(home, source, native_id, kind, session, observations)
        except SessionFailure as error:
            yield Failed.of(error, native_id=native_id, kind=kind)
