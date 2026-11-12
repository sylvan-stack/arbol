"""Private Forester fixtures for C44; the probe reads no vendor protocol input."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from conformance.check import check
from conformance.harness import ScenarioHome

PROBE = r'''
import json, os, subprocess, sys
from pathlib import Path
root = Path(__file__).resolve().parent
chat = os.environ.get("ARBOL_CHAT")
if not chat or not ("-p" in sys.argv or sys.argv[1:] == ["app-server"]):
    raise SystemExit(0)
settings = json.loads((root / "inputs.json").read_text())
os.environ["FORESTER_ROOT"] = str(root / "corpus")
os.environ["MYCEL_CONFIG"] = str(root / "mycel.toml")
marker = root / "booking.json"
turn = 2 if marker.exists() else 1
native = "c44-native-" + str(turn)
os.environ["CODEX_THREAD_ID"] = native
os.environ["CLAUDE_CODE_SESSION_ID"] = native

def call(args, payload=None):
    result = subprocess.run([settings["entry"], *args], cwd=root / "checkout", env=os.environ,
                            input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True, timeout=45)
    return {"exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr}

if turn == 1:
    booked = call(["book", "--for", "C44 chat ownership", "--files", "fixture:owned.txt"])
    if booked["exit"] != 0:
        (root / "failure.json").write_text(json.dumps(booked))
        raise SystemExit(1)
    marker.write_text(booked["stdout"])
where = call(["where"])
payload = {"session_id": native, "cwd": str(root / "checkout"), "tool_name": "Bash",
           "tool_use_id": "normal-" + str(turn), "tool_input": {"command": "printf qualified"}}
normal = call(["hook", "pre-tool-use", "--tool", "codex"], payload)
payload["tool_use_id"] = "managed-" + str(turn)
payload["tool_input"] = {"command": "git commit -m qualified"}
managed = call(["hook", "pre-tool-use", "--tool", "codex"], payload)
payload["tool_name"] = "Edit"
payload["tool_input"] = {"file_path": str(root / "checkout/owned.txt"), "old_string": "old", "new_string": "new"}
edit = call(["hook", "pre-tool-use", "--tool", "codex"], payload)
end = call(["hook", "session-end", "--tool", "codex"], {"session_id": native, "cwd": str(root / "checkout")})
(root / ("turn-" + str(turn) + ".json")).write_text(json.dumps({"chat": chat, "root": os.environ.get("ARBOL_ROOT"),
    "native": native, "where": where, "normal": normal, "managed": managed, "edit": edit, "end": end}))
'''


def command(arguments: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(arguments, cwd=cwd, env=env, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(f"Fixture command failed: {arguments[0]}: {result.stderr}")
    return result.stdout


class ForesterProbe:
    def __init__(self, home: ScenarioHome) -> None:
        raw = os.environ.get("ASD14_FORESTER_ENTRY", "")
        check("Pinned Forester CLI", bool(raw) and Path(raw).is_absolute() and Path(raw).is_file(),
              "ASD14_FORESTER_ENTRY names the absolute pinned CLI", raw)
        self.entry = raw
        self.root = Path(home.home) / "forester-probe"
        self.root.mkdir(mode=0o700)
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        command(["git", "init", "-b", "main"], self.checkout)
        (self.checkout / "owned.txt").write_text("old\n")
        command(["git", "add", "owned.txt"], self.checkout)
        command(["git", "commit", "-m", "Initial fixture"], self.checkout)
        (self.root / "inputs.json").write_text(json.dumps({"entry": raw}))
        (self.root / "mycel.toml").write_text(
            '[repos.fixture]\nenabled = true\ncode_root = ' + json.dumps(str(self.checkout))
            + '\nartifact_root = ' + json.dumps(str(self.root / "fixture-artifacts")) + '\n')
        (self.root / "probe.py").write_text(PROBE)
        original = Path(home.tool_path).read_text().split("exec ", 1)[1]
        Path(home.tool_path).write_text("#!/bin/sh\n" + shlex.quote(sys.executable) + " "
                                       + shlex.quote(str(self.root / "probe.py")) + ' "$@" || exit $?\nexec ' + original)

    def results(self) -> list[dict[str, Any]]:
        return [json.loads(path.read_text()) for path in sorted(self.root.glob("turn-*.json"))]

    def ledger(self) -> list[dict[str, Any]]:
        return [json.loads(line) for path in sorted((self.root / "corpus/ledger").glob("*/*/*.jsonl"))
                for line in path.read_text().splitlines() if line]

    def shell_calls(self) -> list[dict[str, Any]]:
        return [json.loads(line) for path in sorted((self.root / "corpus/shell-calls").rglob("*.jsonl"))
                for line in path.read_text().splitlines() if line]
