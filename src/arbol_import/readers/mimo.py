"""Read saved Mimo sessions from a private copy of their SQLite database (IMP-1)."""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from .form import SessionFailure, Source

_DATABASE = "mimocode.db"
_DATABASE_FILES = (_DATABASE, f"{_DATABASE}-wal", f"{_DATABASE}-shm")
_COPY_ATTEMPTS = 3


def _unreadable(record_type: str) -> SessionFailure:
    return SessionFailure("unreadable_session", f"{_DATABASE}: could not read the {record_type}.")


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _database_files(home_fd: int) -> dict[str, os.stat_result]:
    files = {}
    for name in _DATABASE_FILES:
        try:
            info = os.stat(name, dir_fd=home_fd, follow_symlinks=False)
        except FileNotFoundError:
            if name == _DATABASE:
                raise
            continue
        if not stat.S_ISREG(info.st_mode):
            raise _unreadable("database set")
        files[name] = info
    return files


def _copy_database(home: Path, destination: Path) -> datetime:
    home_fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        files = _database_files(home_fd)
        expected = {name: _signature(info) for name, info in files.items()}
        for name, signature in expected.items():
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=home_fd)
            with os.fdopen(fd, "rb") as original:
                if _signature(os.fstat(fd)) != signature:
                    raise _unreadable("database set")
                copy_fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(copy_fd, "wb") as copy:
                    shutil.copyfileobj(original, copy)
                    if copy.tell() != files[name].st_size:
                        raise _unreadable("database set")
                if _signature(os.fstat(fd)) != signature:
                    raise _unreadable("database set")
        current = {name: _signature(info) for name, info in _database_files(home_fd).items()}
        if current != expected or not os.path.samestat(os.fstat(home_fd), home.stat()):
            raise _unreadable("database set")
        return datetime.fromtimestamp(files[_DATABASE].st_mtime, UTC)
    finally:
        os.close(home_fd)


@contextmanager
def _snapshot(source: Source, home: Path) -> Iterator[tuple[sqlite3.Connection, datetime]]:
    if source.work is None:
        raise _unreadable("database set")
    work = source.work.resolve()
    if work.is_relative_to(home):
        raise _unreadable("database set")
    work.mkdir(parents=True, exist_ok=True)

    for _ in range(_COPY_ATTEMPTS):
        with TemporaryDirectory(prefix="mimo-", dir=work) as temporary:
            private = Path(temporary)
            try:
                mtime = _copy_database(home, private)
                connection = sqlite3.connect(f"{(private / _DATABASE).as_uri()}?mode=ro", uri=True)
            except (OSError, OverflowError, ValueError, sqlite3.Error, SessionFailure):
                continue
            with closing(connection):
                connection.row_factory = sqlite3.Row
                yield connection, mtime
                return
    raise _unreadable("database set")
