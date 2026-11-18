"""The reader form (IMP-1, "What every reader gives IMP-0"): what every tool's reader yields to the importer.

A reader yields one `Session` per top-level session, with its turns, their items and sub-agents, and its archive files,
or one `Failed` in place of a session it cannot read. The records are frozen. Attributes are snake_case; the
specification's camelCase names appear only in docstrings and in what the importer serialises. Nothing here names a
path as a session's identity (IMP-1.11).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal

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
    `cachedInputTokens` (cache read) and `cacheWriteTokens`; `outputTokens`; and `reasoningTokens` only where the tool
    records it. Build one from the tool's counts with `native()`; adding two sums them."""

    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int | None = None

    @classmethod
    def native(cls, *, uncached: int, cache_read: int = 0, cache_write: int = 0, output: int = 0,
               reasoning: int | None = None) -> Usage:
        """From a tool's own counts, where `uncached` is the input it counts apart from cache reads and writes."""
        return cls(uncached + cache_read + cache_write, cache_read, cache_write, output, reasoning)

    def __add__(self, other: Usage) -> Usage:
        if not isinstance(other, Usage):
            return NotImplemented
        reasoning = (None if self.reasoning_tokens is None and other.reasoning_tokens is None
                     else (self.reasoning_tokens or 0) + (other.reasoning_tokens or 0))
        return Usage(self.input_tokens + other.input_tokens,
                     self.cached_input_tokens + other.cached_input_tokens,
                     self.cache_write_tokens + other.cache_write_tokens,
                     self.output_tokens + other.output_tokens,
                     reasoning)


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
    """A file in the tool's home, by its path relative to the home."""

    path: str

    def __post_init__(self) -> None:
        _relative(self.path)


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
