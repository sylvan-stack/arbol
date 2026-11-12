"""Private Forester fixtures for C44; the probe reads no vendor protocol input."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from conformance.check import check, equal
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
           "tool_use_id": "normal-" + str(turn), "tool_input": {"command": "python --version"}}
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
        original = Path(home.tool_path).read_text().removeprefix("#!/bin/sh\n")
        Path(home.tool_path).write_text("#!/bin/sh\n" + shlex.quote(sys.executable) + " "
                                       + shlex.quote(str(self.root / "probe.py")) + ' "$@" || exit $?\n' + original)

    def results(self) -> list[dict[str, Any]]:
        return [json.loads(path.read_text()) for path in sorted(self.root.glob("turn-*.json"))]

    def ledger(self) -> list[dict[str, Any]]:
        return [json.loads(line) for path in sorted((self.root / "corpus/ledger").glob("*/*/*.jsonl"))
                for line in path.read_text().splitlines() if line]

    def shell_calls(self) -> list[dict[str, Any]]:
        return [json.loads(line) for path in sorted((self.root / "corpus/shell-calls").rglob("*.jsonl"))
                for line in path.read_text().splitlines() if line]

    def verify(self, chat: str) -> None:
        turns = self.results()
        equal("Two designated inference probes", len(turns), 2)
        booked = json.loads((self.root / "booking.json").read_text())
        equal("Stored UUID-only booking owner", booked["sessions"], ["arbol:" + chat])
        for turn in turns:
            equal("Probe requested chat", turn["chat"], chat)
            equal("Probe no Root", turn["root"], None)
            equal("Where exit", turn["where"]["exit"], 0)
            rows = json.loads(turn["where"]["stdout"])
            equal("Same booking across native sessions", [row["id"] for row in rows], [booked["id"]])
            equal("Normal hook", turn["normal"]["exit"], 0)
            equal("Managed Git refusal", turn["managed"]["exit"], 2)
            equal("Edit reaches Intention guard", turn["edit"]["exit"], 2)
            check("Booked path reaches Intention guard", "FOR-D38" in turn["edit"]["stderr"],
                  "FOR-D38 rather than an unbooked-path refusal", turn["edit"])
            equal("Native SessionEnd", turn["end"]["exit"], 0)
        check("Different native sessions", turns[0]["native"] != turns[1]["native"], "different sessions", turns)
        hooks = [row for row in self.ledger() if row["type"] == "hook"
                 and row["data"].get("arbolChat") == chat]
        for turn in turns:
            own = [row for row in hooks if row.get("agent") == "codex:" + turn["native"]]
            check("Normal hook by chat UUID", any(row["data"].get("verdict") == "ok" for row in own),
                  "normal hook event", own)
            check("Managed refusal by chat UUID", any(row["data"].get("rule") == "FOR-D112" for row in own),
                  "managed Git refusal hook event", own)
        calls = [row for row in self.shell_calls() if row.get("type") == "started" and row.get("arbolChat") == chat]
        check("Shell calls by chat UUID", len(calls) >= 4, "normal and managed calls across both sessions", calls)
        equal("Shell calls resolve UUID booking", sorted({row.get("booking") for row in calls}), [booked["id"]])
        self.verify_legacy()
        destination = os.environ.get("ASD14_EVIDENCE_DIR")
        if destination:
            target = Path(destination)
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copytree(self.root, target / "forester", dirs_exist_ok=True)

    def verify_legacy(self) -> None:
        import uuid

        root = self.root / "legacy"
        root.mkdir()
        checkout, corpus, remote = root / "checkout", root / "corpus", root / "remote.git"
        for folder in (checkout, corpus):
            folder.mkdir()
            command(["git", "init", "-b", "main"], folder)
        for name in ("owned.txt", "other.txt"):
            (checkout / name).write_text("retained\n")
        command(["git", "add", "owned.txt", "other.txt"], checkout)
        command(["git", "commit", "-m", "Initial legacy fixture"], checkout)
        (corpus / "README.md").write_text("Private legacy ownership qualification.\n")
        command(["git", "add", "README.md"], corpus)
        command(["git", "commit", "-m", "Initial private history corpus"], corpus)
        command(["git", "init", "--bare", str(remote)], root)
        command(["git", "remote", "add", "origin", str(remote)], corpus)
        command(["git", "push", "-u", "origin", "main"], corpus)
        config = root / "mycel.toml"
        config.write_text('[repos.legacy]\nenabled = false\ncode_root = ' + json.dumps(str(checkout))
                          + '\nartifact_root = ' + json.dumps(str(root / "artifacts")) + '\n')
        env = {**os.environ, "FORESTER_ROOT": str(corpus), "MYCEL_CONFIG": str(config)}
        for key in ("ARBOL_ROOT", "ARBOL_CHAT", "CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID"):
            env.pop(key, None)
        journal: list[dict[str, Any]] = []

        def call(arguments: list[str], status: int = 0) -> dict[str, Any]:
            result = subprocess.run([self.entry, *arguments], cwd=checkout, env=env,
                                    capture_output=True, text=True, timeout=45)
            item = {"arguments": arguments, "exit": result.returncode,
                    "stdout": result.stdout, "stderr": result.stderr}
            journal.append(item)
            (root / "commands.json").write_text(json.dumps(journal, indent=2))
            equal("Legacy command exit", result.returncode, status)
            return item

        chat = str(uuid.uuid4())
        owners = ["legacy-a/" + chat, "legacy-b/" + chat]
        historical: list[tuple[str, str]] = []
        for owner in owners:
            booked = json.loads(call(["book", "--for", "C44 legacy history", "--files", "legacy:owned.txt",
                                      "--tool", "arbol", "--session", owner])["stdout"])
            equal("Recorded legacy owner", booked["sessions"], ["arbol:" + owner])
            call(["release", "--booking", booked["id"], "--tool", "arbol", "--session", owner])
            historical.append((booked["id"], owner))
        for booking, owner in historical:
            history = json.loads(call(["history", "--booking", booking, "--json"])["stdout"])
            opened = [row for row in history["bookingRecords"] if row["type"] == "booking.opened"]
            equal("Exact historical owner lookup", [row["data"]["sessions"] for row in opened], [["arbol:" + owner]])
        live = json.loads(call(["book", "--for", "C44 live legacy settlement", "--files", "legacy:owned.txt",
                                "--tool", "arbol", "--session", owners[0]])["stdout"])
        call(["intend", "--files", "legacy:owned.txt", "--no-origin", "Disposable legacy qualification",
              "--why", "Verify open Intention settlement", "--tool", "arbol", "--session", owners[0]])
        refused = call(["release", "--booking", live["id"], "--tool", "arbol", "--session", owners[0]], 1)
        check("Open legacy Intention blocks release", "Intention" in refused["stderr"], "Intention refusal", refused)
        env["ARBOL_CHAT"] = chat
        uuid_booking = json.loads(call(["book", "--for", "C44 UUID-only owner", "--files", "legacy:other.txt"])["stdout"])
        equal("New owner remains UUID-only", uuid_booking["sessions"], ["arbol:" + chat])
        refused = call(["release", "--booking", live["id"]], 1)
        check("UUID cannot claim legacy booking", "another session" in refused["stderr"], "owner refusal", refused)
        call(["release", "--booking", uuid_booking["id"]])
        env.pop("ARBOL_CHAT")
        call(["intend", "--close", "dropped", "--tool", "arbol", "--session", owners[0]])
        call(["release", "--booking", live["id"], "--tool", "arbol", "--session", owners[0]])
        history = json.loads(call(["history", "--booking", live["id"], "--json"])["stdout"])
        released = [row for row in history["bookingRecords"] if row["type"] == "booking.released"]
        equal("Released owner remains exact", [row["data"]["booking"]["sessions"] for row in released],
              [["arbol:" + owners[0]]])
        written = json.loads(call(["history", "--booking", live["id"], "--write"])["stdout"])
        tip = command(["git", "ls-remote", "origin", "refs/heads/main"], corpus).split()[0]
        equal("History published to local remote", tip, written["commit"])
        tracked = command(["git", "ls-tree", "-r", "--name-only", tip], corpus).splitlines()
        check("Settlement history reaches remote", written["path"] in tracked, "published history path", tracked)
        equal("All private legacy bookings settled", json.loads((corpus / "holds.json").read_text())["bookings"], [])
