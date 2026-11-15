"""Narrow process identity for cooperative admission, never an ancestry oracle.

DRV-6.21 uses exact kernel microseconds. Historical Driver owner records and
vendor cleanup rules are not rewritten by this new shared representation.
The library and fixed sysctl command are called only during admitted execution.
"""

from __future__ import annotations

import ctypes
import errno
import os
import re
import selectors
import signal
import socket
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING, Any, NoReturn

from .driver_admission import (
    LIMIT,
    NORMAL_CONTEXT,
    NORMAL_FD,
    Authority,
    Custody,
    Object,
    canonical,
    canonical_uuid,
    custody_loss,
    decode,
    fields,
    handoff_path,
    natural,
    normal_context,
    normal_control,
    private_directory,
    publish,
    read_handoff,
    read_writer,
    refuse,
    sha256,
    token,
    valid_token,
    validate,
    without_authority,
    writer_path,
)

if TYPE_CHECKING:
    from .driver_payload import Payload

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_SECONDS = 253402300799
_STARTED = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})\.([0-9]{6})Z\Z", re.ASCII)


class BsdInfo(ctypes.Structure):
    """Public sys/proc_info.h proc_bsdinfo, qualified 64-bit Darwin layout."""

    _fields_ = [
        ("flags", ctypes.c_uint32), ("status", ctypes.c_uint32), ("xstatus", ctypes.c_uint32),
        ("pid", ctypes.c_uint32), ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32), ("rgid", ctypes.c_uint32),
        ("svuid", ctypes.c_uint32), ("svgid", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
        ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32), ("jobc", ctypes.c_uint32),
        ("tdev", ctypes.c_uint32), ("tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32),
        ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64),
    ]


@lru_cache(maxsize=1)
def library() -> ctypes.CDLL:
    if (sys.platform != "darwin" or ctypes.sizeof(ctypes.c_void_p) != 8
            or ctypes.sizeof(BsdInfo) != 136 or ctypes.alignment(BsdInfo) != 8
            or BsdInfo.pid.offset != 12 or BsdInfo.status.offset != 4
            or BsdInfo.start_sec.offset != 120 or BsdInfo.start_usec.offset != 128):
        refuse()
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.restype = ctypes.c_int
    except (OSError, AttributeError):
        refuse()
    return lib


def start_string(seconds: int, microseconds: int) -> str:
    if (not natural(seconds, positive=True) or seconds > _MAX_SECONDS
            or not natural(microseconds) or microseconds >= 1000000):
        refuse()
    try:
        # Integer timedelta arithmetic preserves tvusec; no floating epoch roundtrip.
        value = _EPOCH + timedelta(seconds=seconds, microseconds=microseconds)
    except (OverflowError, ValueError):
        refuse()
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def valid_start(value: object) -> bool:
    if not isinstance(value, str) or (match := _STARTED.fullmatch(value)) is None:
        return False
    try:
        year, month, day, hour, minute, second, microsecond = map(int, match.groups())
        parsed = datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC)
        return parsed >= _EPOCH and parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") == value
    except ValueError:
        return False


def identity_record(value: object) -> Object:
    if (not isinstance(value, dict) or set(value) != {"pid", "startedAt"}
            or not natural(value["pid"], positive=True) or value["pid"] > 2**31 - 1
            or not valid_start(value["startedAt"])):
        refuse()
    return value


@dataclass(frozen=True)
class Process:
    owner: Object
    parent: int
    group: int


def inspect(pid: int) -> Process | None:
    if not natural(pid, positive=True) or pid > 2**31 - 1:
        refuse()
    value = BsdInfo()
    ctypes.set_errno(0)
    size = library().proc_pidinfo(pid, 3, 0, ctypes.byref(value), ctypes.sizeof(value))
    error = ctypes.get_errno()
    if not size and error == errno.ESRCH:
        return None
    if size != 136 or value.pid != pid:
        refuse()
    if value.status == 5:  # Public sys/proc.h SZOMB is not a live identity.
        return None
    if value.status not in (2, 3, 4) or value.uid != os.getuid() or not value.ppid:
        refuse()  # SIDL/unknown/inaccessible observations supply no authority.
    owner = {"pid": pid, "startedAt": start_string(value.start_sec, value.start_usec)}
    return Process(identity_record(owner), int(value.ppid), int(value.pgid))


def process_identity(pid: int) -> Object:
    value = inspect(pid)
    if value is None:
        refuse()
    return value.owner


def matches(owner: Object, *, parent: int | None = None) -> bool:
    identity_record(owner)
    current = inspect(owner["pid"])
    return (current is not None and current.owner == owner
            and (parent is None or current.parent == parent))


def boot_uuid() -> str:
    if sys.platform != "darwin":
        refuse()
    try:
        result = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"], check=False,
                                capture_output=True, timeout=5,
                                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        if result.returncode or not 0 < len(result.stdout) <= LIMIT:
            refuse()
        lines = result.stdout.decode("ascii", "strict").splitlines()
        if len(lines) != 1:
            refuse()
        value = lines[0].strip().lower()
        if not canonical_uuid(value):
            refuse()
        return value
    except (OSError, UnicodeError, subprocess.SubprocessError):
        refuse()


class Frames:
    """One bounded one-use local handshake. No stdout or argv carries this wire."""

    def __init__(self, descriptor: int):
        self.socket = socket.socket(fileno=descriptor)
        if (descriptor < 3 or self.socket.family != socket.AF_UNIX
                or self.socket.type != socket.SOCK_STREAM):
            self.socket.close()
            refuse()
        os.set_inheritable(descriptor, False)
        self.deadline = time.monotonic() + 20

    def _timeout(self) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            refuse()
        self.socket.settimeout(remaining)

    def _receive(self, size: int) -> bytes:
        raw = bytearray()
        while len(raw) < size:
            self._timeout()
            part = self.socket.recv(size - len(raw))
            if not part:
                refuse()
            raw.extend(part)
        return bytes(raw)

    def receive(self) -> Object:
        length, = struct.unpack("!I", self._receive(4))
        if not 0 < length <= LIMIT:
            refuse()
        return decode(self._receive(length))

    def send(self, value: Object) -> None:
        raw = canonical(value)
        if not 0 < len(raw) <= LIMIT:
            refuse()
        self._timeout()
        self.socket.sendall(struct.pack("!I", len(raw)) + raw)

    def no_extra(self) -> None:
        self.socket.setblocking(False)
        try:
            if self.socket.recv(1, socket.MSG_PEEK):
                refuse()
        except BlockingIOError:
            pass

    def close(self) -> None:
        self.socket.close()


@dataclass
class Guardian:
    """Parent-side main transfer; child independently opens its own admission.

    This object never accesses Driver state. A failed transfer preserves durable
    obligations even when both the socket and this process's lease disappear.
    Runtime signal/TTY supervision is the separate step-8 integration.
    """

    authority: Authority
    payload: Payload
    invocation: str
    writer: str
    epoch: str
    boot: str
    owner: Object
    acceptance_sha256: str
    lease: int
    build_use: int
    handoff: str | None = None
    child_owner: Object | None = None
    transferred: bool = False

    @classmethod
    def admit(cls, authority: Authority, payload: Payload) -> Guardian:
        from .driver_payload import registered, verify_acceptance
        from .launcher import open_use_guard

        if payload.component != authority.component:
            refuse()
        # Guard first: future pruning cannot delete payload between verification
        # and durable reference publication. Persistent child pins take over only
        # through the retention integration; component flock alone is insufficient.
        build_use = open_use_guard(str(authority.registry), payload.component, payload.build)
        lease = -1
        guardian: Guardian | None = None
        try:
            current = registered(authority.registry, payload.component, payload.build)
            if current.root != payload.root or current.digest != payload.digest:
                refuse()
            verify_acceptance(authority, payload)
            acceptance = authority.read("qualification")["acceptanceSha256"]
            owner = process_identity(os.getpid())
            boot = boot_uuid()
            with authority.mutex():
                control = normal_control(authority)
                lease = authority.lease()
                invocation, writer = token(), token()
                guardian = cls(authority, payload, invocation, writer, control["epoch"], boot,
                               owner, acceptance, lease, build_use)
                private_directory(authority.folder / "writers" / invocation, create=True)
                row = guardian._bootstrap_writer()
                validate("writer", row)
                publish(writer_path(authority, invocation, writer), row)
            return guardian
        except BaseException:
            if guardian is not None:
                guardian.abort()
            else:
                if lease >= 0:
                    os.close(lease)
                os.close(build_use)
            raise

    def _bootstrap_writer(self) -> Object:
        return {"version": 1, "invocation": self.invocation, "writer": self.writer, "parent": None,
                "component": self.authority.component, "epoch": self.epoch, "payloadSha256": self.payload.digest,
                "boot": self.boot, **self.owner, "phase": "active", "contextSha256": None}

    def _check(self, *, allow_draining: bool = False) -> None:
        from .driver_payload import verify_acceptance

        if self.lease < 0 or self.transferred:
            refuse()
        control = self.authority.read("control")
        if allow_draining and control["phase"] == "draining":
            if control["epoch"] != self.epoch:
                refuse()
        else:
            normal_control(self.authority, epoch=self.epoch)
        named = (self.authority.folder / "admission.lock").lstat()
        held = os.fstat(self.lease)
        if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
            refuse()
        if (boot_uuid() != self.boot or process_identity(os.getpid()) != self.owner
                or read_writer(self.authority, self.invocation, self.writer) != self._bootstrap_writer()):
            refuse()
        verify_acceptance(self.authority, self.payload, digest=self.acceptance_sha256)

    def _close_owned(self) -> None:
        # Closing independent descriptions cannot unlock an acknowledged child.
        if self.lease >= 0:
            os.close(self.lease)
            self.lease = -1
        if self.build_use >= 0:
            os.close(self.build_use)
            self.build_use = -1

    def abort(self) -> None:
        try:
            with self.authority.mutex():
                custody_loss(self.authority, invocation=self.invocation, epoch=self.epoch,
                             boot=self.boot, payload_sha256=self.payload.digest)
        finally:
            self._close_owned()

    def spawn_main(self, arguments: list[str], *, environment: dict[str, str] | None = None,
                   prepared: Callable[[subprocess.Popen[bytes], Object], None] | None = None) -> subprocess.Popen[bytes]:
        """Preregister, spawn blocked, then accept exact ready/go/started transfer.

        Arguments and inherited normal environment are forwarded without storing
        them. Only one explicitly listed socket descriptor reaches this child.
        """
        if self.handoff is not None or self.transferred:
            refuse()
        handoff, child_writer, nonce = token(), token(), token()
        context_path = self.authority.folder / "handoffs" / (handoff + ".context.json")
        pending: Object = {"version": 1, "handoff": handoff, "component": self.authority.component,
                           "invocation": self.invocation, "parent": self.writer, "child": child_writer,
                           "epoch": self.epoch, "payloadSha256": self.payload.digest, "phase": "pending",
                           "nonce": nonce, "contextSha256": None, "role": "main",
                           "entry": self.payload.descriptor["entry"], "acceptanceSha256": self.acceptance_sha256}
        frames: Frames | None = None
        child_socket: socket.socket | None = None
        try:
            with self.authority.mutex():
                self._check()
                validate("handoff", pending)
                if handoff_path(self.authority, handoff).exists() or context_path.exists():
                    refuse()
                publish(handoff_path(self.authority, handoff), pending)
                self.handoff = handoff
            parent_socket, child_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            frames = Frames(parent_socket.detach())
            child_fd = child_socket.fileno()
            if child_fd < 3:
                refuse()
            inherited = os.environ.copy() if environment is None else dict(environment)
            child_environment = {**without_authority(inherited), NORMAL_FD: str(child_fd),
                                 NORMAL_CONTEXT: str(context_path)}
            child = subprocess.Popen([*self.payload.prefix, *arguments], env=child_environment,
                                     pass_fds=(child_fd,), close_fds=True, process_group=0)
            child_socket.close()
            child_socket = None
            identity = process_identity(child.pid)
            if not matches(identity, parent=os.getpid()):
                refuse()
            self.child_owner = identity
            if prepared is not None:
                prepared(child, identity)
            context: Object = {"version": 1, "kind": "driver-admission-context", "role": "main",
                               "registry": str(self.authority.registry),
                               "registrySha256": sha256(canonical(self.authority.identity)),
                               "component": self.authority.component, "epoch": self.epoch, "boot": self.boot,
                               "invocation": self.invocation, "writer": child_writer,
                               "parent": {"writer": self.writer, **self.owner}, "process": identity,
                               "handoff": handoff, "nonce": nonce, "payloadSha256": self.payload.digest,
                               "acceptanceSha256": self.acceptance_sha256, "entry": self.payload.descriptor["entry"]}
            normal_context(context)
            digest = sha256(canonical(context))
            with self.authority.mutex():
                self._check()
                if read_handoff(self.authority, handoff) != pending or context_path.exists():
                    refuse()
                publish(context_path, context)
                pending = {**pending, "contextSha256": digest}
                publish(handoff_path(self.authority, handoff), pending)
            frames.send({"version": 1, "type": "offer", "contextSha256": digest})
            ready = frames.receive()
            fields(ready, "version type handoff nonce contextSha256 challenge")
            frame = {"version": 1, "handoff": handoff, "nonce": nonce,
                     "contextSha256": digest, "challenge": ready["challenge"]}
            if ready != {**frame, "type": "ready"} or not valid_token(ready["challenge"]):
                refuse()
            expected: Object = {"version": 1, "invocation": self.invocation, "writer": child_writer,
                                "parent": self.writer, "component": self.authority.component, "epoch": self.epoch,
                                "payloadSha256": self.payload.digest, "boot": self.boot, **identity,
                                "phase": "active", "contextSha256": digest}
            with self.authority.mutex():
                self._check()
                if (read_handoff(self.authority, handoff) != pending
                        or read_writer(self.authority, self.invocation, child_writer) != expected
                        or not matches(identity, parent=os.getpid())):
                    refuse()
                accepted = {**pending, "phase": "accepted", "challenge": ready["challenge"]}
                validate("handoff", accepted)
                publish(handoff_path(self.authority, handoff), accepted)
            frames.send({**frame, "type": "go"})
            started = frames.receive()
            fields(started, "version type handoff nonce contextSha256 challenge")
            if started != {**frame, "type": "started"}:
                refuse()
            frames.no_extra()
            with self.authority.mutex():
                # begin may close normal admission after the child's started
                # acknowledgement. This already accepted transfer stays counted
                # in its original epoch while draining; it is not a new launch.
                self._check(allow_draining=True)
                if read_handoff(self.authority, handoff) != accepted:
                    refuse()
                registered_child = read_writer(self.authority, self.invocation, child_writer)
                if registered_child != expected and registered_child != {**expected, "phase": "terminal"}:
                    refuse()
                publish(writer_path(self.authority, self.invocation, self.writer),
                        {**self._bootstrap_writer(), "phase": "terminal"})
                self.transferred = True
            # Only now may the guardian release its transfer obligation. The
            # accepted independent child and durable references remain counted.
            self._close_owned()
            return child
        except BaseException:
            self.abort()
            raise
        finally:
            if child_socket is not None:
                child_socket.close()
            if frames is not None:
                frames.close()


class Terminal:
    """A controlling terminal is shared, never replaced with a proxy or a PTY."""

    def __init__(self) -> None:
        self.descriptor = -1
        self.group = os.getpgrp()
        self.child_group: int | None = None
        try:
            descriptor = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY | os.O_CLOEXEC)
        except OSError as error:
            if error.errno in (errno.ENXIO, errno.ENODEV, errno.ENOENT, errno.ENOTTY):
                return
            raise
        try:
            os.tcgetpgrp(descriptor)
            self.descriptor = descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _current(self) -> int | None:
        try:
            return os.tcgetpgrp(self.descriptor)
        except OSError as error:
            if error.errno in (errno.ENOTTY, errno.ENXIO, errno.EIO):
                return None
            raise

    def _foreground(self, group: int) -> None:
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTTOU})
        try:
            os.tcsetpgrp(self.descriptor, group)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)

    def claim(self, group: int) -> None:
        self.child_group = group
        if self.descriptor >= 0 and self._current() == self.group:
            self._foreground(group)

    def release(self) -> None:
        if (self.descriptor >= 0 and self.child_group is not None
                and self._current() == self.child_group):
            self._foreground(self.group)

    def close(self) -> None:
        try:
            self.release()
        finally:
            if self.descriptor >= 0:
                descriptor, self.descriptor = self.descriptor, -1
                os.close(descriptor)


def _terminate(number: int) -> NoReturn:
    if number not in (signal.SIGKILL, signal.SIGSTOP):
        signal.signal(number, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {number})
    os.kill(os.getpid(), number)
    os._exit(128 + number)


class SignalBridge:
    """Forward asynchronous command control to a verified main/group anchor.

    SIGKILL/STOP cannot be trapped. Guardian loss leaves the child's independent
    lease and durable obligations intact; it is never cleanup or drain evidence.
    """

    def __init__(self, terminal: Terminal):
        self.terminal = terminal
        self.child: subprocess.Popen[bytes] | None = None
        self.owner: Object | None = None
        self.pending: set[int] = set()
        self.received: list[int] = []
        self.previous: dict[int, Any] = {}

    def install(self) -> None:
        names = ("SIGHUP", "SIGINT", "SIGQUIT", "SIGTERM", "SIGUSR1", "SIGUSR2", "SIGALRM", "SIGPIPE",
                 "SIGXCPU", "SIGXFSZ", "SIGVTALRM", "SIGPROF", "SIGURG", "SIGWINCH", "SIGIO",
                 "SIGTSTP", "SIGTTIN", "SIGTTOU", "SIGCONT")
        try:
            for name in names:
                number = getattr(signal, name, None)
                if number is None:
                    continue
                prior = signal.getsignal(number)
                if prior == signal.SIG_IGN and number != signal.SIGCONT:
                    continue
                self.previous[number] = signal.signal(number, self._signal)
        except BaseException:
            self.restore()
            raise

    def restore(self) -> None:
        for number, prior in self.previous.items():
            signal.signal(number, prior)
        self.previous.clear()

    def _forward(self, number: int) -> None:
        if self.child is None or self.owner is None:
            self.pending.add(number)
            return
        current = inspect(self.owner["pid"])
        if current is None or current.owner != self.owner:
            return
        if number == signal.SIGCONT and current.group == self.child.pid:
            self.terminal.claim(current.group)
        try:
            # This group is a signal/TTY convenience, never a custody oracle.
            # A changed/detached main is signalled by its exact identity alone.
            if current.group == self.child.pid:
                os.killpg(current.group, number)
            else:
                os.kill(current.owner["pid"], number)
        except ProcessLookupError:
            pass

    def _signal(self, number: int, frame: FrameType | None) -> None:
        self.received.append(number)
        self._forward(number)

    def prepared(self, child: subprocess.Popen[bytes], owner: Object) -> None:
        self.child, self.owner = child, owner
        current = inspect(child.pid)
        if current is None or current.owner != owner or current.group != child.pid:
            refuse()
        self.terminal.claim(child.pid)
        pending, self.pending = sorted(self.pending), set()
        for number in pending:
            self._forward(number)

    def stopped(self, number: int) -> None:
        self.terminal.release()
        prior = None if number == signal.SIGSTOP else signal.signal(number, signal.SIG_DFL)
        mask = signal.pthread_sigmask(signal.SIG_UNBLOCK, {number})
        try:
            os.kill(os.getpid(), number)
        finally:
            # On foreground resume the SIGCONT handler claims the terminal for
            # the same verified child before forwarding its continuation.
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            if prior is not None:
                signal.signal(number, prior)

    def interrupted(self) -> int | None:
        nonfatal = {getattr(signal, name) for name in (
            "SIGCONT", "SIGWINCH", "SIGURG", "SIGIO", "SIGTSTP", "SIGTTIN", "SIGTTOU") if hasattr(signal, name)}
        return next((number for number in self.received if number not in nonfatal), None)


def supervise(guardian: Guardian, arguments: list[str]) -> int:
    """No read/write on caller stdio. Mirror child's exit or terminating signal."""
    try:
        terminal = Terminal()
    except BaseException:
        guardian.abort()
        raise
    bridge = SignalBridge(terminal)
    ended_by: int | None = None
    exit_code = 1
    try:
        bridge.install()
        child = guardian.spawn_main(arguments, prepared=bridge.prepared)
        while True:
            try:
                pid, status = os.waitpid(child.pid, os.WUNTRACED | os.WCONTINUED)
            except InterruptedError:
                continue
            if pid != child.pid:
                refuse()
            if os.WIFSTOPPED(status):
                bridge.stopped(os.WSTOPSIG(status))
            elif os.WIFCONTINUED(status):
                continue
            elif os.WIFEXITED(status):
                exit_code = os.WEXITSTATUS(status)
                child.returncode = exit_code
                break
            elif os.WIFSIGNALED(status):
                ended_by = os.WTERMSIG(status)
                child.returncode = -ended_by
                break
    except BaseException:
        # A pre-transfer error must not discard the bootstrap lease obligation.
        if not guardian.transferred:
            try:
                guardian.abort()
            except Exception:
                # Already durable unresolved obligations remain. A failed taint
                # write never grants cleanup; preserve the original interruption.
                pass
        interrupted = bridge.interrupted()
        if interrupted is None:
            raise
        ended_by = interrupted
    finally:
        try:
            terminal.close()
        finally:
            bridge.restore()
    if ended_by is not None:
        _terminate(ended_by)
    return exit_code


def request_cancellation(authority: Authority, custody: Custody, sent: set[tuple[int, str]]) -> None:
    """Under the short mutex, request each exact admitted main's normal stop.

    All four existing runs.stop implementations signal the command owner with
    SIGTERM and bound acknowledgement to twenty seconds. The Driver retains
    its own vendor cancellation/escalation duties. No helper/group/descendant
    kill or terminal disposition is inferred here.
    """
    mains = {(row["invocation"], row["child"]) for row in custody.handoffs
             if row["phase"] == "accepted" and row["role"] == "main"}
    for writer in custody.writers:
        if writer["phase"] != "active" or (writer["invocation"], writer["writer"]) not in mains:
            continue
        owner = {key: writer[key] for key in ("pid", "startedAt")}
        key = (owner["pid"], owner["startedAt"])
        if key in sent:
            continue
        if (owner["pid"] == os.getpid()
                or read_writer(authority, writer["invocation"], writer["writer"]) != writer):
            refuse()
        if matches(owner):
            try:
                os.kill(owner["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
        sent.add(key)


@dataclass(frozen=True)
class AdministrativeOutput:
    stdout: bytes
    returncode: int


def administrative_argv(payload: Payload, context: Object, binding: Object) -> list[str]:
    """Only the four agreed administrative rows, never caller-provided child argv."""
    from .driver_payload import request_binding

    request_binding(binding, context)
    if (payload.component != context["component"] or payload.digest != context["payloadSha256"]
            or payload.build != binding["build"]):
        refuse()
    receipt = str(Path(context["registry"]) / context["component"] / ".driver-admission" / "maintenance.json")
    common = [*payload.prefix, "--state-dir", context["stateDirectory"], "state"]
    tail = ["--confirm-quiescent", "--maintenance", receipt, "--backup", binding["backup"]]
    operation = context["operation"]
    if operation == "upgrade":
        return [*common, "upgrade", "--from-format", "1", *tail]
    if operation == "identity-reset":
        return [*common, "identity-reset", *tail]
    if operation == "restore":
        return [*common, "restore", "--source", binding["source"], "--backup", binding["backup"],
                "--confirm-quiescent", "--maintenance", receipt]
    if operation == "identity-recover":
        return [*common, "identity-recover", "--subscription", context["subscription"], "--retire", *tail]
    refuse()


def _signal_administrative(child: subprocess.Popen[bytes], owner: Object | None, number: int) -> None:
    # No group/descendant traversal or unverified kill. An exited unreaped child
    # belongs to Popen's wait handle; a live signal still requires exact start.
    if child.poll() is None and owner is not None and matches(owner):
        try:
            os.kill(owner["pid"], number)
        except ProcessLookupError:
            pass


def run_administrative(payload: Payload, context: Object, binding: Object, descriptor: int,
                       context_path: Path, check: Callable[[], None]) -> AdministrativeOutput:
    """Retain parent EX and pass only a duplicate of that same locked OFD.

    Administrative JSON is privately captured and bounded, not relayed. The
    normal launcher/TTY path does not use this offline-only supervisor. Every
    failure leaves the already-published attempt/control unchanged for recovery.
    """
    from .driver_admission import MAINTENANCE_CONTEXT, MAINTENANCE_FD

    if descriptor < 3 or os.get_inheritable(descriptor):
        refuse()
    argv = administrative_argv(payload, context, binding)
    # Fail unsupported process identity before spawn, never after state effects
    # merely because a coarse PID-only fallback could not be established.
    process_identity(os.getpid())
    duplicate = -1
    child: subprocess.Popen[bytes] | None = None
    owner: Object | None = None
    received: set[int] = set()
    previous: dict[int, Any] = {}
    interrupted = overflow = False
    cancellation: float | None = None
    killed: float | None = None
    exited: float | None = None
    stdout = bytearray()
    totals = {"stdout": 0, "stderr": 0}

    def requested(number: int, frame: FrameType | None) -> None:
        received.add(number)

    try:
        for signal_number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
            prior = signal.getsignal(signal_number)
            if prior != signal.SIG_IGN:
                previous[signal_number] = signal.signal(signal_number, requested)
        check()
        if received:
            refuse()
        duplicate = os.dup(descriptor)
        if duplicate < 3:
            refuse()
        os.set_inheritable(duplicate, True)
        environment = {**without_authority(os.environ.copy()), MAINTENANCE_FD: str(duplicate),
                       MAINTENANCE_CONTEXT: str(context_path)}
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=environment, pass_fds=(duplicate,), close_fds=True, process_group=0)
        os.close(duplicate)
        duplicate = -1
        try:
            owner = process_identity(child.pid)
        except (OSError, ValueError, RuntimeError):
            if child.poll() is None:
                # No trustworthy signal target exists. Close our copies only;
                # the child's inherited EX and durable pending attempt survive.
                raise
        assert child.stdout is not None and child.stderr is not None
        with selectors.DefaultSelector() as selector:
            for name, stream in (("stdout", child.stdout), ("stderr", child.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map() or child.poll() is None:
                now = time.monotonic()
                if received:
                    interrupted = True
                    pending_signals = sorted(received)
                    received.clear()
                    for requested_number in pending_signals:
                        _signal_administrative(child, owner, requested_number)
                    if cancellation is None:
                        cancellation = now
                if overflow and cancellation is None:
                    _signal_administrative(child, owner, signal.SIGTERM)
                    cancellation = now
                if cancellation is not None and now - cancellation >= 5 and child.poll() is None and killed is None:
                    _signal_administrative(child, owner, signal.SIGKILL)
                    killed = now
                if killed is not None and now - killed >= 5 and child.poll() is None:
                    refuse()  # Kernel-stuck/unknown child keeps its lease; no reopen.
                if child.poll() is not None:
                    exited = now if exited is None else exited
                    if selector.get_map() and now - exited >= 5:
                        refuse()  # A retained pipe is not a helper-lifetime oracle.
                for event, _mask in selector.select(0.05):
                    try:
                        block = os.read(event.fd, 65536)
                    except BlockingIOError:
                        continue
                    if not block:
                        selector.unregister(event.fileobj)
                        continue
                    name = event.data
                    totals[name] = min(LIMIT + 1, totals[name] + len(block))
                    if totals[name] > LIMIT:
                        overflow = True
                    elif name == "stdout" and not overflow:
                        stdout.extend(block)
            returncode = child.wait()
        if interrupted or overflow or returncode != 0 or not stdout:
            refuse()
        return AdministrativeOutput(bytes(stdout), returncode)
    finally:
        if duplicate >= 0:
            os.close(duplicate)
        if child is not None:
            for pipe in (child.stdout, child.stderr):
                if pipe is not None:
                    pipe.close()
        for restore_number, prior in previous.items():
            signal.signal(restore_number, prior)
        # Never LOCK_UN or close the caller's original exclusive description.
