"""The reader form (IMP-1, "What every reader gives IMP-0"): what every tool's reader yields to the importer.

A reader yields one `Session` per top-level session, with its turns, their items and sub-agents, and its archive files,
or one `Failed` in place of a session it cannot read. The records are frozen. Attributes are snake_case; the
specification's camelCase names appear only in docstrings and in what the importer serialises. Nothing here names a
path as a session's identity (IMP-1.11).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol

Tool = Literal["claude-code", "codex", "kimi-code", "pi", "mimo"]
TOOLS: tuple[Tool, ...] = ("claude-code", "codex", "kimi-code", "pi", "mimo")

# A top-level session's kind by its tool's kind table (IMP-1.3, IMP-D6).
Kind = Literal["owner", "agent_launched", "scheduled", "arbol_driver", "probe"]
KINDS: tuple[Kind, ...] = ("owner", "agent_launched", "scheduled", "arbol_driver", "probe")

# What started a turn, as a reader gives it. `steered` is IMP-0's, which the importer gives to the segments it splits
# at a steer, so no reader yields it.
Trigger = Literal["typed", "task", "scheduled", "system"]
TRIGGERS: tuple[Trigger, ...] = ("typed", "task", "scheduled", "system")

State = Literal["completed", "failed", "cancelled", "interrupted"]
STATES: tuple[State, ...] = ("completed", "failed", "cancelled", "interrupted")

# The failures of one session a reader reports (IMP-D13). `rows_refused` is the importer's.
FailureCode = Literal["unreadable_session", "unknown_format"]
FAILURE_CODES: tuple[FailureCode, ...] = ("unreadable_session", "unknown_format")


@dataclass(frozen=True)
class Usage:
    """Token usage by the common rule (IMP-1): `inputTokens` is input + cache read + cache write, beside
    `cachedInputTokens` (cache read) and `outputTokens`. Cache writes and reasoning are optional native counters.
    Build one from the tool's counts with `native()`; adding two sums them."""

    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int | None = None
    output_tokens: int = 0
    reasoning_tokens: int | None = None

    @classmethod
    def native(cls, *, uncached: int, cache_read: int = 0, cache_write: int | None = None, output: int = 0,
               reasoning: int | None = None) -> Usage:
        """From a tool's own counts, where `uncached` is the input it counts apart from cache reads and writes."""
        return cls(uncached + cache_read + (cache_write or 0), cache_read, cache_write, output, reasoning)

    def __add__(self, other: Usage) -> Usage:
        if not isinstance(other, Usage):
            return NotImplemented
        return Usage(
            self.input_tokens + other.input_tokens,
            self.cached_input_tokens + other.cached_input_tokens,
            _sum_counter(self.cache_write_tokens, other.cache_write_tokens),
            self.output_tokens + other.output_tokens,
            _sum_counter(self.reasoning_tokens, other.reasoning_tokens),
        )


def _sum_counter(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    return left + (right or 0)


@dataclass(frozen=True)
class Response:
    """One model response of the main agent: its `startedAt` and its usage, so that IMP-0 can assign it to the segment
    it falls in (IMP-D12)."""

    started_at: datetime
    usage: Usage


@dataclass(frozen=True)
class Image:
    """An image part of a tool result, described and never stored (IMP-0.10)."""

    media_type: str
    size: int


@dataclass(frozen=True)
class Result:
    """A tool call's result: its output text, the structured fields the native result carries, and its images."""

    text: str
    fields: Mapping[str, Any] | None = None
    images: tuple[Image, ...] = ()


@dataclass(frozen=True)
class TextBlock:
    """Text the main agent wrote, with the time it was written (IMP-D12)."""

    text: str
    at: datetime


@dataclass(frozen=True)
class CallLink:
    """Identity of a proven parent call. An agent of None identifies the main lane."""

    agent: str | None
    call_id: str


@dataclass(frozen=True)
class ToolCall:
    """A tool call: `callId`, `agent` (the sub-agent that made it, or None for the main agent), `name`, `input`,
    `result` (None when the session holds no result), `ok`, `error`, `parentCallId`, `startedAt`, and the `truncated`
    flag Pi sets on a result it cut."""

    call_id: str
    agent: str | None
    name: str
    input: Any
    result: Result | None
    ok: bool
    error: str | None
    parent_call_id: str | None
    started_at: datetime
    truncated: bool = False
    parent: CallLink | None = None


type Item = TextBlock | ToolCall


@dataclass(frozen=True)
class Subagent:
    """A sub-agent that worked in a turn: its native agent ID, the `callId` of the call that started it or None when that
    call cannot be found, the time of its first record, whether its last turn failed, and its usage, which the turn's
    `usage` leaves out and IMP-0 adds to the run (IMP-D12)."""

    agent_id: str
    call_id: str | None
    first_record_at: datetime
    last_turn_failed: bool
    usage: Usage
    launch: CallLink | None = None


@dataclass(frozen=True)
class Steer:
    """Input the owner added during a turn, and when; IMP-0 splits the turn at it."""

    text: str
    at: datetime


@dataclass(frozen=True)
class Turn:
    """One turn in native order: `turnKey`, `trigger`, `prompt`, `startedAt`, `endedAt` (the end record's time, else the
    time of the turn's last record), `state`, and for a failed turn the tool's error text and kind; `workingFolder`,
    `model` and `effort`; `usage`, the main agent's responses in order; `items` in native order; `subagents`; and
    `steers`."""

    turn_key: str
    trigger: Trigger
    prompt: str
    started_at: datetime
    ended_at: datetime
    state: State
    error: str | None
    error_kind: str | None
    working_folder: str | None
    model: str | None
    effort: str | None
    usage: tuple[Response, ...] = ()
    items: tuple[Item, ...] = ()
    subagents: tuple[Subagent, ...] = ()
    steers: tuple[Steer, ...] = ()

    def __post_init__(self) -> None:
        if self.state != "failed" and (self.error is not None or self.error_kind is not None):
            raise ValueError("Only a failed turn carries an error.")


def _relative(path: str) -> str:
    parts = PurePosixPath(path).parts
    if not path or path.startswith("/") or ".." in parts:
        raise ValueError("An archive file's path is relative to the tool's home and stays inside it.")
    return path


@dataclass(frozen=True)
class HomeFile:
    """A file in the tool's home with its manifest and optional verified read paths."""

    path: str
    read_path: str | None = None

    def __post_init__(self) -> None:
        _relative(self.path)
        if self.read_path is not None:
            _relative(self.read_path)


@dataclass(frozen=True)
class ExportedRows:
    """A session's rows of a tool's database, exported as JSON bytes under a path such as
    `state_5.sqlite#<thread id>.json`, with the database file's modification time as their `mtime` (IMP-D12)."""

    path: str
    content: bytes
    mtime: datetime

    def __post_init__(self) -> None:
        _relative(self.path)


type ArchiveFile = HomeFile | ExportedRows


@dataclass(frozen=True, eq=False)
class Session:
    """One top-level session: `tool`, `nativeId`, `kind`, `title`, `createdAt`, `toolVersion`, `origin` (the facts IMP-1
    names for the tool, a JSON object), its working folder for IMP-0's fallback, `live`, its turns in native order, its
    archive files, and `filesNotArchived`, the count of files it names outside the tool's home.

    A session is identified by `(tool, nativeId)` alone; no path takes part (IMP-1.11). The database checks the lengths
    of native IDs and turn keys, and refuses a violation as `rows_refused` (IMP-0)."""

    tool: Tool
    native_id: str
    kind: Kind
    title: str | None
    created_at: datetime
    tool_version: str | None
    origin: Mapping[str, Any]
    working_folder: str | None
    live: bool
    turns: tuple[Turn, ...] = ()
    archive_files: tuple[ArchiveFile, ...] = ()
    files_not_archived: int = 0

    @property
    def identity(self) -> tuple[Tool, str]:
        return (self.tool, self.native_id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Session) and self.identity == other.identity

    def __hash__(self) -> int:
        return hash(self.identity)


LIVE_WINDOW = timedelta(minutes=10)


def live_by_mtime(paths: Iterable[Path], clock: datetime) -> bool:
    """IMP-0's liveness by modification time: whether any of the session's files changed within 10 minutes of the run's
    clock, an aware time. A file gone since the reader named it has just changed. Kimi Code adds its session lock and
    Mimo uses `time_updated` instead, each in its own reader."""
    since = clock - LIVE_WINDOW
    for path in paths:
        try:
            changed = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        except FileNotFoundError:
            return True
        if changed >= since:
            return True
    return False


class SessionFailure(Exception):
    """One session cannot be read (IMP-D13). The message is built only from a line number, a record type or a file path
    within the tool's home, and never quotes session content (IMP-0.21)."""

    def __init__(self, code: FailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Failed:
    """What a reader yields in place of a session it cannot read: the session's native ID, or the name of its file when
    it failed before the ID was known, with no kind, and the failure's code and message (IMP-D13).

    A session that fails after its native ID is known carries the kind its tool's table gives for the records read
    before the failure (IMP-D16). The kind is optional only so that existing constructions keep working: a reader gives
    it whenever the native ID is known."""

    native_id: str | None
    file: str | None
    code: FailureCode
    message: str
    kind: Kind | None = None

    def __post_init__(self) -> None:
        if (self.native_id is None) == (self.file is None):
            raise ValueError("A failed session is named by its native ID or, before that is known, by its file.")
        if self.kind is not None and self.native_id is None:
            raise ValueError("A failed session named by its file has no kind.")

    @classmethod
    def of(cls, failure: SessionFailure, *, native_id: str | None = None, file: str | None = None,
           kind: Kind | None = None) -> Failed:
        return cls(native_id, file, failure.code, failure.message, kind)


RECORD_TYPE = re.compile(r"[A-Za-z0-9_.:/-]{1,64}")


def unknown_record(record_type: object, where: str, *, conversation: bool) -> None:
    """IMP-D10, for a parsed record a reader does not recognise. A record that is not a conversation record (a turn
    bound, message, loop event, response item or part, by the reader's tool) is skipped; a conversation record of
    unknown shape fails the session with `unknown_format`. `where` is the file within the tool's home and the line."""
    if not conversation:
        return
    named = f"a {record_type} record" if isinstance(record_type, str) and RECORD_TYPE.fullmatch(record_type) \
        else "a record"
    raise SessionFailure("unknown_format", f"{where}: {named} has an unknown shape.")


@dataclass(frozen=True)
class Source:
    """What a reader reads: the tool's home, the Driver's state folder or None, the private work folder for Mimo's
    database copy or None, the run's clock (an aware time), and the native IDs selected, or None for all."""

    home: Path
    driver_state: Path | None
    work: Path | None
    clock: datetime
    selected: frozenset[str] | None = None

    def wants(self, native_id: str) -> bool:
        return self.selected is None or native_id in self.selected


class Reader(Protocol):
    """A tool's reader module, `arbol_import.readers.<tool code name with - as _>`. `read()` yields one `Session` or
    `Failed` per top-level session; a failed session never stops the others. A reader only reads."""

    def read(self, source: Source) -> Iterator[Session | Failed]: ...


def reader_module(tool: Tool) -> str:
    """The name of a tool's reader module, which the command imports by name."""
    return f"{__package__}.{tool.replace('-', '_')}"
