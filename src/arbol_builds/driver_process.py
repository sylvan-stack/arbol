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
import socket
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING

from .driver_admission import (
    LIMIT,
    NORMAL_CONTEXT,
    NORMAL_FD,
    Authority,
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

    def spawn_main(self, arguments: list[str], *, environment: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
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
                                     pass_fds=(child_fd,), close_fds=True)
            child_socket.close()
            child_socket = None
            identity = process_identity(child.pid)
            if not matches(identity, parent=os.getpid()):
                refuse()
            self.child_owner = identity
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
