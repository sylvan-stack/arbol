"""Commented mid-tier selections; see MID_TIER.md before restoring a case."""

# Restore the needed imports and class header only for an explicit testing task.
# import ui.test_bundle as _support
# from ui.test_bundle import (
#     Bundle,
#     Path,
#     ROOT,
#     bundle,
#     importlib,
#     json,
#     spec,
#     tempfile,
#     unittest,
# )


# class Bundle(_support.Bundle):
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


raise RuntimeError("Mid-tier tests require an explicitly requested testing task; see MID_TIER.md.")
