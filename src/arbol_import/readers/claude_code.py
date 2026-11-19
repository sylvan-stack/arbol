"""Read saved Claude Code sessions and their archive files (IMP-1)."""

from __future__ import annotations

import base64
import binascii
import json
import re
import stat
from collections.abc import Generator, Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from .form import (
    Failed,
    Image,
    Item,
    Kind,
    Response,
    Result,
    SessionFailure,
    Source,
    State,
    Steer,
    TextBlock,
    ToolCall,
    Trigger,
    Turn,
    Usage,
    unknown_record,
)
from .lines import file_records


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
            if _inside(home, folder) is None or not stat.S_ISDIR(folder.stat().st_mode):
                continue
            paths = sorted(folder.iterdir())
        except (OSError, RuntimeError):
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


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


@dataclass(frozen=True)
class OrderedFile:
    file: SessionFile
    at: datetime
    mtime: datetime | None
    lookahead_failure: SessionFailure | None = None
    failure_line: int = 1


def _read_records(home: Path, path: Path) -> Generator[tuple[int, Any]]:
    resolved = _regular(home, path)
    yield from file_records(home, resolved.relative_to(home).as_posix())


def _record_time(row: dict[str, Any]) -> datetime | None:
    at = _time(row.get("timestamp"))
    if at is None and row.get("type") == "file-history-snapshot":
        snapshot = row.get("snapshot")
        if isinstance(snapshot, dict):
            return _time(snapshot.get("timestamp"))
    return at


def _order_file(home: Path, file: SessionFile) -> OrderedFile:
    modified = None
    number = 0
    try:
        modified = _mtime(_regular(home, file.path))
        stream = _read_records(home, file.path)
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


def _ordered_sessions(home: Path, source: Source) -> Iterator[Failed | tuple[str, SessionRecords]]:
    files = []
    for file in _discover(home):
        if isinstance(file, Failed):
            yield file
        else:
            files.append(_order_file(home, file))
    files.sort(key=lambda ordered: (ordered.at, ordered.file.path))

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
                for number, raw in _read_records(home, file.path):
                    if ordered.lookahead_failure is not None and number >= ordered.failure_line:
                        raise ordered.lookahead_failure
                    uuid = raw.get("uuid") if isinstance(raw, dict) else None
                    duplicate = isinstance(uuid, str) and (uuid in project_uuids or uuid in session_uuids)
                    row = _validated(home, file, (rank, number), raw, duplicate)
                    if row is None:
                        continue
                    if isinstance(uuid, str):
                        seen_here.add(uuid)
                    if source.wants(native_id):
                        session.rows.append(row)
                if ordered.lookahead_failure is not None:
                    raise ordered.lookahead_failure
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
    "file-history-snapshot",
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
    *, stream_path: Path | None = None,
) -> Record | None:
    row = _object(raw)
    kind = row.get("type")
    record = Record(file, position, row, _record_time(row), duplicate, stream_path)
    if kind in _MESSAGE_TYPES:
        _validate_message(home, record)
        if kind == "user":
            results = _native_results(home, record)
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


_SPILLED = re.compile(r"\A<persisted-output>\s*[^\n]*?Full output saved to:[ \t]*([^\r\n]+)")


def _spill_path(record: Record, text: str) -> Path | None:
    match = _SPILLED.match(text)
    if match is None:
        return None
    path = Path(match[1].strip())
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "tool-results":
        return record.file.directory / path
    return record.file.directory / "tool-results" / path


def _spill_text(home: Path, record: Record, text: str) -> str:
    path = _spill_path(record, text)
    if path is None:
        return text
    folder = record.file.directory / "tool-results"
    try:
        resolved = _inside(home, path)
        if resolved is None or not resolved.is_relative_to(folder):
            return text
        return _regular(home, resolved).read_text(encoding="utf-8")
    except (OSError, RuntimeError, ValueError, SessionFailure):
        raise SessionFailure("unreadable_session", f"{record.where(home)}: the tool result could not be read.") from None


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
        return {
            key: _result_fields(part) for key, part in value.items()
            if key != "base64" and not (key == "data" and value.get("type") == "base64")
        }
    return value


def _native_results(home: Path, record: Record) -> dict[str, NativeResult]:
    results = {}
    native_fields = _object(record.row.get("toolUseResult"))
    for block in _blocks(_message(record).get("content")):
        if block.get("type") != "tool_result":
            continue
        content = block.get("content", "")
        call_id = block["tool_use_id"]
        images = tuple(
            _result_image(home, record, part) for part in _blocks(content) if part.get("type") == "image"
        )
        if record.duplicate:
            continue
        parts = [content] if isinstance(content, str) else [
            part["text"] for part in _blocks(content) if part.get("type") == "text"
        ]
        text = "\n".join(_spill_text(home, record, part) for part in parts)
        extras = {
            key: value for key, value in block.items() if key not in ("type", "tool_use_id", "is_error", "content")
        }
        output = Result(text, _result_fields({**native_fields, **extras}) or None, images)
        results[call_id] = NativeResult(output, not block.get("is_error", False))
    return results


def _results(rows: Iterable[Record]) -> dict[str, NativeResult]:
    results: dict[str, NativeResult] = {}
    for record in rows:
        results.update(record.results)
    return results


def _items(
    rows: Iterable[Record], results: dict[str, NativeResult], *,
    agent: str | None = None, parent_call: str | None = None,
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
                    parent_call_id=parent_call,
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
                cache_write=usage.get("cache_creation_input_tokens") or 0,
                output=usage.get("output_tokens") or 0,
            ),
        )
    return responses
