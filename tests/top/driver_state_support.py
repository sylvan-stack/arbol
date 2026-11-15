"""Prospective ABR-38 external observers; never a metadata-admission shortcut.

The controller calls these only after independent body admission.  Importing this
module opens no registry, state, process, socket or output directory.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import selectors
import signal
import socket
import stat
import subprocess
import termios
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arbol_builds.driver_process import inspect, process_identity, valid_start

Object = dict[str, Any]
DOCUMENT_LIMIT = 4096
CAPTURE_LIMIT = 65536
TREE_LIMIT = 100000
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\Z", re.ASCII)


class ObservationFailed(RuntimeError):
    """A missing observation preserves the attempt; it never grants authority."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object, *, limit: int = DOCUMENT_LIMIT) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if not 0 < len(raw) <= limit:
        raise ObservationFailed("Evidence document exceeds its bound.")
    return raw


def document(raw: bytes, *, limit: int = DOCUMENT_LIMIT) -> Object:
    if not 0 < len(raw) <= limit:
        raise ObservationFailed("Document exceeds its bound.")

    def pairs(items: list[tuple[str, Any]]) -> Object:
        value: Object = {}
        for key, item in items:
            if key in value:
                raise ObservationFailed("Duplicate document field.")
            value[key] = item
        return value

    def constant(_value: str) -> None:
        raise ObservationFailed("Nonfinite JSON value.")

    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ObservationFailed("Malformed bounded document.") from error
    if not isinstance(value, dict):
        raise ObservationFailed("Expected a document object.")
    return value


def exact_fields(value: Object, names: Sequence[str]) -> None:
    if set(value) != set(names):
        raise ObservationFailed("Unexpected document fields.")


def physical_owned(path: Path, *, directory: bool, private: bool = True) -> os.stat_result:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ObservationFailed("Expected a physical absolute owned path.")
    info = path.lstat()
    if info.st_uid != os.getuid() or (private and stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)):
        raise ObservationFailed("Owned private path changed.")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ObservationFailed("Unexpected path type.")
    return info


def directory_identity(path: Path) -> Object:
    info = physical_owned(path, directory=True)
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class FileImage:
    path: Path
    raw: bytes
    device: int
    inode: int
    mode: int

    @property
    def sha256(self) -> str:
        return digest(self.raw)

    def evidence(self) -> Object:
        return {"path": str(self.path), "sha256": self.sha256, "size": len(self.raw),
                "device": self.device, "inode": self.inode, "mode": self.mode}


def read_image(path: Path, *, limit: int = DOCUMENT_LIMIT, private: bool = True) -> FileImage:
    physical_owned(path.parent, directory=True, private=private)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_size > limit
                or (private and stat.S_IMODE(before.st_mode) != 0o600)):
            raise ObservationFailed("Unsafe or oversized observation file.")
        raw = bytearray()
        while len(raw) <= limit:
            part = os.read(descriptor, min(65536, limit + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        after, named = os.fstat(descriptor), path.lstat()
        keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode")
        if (len(raw) > limit or any(getattr(before, key) != getattr(after, key) for key in keys)
                or (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)):
            raise ObservationFailed("Observation file changed while read.")
        return FileImage(path, bytes(raw), before.st_dev, before.st_ino, stat.S_IMODE(before.st_mode))
    finally:
        os.close(descriptor)


def tree_inventory(root: Path) -> list[Object]:
    """Hash actual private evidence, never infer custody from an empty result."""
    physical_owned(root, directory=True)
    rows: list[Object] = []
    for folder, directories, files in os.walk(root, followlinks=False):
        parent = Path(folder)
        physical_owned(parent, directory=True)
        for name in sorted(directories):
            path = parent / name
            info = physical_owned(path, directory=True)
            rows.append({"path": path.relative_to(root).as_posix(), "type": "directory",
                         "device": info.st_dev, "inode": info.st_ino})
        for name in sorted(files):
            path = parent / name
            image = read_image(path, limit=32 * 1024 * 1024)
            rows.append({**image.evidence(), "path": path.relative_to(root).as_posix(), "type": "file"})
        if len(rows) > TREE_LIMIT:
            raise ObservationFailed("Evidence inventory exceeds its bound.")
    return sorted(rows, key=lambda row: str(row["path"]).encode())


class EvidenceRecorder:
    """One exclusively created private attempt, with no overwrite or resume mode."""

    def __init__(self, parent: Path, name: str) -> None:
        if NAME.fullmatch(name) is None:
            raise ObservationFailed("Invalid evidence attempt name.")
        physical_owned(parent, directory=True)
        self.root = parent / name
        self.root.mkdir(mode=0o700)
        sync_directory(parent)
        self.identity = directory_identity(self.root)
        self.files: dict[str, Object] = {}

    def write(self, name: str, value: object, *, limit: int = 32 * 1024 * 1024) -> str:
        return self.write_bytes(name, canonical(value, limit=limit), limit=limit)

    def write_bytes(self, name: str, raw: bytes, *, limit: int = CAPTURE_LIMIT) -> str:
        if NAME.fullmatch(name) is None or name in self.files or len(raw) > limit:
            raise ObservationFailed("Evidence name reused or bound exceeded.")
        if directory_identity(self.root) != self.identity:
            raise ObservationFailed("Evidence directory identity changed.")
        path = self.root / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise ObservationFailed("Incomplete evidence publication.")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        sync_directory(self.root)
        image = read_image(path, limit=limit)
        if image.raw != raw:
            raise ObservationFailed("Evidence bytes changed after publication.")
        self.files[name] = image.evidence()
        return image.sha256


@dataclass(frozen=True)
class ExactProcess:
    pid: int
    started_at: str

    @classmethod
    def read(cls, value: Object) -> ExactProcess:
        exact_fields(value, ("pid", "startedAt"))
        if type(value["pid"]) is not int or not 0 < value["pid"] <= 2**31 - 1 or not valid_start(value["startedAt"]):
            raise ObservationFailed("Invalid exact process identity.")
        return cls(value["pid"], value["startedAt"])

    def object(self) -> Object:
        return {"pid": self.pid, "startedAt": self.started_at}

    def live(self, *, parent: int | None = None) -> bool:
        current = inspect(self.pid)
        return (current is not None and current.owner == self.object()
                and (parent is None or current.parent == parent))


def signal_verified(owner: ExactProcess, number: signal.Signals) -> None:
    """An unknown/reused PID is never a cleanup target; no group fallback."""
    if not owner.live():
        raise ObservationFailed("Verified process changed before signal; preserve custody.")
    os.kill(owner.pid, number)


@dataclass(frozen=True)
class Captured:
    returncode: int
    stdout: bytes
    stderr: bytes
    owner: ExactProcess


class OwnedChild:
    """Caller-owned exact Popen handle; exit/EOF supply no terminal authority."""

    def __init__(self, argv: list[str], *, environment: Mapping[str, str], cwd: Path) -> None:
        if not argv or not all(isinstance(word, str) and "\0" not in word for word in argv):
            raise ObservationFailed("Malformed fixed invocation.")
        self.process = subprocess.Popen(argv, env=dict(environment), cwd=cwd, close_fds=True,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # Failure here intentionally leaves an unverified target unsignalled.
        self.owner = ExactProcess.read(process_identity(self.process.pid))
        if not self.owner.live(parent=os.getpid()):
            raise ObservationFailed("Direct child identity is unavailable.")
        self.reaped = False

    def collect(self, *, seconds: float = 120, limit: int = CAPTURE_LIMIT) -> Captured:
        if not math.isfinite(seconds) or not 0 < seconds <= 7200 or not 0 < limit <= 1024 * 1024:
            raise ObservationFailed("Invalid complete capture budget.")
        child = self.process
        if child.stdin is not None:
            child.stdin.close()
        if child.stdout is None or child.stderr is None:
            raise ObservationFailed("Owned capture streams are unavailable.")
        deadline = time.monotonic() + seconds
        data = {"stdout": bytearray(), "stderr": bytearray()}
        try:
            with selectors.DefaultSelector() as selector:
                for name, stream in (("stdout", child.stdout), ("stderr", child.stderr)):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ObservationFailed("Owned capture timed out; custody remains unresolved.")
                    for key, _ in selector.select(min(.1, remaining)):
                        part = os.read(key.fd, min(65536, limit + 1 - len(data[key.data])))
                        if not part:
                            selector.unregister(key.fileobj)
                        else:
                            data[key.data].extend(part)
                            if len(data[key.data]) > limit:
                                raise ObservationFailed("Owned capture overflow; preserve failure.")
                code = child.wait(timeout=max(.001, deadline - time.monotonic()))
                self.reaped = True
                return Captured(code, bytes(data["stdout"]), bytes(data["stderr"]), self.owner)
        finally:
            child.stdout.close()
            child.stderr.close()

    def request_stop(self) -> None:
        if self.process.poll() is None:
            signal_verified(self.owner, signal.SIGTERM)

    def wait_owned(self, *, seconds: float = 20) -> int:
        code = self.process.wait(timeout=seconds)
        self.reaped = True
        return code


class SocketBarrier:
    """One reviewed helper checkpoint; a data socket never carries admission."""

    def __init__(self, channel: socket.socket, *, case: str, action: str, window: str) -> None:
        if (channel.family != socket.AF_UNIX or channel.type != socket.SOCK_STREAM or channel.fileno() < 3
                or re.fullmatch(r"[0-9a-f]{32}", case, re.ASCII) is None):
            raise ObservationFailed("Invalid separate actor control endpoint/case.")
        actions = {"retain-label", "retain-auth", "drop-sidecar", "corrupt-sidecar", "drop-root", "corrupt-root",
                   "late-auth", "late-usage", "late-run", "late-map", "late-progress", "late-history",
                   "lease-hold", "create-stop", "recover-create"}
        windows = {"none", "L1-result-ready", "H1-independent-lease", "C1-prepared-durable", "C2-record-durable",
                   "C3-sidecar-durable", "C4-committed-durable", "C5-clear-durable", "J1-prepared-present",
                   "J2-prepared-absent", "J3-committed-present", "J4-inconsistent"}
        if action not in actions or window not in windows:
            raise ObservationFailed("Unsupported literal actor action/window.")
        if ((action.startswith("late-") and window != "L1-result-ready")
                or (action == "lease-hold" and window != "H1-independent-lease")
                or (action == "create-stop" and not window.startswith("C"))
                or (action == "recover-create" and not window.startswith("J"))
                or (action.startswith(("retain-", "drop-", "corrupt-")) and window != "none")):
            raise ObservationFailed("Invalid literal actor window pairing.")
        self.channel, self.case, self.action, self.window = channel, case, action, window
        self.replied = False
        self.checkpoint_seen = False
        os.set_inheritable(channel.fileno(), False)
        channel.settimeout(10)

    def checkpoint(self) -> Object:
        if self.checkpoint_seen or self.window == "none" or self.action == "recover-create":
            raise ObservationFailed("This action accepts no further checkpoint.")
        raw = bytearray()
        deadline = time.monotonic() + 10
        while len(raw) <= DOCUMENT_LIMIT:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ObservationFailed("Complete actor checkpoint exceeded its10sec bound.")
            self.channel.settimeout(remaining)
            part = self.channel.recv(1)
            if not part:
                raise ObservationFailed("Actor checkpoint closed before its bounded frame.")
            raw.extend(part)
            if part == b"\n":
                break
        if raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
            raise ObservationFailed("Checkpoint must be one bounded JSONLF frame.")
        value = document(bytes(raw))
        exact_fields(value, ("version", "kind", "case", "action", "window"))
        if value != {"version": 1, "kind": "actor-ready", "case": self.case,
                     "action": self.action, "window": self.window} or type(value["version"]) is not int:
            raise ObservationFailed("Actor checkpoint does not match the fixed case.")
        self.checkpoint_seen = True
        return value

    def reply(self, *, abort_io: bool = False) -> None:
        if not self.checkpoint_seen or self.replied or (abort_io and self.action != "create-stop"):
            raise ObservationFailed("Unsupported or repeated checkpoint response.")
        if not (self.action.startswith("late-") or self.action in ("lease-hold", "create-stop")):
            raise ObservationFailed("This action accepts no control response.")
        self.channel.settimeout(10)
        self.channel.sendall(canonical({"version": 1, "kind": "actor-control", "case": self.case,
                                        "command": "abort-io" if abort_io else "continue"}))
        self.replied = True

    def close(self) -> None:
        self.channel.close()


def _claim_owned_terminal() -> None:
    """Runs in the new child session, after Popen maps the owned slave onto0."""
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class OwnedPTY:
    """A newly owned PTY/session; never borrow or alter the owner's terminal."""

    def __init__(self, argv: list[str], *, environment: Mapping[str, str], cwd: Path) -> None:
        # Popen preexec is restricted to a single-threaded external controller.
        if any(t is not threading.current_thread() and t.is_alive() for t in threading.enumerate()):
            raise ObservationFailed("PTY setup cannot run beside live controller/ACK threads.")
        master, slave = os.openpty()
        self.master = master
        os.set_inheritable(master, False)
        os.set_inheritable(slave, False)
        try:
            self.process = subprocess.Popen(argv, env=dict(environment), cwd=cwd, close_fds=True,
                                            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                                            preexec_fn=_claim_owned_terminal)
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        self.owner = ExactProcess.read(process_identity(self.process.pid))
        if not self.owner.live(parent=os.getpid()):
            raise ObservationFailed("Owned PTY child identity is unavailable; no guessed kill.")
        os.set_blocking(master, False)
        self.reaped = False

    def write(self, raw: bytes) -> None:
        if len(raw) > DOCUMENT_LIMIT or not self.owner.live():
            raise ObservationFailed("Invalid bounded PTY input or stale child.")
        view = memoryview(raw)
        deadline = time.monotonic() + 10
        with selectors.DefaultSelector() as selector:
            selector.register(self.master, selectors.EVENT_WRITE)
            while view:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ObservationFailed("Owned PTY input backpressure exceeded its bound.")
                if selector.select(remaining):
                    try:
                        written = os.write(self.master, view)
                    except BlockingIOError:
                        continue
                    if written <= 0:
                        raise ObservationFailed("PTY input closed before completion.")
                    view = view[written:]

    def read_until(self, marker: bytes, *, seconds: float = 20, limit: int = CAPTURE_LIMIT) -> bytes:
        if not marker or not math.isfinite(seconds) or not 0 < seconds <= 120 or not 0 < limit <= CAPTURE_LIMIT:
            raise ObservationFailed("Invalid bounded PTY observation.")
        raw = bytearray()
        deadline = time.monotonic() + seconds
        with selectors.DefaultSelector() as selector:
            selector.register(self.master, selectors.EVENT_READ)
            while marker not in raw:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or len(raw) >= limit:
                    raise ObservationFailed("PTY observation incomplete; preserve exact attempt.")
                if selector.select(min(.1, remaining)):
                    try:
                        part = os.read(self.master, min(65536, limit + 1 - len(raw)))
                    except BlockingIOError:
                        continue
                    if not part:
                        raise ObservationFailed("PTY closed before independent readiness.")
                    raw.extend(part)
            return bytes(raw)

    def signal(self, number: signal.Signals) -> None:
        signal_verified(self.owner, number)

    def reap(self, *, seconds: float = 20) -> int:
        code = self.process.wait(timeout=seconds)
        self.reaped = True
        return code

    def close(self) -> None:
        if self.master >= 0:
            descriptor, self.master = self.master, -1
            os.close(descriptor)
