# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
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
