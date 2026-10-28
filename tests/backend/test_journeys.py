"""The installed journey frame cannot silently replay or change account boundaries."""
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("journeys", Path(__file__).resolve().parents[2] / "tools/backend_journeys.py")
assert SPEC and SPEC.loader
journeys = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(journeys)


class Reservation(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.budget = journeys.Budget(self.folder)

    def test_an_uncertain_case_cannot_reserve_again(self) -> None:
        """journeys.no-ambiguous-replay"""
        self.budget.reserve("first-path", "The exact initial prompt")
        path = self.folder / "budget.jsonl"
        before = path.read_bytes()
        with self.assertRaises(journeys.Refused):
            self.budget.reserve("first-path", "A changed prompt cannot disguise the same case")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_five_reservations_are_the_entire_ceiling(self) -> None:
        """journeys.five-submission-ceiling"""
        for case in ["first-path", "stop", "gone", "stuck", "restart"]:
            self.budget.reserve(case, case)
        with self.assertRaises(journeys.Refused):
            self.budget.reserve("actions", "A sixth prompt")
        self.assertEqual(len((self.folder / "budget.jsonl").read_text().splitlines()), 5)

    def test_torn_or_unknown_history_never_spends_again(self) -> None:
        """journeys.torn-history-refusal"""
        path = self.folder / "budget.jsonl"
        for data in [b'{"version":1', b'{}\n', b'null\n', b'{"version":2}\n']:
            with self.subTest(data=data):
                path.write_bytes(data)
                with self.assertRaises(journeys.Refused):
                    self.budget.reserve("first-path", "Must not start")
                self.assertEqual(path.read_bytes(), data)

    def test_symlink_journal_is_not_followed(self) -> None:
        """journeys.no-follow-reservations"""
        target = self.folder / "other"
        target.write_text("preserved")
        (self.folder / "budget.jsonl").symlink_to(target)
        with self.assertRaises(OSError):
            self.budget.reserve("first-path", "Must not start")
        self.assertEqual(target.read_text(), "preserved")

    def test_another_reservation_lock_refuses_before_append(self) -> None:
        """journeys.concurrent-reservation-refusal"""
        path = self.folder / "budget.jsonl"
        path.touch(mode=0o600)
        with path.open("r+b") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.budget.reserve("first-path", "Must not start")
        self.assertEqual(path.read_bytes(), b"")


class Forwarding(unittest.TestCase):
    def test_actual_argument_forwarding_and_override_refusal(self) -> None:
        """journeys.test-state-forwarding"""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            installed = home / ".local/bin"
            installed.mkdir(parents=True)
            for name in ["arbol-roots", "arbol-trunk", "arbol-root", "arbol-claude-driver", "arbol-codex-driver"]:
                path = installed / name
                path.write_text("#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
                path.chmod(0o700)
            frame = journeys.Frame(home / "proof", home)
            frame.forwarders()
            for name, original, extra in [
                ("arbol-root", ["--root", "sapling", "list"], ["--bin-dir", str(frame.bin)]),
                ("arbol-claude-driver", ["run", "--request", "private.json"],
                 ["--state-dir", str(home / "Library/Application Support/Arbol/drivers/arbol-claude-driver")]),
                ("arbol-codex-driver", ["subscriptions", "list"],
                 ["--state-dir", str(home / "Library/Application Support/Arbol/drivers/arbol-codex-driver")]),
            ]:
                with self.subTest(program=name):
                    result = subprocess.run([str(frame.bin / name), *original], capture_output=True, check=True)
                    self.assertEqual(json.loads(result.stdout), original + extra)
                    rejected = subprocess.run([str(frame.bin / name), *original, *extra], capture_output=True)
                    self.assertEqual(rejected.returncode, 98)
            rows = [json.loads(line) for line in (frame.evidence / "forwarded.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 3)
            self.assertEqual((frame.evidence / "forwarded.jsonl").stat().st_mode & 0o777, 0o600)
            self.assertEqual((frame.bin / "arbol-trunk").resolve(), (installed / "arbol-trunk").resolve())

    def test_receipts_cannot_overwrite_an_existing_attempt(self) -> None:
        """journeys.immutable-receipts"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            journeys.private_json(path, {"first": True})
            with self.assertRaises(FileExistsError):
                journeys.private_json(path, {"first": False})
            self.assertEqual(json.loads(path.read_text()), {"first": True})
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
