"""The force-stop identity regression moved from the historical Root gate."""

from __future__ import annotations

import signal
import unittest
from datetime import timedelta

from exchange_groups_support import LEADER, STARTED, Refusal, changed_group, force


class GroupIdentity(unittest.TestCase):
    def test_reused_or_unanchored_group_is_never_killed_after_term(self) -> None:
        for replacement in ({LEADER: STARTED + timedelta(seconds=9)}, {LEADER + 1: STARTED}):
            with self.subTest(replacement=replacement), changed_group(replacement) as send:
                with self.assertRaises(Refusal) as error:
                    force()
                self.assertEqual(error.exception.code, "not_ended")
                send.assert_called_once_with(LEADER, signal.SIGTERM)
