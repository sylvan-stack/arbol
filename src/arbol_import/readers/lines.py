"""Line files of a session (IMP-1, common rules): split only at `\\n`, and a last line without one is ignored, because
the tool is still writing it (IMP-1.2)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from compression import zstd
from compression.zstd import ZstdError
from pathlib import Path
from typing import Any, Protocol

from .form import SessionFailure

CHUNK = 1 << 16


class ByteStream(Protocol):
    """What the line reader reads: an open binary file or a decompression stream such as `zstd.ZstdFile`."""

    def read(self, size: int = -1, /) -> bytes: ...


def lines(stream: ByteStream) -> Iterator[tuple[int, bytes]]:
    """The complete lines of a binary stream, an open file or a decompression stream alike, numbered from 1, without
    their `\\n`. Only the byte `\\n` ends a line: never `\\r`, U+2028 or the other separators `str.splitlines` honours."""
    buffer = bytearray()
    number = 0
    while chunk := stream.read(CHUNK):
        buffer += chunk
        start = 0
        while (end := buffer.find(b"\n", start)) >= 0:
            number += 1
            yield number, bytes(buffer[start:end])
            start = end + 1
        del buffer[:start]


def records(stream: ByteStream, file: str) -> Iterator[tuple[int, Any]]:
    """Each complete line decoded as JSON, with its number. `file` names the file within the tool's home for messages.
    An I/O error, a corrupt compressed stream, a line that is not JSON or a file that disappears while it is read
    fails the session with `unreadable_session` (IMP-D13); no message quotes the line."""
    try:
        for number, line in lines(stream):
            try:
                value = json.loads(line)
            except ValueError:
                raise SessionFailure("unreadable_session", f"{file}:{number}: the line is not JSON.") from None
            yield number, value
    except FileNotFoundError:
        raise SessionFailure("unreadable_session", f"{file}: the file disappeared while it was read.") from None
    except (OSError, EOFError, ZstdError):
        raise SessionFailure("unreadable_session", f"{file}: the file could not be read.") from None


def file_records(home: Path, file: str) -> Iterator[tuple[int, Any]]:
    """The records of a line file of the tool's home, opened read-only, by its path within the home. A `.zst` file is
    read through zstd decompression."""
    try:
        stream = (home / file).open("rb")
    except FileNotFoundError:
        raise SessionFailure("unreadable_session", f"{file}: the file disappeared while it was read.") from None
    except OSError:
        raise SessionFailure("unreadable_session", f"{file}: the file could not be read.") from None
    with stream:
        if file.endswith(".zst"):
            with zstd.ZstdFile(stream) as decompressed:
                yield from records(decompressed, file)
        else:
            yield from records(stream, file)
