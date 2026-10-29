"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_note_files as _support
from backend.test_note_files import (
    Error,
    Files,
    Frame,
    MAX_NOTE,
    NoteFiles,
    Params,
    Path,
    ROOT,
    chat,
    identity,
    json,
    mock,
    os,
    parse,
    sys,
    unittest,
    uuid4,
)


class Files(_support.Files):

# TEST-TIER-BEGIN tests/backend/test_note_files.py::Files.test_crash_after_link_preserves_a_complete_note_and_repairs_only_its_verified_temp_link
    def test_crash_after_link_preserves_a_complete_note_and_repairs_only_its_verified_temp_link(self) -> None:
        """notes.crash-publication; notes.verified-temp-recovery"""
        unlink = os.unlink
        def crash(name: str, **kwargs: int) -> None:
            if name.endswith(".new"):
                raise OSError("private simulated crash before temporary unlink")
            unlink(name, **kwargs)
        with mock.patch("arbol_backend.note_files.os.unlink", side_effect=crash):
            with self.assertRaises(OSError):
                self.files.put(self.value)
        self.assertEqual(self.path.stat().st_nlink, 2)
        self.assertEqual(json.loads(self.path.read_bytes()), self.value)
        self.assertEqual(self.files.read(chat(900)).value, self.value)
        self.assertEqual(self.path.stat().st_nlink, 1)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        outside = self.frame.base / "unrelated-hardlink"
        os.link(self.path, outside)
        with self.assertRaises(Error):
            self.files.read(chat(900))
        self.assertTrue(outside.exists())
        self.assertTrue(self.path.exists())
# TEST-TIER-END tests/backend/test_note_files.py::Files.test_crash_after_link_preserves_a_complete_note_and_repairs_only_its_verified_temp_link


# TEST-TIER-BEGIN tests/backend/test_note_files.py::Files.test_conditional_removal_preserves_file_or_directory_replacement
    def test_conditional_removal_preserves_file_or_directory_replacement(self) -> None:
        """notes.conditional-removal; notes.directory-identity"""
        note = self.files.put(self.value)
        original = self.path.with_suffix(".old")
        self.path.rename(original)
        self.path.write_bytes(original.read_bytes())
        self.path.chmod(0o600)
        with self.assertRaises(Error):
            self.files.remove(note)
        self.assertTrue(self.path.exists())
        note = self.files.read(chat(900))
        renamed = self.path.parent.with_name("old-notes")
        self.path.parent.rename(renamed)
        self.path.parent.mkdir(mode=0o700)
        self.path.write_text(json.dumps(self.value))
        self.path.chmod(0o600)
        with self.assertRaises(Error):
            self.files.remove(note)
        self.assertTrue(self.path.exists())
        self.assertTrue((renamed/self.path.name).exists())
# TEST-TIER-END tests/backend/test_note_files.py::Files.test_conditional_removal_preserves_file_or_directory_replacement

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_note_files.py::Files.test_private_atomic_publication_repeat_and_first_timestamp
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: notes.private-file; notes.atomic-publication; notes.first-timestamp
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_note_files.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_private_atomic_publication_repeat_and_first_timestamp(self) -> None:
#         """notes.private-file; notes.atomic-publication; notes.first-timestamp"""
#         note = self.files.put(self.value)
#         self.assertEqual(note.value, self.value)
#         self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
#         self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
#         self.assertEqual(self.path.stat().st_nlink, 1)
#         self.assertEqual(list(self.path.parent.iterdir()), [self.path])
#         raw = self.path.read_bytes()
#         self.assertEqual(self.files.put({**self.value, "at": "2026-10-27T01:03:00.000Z"}).value, self.value)
#         self.assertEqual(self.path.read_bytes(), raw)
#         with self.assertRaises(Error):
#             self.files.put({**self.value, "chat": chat(2)})
#         self.assertEqual(self.path.read_bytes(), raw)
#         self.files.remove(note)
#         self.assertFalse(self.path.exists())
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_note_files.py::Files.test_short_write_and_racing_different_note_never_publish_or_overwrite
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: notes.short-write; notes.no-overwrite
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_note_files.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_short_write_and_racing_different_note_never_publish_or_overwrite(self) -> None:
#         """notes.short-write; notes.no-overwrite"""
#         with mock.patch("arbol_backend.note_files.os.write", return_value=1):
#             with self.assertRaises(Error):
#                 self.files.put(self.value)
#         self.assertFalse(self.path.exists())
#         self.assertEqual(list(self.path.parent.iterdir()), [])
#         other = {**self.value, "chat": chat(2)}
#         def winner(*args: object, **kwargs: object) -> None:
#             self.path.write_text(json.dumps(other))
#             self.path.chmod(0o600)
#             raise FileExistsError
#         with mock.patch("arbol_backend.note_files.os.link", side_effect=winner):
#             with self.assertRaises(Error):
#                 self.files.put(self.value)
#         self.assertEqual(json.loads(self.path.read_bytes()), other)
#         self.assertEqual(list(self.path.parent.iterdir()), [self.path])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_note_files.py::Files.test_no_follow_private_regular_and_bounded_validated_contents
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: notes.file-boundaries; notes.invalid-file
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_note_files.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_no_follow_private_regular_and_bounded_validated_contents(self) -> None:
#         """notes.file-boundaries; notes.invalid-file"""
#         self.files.put(self.value)
#         self.path.chmod(0o644)
#         with self.assertRaises(Error):
#             self.files.read(chat(900))
#         self.path.chmod(0o600)
#         for value in (b"{"+b"x"*MAX_NOTE, json.dumps({**self.value, "root": "another"}).encode(),
#                       json.dumps({**self.value, "exchange": "../escape"}).encode(), b'{"root":1,"root":2}',
#                       b'{"future":NaN}', b"["*1500+b"0"+b"]"*1500):
#             self.path.write_bytes(value)
#             with self.assertRaises(Error):
#                 self.files.read(chat(900))
#         self.path.unlink()
#         os.mkfifo(self.path, 0o600)
#         with self.assertRaises(Error):
#             self.files.read(chat(900))
#         self.path.unlink()
#         outside = self.frame.base / "outside"
#         outside.write_text(json.dumps(self.value))
#         outside.chmod(0o600)
#         self.path.symlink_to(outside)
#         with self.assertRaises(OSError):
#             self.files.read(chat(900))
#         self.assertEqual(json.loads(outside.read_bytes()), self.value)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_backend_test_note_files.py::Files.test_temp_recovery_rejects_unknown_extra_links_and_unsafe_directory
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: notes.unknown-hardlink; notes.directory-no-follow
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_backend_test_note_files.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_temp_recovery_rejects_unknown_extra_links_and_unsafe_directory(self) -> None:
#         """notes.unknown-hardlink; notes.directory-no-follow"""
#         self.files.put(self.value)
#         temporary = self.path.parent / ("."+chat(900)+"."+uuid4().hex+".new")
#         os.link(self.path, temporary)
#         other = self.frame.base / "another-link"
#         os.link(self.path, other)
#         with self.assertRaises(Error):
#             self.files.read(chat(900))
#         self.assertTrue(temporary.exists())
#         self.assertTrue(other.exists())
#         self.path.parent.rename(self.frame.root / "old-notes")
#         self.path.parent.symlink_to(self.frame.root / "old-notes", target_is_directory=True)
#         with self.assertRaises(OSError):
#             self.files.read(chat(900))
# LOW-TIER-SOURCE-END
# LOW-TIER-END
