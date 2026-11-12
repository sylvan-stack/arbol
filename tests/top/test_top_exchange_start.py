"""The detached start regressions moved from the historical Root gate."""

from __future__ import annotations

import os
from unittest.mock import patch

from exchange_start_support import ACCEPTED, Refusal, Starting


class DetachedStart(Starting):
    def test_returns_on_a_fragmented_object_without_waiting_for_trunk_exit(self) -> None:
        self.configure("fragmented")
        pread = os.pread

        def release_after_prefix(fd: int, size: int, offset: int) -> bytes:
            chunk = pread(fd, size, offset)
            if offset == 0 and chunk and b"\n" not in chunk:
                (self.bin / "finish-reply").touch()
            return chunk

        with patch.object(os, "pread", side_effect=release_after_prefix):
            reply = self.begin(timeout=5)
        self.assertEqual((reply.value, reply.status), (ACCEPTED, 0))
        child = self.running_child()
        (self.bin / "finish-work").touch()
        self.assertEqual(child.wait(timeout=5), 0)

    def test_timeout_keeps_request_and_process_and_a_late_writer_can_still_finish(self) -> None:
        self.configure("late")
        before = self.request.read_bytes()
        with self.assertRaises(Refusal) as error:
            self.begin(timeout=0.5)
        self.assertEqual(error.exception.code, "no_answer")
        self.assertEqual(self.request.read_bytes(), before)
        child = self.running_child()
        (self.bin / "finish-reply").touch()
        (self.bin / "finish-work").touch()
        self.assertEqual(child.wait(timeout=5), 0)
        self.assertTrue((self.bin / "work-finished").is_file())
