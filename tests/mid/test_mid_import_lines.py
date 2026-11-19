"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from compression import zstd
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from arbol_import.readers.form import SessionFailure  # noqa: E402
from arbol_import.readers.lines import file_records  # noqa: E402

CHUNK = 1 << 16
MARKER = "fictional-content-marker"


def line(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


class Lines(unittest.TestCase):
    def test_records_split_at_newline_bytes_across_chunks_of_a_zstd_stream(self) -> None:
        """IMP-1.2: a record lost, split or merged at a chunk boundary of a decompression stream, or an unfinished
        record imported as finished, corrupts the imported session. The expected records are the list written here,
        independent of the line splitter."""
        expected: list[tuple[int, Any]] = [(1, {"n": 1, "text": MARKER})]
        data = bytearray(line(expected[0][1]))
        # Record 2 crosses the end of the first 64 KiB chunk.
        expected.append((2, {"n": 2, "text": "x" * (CHUNK + 4000)}))
        data += line(expected[1][1])
        self.assertTrue(len(data) - len(line(expected[1][1])) < CHUNK < len(data))
        # Record 3 ends exactly at the end of a chunk: its newline is the chunk's last byte.
        room = 3 * CHUNK - len(data) - len(line({"n": 3, "text": ""}))
        expected.append((3, {"n": 3, "text": "y" * room}))
        data += line(expected[2][1])
        self.assertEqual(len(data), 3 * CHUNK)
        # Record 4 holds raw U+2028, U+2029 and U+0085 in a string, and a raw CR as JSON whitespace between tokens,
        # all of which `str.splitlines` would take as line ends.
        text = f"before {MARKER} after\u0085end"
        expected.append((4, {"n": 4, "text": text}))
        data += b'{"n":4,\r"text":' + json.dumps(text, ensure_ascii=False).encode() + b"}\n"
        expected.append((5, {"n": 5, "text": MARKER}))
        data += line(expected[4][1])
        # The tool is still writing the last record: complete JSON, but no newline yet.
        data += json.dumps({"n": 6, "text": MARKER}).encode()
        compressed = zstd.compress(bytes(data))

        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            name = "sessions/fictional.jsonl.zst"
            (home / "sessions").mkdir()
            (home / name).write_bytes(compressed)
            self.assertEqual(list(file_records(home, name)), expected)

            (home / name).write_bytes(compressed[: len(compressed) // 2])
            with self.assertRaises(SessionFailure) as failed:
                list(file_records(home, name))
            self.assertEqual(failed.exception.code, "unreadable_session")
            self.assertTrue(failed.exception.message.startswith(f"{name}:"))
            self.assertNotIn(MARKER, failed.exception.message)
            self.assertNotIn(folder, failed.exception.message)
