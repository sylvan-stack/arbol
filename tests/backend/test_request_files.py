"""Private request-file namespace, modes, races and narrowly scoped startup cleanup."""

from __future__ import annotations

import json
import os
import stat
import sys
import time
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Error  # noqa: E402
from arbol_backend.model import identity, parse  # noqa: E402
from arbol_backend.requests import Requests  # noqa: E402
from backend.support import Frame  # noqa: E402


class Files(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = Frame()
        self.files = Requests(identity(ROOT, parse(self.frame.options()), home=self.frame.home))
        self.exchange = str(uuid4())
        self.request = {"chat": str(uuid4()), "message": "exact\n🙂", "route": {"model": "m"},
                        "workingFolder": str(self.frame.base)}

    def tearDown(self) -> None:
        self.frame.close()

    def test_atomic_complete_private_file_and_only_same_payload_adoption(self) -> None:
        """sending.private-request"""
        request = self.files.write(self.exchange, self.request)
        path = Path(request.path)
        self.assertEqual(json.loads(path.read_bytes()), self.request)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual([p.name for p in path.parent.iterdir()], [self.exchange + ".json"])
        adopted = self.files.write(self.exchange, dict(self.request))
        self.assertEqual(adopted.inode, request.inode)
        with self.assertRaises(Error):
            self.files.write(self.exchange, {**self.request, "message": "different"})
        self.assertEqual(json.loads(path.read_bytes()), self.request)
        request.remove()
        adopted.remove()
        self.assertFalse(path.exists())

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

    def test_cleanup_never_unlinks_a_replaced_request(self) -> None:
        """sending.request-inode"""
        request = self.files.write(self.exchange, self.request)
        path = Path(request.path)
        prior = path.with_suffix(".retained")
        path.rename(prior)
        path.write_text("replacement")
        path.chmod(0o600)
        request.remove()
        self.assertEqual(path.read_text(), "replacement")
        self.assertEqual(json.loads(prior.read_bytes()), self.request)

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

    def test_failed_partial_write_and_invalid_identifier_leave_no_file(self) -> None:
        """sending.request-write-failure"""
        with self.assertRaises(Error):
            self.files.write("../escape", self.request)
        self.assertFalse((self.frame.root / "requests").exists())
        with mock.patch("arbol_backend.requests.os.write", side_effect=OSError("private failure")):
            with self.assertRaises(Error):
                self.files.write(self.exchange, self.request)
        self.assertEqual(list((self.frame.root / "requests").iterdir()), [])
