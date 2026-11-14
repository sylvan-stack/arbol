"""Private cooperative Driver authority (DRV-6.18/.21).

Registry obligations are durable; process observations alone never discharge them.
Only independently opened descriptions are closed here. Never unlock an inherited lease.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

Object = dict[str, Any]
COMPONENTS = tuple(f"arbol-{name}-driver" for name in ("claude", "codex", "mimo", "pi"))
LIMIT = 4096
MANIFEST_LIMIT = 32 * 1024 * 1024
HEX = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)


class Refusal(ValueError):
    """A bounded nonsecret refusal; exception text never includes document values."""


def refuse() -> NoReturn:
    raise Refusal("Driver admission authority is missing, changed or unsafe; preserve it for closed recovery.")


def token() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


def valid_token(value: object) -> bool:
    if not isinstance(value, str) or TOKEN.fullmatch(value) is None:
        return False
    try:
        raw = base64.urlsafe_b64decode(value + "=")
        return len(raw) == 32 and base64.urlsafe_b64encode(raw).decode().rstrip("=") == value
    except ValueError:
        return False


def valid_hash(value: object) -> bool:
    return isinstance(value, str) and HEX.fullmatch(value) is not None


def canonical_uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def natural(value: object, *, positive: bool = False) -> bool:
    return type(value) is int and value >= int(positive)


def canonical(value: Object) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                           allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, UnicodeError, TypeError):
        refuse()
    raise AssertionError


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _pairs(items: list[tuple[str, Any]]) -> Object:
    result: Object = {}
    for name, value in items:
        if name in result:
            refuse()
        result[name] = value
    return result


def _constant(value: str) -> Any:
    refuse()


def decode(raw: bytes, *, limit: int = LIMIT, exact: bool = True) -> Object:
    if not raw or len(raw) > limit:
        refuse()
    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_pairs,
                           parse_constant=_constant, parse_float=_constant)
    except (ValueError, UnicodeError):
        refuse()
    if not isinstance(value, dict) or (exact and canonical(value) != raw):
        refuse()
    return value


def fields(value: Object, names: str) -> None:
    if set(value) != set(names.split()) or type(value.get("version")) is not int or value.get("version") != 1:
        refuse()


def physical(path: str | Path, *, directory: bool = True) -> Path:
    """A preexisting absolute physical path, with no symlink component."""
    candidate = Path(path)
    if not candidate.is_absolute() or str(candidate) != os.path.abspath(candidate):
        refuse()
    try:
        if candidate.resolve(strict=True) != candidate:
            refuse()
        info = candidate.lstat()
        if directory and not stat.S_ISDIR(info.st_mode):
            refuse()
    except OSError:
        refuse()
    return candidate


def private_directory(path: Path, *, create: bool = False) -> Path:
    if create:
        # The parent is already verified. Never follow an existing symlink to create children.
        physical(path.parent)
        try:
            path.mkdir(mode=0o700)
            sync_directory(path.parent)
        except FileExistsError:
            pass
    physical(path)
    info = path.lstat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        refuse()
    return path


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _regular(descriptor: int, *, mode: int = 0o600) -> os.stat_result:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != mode:
        refuse()
    return info


def read_bytes(path: Path, *, limit: int = LIMIT) -> bytes:
    private_directory(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = _regular(descriptor)
        if info.st_size > limit:
            refuse()
        raw = bytearray()
        while len(raw) <= limit:
            block = os.read(descriptor, min(65536, limit + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        current = _regular(descriptor)
        named = path.lstat()
        if ((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) !=
                (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
                or (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino) or len(raw) > limit):
            refuse()
        return bytes(raw)
    finally:
        os.close(descriptor)


def read(path: Path, *, limit: int = LIMIT) -> Object:
    return decode(read_bytes(path, limit=limit), limit=limit)


def publish_bytes(path: Path, raw: bytes, *, limit: int = LIMIT) -> None:
    private_directory(path.parent)
    if len(raw) > limit:
        refuse()
    try:
        prior = path.lstat()
        if not stat.S_ISREG(prior.st_mode) or prior.st_uid != os.getuid() or stat.S_IMODE(prior.st_mode) != 0o600:
            refuse()
    except FileNotFoundError:
        pass
    temporary = path.parent / ("." + path.name + "." + token())
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def publish(path: Path, value: Object, *, limit: int = LIMIT) -> None:
    publish_bytes(path, canonical(value), limit=limit)


def remove(path: Path) -> None:
    private_directory(path.parent)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            refuse()
        path.unlink()
        sync_directory(path.parent)
    except FileNotFoundError:
        pass


def validate(kind: str, value: Object) -> None:
    """Strict record field/type boundary. Operation-specific invariants are checked by its consumer."""
    schemas = {
        "control": "version phase session epoch",
        "writer": "version invocation writer parent component epoch payloadSha256 boot pid startedAt phase contextSha256",
        "handoff": "version handoff component invocation parent child epoch payloadSha256 phase nonce contextSha256 role entry acceptanceSha256",
        "taint": "version component epoch boot reason invocation payloadSha256",
        "maintenance": "version kind component session epoch phase gateSha256",
        "qualification": "version component acceptanceSha256",
        "deployment": "version kind session registrySha256 gateSha256 callersSha256 oldBoot newBoot phase components checkpoint",
        "context": "version kind component session epoch gateSha256 payloadSha256 stateDirectory operation attempt receiptSha256 registry acceptanceSha256 generation",
        "operation": "version kind component session epoch gateSha256 payloadSha256 stateDirectory operation attempt receiptSha256 registry acceptanceSha256 generation phase sourceSha256 backupSha256",
        "result": "version kind component session epoch operation attempt payloadSha256 stateDirectorySha256 format generation status backupSha256",
    }
    names = schemas.get(kind)
    if names is None:
        refuse()
    if kind == "handoff" and value.get("phase") == "accepted":
        names += " challenge"
    if kind in ("context", "operation", "result") and value.get("operation") == "identity-recover":
        names += " subscription"
    fields(value, names)
    if "component" in value and value["component"] not in COMPONENTS:
        refuse()
    for key in ("epoch", "invocation", "writer", "handoff", "child", "nonce", "challenge", "attempt", "generation", "checkpoint"):
        if key in value and not valid_token(value[key]):
            refuse()
    for key in ("payloadSha256", "contextSha256", "sourceSha256", "backupSha256"):
        if key in value and value[key] is not None and not valid_hash(value[key]):
            refuse()
    for key in ("gateSha256", "registrySha256", "callersSha256", "receiptSha256", "acceptanceSha256", "stateDirectorySha256"):
        if key in value and not valid_hash(value[key]):
            refuse()
    for key in ("boot", "oldBoot"):
        if key in value and not canonical_uuid(value[key]):
            refuse()
    if "newBoot" in value and value["newBoot"] is not None and not canonical_uuid(value["newBoot"]):
        refuse()
    if "session" in value and value["session"] is not None and not canonical_uuid(value["session"]):
        refuse()
    if kind == "control":
        if value["phase"] not in ("normal", "draining", "exclusive") or (value["phase"] == "normal") != (value["session"] is None):
            refuse()
    if kind == "writer":
        if (not natural(value["pid"], positive=True) or not isinstance(value["startedAt"], str)
                or not value["startedAt"] or value["phase"] not in ("active", "terminal")
                or (value["parent"] is not None and not valid_token(value["parent"]))):
            refuse()
    if kind == "handoff" and (value["phase"] not in ("pending", "accepted")
                              or value["role"] not in ("main", "helper") or not valid_token(value["parent"])):
        refuse()
    if kind == "taint" and value["reason"] not in ("legacy", "custody-loss", "initial-deployment"):
        refuse()
    if kind == "maintenance" and (value["kind"] != "driver-state-maintenance" or value["phase"] != "exclusive"):
        refuse()
    if kind in ("context", "operation", "result"):
        if value["operation"] not in ("upgrade", "identity-reset", "restore", "identity-recover"):
            refuse()
        expected = "driver-state-result" if kind == "result" else "driver-state-context"
        if value["kind"] != expected:
            refuse()
    if kind == "operation" and value["phase"] != "pending":
        refuse()
    if kind == "result" and (type(value["format"]) is not int or value["format"] != 2 or value["status"] != "complete"):
        refuse()
    if kind == "deployment" and (value["kind"] != "driver-gate-deployment" or value["phase"] not in (
            "staged", "closed-installed", "awaiting-boot", "boot-verified", "maintaining", "complete", "failed-closed")):
        refuse()


@dataclass(frozen=True)
class Authority:
    registry: Path
    component: str

    def __post_init__(self) -> None:
        private_directory(self.registry)
        if self.component not in COMPONENTS:
            refuse()

    @property
    def folder(self) -> Path:
        return self.registry / self.component / ".driver-admission"

    @property
    def shared(self) -> Path:
        return self.registry / ".driver-qualification"

    @property
    def identity(self) -> Object:
        info = self.registry.stat()
        return {"path": str(self.registry), "device": info.st_dev, "inode": info.st_ino}

    def initialize(self, session: str, epoch: str) -> None:
        """Deployment-only creation. Existing control is never overwritten as initialization."""
        private_directory(self.registry / self.component, create=True)
        private_directory(self.folder, create=True)
        for name in ("writers", "handoffs", "sessions", "archive"):
            private_directory(self.folder / name, create=True)
        for name in ("control.lock", "admission.lock"):
            fd = self.open_lock(name, create=True)
            os.close(fd)
        if not (self.folder / "control.json").exists():
            with self.mutex():
                if not (self.folder / "control.json").exists():
                    self.write("control", {"version": 1, "phase": "draining", "session": session, "epoch": epoch})

    def open_lock(self, name: str, *, create: bool = False) -> int:
        if name not in ("control.lock", "admission.lock"):
            refuse()
        private_directory(self.folder)
        path = self.folder / name
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_CREAT if create else 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            info = _regular(descriptor)
            named = path.lstat()
            if (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino):
                refuse()
            if create:
                os.fsync(descriptor)
                sync_directory(path.parent)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @contextmanager
    def mutex(self, *, seconds: float = 20) -> Iterator[None]:
        fd = self.open_lock("control.lock")
        deadline = time.monotonic() + seconds
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        refuse()
                    time.sleep(min(0.01, max(0, deadline - time.monotonic())))
            current = self.folder / "control.lock"
            if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != (current.stat().st_dev, current.stat().st_ino):
                refuse()
            yield
        finally:
            os.close(fd)

    def lease(self, *, exclusive: bool = False) -> int:
        descriptor = self.open_lock("admission.lock")
        try:
            fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def read(self, kind: str) -> Object:
        value = read(self.folder / (kind + ".json"))
        validate(kind, value)
        return value

    def write(self, kind: str, value: Object) -> None:
        validate(kind, value)
        publish(self.folder / (kind + ".json"), value)
