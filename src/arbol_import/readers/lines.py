"""Line files of a session (IMP-1, common rules): split only at `\\n`, and a last line without one is ignored, because
the tool is still writing it (IMP-1.2)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO

CHUNK = 1 << 16


def lines(stream: BinaryIO) -> Iterator[tuple[int, bytes]]:
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
