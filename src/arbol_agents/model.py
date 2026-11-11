"""The typed form of an agent record (AGR-0)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected a JSON object.")
    return dict(value)


def text_value(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Expected text in {key}.")
    return value


def optional_text(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Expected text in {key}.")
    return value


@dataclass(frozen=True)
class Owner:
    pid: int
    startedAt: str

    @classmethod
    def parse(cls, value: object) -> Owner:
        data = object_value(value)
        pid = data.get("pid")
        if type(pid) is not int or pid <= 0:
            raise ValueError("Expected a positive process identifier.")
        return cls(pid, text_value(data, "startedAt"))

    def json(self) -> dict[str, object]:
        return {"pid": self.pid, "startedAt": self.startedAt}


@dataclass(frozen=True)
class LastEvent:
    name: str
    at: str

    @classmethod
    def parse(cls, value: object) -> LastEvent:
        data = object_value(value)
        return cls(text_value(data, "name"), text_value(data, "at"))

    def json(self) -> dict[str, object]:
        return {"name": self.name, "at": self.at}


@dataclass(frozen=True)
class End:
    at: str
    reason: str

    @classmethod
    def parse(cls, value: object) -> End:
        data = object_value(value)
        return cls(text_value(data, "at"), text_value(data, "reason"))

    def json(self) -> dict[str, object]:
        return {"at": self.at, "reason": self.reason}


@dataclass
class Call:
    id: str
    name: str
    asks: bool = False

    @classmethod
    def parse(cls, value: object) -> Call:
        data = object_value(value)
        asks = data.get("asks")
        if type(asks) is not bool:
            raise ValueError("Expected a boolean asks mark.")
        return cls(text_value(data, "id"), text_value(data, "name"), asks)

    def json(self) -> dict[str, object]:
        return {"id": self.id, "name": self.name, "asks": self.asks}


@dataclass
class AgentRecord:
    tool: str
    session: str
    owner: Owner
    startedAt: str
    waitingFor: str
    since: str
    lastEvent: LastEvent
    workingFolder: str = ""
    entrypoint: str | None = None
    transcript: str | None = None
    model: str | None = None
    toolName: str | None = None
    background: int | None = None
    end: End | None = None
    calls: list[Call] = field(default_factory=list)

    @classmethod
    def fresh(cls, tool: str, session: str, owner: Owner, entrypoint: str | None, at: str) -> AgentRecord:
        return cls(tool=tool, session=session, owner=owner, startedAt=at, waitingFor="message", since=at,
                   lastEvent=LastEvent("", at), entrypoint=entrypoint)

    @classmethod
    def parse(cls, value: object) -> AgentRecord:
        data = object_value(value)
        if type(data.get("agentRecord")) is not int or data.get("agentRecord") != 1:
            raise ValueError("Unknown agent-record format.")
        calls_value = data.get("calls")
        if not isinstance(calls_value, list):
            raise ValueError("Expected a list of open calls.")
        background = data.get("background")
        if background is not None and (type(background) is not int or background < 0):
            raise ValueError("Expected a nonnegative background count.")
        end_value = data.get("end")
        return cls(
            tool=text_value(data, "tool"),
            session=text_value(data, "session"),
            owner=Owner.parse(data.get("owner")),
            startedAt=text_value(data, "startedAt"),
            waitingFor=text_value(data, "waitingFor"),
            since=text_value(data, "since"),
            lastEvent=LastEvent.parse(data.get("lastEvent")),
            workingFolder=text_value(data, "workingFolder"),
            entrypoint=optional_text(data, "entrypoint"),
            transcript=optional_text(data, "transcript"),
            model=optional_text(data, "model"),
            toolName=optional_text(data, "toolName"),
            background=background,
            end=End.parse(end_value) if end_value is not None else None,
            calls=[Call.parse(call) for call in calls_value],
        )

    def json(self) -> dict[str, object]:
        result: dict[str, object] = {
            "agentRecord": 1,
            "tool": self.tool,
            "session": self.session,
            "owner": self.owner.json(),
            "workingFolder": self.workingFolder,
            "startedAt": self.startedAt,
            "waitingFor": self.waitingFor,
            "since": self.since,
            "lastEvent": self.lastEvent.json(),
            "calls": [call.json() for call in self.calls],
        }
        for key, value in (
            ("entrypoint", self.entrypoint),
            ("transcript", self.transcript),
            ("model", self.model),
            ("toolName", self.toolName),
            ("background", self.background),
        ):
            if value is not None:
                result[key] = value
        if self.end is not None:
            result["end"] = self.end.json()
        return result
