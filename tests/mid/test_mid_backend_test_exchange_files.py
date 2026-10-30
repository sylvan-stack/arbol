"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_exchange_files as _support
from backend.test_exchange_files import (
    Error,
    os,
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

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_exchange_files.py::Files.test_valid_records_truthful_states_unknown_fields_and_immutable_identity
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: live.records; live.states
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_exchange_files.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_valid_records_truthful_states_unknown_fields_and_immutable_identity(self) -> None:
#         """live.records; live.states"""
#         self.value["future"] = {"extra": "ignored"}
#         self.save()
#         item = self.reader.read(self.exchange)
#         self.assertEqual(item.status(True)["state"], "accepting")  # type: ignore[index]
#         self.assertIsNone(item.status(False))
#         self.value["acceptedAt"] = "2026-10-27T00:00:01Z"
#         self.value["signsOfLife"]["waitingFor"] = "future_wait"
#         self.save()
#         item = self.reader.read(self.exchange)
#         self.assertEqual(item.status(True)["waitingFor"], "future_wait")  # type: ignore[index]
#         self.assertEqual(item.status(False)["state"], "gone")  # type: ignore[index]
#         self.assertEqual(item.status(True, stopping=True)["state"], "stopping")  # type: ignore[index]
#         self.value["end"] = {"state": "future_end", "at": "2026-10-27T00:00:02Z"}
#         self.save()
#         item = self.reader.read(self.exchange)
#         self.assertEqual(item.status(True)["state"], "ending")  # type: ignore[index]
#         self.assertEqual(item.status(False)["state"], "unsaved")  # type: ignore[index]
#         self.assertEqual(item.end, {"state": "future_end", "at": "2026-10-27T00:00:02.000Z"})
#         self.value["process"]["pid"] += 1
#         self.save()
#         with self.assertRaises(Error):
#             self.reader.read(self.exchange)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_exchange_files.py::Files.test_record_shape_size_and_safe_end_diagnostics
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: live.record-validation; live.record-privacy
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_exchange_files.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_record_shape_size_and_safe_end_diagnostics(self) -> None:
#         """live.record-validation; live.record-privacy"""
#         for field, bad in [("chat", "../x"), ("root", "another"), ("exchange", str(uuid4())),
#                            ("rootContract", True), ("build", "00"), ("trunk", "../x"), ("workingFolder", "relative")]:
#             with self.assertRaises(Error):
#                 record({**self.value, field: bad}, self.identity, self.exchange)
#         for process in [{"pid": True, "startedAt": "2026-10-27T00:00:00Z"},
#                         {"pid": 1, "startedAt": "2026-10-27T00:00:00"}]:
#             with self.assertRaises(Error):
#                 record({**self.value, "process": process}, self.identity, self.exchange)
#         self.value["end"] = {"state": "failed", "at": "2026-10-27T00:00:03Z",
#             "error": {"code": "unknown_cause", "message": "opaquePrivateProof", "token": "private"}}
#         self.save()
#         result = self.reader.read(self.exchange, secrets=("opaquePrivateProof",))
#         self.assertNotIn("opaquePrivateProof", str(result.end))
#         self.assertNotIn("token", result.end["error"])  # type: ignore[index]
#         (self.folder / "record.json").write_bytes(b" " * (MAX_RECORD + 1))
#         with self.assertRaises(Error):
#             self.reader.read(self.exchange)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_exchange_files.py::Files.test_actual_ps_uses_only_clean_utc_environment_and_two_seconds_inclusive
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: live.process-identity; live.process-environment
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_exchange_files.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_actual_ps_uses_only_clean_utc_environment_and_two_seconds_inclusive(self) -> None:
#         """live.process-identity; live.process-environment"""
#         actual = asyncio.create_subprocess_exec
#         observed_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
#         async def observed(*args: Any, **kwargs: Any) -> Any:
#             observed_calls.append((args, kwargs))
#             return await actual(*args, **kwargs)
#         with mock.patch.dict(os.environ, {"TZ": "Pacific/Honolulu", "LC_ALL": "fictional", "PGPASSWORD": "private"}):
#             with mock.patch("arbol_backend.exchange_files.asyncio.create_subprocess_exec", side_effect=observed):
#                 starts = await processes({os.getpid()})
#         start = starts[os.getpid()]
#         assert start is not None
#         self.assertEqual(start.tzinfo, UTC)
#         self.assertEqual(observed_calls[0][0][0], "/bin/ps")
#         self.assertEqual(observed_calls[0][1]["env"], {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"})
#         self.value["process"]["startedAt"] = (start + timedelta(seconds=2)).isoformat()
#         self.assertTrue(living(record(self.value, self.identity, self.exchange), starts))
#         self.value["process"]["startedAt"] = (start + timedelta(seconds=2.001)).isoformat()
#         self.assertFalse(living(record(self.value, self.identity, self.exchange), starts))
#         self.assertEqual(await processes({2147483647}), {2147483647: None})
#         self.assertEqual(await processes(set()), {})
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_exchange_files.py::Files.test_failed_ps_is_unknown_and_timeout_kills_only_its_read_only_group
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: live.process-failure
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_exchange_files.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_failed_ps_is_unknown_and_timeout_kills_only_its_read_only_group(self) -> None:
#         """live.process-failure"""
#         class Output:
#             async def read(self, limit: int) -> bytes:
#                 await asyncio.sleep(1)
#                 return b""
#         class Child:
#             stdout = Output()
#             returncode: int | None = None
#             pid = 987654321
#             async def wait(self) -> int:
#                 self.returncode = -9
#                 return -9
#         child = Child()
#         with mock.patch("arbol_backend.exchange_files.asyncio.create_subprocess_exec", return_value=child):
#             with mock.patch("arbol_backend.exchange_files.os.killpg") as kill:
#                 with self.assertRaises(Error):
#                     await processes({1}, seconds=0.01)
#                 self.assertEqual(kill.call_count, 1)
#                 self.assertEqual(kill.call_args.args[0], child.pid)
#         class BadOutput:
#             async def read(self, limit: int) -> bytes:
#                 return b"unexpected output"
#         child.stdout = BadOutput()  # type: ignore[assignment]
#         child.returncode = 0
#         with mock.patch("arbol_backend.exchange_files.asyncio.create_subprocess_exec", return_value=child):
#             with self.assertRaises(Error):
#                 await processes({1})
# LOW-TIER-SOURCE-END
# LOW-TIER-END
