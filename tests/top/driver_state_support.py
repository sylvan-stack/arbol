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
from types import TracebackType
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


class HelperSpanCollector:
    """H1-only data collection; it grants no admission or semantic report trust.

    Use as a context manager around an already independently owned provider.
    The controller must validate the pinned report/custody/ACK bindings before
    continue_after_validation. This class only validates the finite wire shape.
    It never signals/reaps a Suite or helper, supplies terminal authority, or
    implements the separately blocked terminal-close pause protocol.
    """

    def __init__(self, child: OwnedChild, *, case: str, seconds: float = 120,
                 limit: int = CAPTURE_LIMIT) -> None:
        if (re.fullmatch(r"[0-9a-f]{32}", case, re.ASCII) is None
                or not math.isfinite(seconds) or not 20 < seconds <= 7200
                or type(limit) is not int or not 4096 <= limit <= 1024 * 1024):
            raise ObservationFailed("Invalid H1 case or complete interactive budget.")
        self.child, self.case, self.limit = child, case, limit
        self.end = time.monotonic() + seconds
        self.deadline = self.end - 20  # Owned cleanup is inside the complete bound.
        self._selector: selectors.BaseSelector | None = None
        self._data = {"stdout": bytearray(), "stderr": bytearray()}
        self._open: set[str] = set()
        self._ready: bytes | None = None
        self._report_hash: str | None = None
        self._ready_at: float | None = None
        self._continued = False
        self._entered = False
        self._finished = False
        self._closed = False
        self.cleanup_observation: Object | None = None

    def __enter__(self) -> HelperSpanCollector:
        if self._entered or self._closed:
            raise ObservationFailed("Interactive capture cannot be reused.")
        self._entered = True
        try:
            if self.child.reaped or not self.child.owner.live(parent=os.getpid()):
                raise ObservationFailed("Interactive provider ownership changed.")
            child = self.child.process
            if child.stdin is None or child.stdout is None or child.stderr is None:
                raise ObservationFailed("Interactive owned streams are unavailable.")
            self._selector = selectors.DefaultSelector()
            for name, stream in (("stdout", child.stdout), ("stderr", child.stderr)):
                os.set_blocking(stream.fileno(), False)
                self._selector.register(stream, selectors.EVENT_READ, name)
                self._open.add(name)
            os.set_blocking(child.stdin.fileno(), False)
            return self
        except BaseException as error:
            result = self.abort()
            error.add_note("Interactive setup cleanup: " + repr(result))
            raise

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> None:
        if not self._finished:
            result = self.abort()
            if error is not None:
                error.add_note("Interactive failed-span cleanup: " + repr(result))
            else:
                raise ObservationFailed("Interactive span ended without real capture: " + repr(result))

    def _active(self) -> selectors.BaseSelector:
        if not self._entered or self._closed or self._selector is None:
            raise ObservationFailed("Interactive capture is not active.")
        return self._selector

    def _pump(self, *, until: float) -> None:
        selector = self._active()
        remaining = until - time.monotonic()
        if remaining <= 0:
            raise ObservationFailed("Interactive capture exceeded its finite bound.")
        for key, events in selector.select(min(.05, remaining)):
            if not events & selectors.EVENT_READ:
                continue
            name = key.data
            if name not in ("stdout", "stderr"):
                raise ObservationFailed("Unexpected interactive endpoint.")
            limit = 4096 if name == "stdout" else self.limit
            try:
                part = os.read(key.fd, min(65536, limit + 1 - len(self._data[name])))
            except BlockingIOError:
                continue
            if not part:
                selector.unregister(key.fileobj)
                self._open.discard(name)
            else:
                self._data[name].extend(part)
                if len(self._data[name]) > limit:
                    raise ObservationFailed("Interactive output overflow; preserve failed span.")
                if self._ready is not None and bytes(self._data["stdout"]) != self._ready:
                    raise ObservationFailed("Extra interactive control bytes after the single H1 frame.")

    def ready(self) -> bytes:
        """Return exact syntax-verified bytes, NOT a validated report or ACK."""
        self._active()
        if self._ready is not None:
            raise ObservationFailed("H1 ready frame cannot be consumed twice.")
        while b"\n" not in self._data["stdout"]:
            if "stdout" not in self._open or self.child.process.poll() is not None:
                raise ObservationFailed("H1 stream exited before its complete ready frame.")
            self._pump(until=self.deadline)
        raw = bytes(self._data["stdout"])
        if raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
            raise ObservationFailed("H1 ready must be exactly one bounded JSONLF frame.")
        value = document(raw)
        exact_fields(value, ("version", "kind", "case", "reportSha256"))
        if (type(value["version"]) is not int or value["version"] != 1
                or value["kind"] != "helper-span-ready" or value["case"] != self.case
                or not isinstance(value["reportSha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", value["reportSha256"], re.ASCII) is None
                or canonical(value) != raw or not self.child.owner.live(parent=os.getpid())):
            raise ObservationFailed("H1 ready does not bind this live owned case/finite grammar.")
        self._ready, self._report_hash = raw, value["reportSha256"]
        self._ready_at = time.monotonic()
        return raw

    @property
    def ready_observed_at(self) -> float:
        if self._ready_at is None:
            raise ObservationFailed("No actual ready receipt timestamp exists.")
        return self._ready_at

    def raw_observation(self) -> Object:
        """Bounded immutable copies for private FAILED as well as positive evidence.

        An observer must preserve this before discarding a failed collector;
        hashes alone cannot retain malformed/extra/partial actual output bytes.
        """
        stdout, stderr = bytes(self._data["stdout"]), bytes(self._data["stderr"])
        return {"provider": self.child.owner.object(), "providerReaped": self.child.reaped,
                "providerReturncode": self.child.process.returncode, "readyObservedAt": self._ready_at,
                "continueSent": self._continued, "stdoutHex": stdout.hex(), "stderrHex": stderr.hex(),
                "stdoutSha256": digest(stdout), "stderrSha256": digest(stderr),
                "readySha256": None if self._ready is None else digest(self._ready),
                "cleanup": self.cleanup_observation, "custodyResolutionClaimed": False}

    def continue_after_validation(self, *, report_sha256: str) -> None:
        """Caller independently validated REAL report/custody/source before here."""
        selector = self._active()
        if (self._ready is None or self._ready_at is None or self._continued
                or report_sha256 != self._report_hash
                or not self.child.owner.live(parent=os.getpid())):
            raise ObservationFailed("Unvalidated/repeated H1 continue or changed provider.")
        child = self.child.process
        if child.stdin is None or child.stdin.closed:
            raise ObservationFailed("Owned H1 control input is unavailable.")
        raw = canonical({"version": 1, "kind": "helper-span-control", "case": self.case, "command": "continue"})
        deadline = min(self.deadline, self._ready_at + 5)
        view = memoryview(raw)
        selector.register(child.stdin, selectors.EVENT_WRITE, "control")
        try:
            while view:
                self._pump(until=deadline)
                try:
                    count = os.write(child.stdin.fileno(), view)
                except BlockingIOError:
                    continue
                if count <= 0:
                    raise ObservationFailed("Owned H1 input closed before complete continue.")
                view = view[count:]
            self._continued = True
        finally:
            selector.unregister(child.stdin)
        # There is no second command. EOF is no acknowledgement/terminal claim.
        child.stdin.close()

    def _capture(self) -> Captured:
        self._active()
        while self._open:
            self._pump(until=self.deadline)
        code = self.child.process.wait(timeout=max(.001, self.deadline - time.monotonic()))
        self.child.reaped = True
        if bytes(self._data["stdout"]) != self._ready:
            raise ObservationFailed("H1 capture has extra or truncated control data.")
        errors = self._close_endpoints()
        if errors:
            raise ObservationFailed("Interactive endpoint closure failed: " + repr(errors))
        self._finished = True
        return Captured(code, bytes(self._data["stdout"]), bytes(self._data["stderr"]), self.child.owner)

    def finish_positive(self) -> Captured:
        if not self._continued:
            raise ObservationFailed("Positive H1 capture requires its genuine continue.")
        captured = self._capture()
        if captured.returncode != 0:
            raise ObservationFailed("Positive H1 provider failed; no complete check success.")
        return captured

    def capture_ended_failure(self) -> Captured:
        """A deliberate failed subject is never a positive gate/capture shortcut."""
        if self._ready is None or self._continued:
            raise ObservationFailed("Failed-span capture requires ready and NO positive continue.")
        self._active()
        stdin = self.child.process.stdin
        if stdin is not None and not stdin.closed:
            stdin.close()  # Failure/EOF only, never a successful continuation.
        captured = self._capture()
        if captured.returncode == 0:
            raise ObservationFailed("Failed H1 subject unexpectedly reported success.")
        return captured

    def _close_endpoints(self) -> list[str]:
        errors: list[str] = []
        if self._selector is not None:
            try:
                self._selector.close()
            except BaseException as error:
                errors.append("selector:" + type(error).__name__)
        for stream in (self.child.process.stdin, self.child.process.stdout, self.child.process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except BaseException as error:
                    errors.append("stream:" + type(error).__name__)
        self._closed = True
        return errors

    def abort(self) -> Object:
        """Only this actual owned provider is stopped/waited; no descendant claim."""
        if self.cleanup_observation is not None:
            return self.cleanup_observation
        errors: list[str] = []
        stdin = self.child.process.stdin
        if stdin is not None:
            try:
                stdin.close()
            except BaseException as error:
                errors.append("failure-input:" + type(error).__name__)
        try:
            self.child.request_stop()
        except BaseException as error:
            errors.append("owned-stop:" + type(error).__name__)
        try:
            self.child.wait_owned(seconds=max(.001, min(20, self.end - time.monotonic())))
        except BaseException as error:
            errors.append("owned-wait:" + type(error).__name__)
        finally:
            errors.extend(self._close_endpoints())
        self.cleanup_observation = {"provider": self.child.owner.object(), "providerReaped": self.child.reaped,
            "providerReturncode": self.child.process.returncode, "errors": errors,
            "stdoutSha256": digest(bytes(self._data["stdout"])), "stderrSha256": digest(bytes(self._data["stderr"])),
            "observerReapedDescendant": False, "custodyResolutionClaimed": False}
        return self.cleanup_observation


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
