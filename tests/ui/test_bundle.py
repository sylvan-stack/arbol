"""Renderer identity/CSP/assets survive relocation and reject changed payloads."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("test_elma_bundle", ROOT / "tools/elma_bundle.py")
assert spec and spec.loader
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class Bundle(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name) / "relocated/ui/elma"
        (self.folder / "assets").mkdir(parents=True)
        (self.folder / "index.html").write_text(
            '<meta http-equiv="Content-Security-Policy" content="' + bundle.CSP + '">'
            '<script type="module" src="./assets/app.js"></script><link rel="stylesheet" href="./assets/app.css">'
        )
        (self.folder / "assets/app.js").write_text("/* fictional renderer */")
        (self.folder / "assets/app.css").write_text('@font-face{font-family:fixture;src:url("./ui.woff2")}')
        for name in ("ui.woff2", "mono.woff2"):
            (self.folder / "assets" / name).write_bytes(b"fictional font")
        (self.folder / "LICENSES.json").write_text("[]")
        self.sign()

    def sign(self) -> None:
        (self.folder / "bundle.json").write_text(json.dumps({"format": 1, "build": "9", "designSystem": {"commit": "a" * 40},
                                                            "files": bundle.payload(self.folder)}))

# TEST-TIER-DISABLED-BEGIN tests/ui/test_bundle.py::Bundle.test_relocated_local_assets_identity_and_every_file_hash
#     def test_relocated_local_assets_identity_and_every_file_hash(self) -> None:
#         """elma.package-relocation; elma.package-identity; elma.package-hashes"""
#         self.assertEqual(bundle.verify(self.folder, "9")["build"], "9")
#         with self.assertRaises(ValueError):
#             bundle.verify(self.folder, "a")
#         for path in (self.folder / "assets/app.js", self.folder / "assets/extra.js", self.folder / "nested/bundle.json"):
#             with self.subTest(path=path.name):
#                 previous = path.read_bytes() if path.exists() else None
#                 path.parent.mkdir(exist_ok=True)
#                 path.write_text("changed")
#                 with self.assertRaises(ValueError):
#                     bundle.verify(self.folder, "9")
#                 if previous is None:
#                     path.unlink()
#                 else:
#                     path.write_bytes(previous)
# TEST-TIER-DISABLED-END tests/ui/test_bundle.py::Bundle.test_relocated_local_assets_identity_and_every_file_hash

# TEST-TIER-DISABLED-BEGIN tests/ui/test_bundle.py::Bundle.test_resigned_external_inline_fonts_and_symlinks_are_rejected
#     def test_resigned_external_inline_fonts_and_symlinks_are_rejected(self) -> None:
#         """elma.package-csp; elma.package-fonts; elma.package-paths"""
#         index = self.folder / "index.html"
#         original = index.read_text()
#         for changed in (original.replace("script-src 'self'", "script-src * 'unsafe-eval'"),
#                         original.replace("./assets/app.js", "https://invalid.example/app.js"),
#                         original + "<script>fictional()</script>"):
#             with self.subTest(index=changed):
#                 index.write_text(changed)
#                 self.sign()
#                 with self.assertRaises(ValueError):
#                     bundle.verify(self.folder, "9")
#         index.write_text(original)
#         (self.folder / "assets/app.css").write_text('@font-face{src:url("https://invalid.example/font.woff2")}')
#         self.sign()
#         with self.assertRaises(ValueError):
#             bundle.verify(self.folder, "9")
#         (self.folder / "assets/escape.js").symlink_to(index)
#         with self.assertRaises(ValueError):
#             bundle.payload(self.folder)
# TEST-TIER-DISABLED-END tests/ui/test_bundle.py::Bundle.test_resigned_external_inline_fonts_and_symlinks_are_rejected
