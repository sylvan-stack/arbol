"""Read saved Claude Code sessions and their archive files (IMP-1)."""

from __future__ import annotations

import json
import re
import stat
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .form import Failed, SessionFailure, Source
from .lines import file_records


@dataclass(frozen=True)
class SessionFile:
    path: Path

    @property
    def native_id(self) -> str:
        return self.path.stem

    @property
    def directory(self) -> Path:
        return self.path.with_suffix("")


def _inside(root: Path, path: Path) -> Path | None:
    resolved = path.resolve()
    return resolved if resolved.is_relative_to(root) else None


def _unreadable(home: Path, path: Path) -> SessionFailure:
    return SessionFailure("unreadable_session", f"{path.relative_to(home)}: could not be read.")


def _regular(home: Path, path: Path) -> Path:
    try:
        resolved = _inside(home, path)
        if resolved is not None and stat.S_ISREG(resolved.stat().st_mode):
            return resolved
    except (OSError, RuntimeError, ValueError):
        pass
    raise _unreadable(home, path)


def _discover(home: Path) -> Iterator[SessionFile | Failed]:
    projects = home / "projects"
    try:
        if _inside(home, projects) is None:
            raise _unreadable(home, projects)
        folders = sorted(projects.iterdir())
    except FileNotFoundError:
        return
    except (OSError, RuntimeError, SessionFailure):
        yield Failed.of(_unreadable(home, projects), file="projects")
        return
    for folder in folders:
        try:
            if _inside(home, folder) is None or not stat.S_ISDIR(folder.stat().st_mode):
                continue
            paths = sorted(folder.iterdir())
        except (OSError, RuntimeError):
            yield Failed.of(_unreadable(home, folder), file=folder.relative_to(home).as_posix())
            continue
        yield from (SessionFile(path) for path in paths if path.suffix == ".jsonl")


_NATIVE_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)


def _map_entries(root: Path, directory: Path) -> Iterator[Path]:
    try:
        if _inside(root, directory) is not None:
            yield from directory.iterdir()
    except (OSError, RuntimeError):
        pass


def _driver_ids(state: Path | None) -> set[str]:
    if state is None:
        return set()
    try:
        root = state.resolve()
    except (OSError, RuntimeError):
        return set()

    native_ids = set()
    for subscription in _map_entries(root, root / "subscriptions"):
        for entry in _map_entries(root, subscription / "chats"):
            if entry.suffix != ".json":
                continue
            try:
                value = json.loads(_regular(root, entry).read_bytes())
            except (OSError, ValueError, RecursionError, SessionFailure):
                continue
            conversation = value.get("conversation") if isinstance(value, dict) else None
            if isinstance(conversation, str) and _NATIVE_ID.fullmatch(conversation):
                native_ids.add(conversation)
    return native_ids


def _time(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.utcoffset() is not None:
                return parsed.astimezone(UTC)
        except (ValueError, OverflowError):
            pass
    return None


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


@dataclass(frozen=True)
class OrderedFile:
    file: SessionFile
    at: datetime
    mtime: datetime | None
    lookahead_failure: SessionFailure | None = None
    failure_line: int = 1


def _read_records(home: Path, path: Path) -> Generator[tuple[int, Any]]:
    resolved = _regular(home, path)
    yield from file_records(home, resolved.relative_to(home).as_posix())


def _order_file(home: Path, file: SessionFile) -> OrderedFile:
    modified = None
    number = 0
    try:
        modified = _mtime(_regular(home, file.path))
        stream = _read_records(home, file.path)
        try:
            for line, row in stream:
                number = line
                at = _time(row.get("timestamp")) if isinstance(row, dict) else None
                if at is not None:
                    return OrderedFile(file, at, modified)
        finally:
            stream.close()
    except (OSError, OverflowError, RecursionError, SessionFailure) as error:
        failure = error if isinstance(error, SessionFailure) else _unreadable(home, file.path)
        return OrderedFile(file, modified or datetime.min.replace(tzinfo=UTC), modified, failure, number + 1)
    assert modified is not None
    return OrderedFile(file, modified, modified)


@dataclass(frozen=True)
class Record:
    file: SessionFile
    position: tuple[int, int]
    row: dict[str, Any]
    at: datetime | None
    duplicate: bool

    def where(self, home: Path) -> str:
        return f"{self.file.path.relative_to(home)}:{self.position[1]}"


@dataclass
class SessionRecords:
    files: list[OrderedFile] = field(default_factory=list)
    rows: list[Record] = field(default_factory=list)
    failure: SessionFailure | None = None


def _ordered_sessions(home: Path, source: Source) -> Iterator[Failed | tuple[str, SessionRecords]]:
    files = []
    for file in _discover(home):
        if isinstance(file, Failed):
            yield file
        else:
            files.append(_order_file(home, file))
    files.sort(key=lambda ordered: (ordered.at, ordered.file.path))

    remaining: dict[str, int] = {}
    for ordered in files:
        native_id = ordered.file.native_id
        remaining[native_id] = remaining.get(native_id, 0) + 1

    projects: dict[Path, set[str]] = {}
    previous_copies: dict[str, set[str]] = {}
    sessions: dict[str, SessionRecords] = {}

    # Context IDs go through the same scan even when they won't be yielded.
    for rank, ordered in enumerate(files):
        file = ordered.file
        native_id = file.native_id
        session = sessions.setdefault(native_id, SessionRecords())
        session.files.append(ordered)
        project_uuids = projects.setdefault(file.path.parent, set())
        session_uuids = previous_copies.setdefault(native_id, set())
        seen_here: set[str] = set()
        if session.failure is None:
            try:
                for number, raw in _read_records(home, file.path):
                    if ordered.lookahead_failure is not None and number >= ordered.failure_line:
                        raise ordered.lookahead_failure
                    if not isinstance(raw, dict):
                        continue
                    uuid = raw.get("uuid")
                    duplicate = isinstance(uuid, str) and (uuid in project_uuids or uuid in session_uuids)
                    row = Record(file, (rank, number), raw, _time(raw.get("timestamp")), duplicate)
                    if isinstance(uuid, str):
                        seen_here.add(uuid)
                    if source.wants(native_id):
                        session.rows.append(row)
                if ordered.lookahead_failure is not None:
                    raise ordered.lookahead_failure
            except SessionFailure as error:
                session.failure = error
            except (OSError, RecursionError):
                session.failure = _unreadable(home, file.path)
        project_uuids.update(seen_here)
        session_uuids.update(seen_here)
        remaining[native_id] -= 1
        if remaining[native_id] == 0:
            previous_copies.pop(native_id)
            finished = sessions.pop(native_id)
            if source.wants(native_id):
                yield native_id, finished
