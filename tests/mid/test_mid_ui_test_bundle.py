
# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_ui_test_bundle.py::Bundle.test_relocated_local_assets_identity_and_every_file_hash
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: elma.package-relocation; elma.package-identity; elma.package-hashes
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_ui_test_bundle.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_ui_test_bundle.py::Bundle.test_resigned_external_inline_fonts_and_symlinks_are_rejected
# Reason: Reviewed backend source and fixture: straightforward projection/validation, ordinary state transitions or a repeated variant of retained concurrency, durable recovery, isolation and unsafe-file checks; no distinct consequential observation beyond those selections. Case reviewed: elma.package-csp; elma.package-fonts; elma.package-paths
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_ui_test_bundle.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END
