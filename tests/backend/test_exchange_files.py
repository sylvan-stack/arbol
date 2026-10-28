"""Private folder boundaries, immutable records and actual clean-UTC process identity."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Error  # noqa: E402
from arbol_backend.exchange_files import MAX_RECORD, Folders, living, processes, record  # noqa: E402
from arbol_backend.model import identity, parse  # noqa: E402
from backend.support import Frame  # noqa: E402


class Files(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.frame = Frame()
        self.identity = identity(ROOT, parse(self.frame.options()), home=self.frame.home)
        self.reader = Folders(self.identity)
        self.parent = self.frame.root / "exchanges"
        self.parent.mkdir(mode=0o700)
        self.exchange, self.chat = str(uuid4()), str(uuid4())
        self.folder = self.parent / self.exchange
        self.folder.mkdir(mode=0o700)
        self.value: dict[str, Any] = {"rootContract": 1, "root": self.identity.root, "exchange": self.exchange,
            "chat": self.chat, "trunk": "trivial", "build": "0", "route": {}, "workingFolder": str(self.frame.base),
            "process": {"pid": os.getpid(), "startedAt": "2026-10-27T00:00:00Z"},
            "signsOfLife": {"heartbeat": 0, "waitingFor": "driver", "since": "2026-10-27T00:00:00Z"}}
        self.save()
        for name in ("events.jsonl", "control"):
            (self.folder / name).touch(mode=0o600)

    def tearDown(self) -> None:
        self.frame.close()

    def save(self) -> None:
        path = self.folder / "record.json"
        temporary = self.folder / "record.json.new"
        temporary.write_text(json.dumps(self.value))
        temporary.chmod(0o600)
        temporary.replace(path)

    async def test_valid_records_truthful_states_unknown_fields_and_immutable_identity(self) -> None:
        """live.records; live.states"""
        self.value["future"] = {"extra": "ignored"}
        self.save()
        item = self.reader.read(self.exchange)
        self.assertEqual(item.status(True)["state"], "accepting")  # type: ignore[index]
        self.assertIsNone(item.status(False))
        self.value["acceptedAt"] = "2026-10-27T00:00:01Z"
        self.value["signsOfLife"]["waitingFor"] = "future_wait"
        self.save()
        item = self.reader.read(self.exchange)
        self.assertEqual(item.status(True)["waitingFor"], "future_wait")  # type: ignore[index]
        self.assertEqual(item.status(False)["state"], "gone")  # type: ignore[index]
        self.assertEqual(item.status(True, stopping=True)["state"], "stopping")  # type: ignore[index]
        self.value["end"] = {"state": "future_end", "at": "2026-10-27T00:00:02Z"}
        self.save()
        item = self.reader.read(self.exchange)
        self.assertEqual(item.status(True)["state"], "ending")  # type: ignore[index]
        self.assertEqual(item.status(False)["state"], "unsaved")  # type: ignore[index]
        self.assertEqual(item.end, {"state": "future_end", "at": "2026-10-27T00:00:02.000Z"})
        self.value["process"]["pid"] += 1
        self.save()
        with self.assertRaises(Error):
            self.reader.read(self.exchange)

    async def test_atomically_retired_record_events_and_control_are_transient_missing(self) -> None:
        """live.retired-inode; live.retired-control-no-append"""
        opened = os.open
        fstat = os.fstat
        for name in ("record.json", "events.jsonl", "control"):
            retired: list[int] = []
            def raced(path: Any, flags: int, *args: Any, _name: str = name, _retired: list[int] = retired, **kwargs: Any) -> int:
                fd = opened(path, flags, *args, **kwargs)
                if path == _name and not _retired:
                    current = self.folder / _name
                    replacement = self.folder / (_name + ".replacement")
                    replacement.write_bytes(current.read_bytes())
                    replacement.chmod(0o600)
                    replacement.replace(current)
                    self.assertEqual(fstat(fd).st_nlink, 0)
                    _retired.append(fd)
                return fd
            folder = self.reader.open(self.exchange)
            try:
                with self.subTest(file=name), mock.patch("arbol_backend.exchange_files.os.open", side_effect=raced):
                    with self.assertRaises(FileNotFoundError):
                        folder.open(name, append=name == "control")
                self.assertEqual(len(retired), 1)
                with self.assertRaises(OSError):
                    fstat(retired[0])
            finally:
                folder.close()
        self.assertEqual(self.reader.read(self.exchange).chat, self.chat)

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

    async def test_record_shape_size_and_safe_end_diagnostics(self) -> None:
        """live.record-validation; live.record-privacy"""
        for field, bad in [("chat", "../x"), ("root", "another"), ("exchange", str(uuid4())),
                           ("rootContract", True), ("build", "00"), ("trunk", "../x"), ("workingFolder", "relative")]:
            with self.assertRaises(Error):
                record({**self.value, field: bad}, self.identity, self.exchange)
        for process in [{"pid": True, "startedAt": "2026-10-27T00:00:00Z"},
                        {"pid": 1, "startedAt": "2026-10-27T00:00:00"}]:
            with self.assertRaises(Error):
                record({**self.value, "process": process}, self.identity, self.exchange)
        self.value["end"] = {"state": "failed", "at": "2026-10-27T00:00:03Z",
            "error": {"code": "unknown_cause", "message": "opaquePrivateProof", "token": "private"}}
        self.save()
        result = self.reader.read(self.exchange, secrets=("opaquePrivateProof",))
        self.assertNotIn("opaquePrivateProof", str(result.end))
        self.assertNotIn("token", result.end["error"])  # type: ignore[index]
        (self.folder / "record.json").write_bytes(b" " * (MAX_RECORD + 1))
        with self.assertRaises(Error):
            self.reader.read(self.exchange)

    async def test_actual_ps_uses_only_clean_utc_environment_and_two_seconds_inclusive(self) -> None:
        """live.process-identity; live.process-environment"""
        actual = asyncio.create_subprocess_exec
        observed_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        async def observed(*args: Any, **kwargs: Any) -> Any:
            observed_calls.append((args, kwargs))
            return await actual(*args, **kwargs)
        with mock.patch.dict(os.environ, {"TZ": "Pacific/Honolulu", "LC_ALL": "fictional", "PGPASSWORD": "private"}):
            with mock.patch("arbol_backend.exchange_files.asyncio.create_subprocess_exec", side_effect=observed):
                starts = await processes({os.getpid()})
        start = starts[os.getpid()]
        assert start is not None
        self.assertEqual(start.tzinfo, UTC)
        self.assertEqual(observed_calls[0][0][0], "/bin/ps")
        self.assertEqual(observed_calls[0][1]["env"], {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"})
        self.value["process"]["startedAt"] = (start + timedelta(seconds=2)).isoformat()
        self.assertTrue(living(record(self.value, self.identity, self.exchange), starts))
        self.value["process"]["startedAt"] = (start + timedelta(seconds=2.001)).isoformat()
        self.assertFalse(living(record(self.value, self.identity, self.exchange), starts))
        self.assertEqual(await processes({2147483647}), {2147483647: None})
        self.assertEqual(await processes(set()), {})

    async def test_failed_ps_is_unknown_and_timeout_kills_only_its_read_only_group(self) -> None:
        """live.process-failure"""
        class Output:
            async def read(self, limit: int) -> bytes:
                await asyncio.sleep(1)
                return b""
        class Child:
            stdout = Output()
            returncode: int | None = None
            pid = 987654321
            async def wait(self) -> int:
                self.returncode = -9
                return -9
        child = Child()
        with mock.patch("arbol_backend.exchange_files.asyncio.create_subprocess_exec", return_value=child):
            with mock.patch("arbol_backend.exchange_files.os.killpg") as kill:
                with self.assertRaises(Error):
                    await processes({1}, seconds=0.01)
                self.assertEqual(kill.call_count, 1)
                self.assertEqual(kill.call_args.args[0], child.pid)
        class BadOutput:
            async def read(self, limit: int) -> bytes:
                return b"unexpected output"
        child.stdout = BadOutput()  # type: ignore[assignment]
        child.returncode = 0
        with mock.patch("arbol_backend.exchange_files.asyncio.create_subprocess_exec", return_value=child):
            with self.assertRaises(Error):
                await processes({1})
