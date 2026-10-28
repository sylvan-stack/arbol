"""Installed BKD journeys: private evidence, test-state forwarding and bounded spending.

Run individual cases deliberately. This module never starts a vendor request itself.
It imports no Root, Trunk or Driver implementation; those boundaries are installed CLIs.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import shlex
import signal
import stat
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

CASES = {
    "first-path": ("BKD-0.12", "BKD-0.14", "BKD-0.26", "BKD-1.5", "BKD-2.5", "BKD-2.11"),
    "actions": tuple(f"BKD-2.{n}" for n in (7, 8, 9, 10, 17, 18, 20)),
    "root-states": ("BKD-0.2", "BKD-2.1"),
    "stop": ("BKD-0.16", "BKD-2.12", "BKD-2.13"),
    "gone": ("BKD-0.14", "BKD-0.18", "BKD-2.16"),
    "stuck": ("BKD-0.19", "BKD-0.20", "BKD-2.16", "ARC-3.10"),
    "database-away": ("BKD-0.23", "BKD-0.24", "BKD-2.21"),
    "restart": ("BKD-0.21", "BKD-0.22", "BKD-1.7", "BKD-2.22"),
    "space": ("BKD-0.27", "BKD-0.28", "BKD-2.21"),
    "reimport": ("BKD-0.33", "BKD-1.13", "BKD-2.24"),
}


class Refused(RuntimeError):
    """A journey precondition failed; inspect evidence instead of blindly retrying."""


def require(value: object, message: str) -> None:
    if not value:
        raise Refused(message)


def private_json(path: Path, value: Any) -> None:
    """Publish a new receipt without replacing an earlier attempt."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


class Budget:
    """Five individually reserved attempts; uncertain submissions never get refunded."""

    def __init__(self, folder: Path):
        self.folder, self.limit = folder, 5

    def reserve(self, case: str, prompt: str) -> str:
        require(case in CASES and bool(prompt), "Name a known case and its exact prompt.")
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.folder / "budget.jsonl", os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            require(stat.S_ISREG(os.fstat(fd).st_mode), "The budget journal must be a regular file.")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.lseek(fd, 0, os.SEEK_SET)
            with os.fdopen(os.dup(fd), "rb") as source:
                data = source.read()
            require(not data or data.endswith(b"\n"), "An incomplete reservation requires reconciliation.")
            try:
                rows = [json.loads(line) for line in data.splitlines()]
                require(all(isinstance(row, dict) and row.get("version") == 1
                            and row.get("state") == "reserved" and row.get("case") in CASES
                            and str(uuid.UUID(row["attempt"])) == row["attempt"] for row in rows),
                        "Unknown reservation history requires reconciliation.")
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                raise Refused("Unreadable reservation history requires reconciliation.") from error
            require(len({row["attempt"] for row in rows}) == len(rows), "Duplicate reservation history.")
            require(len(rows) < self.limit, "The five-submission ceiling is exhausted.")
            require(not any(row["case"] == case for row in rows), "This case already reserved a submission; inspect it.")
            attempt = str(uuid.uuid4())
            row = {"version": 1, "attempt": attempt, "case": case, "state": "reserved",
                   "at": time.time(), "prompt": prompt}
            data = (json.dumps(row, allow_nan=False) + "\n").encode()
            require(os.write(fd, data) == len(data), "The reservation was not fully written.")
            os.fsync(fd)
            return attempt
        finally:
            os.close(fd)


class Frame:
    def __init__(self, evidence: Path, home: Path | None = None):
        self.home = home or Path.home()
        self.evidence = evidence
        evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(evidence.stat().st_mode & 0o077 == 0, "Evidence must be private.")
        self.bin = evidence / "bin"
        self.env = {"HOME": str(self.home), "USER": os.environ.get("USER", ""),
                    "LOGNAME": os.environ.get("LOGNAME", ""), "TERM": "xterm-256color"}
        self.children: list[subprocess.Popen[bytes]] = []

    def command(self, *arguments: str, timeout: float = 30) -> Any:
        result = subprocess.run(["/bin/zsh", "-l", "-c", shlex.join(arguments)], env=self.env,
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
        require(result.returncode == 0, "An installed command refused; inspect its private receipt.")
        return json.loads(result.stdout)

    def preflight(self) -> dict[str, Any]:
        roots = self.command("arbol-roots", "list")
        result: dict[str, Any] = {"roots": [], "drivers": []}
        for root in roots:
            listing = self.command("arbol-root", "--root", root["root"], "list")
            require(listing.get("exchanges") == [] and listing.get("unreadable") == [],
                    "An active or unreadable retained Exchange prevents a fresh drill.")
            result["roots"].append({"root": root["root"], "status": root["status"],
                                    "build": listing["rootBuild"], "current": root.get("current", False)})
        for name, account in (("claude", "test-anthropic"), ("codex", "test-chatgpt")):
            base = self.home / "Library/Application Support/Arbol/drivers"
            state = base / ("arbol-" + name + "-driver")
            for directory in (state / "runs", base / name / "runs"):
                require(directory.is_dir() and not list(directory.iterdir()), "An existing Driver run prevents a drill.")
            subscriptions = self.command("arbol-" + name + "-driver", "subscriptions", "list", "--state-dir", str(state))
            require(any(row.get("id") == account and row.get("state") == "signed_in" for row in subscriptions),
                    "The required test Subscription is not signed in.")
            result["drivers"].append({"driver": name, "subscription": account, "state": "signed_in"})
        return result

    def forwarders(self) -> None:
        """Forward actual installed programs; only supported isolation options are added."""
        self.bin.mkdir(mode=0o700, exist_ok=False)
        installed = self.home / ".local/bin"
        for name in ("arbol-roots", "arbol-trunk"):
            require((installed / name).is_file(), "An installed launcher is missing.")
            (self.bin / name).symlink_to(installed / name)
        for name in ("arbol-root", "arbol-claude-driver", "arbol-codex-driver"):
            require((installed / name).is_file(), "An installed launcher is missing.")
            extra = ["--bin-dir", str(self.bin)] if name == "arbol-root" else [
                "--state-dir", str(self.home / "Library/Application Support/Arbol/drivers" / name)]
            source = ("#!/usr/bin/env python3\nimport os,sys,json,time\n"
                      + "args=sys.argv[1:]\n"
                      + f"extra={extra!r}\n"
                      + "if any(x.split('=',1)[0] == extra[0] for x in args): raise SystemExit(98)\n"
                      + f"fd=os.open({str(self.evidence / 'forwarded.jsonl')!r},os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)\n"
                      + f"os.write(fd,(json.dumps({{'program':{name!r},'args':args,'at':time.time()}})+'\\n').encode());os.close(fd)\n"
                      + f"os.execv({str(installed / name)!r},[{str(installed / name)!r},*args,*extra])\n")
            path = self.bin / name
            path.write_text(source)
            path.chmod(0o700)

    def start(self, root: str = "sapling") -> dict[str, Any]:
        """A clean login shell starts the installed Backend by name, on its real Root."""
        args = ["arbol", "--root", root, "backend", "--bin-dir", str(self.bin)]
        child = subprocess.Popen(["/bin/zsh", "-l", "-c", "exec " + shlex.join(args)], env=self.env,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True)
        self.children.append(child)
        import select
        assert child.stdout is not None
        require(bool(select.select([child.stdout], [], [], 10)[0]),
                "The installed Backend did not give its ready receipt.")
        ready = json.loads(child.stdout.readline())
        require(isinstance(ready, dict), "The ready receipt must be an object.")
        assert isinstance(ready, dict)
        require(ready.get("ready") is True and ready.get("root") == root, "The installed Backend refused startup.")
        private_json(self.evidence / "backend-ready.json", ready)
        return ready

    def relay(self, folder: Path, root: str = "sapling") -> str:
        child = subprocess.Popen([str(folder / "runtime/python/bin/python3.14"), "-I", "-B",
                                  str(folder / "tools/bridge_relay.py"), "--root", root], env=self.env,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True)
        self.children.append(child)
        import select
        assert child.stdout is not None
        require(bool(select.select([child.stdout], [], [], 10)[0]),
                "The packaged development relay did not give its private address.")
        url = child.stdout.readline().decode().strip()
        require(url.startswith("http://127.0.0.1:"), "The relay did not select loopback.")
        return url

    def close(self) -> list[dict[str, Any]]:
        receipts = []
        for child in reversed(self.children):
            began = time.monotonic()
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
            out, err = child.communicate(timeout=8)
            receipts.append({"pid": child.pid, "status": child.returncode, "seconds": time.monotonic() - began,
                             "stdoutQuiet": not out, "stderrQuiet": not err})
        self.children.clear()
        return receipts


class Bridge:
    """One installed Unix connection, with concurrent correlated calls and event capture."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer
        self.calls: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.events: list[dict[str, Any]] = []
        self.task = asyncio.create_task(self.read())

    @classmethod
    async def connect(cls, path: Path) -> Bridge:
        reader, writer = await asyncio.open_unix_connection(str(path), limit=16 * 1024 * 1024)
        value = cls(reader, writer)
        await value.until(lambda: any(row.get("type") == "hello" for row in value.events))
        return value

    async def read(self) -> None:
        try:
            while line := await self.reader.readline():
                row = json.loads(line)
                if row.get("type") == "reply" and row.get("id") in self.calls:
                    future = self.calls[row["id"]]
                    if not future.done():
                        future.set_result(row)
                else:
                    self.events.append(row)
        finally:
            for future in self.calls.values():
                if not future.done():
                    future.set_exception(Refused("The installed connection ended; inspect before repeating a mutation."))

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        key = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.calls[key] = future
        self.writer.write((json.dumps({"type": "call", "id": key, "method": method, "params": params}) + "\n").encode())
        await self.writer.drain()
        try:
            return await asyncio.wait_for(asyncio.shield(future), 130)
        finally:
            self.calls.pop(key, None)

    async def until(self, probe: Any, seconds: float = 20) -> Any:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = probe()
            if value:
                return value
            await asyncio.sleep(0.03)
        raise Refused("The installed observation deadline passed.")

    async def close(self) -> None:
        self.writer.close()
        await self.writer.wait_closed()
        await self.task
