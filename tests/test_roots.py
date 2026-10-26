"""The global Root catalogue: private homes and stand-ins, with a separate real-server example (SYL-160)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arbol_roots.model import Refused, catalogue, places, save_record  # noqa: E402

ENTRY = ROOT / "bin/roots_entry.py"
ENV = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}


def record(name: str = "sapling", state: str = "preparing", created: str = "2026-10-26T09:00:00.000Z",
           version: int = 1) -> dict[str, Any]:
    value: dict[str, Any] = {"root": name, "name": name.title(), "status": state, "createdAt": created,
                             "database": "arbol_" + name, "app": "0", "rootContract": version}
    if state == "failed":
        value["failed"] = {"at": created, "reason": "private failure"}
    return value


class Catalogue(unittest.TestCase):
    def test_roots_frame_has_json_help_and_refuses_bad_command_lines_without_side_effects(self) -> None:
        """roots.cli: command counts, identifiers and inapplicable options fail as JSON before any work."""
        with tempfile.TemporaryDirectory() as home:
            for arguments in ([], ["unknown"], ["list", "extra"], ["ready", "../bad"],
                              ["list", "--name", "no"], ["create", "sapling", "--unknown", "x"],
                              ["show", "--roots-dir"]):
                result = subprocess.run([sys.executable, "-I", "-B", str(ENTRY), *arguments],
                                        env={**ENV, "HOME": home}, capture_output=True, timeout=20, check=False)
                self.assertEqual(result.returncode, 1, arguments)
                self.assertEqual(json.loads(result.stdout)["error"]["code"], "invalid_input", arguments)
                self.assertEqual(result.stderr, b"", arguments)
                self.assertEqual(os.listdir(home), [], arguments)
            result = subprocess.run([sys.executable, "-I", "-B", str(ENTRY), "--help"],
                                    env={**ENV, "HOME": home}, capture_output=True, timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("arbol-roots create", json.loads(result.stdout)["usage"])

    def test_roots_atomic_record_writes_validate_fields_preserve_extras_and_leave_no_temporary_file(self) -> None:
        """roots.record: complete records, compatible metadata and invalid writes use the shared header format."""
        with tempfile.TemporaryDirectory() as home:
            paths = places({"--roots-dir": str(Path(home, "roots"))})
            (paths.roots / "sapling").mkdir(parents=True)
            value = {**record(), "future": {"retained": True}}
            save_record(paths, value, complete=True)
            self.assertEqual(catalogue(paths), [value])
            self.assertEqual(list((paths.roots / "sapling").iterdir()), [paths.roots / "sapling/root.json"])
            before = (paths.roots / "sapling/root.json").read_bytes()
            for patch in ({"root": "../other"}, {"name": " "}, {"database": "postgres"}, {"database": "x" * 64},
                          {"app": "01"}, {"rootContract": 0}, {"grewFrom": "sapling"},
                          {"status": "failed", "failed": {"at": "invalid", "reason": "x"}}):
                with self.subTest(patch=patch), self.assertRaises(Refused):
                    save_record(paths, {**value, **patch}, complete=True)
                self.assertEqual((paths.roots / "sapling/root.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
