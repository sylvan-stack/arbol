"""Read saved Pi SessionManager v3 sessions and their archive references (IMP-1)."""

from __future__ import annotations

import re
import stat
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .form import Kind, SessionFailure, Source, unknown_record
from .lines import file_records

_NATIVE_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")


def _iso_time(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            at = datetime.fromisoformat(value)
            if at.utcoffset() is not None:
                return at.astimezone(UTC)
        except (ValueError, OverflowError):
            pass
    return None


def _unreadable(file: str) -> SessionFailure:
    return SessionFailure("unreadable_session", f"{file}: the file could not be read.")


def _session_name(path: Path) -> bool:
    prefix, separator, suffix = path.stem.partition("_")
    return path.suffix == ".jsonl" and bool(prefix and separator and suffix)


def _children(home: Path, directory: Path) -> list[Path]:
    file = directory.relative_to(home).as_posix()
    try:
        resolved = directory.resolve()
        if not resolved.is_relative_to(home / "sessions"):
            raise _unreadable(file)
        if stat.S_ISDIR(resolved.stat().st_mode):
            return sorted(resolved.iterdir())
    except FileNotFoundError:
        pass
    except (OSError, RuntimeError, ValueError):
        raise _unreadable(file) from None
    return []


def _session_path(home: Path, path: Path) -> Path:
    try:
        resolved = path.resolve()
        parts = resolved.relative_to(home).parts
        if (len(parts) == 3 and parts[0] == "sessions" and _session_name(resolved)
                and stat.S_ISREG(resolved.stat().st_mode)):
            return resolved
    except (OSError, RuntimeError, ValueError):
        pass
    raise _unreadable(path.relative_to(home).as_posix())


def _session_records(home: Path, file: str) -> Generator[tuple[int, Any]]:
    yield from file_records(home, file)


@dataclass(frozen=True)
class _Header:
    native_id: str
    created_at: datetime
    cwd: str


def _header(row: Any, file: str, line: int) -> _Header:
    if isinstance(row, dict) and row.get("type") == "session" and type(row.get("version")) is int:
        native_id = row.get("id")
        at = _iso_time(row.get("timestamp"))
        cwd = row.get("cwd")
        if row["version"] == 3 and isinstance(native_id, str) and _NATIVE_ID.fullmatch(native_id):
            if at is not None and isinstance(cwd, str):
                return _Header(native_id, at, cwd)
    unknown_record("session", f"{file}:{line}", conversation=True)
    raise AssertionError("A malformed session header must fail.")


def _selected_header(rows: Iterator[tuple[int, Any]], file: str, source: Source) -> _Header | None:
    first = next(rows, None)
    if first is None:
        return None
    line, row = first
    header = _header(row, file, line)
    return header if source.wants(header.native_id) else None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True)
class _Entry:
    file: str
    line: int
    row: dict[str, Any]

    @property
    def native_id(self) -> str | None:
        return _string(self.row.get("id"))

    @property
    def at(self) -> datetime | None:
        return _iso_time(self.row.get("timestamp"))

    @property
    def has_parent(self) -> bool:
        return "parentId" in self.row and (
            self.row["parentId"] is None or _string(self.row["parentId"]) is not None
        )


@dataclass
class _Scan:
    file: str
    entries: list[_Entry] = field(default_factory=list)
    kind: Kind = "owner"
    title: str | None = None

    def add(self, line: int, row: Any) -> None:
        if not isinstance(row, dict):
            return
        entry = _Entry(self.file, line, row)
        self.entries.append(entry)
        if (line == 2 and row.get("type") == "custom" and row.get("customType") == "arbol-history-import"
                and entry.native_id is not None and entry.has_parent and entry.at is not None):
            self.kind = "arbol_driver"
        if row.get("type") == "session_info":
            name = _string(row.get("name"))
            self.title = name if name and name.strip() else None
