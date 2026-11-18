"""The reader form (IMP-1, "What every reader gives IMP-0"): what every tool's reader yields to the importer.

A reader yields one `Session` per top-level session, with its turns, their items and sub-agents, and its archive files,
or one `Failed` in place of a session it cannot read. The records are frozen. Attributes are snake_case; the
specification's camelCase names appear only in docstrings and in what the importer serialises. Nothing here names a
path as a session's identity (IMP-1.11).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

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
