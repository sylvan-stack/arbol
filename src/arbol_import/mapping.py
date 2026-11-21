"""Project a saved harness session into the importer's database rows (IMP-0)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from .readers.form import Kind, Session, State, Tool, Trigger

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]
type JsonObject = dict[str, Json]
type ExchangeTrigger = Trigger | Literal["steered"]


@dataclass(frozen=True)
class MessageRow:
    position: int
    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True)
class ToolCallRow:
    position: int
    call_id: str
    parent_call_id: str | None
    name: str
    input: Json
    result: JsonObject | None
    ok: bool
    error: str | None
    truncated: bool = False
    interrupted: bool = False


@dataclass(frozen=True)
class MappedSegment:
    turn_key: str
    trigger: ExchangeTrigger
    accepted_at: datetime
    ended_at: datetime
    state: State
    working_folder: str
    messages: tuple[MessageRow, ...]
    calls: tuple[ToolCallRow, ...] = ()


@dataclass(frozen=True)
class MappedSession:
    tool: Tool
    native_id: str
    kind: Kind
    title: str | None
    created_at: datetime
    origin: Mapping[str, object]
    segments: tuple[MappedSegment, ...]


def stored_text(value: str) -> str:
    return value.replace("\0", "\ufffd").encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def map_session(session: Session, owner_home: Path) -> MappedSession:
    """Keep native identity and row order independent of allocation and persistence."""
    title = stored_text(session.title or "").strip()[:240] or None
    segments = tuple(
        MappedSegment(
            turn.turn_key, turn.trigger, turn.started_at, turn.ended_at, turn.state,
            stored_text(turn.working_folder or session.working_folder or str(owner_home)),
            (MessageRow(0, "user", stored_text(turn.prompt)),),
        )
        for turn in session.turns
    )
    return MappedSession(session.tool, session.native_id, session.kind, title, session.created_at, session.origin, segments)
