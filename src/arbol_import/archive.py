"""Inspect and retain byte-exact native session inputs (IMP-0.13)."""

import os
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from .readers.form import ArchiveFile, ExportedRows, FileObservation
from .readers.lines import open_input

_CHUNK = 1 << 20


class UnreadableInput(ValueError):
    code = "unreadable_session"

    def __init__(self) -> None:
        super().__init__("A selected native archive file is unavailable or changed during import.")


@dataclass(frozen=True)
class FileEntry:
    path: str
    sha256: str
    size: int
    mtime: datetime


def _relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(path.parts) and not path.is_absolute() and ".." not in path.parts
        and "\0" not in value and path.as_posix() == value
    )


@contextmanager
def _input(home: Path, source: ArchiveFile) -> Iterator[tuple[BinaryIO, datetime]]:
    if not _relative_path(source.path):
        raise UnreadableInput()
    if isinstance(source, ExportedRows):
        with BytesIO(source.content) as exported:
            yield exported, source.mtime
        return

    path = source.read_path or source.path
    observed = source.observation
    if observed is None or not _relative_path(path):
        raise UnreadableInput()
    with ExitStack() as opened:
        try:
            stream = opened.enter_context(open_input(home, path))
            if FileObservation.from_stat(os.fstat(stream.fileno())) != observed:
                raise UnreadableInput()
        except OSError:
            raise UnreadableInput() from None
        yield stream, observed.modified_at
        try:
            if FileObservation.from_stat(os.fstat(stream.fileno())) != observed:
                raise UnreadableInput()
        except OSError:
            raise UnreadableInput() from None


def _chunks(stream: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := stream.read(_CHUNK):
            yield chunk
    except OSError:
        raise UnreadableInput() from None


def _measure(home: Path, source: ArchiveFile, copy: Callable[[bytes], object] | None = None) -> FileEntry:
    digest = sha256()
    size = 0
    with _input(home, source) as (stream, mtime):
        for chunk in _chunks(stream):
            digest.update(chunk)
            size += len(chunk)
            if copy is not None:
                copy(chunk)
    return FileEntry(source.path, digest.hexdigest(), size, mtime)
