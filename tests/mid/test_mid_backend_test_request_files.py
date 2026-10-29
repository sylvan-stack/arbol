"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_request_files as _support
from backend.test_request_files import (
    Error,
    Files,
    Frame,
    Path,
    ROOT,
    Requests,
    identity,
    json,
    mock,
    os,
    parse,
    stat,
    sys,
    time,
    unittest,
    uuid4,
)


class Files(_support.Files):

# TEST-TIER-BEGIN tests/backend/test_request_files.py::Files.test_no_follow_directory_file_fifo_hardlink_or_insecure_mode
    def test_no_follow_directory_file_fifo_hardlink_or_insecure_mode(self) -> None:
        """sending.request-path-safety"""
        directory = self.frame.root / "requests"
        outside = self.frame.base / "outside"
        outside.mkdir(mode=0o700)
        directory.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(Error):
            self.files.write(self.exchange, self.request)
        self.assertEqual(list(outside.iterdir()), [])
        directory.unlink()
        directory.mkdir(mode=0o700)
        path = directory / (self.exchange + ".json")
        target = outside / "keep"
        target.write_text("keep")
        target.chmod(0o600)
        path.symlink_to(target)
        with self.assertRaises(Error):
            self.files.write(self.exchange, self.request)
        self.assertEqual(target.read_text(), "keep")
        path.unlink()
        os.mkfifo(path, 0o600)
        with self.assertRaises(Error):
            self.files.write(self.exchange, self.request)
        path.unlink()
        os.link(target, path)
        with self.assertRaises(Error):
            self.files.write(self.exchange, self.request)
        path.unlink()
        path.write_text(json.dumps(self.request))
        path.chmod(0o644)
        with self.assertRaises(Error):
            self.files.write(self.exchange, self.request)
        path.unlink()
        directory.chmod(0o755)
        with self.assertRaises(Error):
            self.files.write(self.exchange, self.request)
        self.assertEqual(list(directory.iterdir()), [])
# TEST-TIER-END tests/backend/test_request_files.py::Files.test_no_follow_directory_file_fifo_hardlink_or_insecure_mode


# TEST-TIER-BEGIN tests/backend/test_request_files.py::Files.test_startup_removes_only_owned_private_matching_hour_old_files
    def test_startup_removes_only_owned_private_matching_hour_old_files(self) -> None:
        """sending.request-startup-cleanup"""
        request = self.files.write(self.exchange, self.request)
        path = Path(request.path)
        os.close(request.folder)
        now = time.time()
        os.utime(path, (now - 3601, now - 3601))
        directory = path.parent
        old_temp = directory / ("." + str(uuid4()) + "." + str(uuid4()) + ".tmp")
        old_temp.write_text("partial")
        old_temp.chmod(0o600)
        os.utime(old_temp, (now - 3601, now - 3601))
        keep: list[Path] = []
        for name, mode in [(str(uuid4()) + ".json", 0o644), ("unrelated.json", 0o600)]:
            p = directory / name
            p.write_text("keep")
            p.chmod(mode)
            os.utime(p, (now - 7200, now - 7200))
            keep.append(p)
        recent = self.files.write(str(uuid4()), self.request)
        os.close(recent.folder)
        keep.append(Path(recent.path))
        link = directory / (str(uuid4()) + ".json")
        link.symlink_to(keep[0])
        keep.append(link)
        self.files.clean(now=now)
        self.assertFalse(path.exists())
        self.assertFalse(old_temp.exists())
        self.assertTrue(all(p.exists() for p in keep))
# TEST-TIER-END tests/backend/test_request_files.py::Files.test_startup_removes_only_owned_private_matching_hour_old_files
