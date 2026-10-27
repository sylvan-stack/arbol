"""Launcher-only child calls; timed-out mutations remain tracked, never killed."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, BinaryIO

from .model import Identity, Refused

LIMITS = {"start": 25.0, "stop": 90.0, "settle": 120.0, "list": 10.0, "account": 10.0}
DRIVERS = {"claude", "codex", "pi"}
ACCOUNT_COMMANDS = {"check", "usage", "models"}
MAX_OUTPUT = 1024 * 1024


@dataclass
class Child:
    process: subprocess.Popen[bytes]
    kill_on_timeout: bool
    output: BinaryIO
    position: int = 0
    data: bytearray = field(default_factory=bytearray)
    overflow: bool = False
    eof: bool = False
    waiting: bool = True

    def read(self) -> None:
        # A chatty child must not monopolize the event loop.
        for _ in range(16):
            chunk = os.pread(self.output.fileno(), 65536, self.position)
            if not chunk:
                self.eof = self.process.poll() is not None
                return
            self.position += len(chunk)
            available = max(0, MAX_OUTPUT - len(self.data))
            self.data.extend(chunk[:available])
            self.overflow |= len(chunk) > available

    def close(self) -> None:
        self.output.close()


class Programs:
    def __init__(self, identity: Identity, *, limits: dict[str, float] | None = None) -> None:
        self.identity = identity
        self.drivers = {path.name[len("arbol-"):-len("-driver")]
                        for path in identity.bin_dir.glob("arbol-*-driver")
                        if path.is_file() and os.access(path, os.X_OK)
                        and re.fullmatch(r"arbol-[a-z][a-z0-9-]*-driver", path.name)}
        self.limits = dict(LIMITS if limits is None else limits)
        self.running: dict[tuple[str, str], Child] = {}

    def reap(self) -> None:
        for key, child in list(self.running.items()):
            if child.waiting:
                continue
            child.read()
            if child.process.poll() is not None:
                child.close()
                del self.running[key]

    async def call(self, program: str, args: list[str], *, kind: str, key: str = "") -> Any:
        allowed = {"arbol-root", "arbol-roots", *("arbol-" + x + "-driver" for x in self.drivers)}
        if program not in allowed or kind not in LIMITS:
            raise Refused("invalid_input", "Unsupported backend child command.")
        if program.endswith("-driver"):
            account = args == ["subscriptions", "list"] or (
                len(args) == 3
                and args[:1] == ["subscriptions"]
                and args[1] in ACCOUNT_COMMANDS
                and bool(args[2])
                and not args[2].startswith("-")
            )
            if kind != "account" or not account:
                raise Refused("invalid_input", "Only Driver account/catalogue commands are allowed.")
        elif program == "arbol-roots":
            if kind != "list" or args != ["list"]:
                raise Refused("invalid_input", "Only the Root catalogue listing is available here.")
        elif kind not in ("start", "stop", "settle", "list") or not args or args[0] != kind:
            raise Refused("invalid_input", "Root command and deadline must agree.")
        if "--root" in args:
            raise Refused("invalid_input", "A child cannot override this backend's Root.")
        self.reap()
        if program == "arbol-root" and kind in ("settle", "list"):
            key = self.identity.root
        if program == "arbol-root" and kind in ("start", "stop") and "--exchange" in args:
            index = args.index("--exchange")
            if index + 1 == len(args):
                raise Refused("invalid_input", "An Exchange identifier is required.")
            key = args[index + 1]
        identity = (kind, key or self.identity.root)
        if identity in self.running:
            raise Refused("in_progress", "This command is still running.")
        arguments = [str(self.identity.bin_dir / program)]
        if program == "arbol-root":
            arguments += ["--root", self.identity.root]
        arguments += args
        env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
        env["PATH"] = str(self.identity.bin_dir) + os.pathsep + env.get("PATH", "/usr/bin:/bin")
        output = tempfile.TemporaryFile(mode="w+b")
        try:
            child = Child(
                subprocess.Popen(
                    arguments,
                    cwd=self.identity.folder,
                    env=env,
                    close_fds=True,
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                ),
                kind in ("list", "account"),
                output,
            )
        except OSError as error:
            output.close()
            raise Refused("no_answer", "The launcher could not be started.") from error
        self.running[identity] = child
        deadline = time.monotonic() + self.limits[kind]
        try:
            while True:
                child.read()
                status = child.process.poll()
                if status is not None and child.eof:
                    if status != 0 or child.overflow:
                        raise Refused("no_answer", "The launcher returned no bounded successful reply.")
                    try:
                        return json.loads(child.data)
                    except (ValueError, UnicodeError) as error:
                        raise Refused("no_answer", "The launcher returned no valid JSON reply.") from error
                if time.monotonic() >= deadline:
                    if child.kill_on_timeout:
                        self.kill(child)
                    raise Refused("no_answer", "The launcher did not answer within its time limit.")
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            if child.kill_on_timeout:
                self.kill(child)
                await asyncio.to_thread(child.process.wait)
            raise
        finally:
            child.waiting = False
            if child.process.poll() is not None:
                child.close()
                self.running.pop(identity, None)

    @staticmethod
    def kill(child: Child) -> None:
        if child.process.poll() is not None:
            return
        try:
            os.killpg(child.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError as error:
            # macOS can report EPERM for a group whose final child just exited.
            if child.process.poll() is None:
                raise Refused("no_answer", "The listing process group could not be stopped.") from error

    async def current_root(self) -> dict[str, Any] | None:
        value = await self.call("arbol-roots", ["list"], kind="list", key="catalogue")
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise Refused("no_answer", "The Root catalogue returned an invalid list.")
        current = [row for row in value if row.get("current") is True]
        if len(current) > 1:
            raise Refused("no_answer", "The Root catalogue names several current Roots.")
        return current[0] if current else None

    def close(self) -> None:
        for child in self.running.values():
            if child.kill_on_timeout:
                self.kill(child)
            child.close()
            child.process.poll()
        # Never signal an unresolved start/stop/settle, and never wait for it here.
        self.running.clear()
