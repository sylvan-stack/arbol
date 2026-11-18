"""The reader form (IMP-1, "What every reader gives IMP-0"): what every tool's reader yields to the importer.

A reader yields one `Session` per top-level session, with its turns, their items and sub-agents, and its archive files,
or one `Failed` in place of a session it cannot read. The records are frozen. Attributes are snake_case; the
specification's camelCase names appear only in docstrings and in what the importer serialises. Nothing here names a
path as a session's identity (IMP-1.11).
"""

from __future__ import annotations

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
