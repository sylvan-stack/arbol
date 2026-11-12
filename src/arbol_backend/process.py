"""Launcher-only child calls; timed-out mutations remain tracked, never killed."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from .bridge import BRIDGE_VERSION, constant, finite, pairs
from .database import configured_target, current_lease, explicit_target
from .exchange_admission import GENERATION_ENV
from .model import Identity, Refused

LIMITS = {"start": 25.0, "stop": 90.0, "settle": 120.0, "list": 10.0, "account": 10.0}
DRIVERS = {"claude", "codex", "pi"}
ACCOUNT_COMMANDS = {"check", "usage", "models"}
MAX_OUTPUT = 1024 * 1024


START_SECONDS = 12.0
READY_MAX = 4096


def lock_pid(folder: Path) -> int | None:
    try:
        fd = os.open(folder / "backend.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
                return None
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                pass  # Only an actively held backend lifetime lock can name the PID.
            else:
                return None
            record = json.loads(os.read(fd, READY_MAX))
        finally:
            os.close(fd)
        pid = record.get("pid") if isinstance(record, dict) else None
        if type(pid) is not int or not 1 <= pid <= 2147483647:
            return None
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError, UnicodeError):
        return None


def backend_ready(identity: Identity, pid: int, build: str) -> dict[str, Any]:
    return {"ready": True, "build": build, "socket": str(identity.folder / "backend.sock"), "pid": pid}


async def running_backend(identity: Identity) -> dict[str, Any] | None:
    path = identity.folder / "backend.sock"
    pid = lock_pid(identity.folder)
    if pid is None:
        return None
    try:
        before = path.lstat()
        if not stat.S_ISSOCK(before.st_mode) or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o600:
            raise Refused("invalid_input", "The backend endpoint is not an owner-only socket.")
        async with asyncio.timeout(0.75):
            reader, writer = await asyncio.open_unix_connection(path, limit=READY_MAX)
            try:
                hello = json.loads(await reader.readuntil(b"\n"))
            finally:
                writer.close()
                await writer.wait_closed()
        after = path.lstat()
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or lock_pid(identity.folder) != pid:
            return None
    except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        return None
    except (ValueError, UnicodeError) as error:
        raise Refused("no_answer", "The backend did not send a valid greeting.") from error
    if (not isinstance(hello, dict) or hello.get("type") != "hello" or type(hello.get("bridge")) is not int or hello["bridge"] != BRIDGE_VERSION
            or not isinstance(hello.get("build"), str) or not re.fullmatch(r"0|[1-9a-f][0-9a-f]*", hello["build"])):
        raise Refused("bridge_incompatible", "The backend at the installation endpoint does not speak Bridge 2.")
    return backend_ready(identity, pid, hello["build"])


async def acquire_backend(identity: Identity, arguments: list[str]) -> dict[str, Any]:
    """Attach to the owner-only socket or race to start one backend under its lifetime lock."""
    deadline = time.monotonic() + START_SECONDS
    contender: subprocess.Popen[bytes] | None = None
    keep = False
    with tempfile.TemporaryFile(mode="w+b") as output:
        try:
            while time.monotonic() < deadline:
                existing = await running_backend(identity)
                if existing is not None:
                    if contender is None or existing["pid"] != contender.pid:
                        return existing
                    line = os.pread(output.fileno(), READY_MAX, 0)
                    if b"\n" in line:
                        if existing["build"] != identity.build or json.loads(line.split(b"\n", 1)[0]) != existing:
                            raise Refused("no_answer", "The backend did not confirm the private endpoint.")
                        keep = True
                        return existing
                if contender is not None and contender.poll() is not None:
                    line = os.pread(output.fileno(), READY_MAX, 0)
                    try:
                        reply = json.loads(line)
                    except (ValueError, UnicodeError) as error:
                        raise Refused("no_answer", "The backend did not return a valid ready line.") from error
                    if not isinstance(reply, dict) or not isinstance(reply.get("error"), dict):
                        raise Refused("no_answer", "The backend did not become ready.")
                    code = reply["error"].get("code")
                    if code != "already_running":
                        raise Refused("invalid_input" if code == "invalid_input" else "no_answer",
                                      "The backend refused to start.")
                    contender = None
                    await asyncio.sleep(0.20)
                if contender is None and lock_pid(identity.folder) is None:
                    output.truncate(0)
                    output.seek(0)
                    contender = subprocess.Popen(
                        [sys.executable, "-I", "-B", str(identity.package / "bin/arbol_entry.py"), *arguments],
                        start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL,
                        stdout=output, stderr=subprocess.DEVNULL,
                    )
                await asyncio.sleep(0.05)
            raise Refused("no_answer", "The backend did not become ready within its time limit.")
        finally:
            if contender is not None and not keep and contender.poll() is None:
                try:
                    contender.terminate()
                except ProcessLookupError:
                    pass


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

    async def call(self, program: str, args: list[str], *, kind: str, key: str = "") -> Any:
        allowed = {"arbol-exchanges", *("arbol-" + name + "-driver" for name in self.drivers)}
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
        elif kind not in ("start", "stop", "settle", "list") or not args or args[0] != kind:
            raise Refused("invalid_input", "Runtime command and deadline must agree.")
        self.reap()
        identity = kind, key
        if identity in self.running:
            raise Refused("in_progress", "This command is still running.")
        if program == "arbol-exchanges":
            arguments = [str(self.identity.package / "bin/arbol-exchanges")]
            if self.identity.fixture:
                configured = configured_target(self.identity)
                explicit = explicit_target(self.identity)
                if explicit is not None and explicit != configured:
                    raise Refused("invalid_input", "The isolated backend and Exchange runtime must use the same database.")
                arguments += ["--runtime-dir", str(self.identity.folder), "--bin-dir", str(self.identity.bin_dir)]
        else:
            arguments = [str(self.identity.bin_dir / program)]
        arguments += args
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("PG") and key not in
               {"ARBOL_ROOT", "ARBOL_CHAT", "ARBOL_EXCHANGE_RUNTIME_DIR", "ARBOL_EXCHANGE_BIN_DIR", GENERATION_ENV}}
        if program == "arbol-exchanges" and kind in ("start", "stop", "settle"):
            lease = current_lease(self.identity.folder)
            if lease is None:
                raise Refused("maintenance", "A runtime mutation requires an installation permit.")
            env[GENERATION_ENV] = lease.state.generation
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
                        structured_refusal = (kind in ("start", "stop", "settle", "list", "account") and status == 1
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
