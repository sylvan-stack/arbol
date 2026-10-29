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
