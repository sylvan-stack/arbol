"""Settings snapshots and whole-file changes for the hook installer."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .model import object_value


class SettingsError(ValueError):
    """The user's settings could not be read or safely updated."""


def write_complete(path: Path, contents: bytes, mode: int, *, first_only: bool = False) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        if first_only:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise SettingsError(f"Backup is not a regular file: {path}") from None
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class SettingsFile:
    path: Path
    contents: bytes | None
    mode: int = 0o600

    @classmethod
    def read(cls, path: Path) -> SettingsFile:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                mode = os.fstat(stream.fileno()).st_mode
                if not stat.S_ISREG(mode):
                    raise SettingsError(f"Settings are not a regular file: {path}")
                return cls(path, stream.read(), stat.S_IMODE(mode))
        except FileNotFoundError:
            return cls(path, None)
        except OSError:
            raise SettingsError(f"Could not read settings: {path}") from None

    def verify_current(self) -> None:
        if self != self.read(self.path):
            raise SettingsError(f"Settings changed while editing: {self.path}")

    def backup(self) -> None:
        self.verify_current()
        backup = self.path.with_name(f"{self.path.name}.before-arbol-agents")
        absent = backup.with_name(f"{backup.name}.absent")
        if self.read(backup).contents is not None or self.read(absent).contents is not None:
            return
        if self.contents is None:
            write_complete(absent, b"", 0o600, first_only=True)
        else:
            write_complete(backup, self.contents, 0o600, first_only=True)

    def save(self, contents: bytes) -> None:
        if contents != self.contents:
            self.backup()
            self.verify_current()
            write_complete(self.path, contents, self.mode)

    def restore(self, contents_written: bytes) -> None:
        if self.read(self.path).contents != contents_written:
            raise SettingsError(f"Settings changed before rollback: {self.path}")
        if self.contents is None:
            self.path.unlink()
        else:
            write_complete(self.path, self.contents, self.mode)


@dataclass(frozen=True)
class HookEdit:
    contents: bytes | None
    count: int


def json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON key.")
    return result


def reject_constant(_: str) -> object:
    raise ValueError("Non-JSON number.")


def timeout_for(tool: str, event: str) -> int:
    return 3 if tool == "codex" and event == "SessionEnd" else 5


@dataclass(frozen=True)
class HookGroup:
    fields: dict[str, object]
    handlers: list[dict[str, object]]

    @classmethod
    def parse(cls, raw: object) -> HookGroup:
        fields = object_value(raw)
        handlers = fields.pop("hooks", None)
        if not isinstance(handlers, list):
            raise ValueError("Expected a list of hook handlers.")
        return cls(fields, [object_value(handler) for handler in handlers])

    def json(self) -> dict[str, object]:
        return {**self.fields, "hooks": self.handlers}


class JsonHooks:
    def __init__(self, snapshot: SettingsFile, tool: str, command: str, events: Iterable[str]) -> None:
        self.snapshot = snapshot
        self.tool = tool
        self.command = command
        self.events = sorted(events)
        self.groups: dict[str, list[HookGroup]] = {}
        try:
            raw = json.loads(
                snapshot.contents if snapshot.contents is not None else b"{}",
                object_pairs_hook=json_object,
                parse_constant=reject_constant,
            )
            self.document = object_value(raw)
            for event, groups in object_value(self.document.get("hooks", {})).items():
                if not isinstance(groups, list):
                    raise ValueError("Expected a list of matcher groups.")
                self.groups[event] = [HookGroup.parse(group) for group in groups]
        except (ValueError, RecursionError):
            raise SettingsError(f"Invalid JSON hook settings: {snapshot.path}") from None

    def installed(self) -> bool:
        return all(
            any(
                group.fields.get("matcher") in (None, "")
                and handler.get("type") == "command"
                and handler.get("command") == self.command
                and handler.get("timeout") == timeout_for(self.tool, event)
                and not handler.get("async")
                and not handler.get("once")
                for group in self.groups.get(event, [])
                for handler in group.handlers
            )
            for event in self.events
        )

    def install(self) -> HookEdit:
        groups = self.groups.copy()
        count = 0
        for event in self.events:
            existing = groups.get(event, [])
            if any(handler.get("command") == self.command for group in existing for handler in group.handlers):
                continue
            handler = {"type": "command", "command": self.command, "timeout": timeout_for(self.tool, event)}
            groups[event] = [*existing, HookGroup({}, [handler])]
            count += 1
        return self.encode(groups, count)

    def uninstall(self) -> HookEdit:
        groups: dict[str, list[HookGroup]] = {}
        count = 0
        for event, existing in self.groups.items():
            kept = []
            for group in existing:
                handlers = [handler for handler in group.handlers if handler.get("command") != self.command]
                removed = len(group.handlers) - len(handlers)
                count += removed
                if not removed or handlers:
                    kept.append(HookGroup(group.fields, handlers))
            if kept or not existing:
                groups[event] = kept
        return self.encode(groups, count)

    def encode(self, groups: dict[str, list[HookGroup]], count: int) -> HookEdit:
        if not count:
            return HookEdit(self.snapshot.contents, 0)
        document = self.document.copy()
        if groups:
            document["hooks"] = {event: [group.json() for group in rows] for event, rows in groups.items()}
        else:
            document.pop("hooks", None)
        return HookEdit((json.dumps(document, indent=2) + "\n").encode("utf-8"), count)
