"""Launcher-only child calls; timed-out mutations remain tracked, never killed."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, BinaryIO
from uuid import UUID

from .bridge import constant, finite, pairs
from .model import ROOT_ID, Identity, Refused

LIMITS = {"start": 25.0, "stop": 90.0, "settle": 120.0, "list": 10.0, "account": 10.0, "migrate-check": 90.0, "reimport": 90.0}
DRIVERS = {"claude", "codex", "pi"}
ACCOUNT_COMMANDS = {"check", "usage", "models"}
MAX_OUTPUT = 1024 * 1024
GLOBAL_CATALOGUE = "roots.catalogue"


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
        self.drivers: set[str] = set()
        self.find_drivers()
        self.limits = dict(LIMITS if limits is None else limits)
        self.running: dict[tuple[str, str], Child] = {}

    def find_drivers(self) -> set[str]:
        self.drivers = {path.name[len("arbol-"):-len("-driver")]
                        for path in self.identity.bin_dir.glob("arbol-*-driver")
                        if path.is_file() and os.access(path, os.X_OK)
                        and re.fullmatch(r"arbol-[a-z][a-z0-9-]*-driver", path.name)}
        return self.drivers

    def reap(self) -> None:
        for key, child in list(self.running.items()):
            if child.waiting:
                continue
            child.read()
            if child.process.poll() is not None:
                child.close()
                del self.running[key]

    def command_key(self, kind: str, key: str, root: str | None = None) -> tuple[str, str]:
        selected = self.identity.root if root is None else root
        return kind, key if selected == self.identity.root else selected+":"+key

    async def call(self, program: str, args: list[str], *, kind: str, key: str = "", root: str | None = None) -> Any:
        selected = self.identity.root if root is None else root
        if (not isinstance(selected, str) or not ROOT_ID.fullmatch(selected)
                or root is not None and program != "arbol-root"
                or selected != self.identity.root and kind not in ("list", "stop", "settle")):
            raise Refused("invalid_input", "Unsupported explicit Root command.")
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
            valid = kind == "list" and args == ["list"]
            if kind == "migrate-check" and args == ["migrate", self.identity.root, "--check"]:
                valid, key = True, self.identity.root
            if kind == "reimport" and len(args) == 4 and args[:3] == ["migrate", self.identity.root, "--chat"]:
                try:
                    valid = str(UUID(args[3])) == args[3]
                except ValueError:
                    valid = False
                key = args[3]
            if not valid:
                raise Refused("invalid_input", "Unsupported own-Root catalogue or migration command.")
        elif kind not in ("start", "stop", "settle", "list") or not args or args[0] != kind:
            raise Refused("invalid_input", "Root command and deadline must agree.")
        if "--root" in args:
            raise Refused("invalid_input", "A child cannot override this backend's Root.")
        self.reap()
        if program == "arbol-root" and kind in ("settle", "list"):
            key = selected
        if program == "arbol-root" and kind in ("start", "stop") and "--exchange" in args:
            index = args.index("--exchange")
            if index + 1 == len(args):
                raise Refused("invalid_input", "An Exchange identifier is required.")
            key = args[index + 1]
        identity = self.command_key(kind, key or self.identity.root, selected)
        if identity in self.running:
            raise Refused("in_progress", "This command is still running.")
        arguments = [str(self.identity.bin_dir / program)]
        if program == "arbol-root":
            arguments += ["--root", selected]
        arguments += args
        env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
        env["HOME"] = str(self.identity.home)
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
                    if child.overflow:
                        raise Refused("no_answer", "The launcher returned no bounded successful reply.")
                    try:
                        value = (json.loads(child.data, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite)
                                 if kind == "account" else json.loads(child.data))
                        structured_refusal = (kind in ("start", "stop", "settle", "list", "migrate-check", "reimport", "account") and status == 1
                                              and isinstance(value, dict) and isinstance(value.get("error"), dict))
                        if status != 0 and not structured_refusal:
                            raise Refused("no_answer", "The launcher returned no bounded successful reply.")
                        return value
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
        # macOS may refuse a group signal before waitpid can report its final exit.
        # Reap that bounded transition instead of turning clean shutdown into another stdout reply.
        for grace in (0.01, 0.04, 0.15):
            if child.process.poll() is not None:
                return
            try:
                os.killpg(child.process.pid, signal.SIGKILL)
                return
            except ProcessLookupError:
                return
            except PermissionError:
                try:
                    child.process.wait(timeout=grace)
                    return
                except subprocess.TimeoutExpired:
                    continue
        raise Refused("no_answer", "The listing process group could not be stopped.")

    async def current_root(self) -> dict[str, Any] | None:
        value = await self.call("arbol-roots", ["list"], kind="list", key=GLOBAL_CATALOGUE)
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
            if child.process.poll() is None:
                # Reap the detached manager eventually without holding shutdown or logging Popen warnings.
                threading.Thread(target=child.process.wait, daemon=True).start()
        # Never signal an unresolved start/stop/settle, and never wait for it here.
        self.running.clear()
