"""Private subprocess fixture for the installation start regressions."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))

from arbol_backend import exchange_start  # noqa: E402
from arbol_backend.exchange_command import parse  # noqa: E402
from arbol_backend.exchange_context import Context  # noqa: E402
from arbol_backend.exchange_context import Refusal as Refusal  # noqa: E402
from arbol_backend.exchange_launcher import Reply  # noqa: E402
from arbol_backend.model import Identity  # noqa: E402
from arbol_installation.admission import GENERATION_ENV, STATE, directory, prepare_directory  # noqa: E402

EXCHANGE = "7f3a2c1e-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
ACCEPTED = {
    "accepted": True, "duplicate": False, "exchange": EXCHANGE,
    "chat": "7f3a2c1e-4b5d-4e6f-8a9b-0c1d2e3f4a5c", "number": 1, "trunk": "trivial", "build": "a",
}
POPEN = subprocess.Popen


class Starting(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="exchange-start-")
        self.addCleanup(temp.cleanup)
        home = Path(temp.name).resolve()
        self.bin = home / "bin with spaces"
        self.bin.mkdir()
        runtime = home / "runtime"
        self.context = Context(Identity("0", runtime, self.bin, home / ".arbol", None, home, home, ((1, 1),)))
        prepare_directory(runtime)
        # The receipt lookup is stubbed; no database is configured or contacted.
        # Exercise the real file permit and UUID lock against this fixture state.
        with directory(runtime) as folder:
            fd = os.open(STATE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=folder)
            with os.fdopen(fd, "w") as stream:
                json.dump({"format": 1, "state": "normal", "generation": "a" * 32, "release": "b" * 64,
                           "source": {"host": str(home / "socket"), "port": 5432, "database": "unused",
                                      "databaseOid": 1}, "session": None}, stream)
        standin = Path(__file__).with_name("exchange_trunk_standin.py").resolve()
        launcher = self.bin / "arbol-trunk"
        launcher.write_text("#!/bin/sh\nexec " + shlex.join([sys.executable, "-I", "-B", str(standin), str(self.bin)])
                            + ' "$@"\n')
        launcher.chmod(0o700)
        self.request = home / "request with spaces"
        self.request.write_bytes(b"\xff the coordinator must not parse this file")
        self.child: subprocess.Popen[bytes] | None = None
        self.addCleanup(self.clean_child)

    def clean_child(self) -> None:
        if self.child is not None:
            if self.child.poll() is None:
                self.child.kill()
            self.child.wait(timeout=5)

    def begin(self, *, timeout: float) -> Reply:
        command = parse(["start", "trivial", "-v", "a", "--exchange", EXCHANGE, "--request", str(self.request)])

        def spawn(args: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
            child: subprocess.Popen[bytes] = POPEN(args, **kwargs)
            self.child = child
            return child

        with patch.dict(os.environ, {GENERATION_ENV: "a" * 32}), patch.object(exchange_start, "receipt", return_value=None):
            with patch("arbol_backend.exchange_start.subprocess.Popen", side_effect=spawn):
                return exchange_start.start(self.context, command, timeout=timeout)

    def configure(self, mode: str) -> None:
        (self.bin / "reply.json").write_text(json.dumps({"mode": mode, "reply": ACCEPTED}) + "\n")

    def running_child(self) -> subprocess.Popen[bytes]:
        child = self.child
        assert child is not None, "The coordinator did not start a Trunk"
        self.assertIsNone(child.poll())
        self.assertEqual(os.getpgid(child.pid), child.pid)
        return child
