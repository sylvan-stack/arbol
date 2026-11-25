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
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from .driver_payload import CandidateScope

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
    if kind == "deployment":
        if (value["phase"] in ("boot-verified", "maintaining", "complete")
                and (not canonical_uuid(value["newBoot"]) or value["newBoot"] == value["oldBoot"])):
            refuse()
        if value["phase"] in ("staged", "closed-installed") and value["newBoot"] is not None:
            refuse()
        rows = value["components"]
        if not isinstance(rows, list) or len(rows) != len(COMPONENTS):
            refuse()
        for component, row in zip(COMPONENTS, rows, strict=True):
            if (not isinstance(row, dict) or set(row) != {"component", "epoch", "launcherSha256", "closed"}
                    or row["component"] != component or row["closed"] is not True
                    or not valid_token(row["epoch"]) or not valid_hash(row["launcherSha256"])):
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


NORMAL_FD = "ARBOL_DRIVER_ADMISSION_FD"
NORMAL_CONTEXT = "ARBOL_DRIVER_ADMISSION_CONTEXT"
MAINTENANCE_FD = "ARBOL_DRIVER_MAINTENANCE_FD"
MAINTENANCE_CONTEXT = "ARBOL_DRIVER_MAINTENANCE_CONTEXT"
AUTHORITY_ENV = (NORMAL_FD, NORMAL_CONTEXT, MAINTENANCE_FD, MAINTENANCE_CONTEXT)


def without_authority(environment: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in environment.items() if key not in AUTHORITY_ENV}


def normal_context(value: Object) -> None:
    from .driver_payload import relative
    from .driver_process import identity_record

    fields(value, "version kind role registry registrySha256 component epoch boot invocation writer parent process handoff nonce payloadSha256 acceptanceSha256 entry")
    if (value["kind"] != "driver-admission-context" or value["role"] not in ("main", "helper")
            or value["component"] not in COMPONENTS or not isinstance(value["registry"], str)):
        refuse()
    for key in ("epoch", "invocation", "writer", "handoff", "nonce"):
        if not valid_token(value[key]):
            refuse()
    for key in ("registrySha256", "payloadSha256", "acceptanceSha256"):
        if not valid_hash(value[key]):
            refuse()
    if not canonical_uuid(value["boot"]):
        refuse()
    relative(value["entry"])
    identity_record(value["process"])
    parent = value["parent"]
    if (not isinstance(parent, dict) or set(parent) != {"writer", "pid", "startedAt"}
            or not valid_token(parent["writer"])):
        refuse()
    identity_record({key: parent[key] for key in ("pid", "startedAt")})


def writer_path(authority: Authority, invocation: str, writer: str) -> Path:
    if not valid_token(invocation) or not valid_token(writer):
        refuse()
    return authority.folder / "writers" / invocation / (writer + ".json")


def read_writer(authority: Authority, invocation: str, writer: str) -> Object:
    value = read(writer_path(authority, invocation, writer))
    validate("writer", value)
    if (value["component"] != authority.component or value["invocation"] != invocation
            or value["writer"] != writer):
        refuse()
    return value


def handoff_path(authority: Authority, handoff: str) -> Path:
    if not valid_token(handoff):
        refuse()
    return authority.folder / "handoffs" / (handoff + ".json")


def read_handoff(authority: Authority, handoff: str) -> Object:
    value = read(handoff_path(authority, handoff))
    validate("handoff", value)
    if value["handoff"] != handoff or value["component"] != authority.component:
        refuse()
    return value


def fresh_install(registry: Path) -> Object | None:
    try:
        value = read(registry / ".driver-qualification" / "fresh-install.json")
    except FileNotFoundError:
        return None
    fields(value, "version kind mode session boot registrySha256 gateSha256 promotionSha256 phase components")
    if (value["kind"] != "driver-fresh-install" or value["mode"] != "fresh"
            or value["phase"] not in ("staging", "complete")
            or not canonical_uuid(value["session"]) or not canonical_uuid(value["boot"])
            or any(not valid_hash(value[name]) for name in ("registrySha256", "gateSha256", "promotionSha256"))
            or not isinstance(value["components"], list) or len(value["components"]) != len(COMPONENTS)):
        refuse()
    row_fields = set("component build payloadSha256 launcher launcherSha256 stateDirectory stateDirectoryIdentity epoch".split())
    for name, row in zip(COMPONENTS, value["components"], strict=True):
        if (not isinstance(row, dict) or set(row) != row_fields or row["component"] != name
                or not isinstance(row["build"], str) or not isinstance(row["launcher"], str)
                or not isinstance(row["stateDirectory"], str) or not valid_hash(row["payloadSha256"])
                or not valid_hash(row["launcherSha256"]) or not valid_token(row["epoch"])):
            refuse()
        identity = row["stateDirectoryIdentity"]
        if identity is None and value["phase"] == "staging":
            continue
        if (not isinstance(identity, dict) or set(identity) != {"device", "inode"}
                or not natural(identity["device"]) or not natural(identity["inode"], positive=True)):
            refuse()
    return value


def normal_control(authority: Authority, *, epoch: str | None = None,
                   candidate: CandidateScope | None = None) -> Object:
    """Caller holds the mutex. A durable closed deployment overrides normal controls."""
    control = authority.read("control")
    if control["phase"] != "normal" or (epoch is not None and control["epoch"] != epoch):
        refuse()
    fresh = fresh_install(authority.registry)
    if fresh is not None and fresh["phase"] != "complete":
        refuse()
    deployment = authority.shared / "deployment.json"
    if deployment.exists():
        value = read(deployment)
        validate("deployment", value)
        if value["phase"] != "complete":
            refuse()
    try:
        taint = authority.read("taint")
    except FileNotFoundError:
        taint = None
    if taint is not None:
        if taint["component"] != authority.component or taint["reason"] != "legacy":
            refuse()
    if not reconcile(authority, control=control, candidate=candidate).unknown:
        return control
    refuse()


def custody_loss(authority: Authority, *, invocation: str, epoch: str, boot: str,
                 payload_sha256: str | None) -> None:
    """Caller holds the mutex. Preserve an earlier cause before adding this one.

    Normal launch checks this taint as closed; begin can claim a caller-owned
    maintenance session without an invented automatic session UUID.
    """
    path = authority.folder / "taint.json"
    try:
        prior = read_bytes(path)
    except FileNotFoundError:
        prior = None
    if prior is not None:
        archive = private_directory(authority.folder / "archive") / ("taint-" + sha256(prior) + ".json")
        if archive.exists() and read_bytes(archive) != prior:
            refuse()
        if not archive.exists():
            publish_bytes(archive, prior)
    value = {"version": 1, "component": authority.component, "epoch": epoch, "boot": boot,
             "reason": "custody-loss", "invocation": invocation, "payloadSha256": payload_sha256}
    authority.write("taint", value)


@dataclass(frozen=True)
class Custody:
    writers: tuple[Object, ...]
    handoffs: tuple[Object, ...]
    active: int
    pending: int
    unknown: bool

    @property
    def resolved(self) -> bool:
        return not self.unknown and not self.active and not self.pending


@dataclass(frozen=True)
class ClosedGuardian:
    """One state-free root nominated by the installed recovery verifier."""

    lease: int
    invocation: str
    writer: str


def _documents(folder: Path, *, limit: int = 100000) -> list[Path]:
    private_directory(folder)
    found: list[Path] = []
    for path in folder.iterdir():
        if len(found) >= limit or not path.name.endswith(".json"):
            refuse()
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            refuse()
        found.append(path)
    return sorted(found)


def _custody_payload(authority: Authority, digest: str, *,
                     candidate: CandidateScope | None = None) -> Object:
    from .driver_payload import BUILD, registered, registered_descriptor

    if not valid_hash(digest):
        refuse()
    matches: list[Object] = []
    count = 0
    for folder in (authority.registry / authority.component).iterdir():
        count += 1
        if count > 100000:
            refuse()
        if not BUILD.fullmatch(folder.name):
            continue
        raw = registered_descriptor(authority.registry, authority.component, folder.name)
        if raw is None:
            continue
        if sha256(raw) == digest:
            payload = (registered(authority.registry, authority.component, folder.name) if candidate is None else
                       candidate.registered(authority.registry, authority.component, folder.name))
            matches.append(payload.descriptor)
    if len(matches) != 1:
        refuse()
    return matches[0]


def reconcile(authority: Authority, *, control: Object | None = None, persist_unknown: bool = True,
              boot: str | None = None, candidate: CandidateScope | None = None,
              closed_guardian: ClosedGuardian | None = None) -> Custody:
    """Under control mutex: inspect obligations, never infer terminal from death.

    Every preexisting helper is checked against its exact original admitted
    invocation/epoch/payload. Its accepted record survives its parent's exit.
    """
    from .driver_process import boot_uuid, identity_record, matches

    if candidate is not None and candidate.registry != authority.registry:
        refuse()
    control = authority.read("control") if control is None else control
    if closed_guardian is not None:
        if (persist_unknown or candidate is not None or control != authority.read("control")
                or not valid_token(closed_guardian.invocation) or not valid_token(closed_guardian.writer)):
            refuse()
        _exclusive(authority, closed_guardian.lease)
    boot = boot_uuid() if boot is None else boot
    if not canonical_uuid(boot):
        refuse()
    writers: dict[tuple[str, str], Object] = {}
    handoffs: dict[str, Object] = {}
    contexts: dict[str, tuple[Object, str]] = {}
    active = pending = 0
    unknown = False
    guardian_seen = False
    try:
        if (authority.folder / "archive" / "custody-pending.json").exists():
            refuse()  # Only closed exclusive archive recovery may interpret missing directories.
        root = private_directory(authority.folder / "writers")
        for invocation in sorted(root.iterdir()):
            if not valid_token(invocation.name):
                refuse()
            for path in _documents(invocation):
                writer_name = path.name.removesuffix(".json")
                value = read_writer(authority, invocation.name, writer_name)
                identity_record({key: value[key] for key in ("pid", "startedAt")})
                if (value["epoch"] != control["epoch"] or value["boot"] != boot
                        or not valid_hash(value["payloadSha256"])):
                    refuse()
                if value["parent"] is None:
                    if value["contextSha256"] is not None:
                        refuse()
                elif not valid_hash(value["contextSha256"]):
                    refuse()
                if len(writers) >= 100000:
                    refuse()
                writers[(invocation.name, writer_name)] = value
        for path in _documents(authority.folder / "handoffs"):
            if path.name.endswith(".context.json"):
                handoff = path.name.removesuffix(".context.json")
                if not valid_token(handoff):
                    refuse()
                raw = read_bytes(path)
                value = decode(raw)
                normal_context(value)
                if value["handoff"] != handoff:
                    refuse()
                contexts[handoff] = (value, sha256(raw))
            else:
                handoff = path.name.removesuffix(".json")
                handoffs[handoff] = read_handoff(authority, handoff)
        payloads: dict[str, Object] = {}
        incoming: dict[tuple[str, str], Object] = {}
        for handoff, value in handoffs.items():
            invocation = value["invocation"]
            parent = writers.get((invocation, value["parent"]))
            child = writers.get((invocation, value["child"]))
            if (parent is None or value["epoch"] != control["epoch"]
                    or value["payloadSha256"] != parent["payloadSha256"]
                    or value["epoch"] != parent["epoch"] or not valid_hash(value["payloadSha256"])):
                refuse()
            key = (invocation, value["child"])
            if key in incoming:
                refuse()
            incoming[key] = value
            if value["phase"] == "pending":
                pending += 1
                if parent["phase"] != "active":
                    refuse()
            elif child is None:
                refuse()
            if (candidate is not None
                    and value["acceptanceSha256"] != candidate.acceptance(authority.component)[0]):
                refuse()  # Never retarget an old pending/accepted handoff to a new selection.
            payload = payloads.get(value["payloadSha256"])
            if payload is None:
                payload = _custody_payload(authority, value["payloadSha256"], candidate=candidate)
                payloads[value["payloadSha256"]] = payload
            allowed = [payload["entry"]] if value["role"] == "main" else payload["helpers"]
            if value["entry"] not in allowed:
                refuse()
            context_pair = contexts.get(handoff)
            if value["contextSha256"] is None:
                if context_pair is not None or child is not None or value["phase"] != "pending":
                    refuse()
                continue
            if context_pair is None:
                refuse()
            context, digest = context_pair
            expected_parent = {"writer": parent["writer"], **{key: parent[key] for key in ("pid", "startedAt")}}
            if (digest != value["contextSha256"] or context["registry"] != str(authority.registry)
                    or context["registrySha256"] != sha256(canonical(authority.identity))
                    or context["component"] != authority.component or context["epoch"] != value["epoch"]
                    or context["boot"] != boot or context["invocation"] != invocation
                    or context["writer"] != value["child"] or context["parent"] != expected_parent
                    or any(context[key] != value[key] for key in (
                        "handoff", "nonce", "payloadSha256", "acceptanceSha256", "role", "entry"))):
                refuse()
            if child is not None and (child["parent"] != parent["writer"]
                                      or child["contextSha256"] != digest
                                      or child["payloadSha256"] != value["payloadSha256"]
                                      or context["process"] != {key: child[key] for key in ("pid", "startedAt")}):
                refuse()
            if value["phase"] == "pending" and not matches(context["process"], parent=parent["pid"]):
                refuse()
        if set(contexts) - set(handoffs):
            refuse()
        for key, writer in writers.items():
            if writer["parent"] is not None:
                handoff_value = incoming.get(key)
                if handoff_value is None or handoff_value["parent"] != writer["parent"]:
                    refuse()
                if writer["phase"] == "terminal" and handoff_value["phase"] != "accepted":
                    refuse()
            elif writer["phase"] == "terminal" and not any(
                    value["parent"] == writer["writer"] and value["invocation"] == writer["invocation"]
                    and value["phase"] == "accepted" for value in handoffs.values()):
                refuse()
            if writer["phase"] == "active":
                if closed_guardian is not None and key == (closed_guardian.invocation, closed_guardian.writer):
                    if writer["parent"] is not None or matches({key: writer[key] for key in ("pid", "startedAt")}):
                        refuse()
                    guardian_seen = True
                    continue
                active += 1
                if not matches({key: writer[key] for key in ("pid", "startedAt")}):
                    refuse()
        if closed_guardian is not None and (not guardian_seen or active or pending):
            refuse()
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        unknown = True
        if persist_unknown:
            custody_loss(authority, invocation=token(), epoch=control["epoch"], boot=boot, payload_sha256=None)
    return Custody(tuple(writers.values()), tuple(handoffs.values()), active, pending, unknown)


def _exclusive(authority: Authority, descriptor: int) -> None:
    """Verify the held description without ever unlocking it."""
    named = (authority.folder / "admission.lock").lstat()
    held = _regular(descriptor)
    if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
        refuse()
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    independent = authority.open_lock("admission.lock")
    try:
        try:
            fcntl.flock(independent, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        refuse()
    finally:
        os.close(independent)


def archive_terminal(authority: Authority, descriptor: int, *, candidate: CandidateScope | None = None) -> None:
    """Under control mutex and closed exclusive admission, archive whole trees.

    The bounded private archive journal makes the two directory renames resumable.
    It carries no new public admission fields and no account or process argv.
    """
    control = authority.read("control")
    if control["phase"] not in ("draining", "exclusive"):
        refuse()
    _exclusive(authority, descriptor)
    archive = private_directory(authority.folder / "archive")
    journal_path = archive / "custody-pending.json"
    try:
        journal = read(journal_path)
    except FileNotFoundError:
        custody = reconcile(authority, control=control, candidate=candidate)
        if not custody.resolved:
            refuse()
        journal = {"version": 1, "kind": "driver-custody-archive", "epoch": control["epoch"],
                   "archive": token(), "phase": "prepared"}
        private_directory(archive / ("custody-" + journal["archive"]), create=True)
        publish(journal_path, journal)
    fields(journal, "version kind epoch archive phase")
    if (journal["kind"] != "driver-custody-archive" or journal["epoch"] != control["epoch"]
            or not valid_token(journal["archive"])
            or journal["phase"] not in ("prepared", "writers", "handoffs", "complete")):
        refuse()
    destination = private_directory(archive / ("custody-" + journal["archive"]))
    phases = ("prepared", "writers", "handoffs", "complete")
    for index, name in enumerate(("writers", "handoffs")):
        source, target = authority.folder / name, destination / name
        if phases.index(journal["phase"]) <= index:
            if target.exists():
                private_directory(target)
                if source.exists():
                    refuse()
            else:
                private_directory(source)
                os.rename(source, target)
                sync_directory(destination)
                sync_directory(authority.folder)
            journal = {**journal, "phase": phases[index + 1]}
            publish(journal_path, journal)
        else:
            private_directory(target)
    # The old complete trees remain private recovery evidence. Recreate only
    # after both renames are durable; normal admission stays closed throughout.
    for name in ("writers", "handoffs"):
        private_directory(authority.folder / name, create=True)
    publish(journal_path, {**journal, "phase": "complete"})
    remove(journal_path)


@contextmanager
def deployment_mutex(registry: Path) -> Iterator[None]:
    """Serialize first-time authority creation and resumable rollout publication.

    This independent stable lock never substitutes for the four lexical short
    control mutexes or component admission. No child/operator work runs under it.
    """
    shared = private_directory(registry / ".driver-qualification", create=True)
    path = shared / "deployment.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        held = _regular(descriptor)
        named = path.lstat()
        if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
            refuse()
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.fsync(descriptor)
        sync_directory(shared)
        yield
    finally:
        os.close(descriptor)


def lock_identity(authority: Authority, name: str) -> Object:
    descriptor = authority.open_lock(name)
    try:
        info = os.fstat(descriptor)
        return {"device": info.st_dev, "inode": info.st_ino}
    finally:
        os.close(descriptor)


def admission_fingerprint(authority: Authority, *, folder: Path | None = None) -> str:
    """All preexisting admission markers are bound; a later marker changes it."""
    folder = authority.folder / "normal-admissions" if folder is None else folder
    paths = _documents(folder) if os.path.lexists(folder) else []
    hashes: list[Object] = []
    for path in paths:
        if not valid_token(path.name.removesuffix(".json")):
            refuse()
        raw = read_bytes(path)
        value = decode(raw)
        fields(value, "version kind component epoch boot invocation build payloadSha256 checkpoint")
        if (value["kind"] != "driver-normal-admission" or value["component"] != authority.component
                or value["invocation"] != path.name.removesuffix(".json")
                or not valid_token(value["epoch"]) or not canonical_uuid(value["boot"])
                or (value["payloadSha256"] is not None and not valid_hash(value["payloadSha256"]))
                or (value["checkpoint"] is not None and not valid_token(value["checkpoint"]))):
            refuse()
        hashes.append({"name": path.name, "sha256": sha256(raw)})
    # This is a hash input, not a protocol document or authority substituted by
    # an empty directory. Existing bounded raw markers are preserved separately.
    return sha256(canonical({"version": 1, "markers": hashes}))


def archive_boot_custody(authority: Authority, descriptor: int, record: Object, new_boot: str) -> None:
    """Under all four closed mutexes/EX leases after verified genuine boot change.

    Preserve opaque old custody trees by same-filesystem rename. Empty replacement
    directories are a consequence of that authorized boundary, never lifetime proof.
    Driver state/vendor journals, guard inodes and per-session operations stay put.
    """
    _exclusive(authority, descriptor)
    control = authority.read("control")
    if (control["phase"] != "draining" or control["session"] != record["session"]
            or not canonical_uuid(new_boot) or new_boot == record["oldBoot"]):
        refuse()
    base = private_directory(authority.folder / "boot-archive", create=True)
    destination = private_directory(base / record["checkpoint"], create=True)
    inventory_path = destination / "inventory.json"
    names = ("writers", "handoffs", "normal-admissions", "archive", "taint.json", "maintenance.json")
    directories = set(names[:4])
    try:
        inventory = read(inventory_path)
    except FileNotFoundError:
        rows: list[Object] = []
        for name in names:
            source, target = authority.folder / name, destination / name
            if os.path.lexists(target):
                refuse()
            present = os.path.lexists(source)
            row: Object = {"name": name, "present": present, "device": None, "inode": None, "sha256": None}
            if present:
                if name in directories:
                    private_directory(source)
                else:
                    raw = read_bytes(source)
                    row["sha256"] = sha256(raw)
                    if name == "taint.json":
                        taint = decode(raw)
                        validate("taint", taint)
                        if (taint["component"] != authority.component or taint["epoch"] != control["epoch"]
                                or taint["boot"] != record["oldBoot"]):
                            refuse()
                info = source.lstat()
                row.update(device=info.st_dev, inode=info.st_ino)
            elif name in ("writers", "handoffs", "archive", "taint.json"):
                refuse()
            rows.append(row)
        inventory = {"version": 1, "kind": "driver-boot-custody", "component": authority.component,
                     "session": record["session"], "checkpoint": record["checkpoint"],
                     "oldBoot": record["oldBoot"], "newBoot": new_boot, "entries": rows}
        publish(inventory_path, inventory)
    fields(inventory, "version kind component session checkpoint oldBoot newBoot entries")
    if (inventory["kind"] != "driver-boot-custody" or inventory["component"] != authority.component
            or any(inventory[key] != record[key] for key in ("session", "checkpoint", "oldBoot"))
            or inventory["newBoot"] != new_boot or not isinstance(inventory["entries"], list)
            or len(inventory["entries"]) != len(names)):
        refuse()
    complete_path = destination / "complete.json"
    completed = os.path.lexists(complete_path)
    complete = {"version": 1, "kind": "driver-boot-custody-complete", "inventorySha256": sha256(canonical(inventory))}
    if completed and read(complete_path) != complete:
        refuse()
    for name, row in zip(names, inventory["entries"], strict=True):
        if (not isinstance(row, dict) or set(row) != {"name", "present", "device", "inode", "sha256"}
                or row["name"] != name or type(row["present"]) is not bool):
            refuse()
        source, target = authority.folder / name, destination / name
        if not row["present"]:
            if any(row[key] is not None for key in ("device", "inode", "sha256")) or os.path.lexists(target):
                refuse()
        else:
            if (not natural(row["device"]) or not natural(row["inode"])
                    or (name in directories and row["sha256"] is not None)
                    or (name not in directories and not valid_hash(row["sha256"]))):
                refuse()
            current = target if os.path.lexists(target) else source
            info = current.lstat()
            if (info.st_dev, info.st_ino) != (row["device"], row["inode"]):
                refuse()
            if name in directories:
                private_directory(current)
            elif sha256(read_bytes(current)) != row["sha256"]:
                refuse()
            if current == source:
                if completed:
                    refuse()
                os.rename(source, target)
                sync_directory(destination)
                sync_directory(authority.folder)
        if os.path.lexists(source):
            if not completed or name not in directories:
                refuse()
            private_directory(source)
            if next(source.iterdir(), None) is not None:
                refuse()
    if not completed:
        publish(complete_path, complete)
    for name in names[:4]:
        private_directory(authority.folder / name, create=True)
    sync_directory(authority.folder)
