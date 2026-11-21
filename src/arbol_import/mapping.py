"""Project a saved harness session into the importer's database rows (IMP-0)."""

from bisect import bisect_right
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Literal

from .readers.form import Item, Kind, Session, State, TextBlock, Tool, Trigger, Turn, Usage

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
    usage: Usage
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


@dataclass
class _Segment:
    turn_key: str
    trigger: ExchangeTrigger
    prompt: str
    accepted_at: datetime
    ended_at: datetime
    state: State
    items: list[Item] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


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


def segment_keys(turn: Turn) -> tuple[str, ...]:
    """Return the native keys even when the caller withholds this turn's rows."""
    return (turn.turn_key, *(f"{turn.turn_key}#{index}" for index in range(1, len(turn.steers) + 1)))


def _item_time(item: Item) -> datetime:
    return item.at if isinstance(item, TextBlock) else item.started_at


def _split_turn(turn: Turn) -> list[_Segment]:
    steers = sorted(turn.steers, key=lambda steer: steer.at)
    boundaries = [steer.at for steer in steers]
    end_times = [*boundaries, turn.ended_at]
    keys = segment_keys(turn)
    segments = [_Segment(keys[0], turn.trigger, turn.prompt, turn.started_at, end_times[0], turn.state)]
    for index, steer in enumerate(steers, start=1):
        segments[-1].state = "completed"
        segments.append(_Segment(keys[index], "steered", steer.text, steer.at, end_times[index], turn.state))
    for item in turn.items:
        segments[bisect_right(boundaries, _item_time(item))].items.append(item)
    for response in turn.usage:
        segments[bisect_right(boundaries, response.started_at)].usage += response.usage
    return segments


def _map_turn(turn: Turn, working_folder: str) -> Iterator[MappedSegment]:
    for segment in _split_turn(turn):
        messages = [MessageRow(0, "user", stored_text(segment.prompt))]
        for item in segment.items:
            if isinstance(item, TextBlock):
                messages.append(MessageRow(len(messages), "assistant", stored_text(item.text)))
        yield MappedSegment(
            segment.turn_key, segment.trigger, segment.accepted_at, segment.ended_at,
            segment.state, working_folder, segment.usage, tuple(messages),
        )


def map_session(session: Session, owner_home: Path) -> MappedSession:
    """Keep native identity and row order independent of allocation and persistence."""
    title = stored_text(session.title or "").strip()[:240] or None
    fallback_folder = session.working_folder or str(owner_home)
    try:
        origin = _stored_object(session.origin)
        segments = tuple(
            segment for turn in session.turns
            for segment in _map_turn(turn, stored_text(turn.working_folder or fallback_folder))
        )
    except RecursionError:
        raise MappingError("A saved object is nested too deeply.") from None
    return MappedSession(session.tool, session.native_id, session.kind, title, session.created_at, origin, segments)
