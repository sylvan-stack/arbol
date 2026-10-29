"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_exchange_files as _support
from backend.test_exchange_files import (
    Any,
    Error,
    Files,
    Folders,
    Frame,
    MAX_RECORD,
    Path,
    ROOT,
    UTC,
    asyncio,
    identity,
    json,
    living,
    mock,
    os,
    parse,
    processes,
    record,
    sys,
    timedelta,
    unittest,
    uuid4,
)


class Files(_support.Files):

# TEST-TIER-BEGIN tests/backend/test_exchange_files.py::Files.test_identifier_mode_symlink_fifo_hardlink_and_dot_boundaries
    async def test_identifier_mode_symlink_fifo_hardlink_and_dot_boundaries(self) -> None:
        """live.private-files"""
        for name in (".ignored", "not-a-uuid"):
            (self.parent / name).mkdir(mode=0o700)
        symlink = self.parent / str(uuid4())
        symlink.symlink_to(self.folder, target_is_directory=True)
        self.assertEqual(self.reader.names(), [self.exchange])
        with self.assertRaises(Error):
            self.reader.open("../../escape")
        with self.assertRaises(OSError):
            self.reader.open(symlink.name)
        directory = self.reader.open(self.exchange)
        try:
            path = self.folder / "events.jsonl"
            path.unlink()
            os.mkfifo(path, 0o600)
            with self.assertRaises(Error):
                directory.open("events.jsonl")
            path.unlink()
            path.symlink_to(self.folder / "record.json")
            with self.assertRaises(OSError):
                directory.open("events.jsonl")
            path.unlink()
            os.link(self.folder / "record.json", path)
            with self.assertRaises(Error):
                directory.open("events.jsonl")
            path.unlink()
            (self.folder / "control").chmod(0o644)
            with self.assertRaises(Error):
                directory.open("control", append=True)
            with self.assertRaises(Error):
                directory.open("private-driver-request.json")
        finally:
            directory.close()
        self.assertFalse((self.folder / "private-driver-request.json").exists())
# TEST-TIER-END tests/backend/test_exchange_files.py::Files.test_identifier_mode_symlink_fifo_hardlink_and_dot_boundaries
