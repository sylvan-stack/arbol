"""Read Codex session rollouts for the Arbol importer (IMP-1)."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import stat
from collections.abc import Generator, Iterator
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from struct import Struct, unpack
from tempfile import TemporaryDirectory
from typing import Any, BinaryIO

from .form import SessionFailure, unknown_record
from .lines import file_records, lines

type Object = dict[str, Any]

_ROLLOUT = re.compile(r"(?:sessions/[0-9]{4}/[0-9]{2}/[0-9]{2}|archived_sessions)/rollout-[^/]+\.jsonl(?:\.zst)?")
_NATIVE_ID = re.compile(r"[A-Za-z0-9_-]+")
_ORIGIN_FIELDS = ("originator", "source", "thread_source", "cwd")


def _id(value: object) -> str | None:
    return value if isinstance(value, str) and _NATIVE_ID.fullmatch(value) else None


def _time(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            at = datetime.fromisoformat(value)
            if at.utcoffset() is not None:
                return at.astimezone(UTC)
        except (ValueError, OverflowError):
            pass
    return None


def _inside(root: Path, path: Path) -> Path | None:
    try:
        target = path.resolve(strict=True)
        if target.is_relative_to(root):
            return target
    except (OSError, RuntimeError, ValueError):
        pass
    return None


@dataclass
class Rollout:
    relative: str
    mtime_ns: int = 0
    native_id: str | None = None
    parent: str | None = None
    created_at: datetime | None = None
    version: str | None = None
    role: str | None = None
    history_start: int | None = None
    origin: Object = field(default_factory=dict)
    failure: SessionFailure | None = None
    outside: bool = False


def _rollout_target(home: Path, relative: str) -> Path:
    try:
        target = (home / relative).resolve(strict=True)
        if (
            target.is_relative_to(home)
            and _ROLLOUT.fullmatch(target.relative_to(home).as_posix())
            and target.name.endswith(".zst") == relative.endswith(".zst")
            and stat.S_ISREG(target.stat().st_mode)
        ):
            return target
    except (OSError, RuntimeError, ValueError):
        pass
    raise SessionFailure("unreadable_session", f"{relative}: the rollout could not be read.")


def _records(home: Path, relative: str) -> Generator[tuple[int, Any]]:
    target = _rollout_target(home, relative)
    try:
        yield from file_records(home, target.relative_to(home).as_posix())
    except RecursionError:
        raise SessionFailure("unreadable_session", f"{relative}: a line could not be decoded.") from None


def _header(rollout: Rollout, row: object, line: int) -> None:
    where = f"{rollout.relative}:{line}"
    if not isinstance(row, dict) or row.get("type") != "session_meta" or not isinstance(row.get("payload"), dict):
        unknown_record("session_meta", where, conversation=True)
        return
    meta: Object = row["payload"]
    rollout.native_id = _id(meta.get("id"))
    rollout.created_at = _time(meta.get("timestamp"))
    source = meta.get("source")
    for name in _ORIGIN_FIELDS:
        value = meta.get(name)
        if isinstance(value, str) or (name == "source" and isinstance(value, dict)):
            rollout.origin[name] = value
    version = meta.get("cli_version")
    rollout.version = version if isinstance(version, str) else None
    agent = source.get("subagent") if isinstance(source, dict) else None
    spawn = agent.get("thread_spawn") if isinstance(agent, dict) else None
    if not isinstance(spawn, dict):
        spawn = {}
    role = meta.get("agent_role", meta.get("agent_type", spawn.get("agent_role", spawn.get("agent_type"))))
    rollout.role = role if isinstance(role, str) else None
    parents = [meta.get("parent_thread_id"), spawn.get("parent_thread_id")]
    if meta.get("attached_thread") is True:
        parents.append(meta.get("forked_from_id"))
    parent_ids = {native_id for value in parents if (native_id := _id(value)) is not None}
    rollout.parent = next(iter(parent_ids)) if len(parent_ids) == 1 else None
    cutoff = meta.get("subagent_history_start_ordinal")
    if type(cutoff) is int and cutoff >= 0:
        rollout.history_start = cutoff
    if (
        rollout.native_id is None
        or rollout.created_at is None
        or len(parent_ids) > 1
        or rollout.native_id in parent_ids
        or any(value is not None and _id(value) is None for value in parents)
        or (isinstance(agent, dict) and "thread_spawn" in agent and _id(spawn.get("parent_thread_id")) is None)
        or (source is not None and not isinstance(source, (str, dict)))
        or (cutoff is not None and rollout.history_start is None)
        or any(meta.get(name) is not None and not isinstance(meta[name], str)
               for name in ("originator", "thread_source", "cwd", "cli_version"))
        or (role is not None and rollout.role is None)
    ):
        unknown_record("session_meta", where, conversation=True)


def _discover(home: Path) -> Iterator[Rollout]:
    patterns = ("sessions/[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/rollout-*.jsonl*",
                "archived_sessions/rollout-*.jsonl*")
    for pattern in patterns:
        for path in sorted(home.glob(pattern)):
            relative = path.relative_to(home).as_posix()
            if not _ROLLOUT.fullmatch(relative):
                continue
            rollout = Rollout(relative)
            try:
                target = path.resolve(strict=True)
                if not target.is_relative_to(home):
                    rollout.outside = True
                    yield rollout
                    continue
                if not stat.S_ISREG(target.stat().st_mode):
                    continue
                rollout.mtime_ns = _rollout_target(home, relative).stat().st_mtime_ns
                with closing(_records(home, relative)) as records:
                    first = next(records, None)
                if first is None:
                    continue
                _header(rollout, first[1], first[0])
            except SessionFailure as failure:
                rollout.failure = failure
            except (OSError, RuntimeError, ValueError):
                rollout.failure = SessionFailure("unreadable_session", f"{relative}: the rollout could not be read.")
            yield rollout


_DB = "state_5.sqlite"
_WAL = _DB + "-wal"
_COPY_ATTEMPTS = 3
_COPY_CHUNK = 1 << 20


@dataclass
class Catalogue:
    threads: dict[str, Object] = field(default_factory=dict)
    edges: list[Object] = field(default_factory=list)
    mtime: datetime | None = None


def _stamp(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _catalogue_file(home: Path, name: str) -> tuple[Path, os.stat_result] | None:
    path = home / name
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    target = _inside(home, path)
    if target is None:
        raise OSError("Catalogue file is unavailable")
    info = target.stat()
    if not stat.S_ISREG(info.st_mode):
        raise OSError("Catalogue file is not regular")
    return target, info


def _catalogue_pair(home: Path) -> dict[str, tuple[Path, os.stat_result]]:
    files = {}
    for name in (_DB, _WAL):
        entry = _catalogue_file(home, name)
        if entry is not None:
            files[name] = entry
    if _DB not in files:
        raise OSError("Catalogue is unavailable")
    return files


def _pair_stamp(files: dict[str, tuple[Path, os.stat_result]]) -> dict[str, tuple[Path, tuple[int, ...]]]:
    return {name: (path, _stamp(info)) for name, (path, info) in files.items()}


def _open_catalogue(path: Path, expected: os.stat_result) -> BinaryIO:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if _stamp(os.fstat(descriptor)) != _stamp(expected):
            raise OSError("Catalogue changed during snapshot")
        stream = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    return stream


def _copy_catalogue(home: Path, private: Path) -> datetime:
    before = _catalogue_pair(home)
    expected = _pair_stamp(before)
    for name, (path, info) in before.items():
        with _open_catalogue(path, info) as original, (private / name).open("xb") as copy:
            shutil.copyfileobj(original, copy, _COPY_CHUNK)
            if _stamp(os.fstat(original.fileno())) != _stamp(info):
                raise OSError("Catalogue changed during snapshot")
    if _pair_stamp(_catalogue_pair(home)) != expected:
        raise OSError("Catalogue changed during snapshot")
    for name, (path, info) in before.items():
        with _open_catalogue(path, info) as original, (private / name).open("rb") as copy:
            while True:
                chunk = copy.read(_COPY_CHUNK)
                if original.read(_COPY_CHUNK) != chunk:
                    raise OSError("Catalogue bytes changed during snapshot")
                if not chunk:
                    break
            if _stamp(os.fstat(original.fileno())) != _stamp(info):
                raise OSError("Catalogue changed during snapshot")
    if _pair_stamp(_catalogue_pair(home)) != expected:
        raise OSError("Catalogue changed during snapshot")
    return datetime.fromtimestamp(before[_DB][1].st_mtime, UTC)


def _wal_checksum(data: bytes, words: Struct, checksum: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    first, second = checksum
    for left, right in words.iter_unpack(data):
        first = (first + left + second) & 0xffffffff
        second = (second + right + first) & 0xffffffff
    return first, second


def _verify_catalogue(private: Path) -> None:
    # SQLite recovery stops at an invalid WAL frame. Verify the active frames
    # ourselves so a corrupt committed overlay cannot silently look like an old DB.
    with (private / _DB).open("rb") as database:
        header = database.read(100)
    if len(header) != 100 or header[:16] != b"SQLite format 3\x00":
        raise ValueError("Invalid catalogue header")
    wal = private / _WAL
    if not wal.exists() or not wal.stat().st_size:
        return
    with wal.open("rb") as stream:
        wal_header = stream.read(32)
        magic = int.from_bytes(wal_header[:4], "big")
        version = int.from_bytes(wal_header[4:8], "big")
        page_size = int.from_bytes(wal_header[8:12], "big")
        db_page_size = int.from_bytes(header[16:18], "big")
        if db_page_size == 1:
            db_page_size = 65536
        if (
            len(wal_header) != 32
            or magic not in (0x377f0682, 0x377f0683)
            or version != 3007000
            or page_size != db_page_size
            or page_size < 512 or page_size > 65536 or page_size & (page_size - 1)
            or header[18:20] != b"\x02\x02"
        ):
            raise ValueError("Invalid catalogue WAL header")
        words = Struct("<II" if magic == 0x377f0682 else ">II")
        checksum = _wal_checksum(wal_header[:24], words)
        if checksum != unpack(">II", wal_header[24:32]):
            raise ValueError("Invalid catalogue WAL checksum")
        while frame := stream.read(24):
            if len(frame) != 24:
                raise ValueError("Incomplete catalogue WAL frame")
            # A WAL reset can leave intact frames from the previous generation.
            if frame[8:12] != wal_header[16:20]:
                break
            page = stream.read(page_size)
            if len(page) != page_size or frame[:4] == b"\0" * 4 or frame[12:16] != wal_header[20:24]:
                raise ValueError("Invalid catalogue WAL frame")
            checksum = _wal_checksum(page, words, _wal_checksum(frame[:8], words, checksum))
            if checksum != unpack(">II", frame[16:24]):
                raise ValueError("Invalid catalogue WAL frame checksum")


def _catalogue_rows(connection: sqlite3.Connection, table: str) -> Iterator[Object]:
    try:
        cursor = connection.execute(f"SELECT * FROM {table}")
        with closing(cursor):
            columns = [column[0] for column in cursor.description]
            for cells in cursor:
                try:
                    yield dict(zip(columns, (cell.decode("utf-8") if isinstance(cell, bytes) else cell
                                             for cell in cells), strict=True))
                except UnicodeError:
                    continue
    except sqlite3.Error:
        return


def _read_catalogue(home: Path, work: Path | None) -> Catalogue:
    if work is None:
        return Catalogue()
    try:
        work = work.resolve(strict=True)
        if work.is_relative_to(home) or not work.is_dir():
            return Catalogue()
    except (OSError, RuntimeError, ValueError):
        return Catalogue()
    for _ in range(_COPY_ATTEMPTS):
        try:
            with TemporaryDirectory(prefix="codex-catalogue-", dir=work) as directory:
                private = Path(directory)
                mtime = _copy_catalogue(home, private)
                _verify_catalogue(private)
                uri = (private / _DB).as_uri() + "?mode=ro"
                with closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
                    connection.text_factory = bytes
                    connection.execute("PRAGMA trusted_schema=OFF")
                    connection.execute("BEGIN")
                    connection.execute("SELECT name FROM sqlite_schema LIMIT 1").fetchone()
                    threads = {key: row for row in _catalogue_rows(connection, "threads")
                               if (key := _id(row.get("id"))) is not None}
                    edges = [row for row in _catalogue_rows(connection, "thread_spawn_edges")
                             if _id(row.get("parent_thread_id")) and _id(row.get("child_thread_id"))]
                return Catalogue(threads, edges, mtime)
        except (OSError, RuntimeError, ValueError, sqlite3.Error):
            continue
    return Catalogue()


def _titles(home: Path) -> dict[str, str]:
    titles: dict[str, str] = {}
    path = _inside(home, home / "session_index.jsonl")
    if path is None:
        return titles
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return titles
        with path.open("rb") as stream:
            for _, raw in lines(stream):
                try:
                    row = json.loads(raw)
                except (ValueError, RecursionError):
                    continue
                if isinstance(row, dict) and (native_id := _id(row.get("id"))) is not None:
                    if isinstance(row.get("thread_name"), str):
                        titles[native_id] = row["thread_name"]
    except OSError:
        pass
    return titles
