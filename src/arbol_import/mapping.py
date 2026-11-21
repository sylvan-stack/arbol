"""Project a saved harness session into the importer's database rows (IMP-0)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
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
    origin: JsonObject
    segments: tuple[MappedSegment, ...]


class MappingError(ValueError):
    """A content-free per-session mapping refusal."""


def stored_text(value: str) -> str:
    return value.replace("\0", "\ufffd").encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def _stored_object[Key](value: Mapping[Key, object]) -> JsonObject:
    result: JsonObject = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise MappingError("A saved object has a non-text key.")
        result[stored_text(key)] = _stored_json(item)
    return result


def _stored_json(value: object) -> Json:
    if isinstance(value, str):
        return stored_text(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    if isinstance(value, Mapping):
        return _stored_object(value)
    if isinstance(value, (list, tuple)):
        return [_stored_json(item) for item in value]
    raise MappingError("A saved value could not be stored as JSON.")


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
    try:
        origin = _stored_object(session.origin)
    except RecursionError:
        raise MappingError("A saved object is nested too deeply.") from None
    return MappedSession(session.tool, session.native_id, session.kind, title, session.created_at, origin, segments)
