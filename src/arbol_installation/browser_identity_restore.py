"""Target-bound Browser admission independent of the restored database."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from .admission import lock, private_dir, private_file, unique_pairs

DIRECTORY = "browser-identity-restores"
GUARD = "lock"
CONTROL = "control.json"
LIMIT = 4096
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
TOKEN = re.compile(r"[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]\Z")
FIELDS = frozenset({"version", "kind", "endpointSha256", "targetCluster", "attempt", "snapshotSha256", "phase", "databaseOid"})
type Phase = Literal["blocked", "invalidated"]


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def endpoint(socket: Path, port: int, database: str) -> str:
    if (not socket.is_absolute() or socket.resolve(strict=True) != socket or not socket.is_dir()
            or type(port) is not int or not 1 <= port <= 65535
            or not database or "\0" in database or len(database.encode()) > 63):
        raise ValueError("The Browser restore endpoint is invalid.")
    return hashlib.sha256(canonical({"socket": str(socket), "port": port, "database": database})).hexdigest()


@dataclass(frozen=True)
class RestoreMarker:
    endpoint: str
    cluster: str
    attempt: str
    snapshot: str
    phase: Phase
    oid: int | None = None

    def document(self) -> dict[str, Any]:
        return {"version": 1, "kind": "browser-identity-restore", "endpointSha256": self.endpoint,
                "targetCluster": self.cluster, "attempt": self.attempt, "snapshotSha256": self.snapshot,
                "phase": self.phase, "databaseOid": self.oid}

    @classmethod
    def read(cls, data: bytes, expected: str) -> RestoreMarker:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs)
        if (not isinstance(value, dict) or value.keys() != FIELDS or type(value["version"]) is not int
                or value["version"] != 1 or value["kind"] != "browser-identity-restore"
                or value["endpointSha256"] != expected or not isinstance(value["targetCluster"], str)
                or re.fullmatch(r"[1-9][0-9]{0,19}", value["targetCluster"]) is None
                or not isinstance(value["attempt"], str) or TOKEN.fullmatch(value["attempt"]) is None
                or not isinstance(value["snapshotSha256"], str) or DIGEST.fullmatch(value["snapshotSha256"]) is None
                or value["phase"] not in ("blocked", "invalidated")):
            raise ValueError("The Browser restore marker is invalid.")
        oid = value["databaseOid"]
        if (value["phase"] == "blocked") != (oid is None) or (
                oid is not None and (type(oid) is not int or not 1 <= oid <= 0xffffffff)):
            raise ValueError("The Browser restore database identity is invalid.")
        return cls(expected, value["targetCluster"], value["attempt"], value["snapshotSha256"], value["phase"], oid)


@contextmanager
def private_directory(parent: int, name: str) -> Iterator[int]:
    with suppress(FileExistsError):
        os.mkdir(name, mode=0o700, dir_fd=parent)
        os.fsync(parent)
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        private_dir(fd)
        yield fd
    finally:
        os.close(fd)


@dataclass(frozen=True)
class RestoreGate:
    path: Path
    endpoint: str
    directory: int
    guard: int
    exclusive: bool

    def current(self) -> None:
        if self.path.resolve(strict=True) != self.path or not os.path.samestat(os.fstat(self.directory), self.path.stat()):
            raise ValueError("The Browser restore gate directory changed.")
        held, named = os.fstat(self.guard), os.stat(GUARD, dir_fd=self.directory, follow_symlinks=False)
        private_file(held)
        private_file(named)
        if not os.path.samestat(held, named):
            raise ValueError("The Browser restore gate lock changed.")

    def read(self, name: str = CONTROL) -> RestoreMarker | None:
        self.current()
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.directory)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(fd)
            private_file(opened)
            data = stream.read(LIMIT + 1)
            closed = os.fstat(fd)
            named = os.stat(name, dir_fd=self.directory, follow_symlinks=False)
            private_file(named)
            if (not 1 <= len(data) == opened.st_size <= LIMIT or not os.path.samestat(opened, named)
                    or (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                    != (closed.st_size, closed.st_mtime_ns, closed.st_ctime_ns)):
                raise ValueError("The Browser restore marker changed or exceeded its bound.")
        marker = RestoreMarker.read(data, self.endpoint)
        self.current()
        return marker

    def begin(self, cluster: str, snapshot: str) -> RestoreMarker:
        if not self.exclusive:
            raise ValueError("Starting a Browser restore requires the exclusive gate.")
        previous = self.read()
        if previous is not None:
            archive = f"previous-{previous.attempt}-{previous.phase}.json"
            retained = self.read(archive)
            if retained is None:
                self.write(archive, previous, replace_existing=False)
            elif retained != previous:
                raise ValueError("The retained Browser restore marker differs.")
        marker = RestoreMarker(self.endpoint, cluster, secrets.token_urlsafe(32), snapshot, "blocked")
        self.write(CONTROL, marker, replace_existing=True)
        return marker

    def complete(self, blocked: RestoreMarker, oid: int) -> RestoreMarker:
        if blocked.phase != "blocked" or self.read() != blocked:
            raise ValueError("The Browser restore attempt changed before completion.")
        marker = replace(blocked, phase="invalidated", oid=oid)
        self.write(CONTROL, marker, replace_existing=True)
        return marker

    def write(self, name: str, marker: RestoreMarker, *, replace_existing: bool) -> None:
        if not self.exclusive:
            raise ValueError("Publishing a Browser restore requires the exclusive gate.")
        self.current()
        data = canonical(marker.document())
        if len(data) > LIMIT or RestoreMarker.read(data, self.endpoint) != marker:
            raise ValueError("The Browser restore marker cannot be published.")
        temporary = f".{secrets.token_hex(16)}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if replace_existing:
                os.replace(temporary, name, src_dir_fd=self.directory, dst_dir_fd=self.directory)
            else:
                os.link(temporary, name, src_dir_fd=self.directory, dst_dir_fd=self.directory, follow_symlinks=False)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=self.directory)
        os.fsync(self.directory)
        self.current()


@contextmanager
def restore_gate(runtime: Path, target: str, *, exclusive: bool = False) -> Iterator[RestoreGate]:
    if not runtime.is_absolute() or runtime.resolve(strict=True) != runtime or DIGEST.fullmatch(target) is None:
        raise ValueError("The Browser restore runtime or target is invalid.")
    with ExitStack() as held:
        root = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        held.callback(os.close, root)
        private_dir(root)
        parent = held.enter_context(private_directory(root, DIRECTORY))
        directory = held.enter_context(private_directory(parent, target))
        with suppress(FileExistsError):
            fd = os.open(GUARD, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            os.close(fd)
            os.fsync(directory)
        guard = held.enter_context(lock(directory, GUARD, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH))
        gate = RestoreGate(runtime / DIRECTORY / target, target, directory, guard, exclusive)
        gate.current()
        yield gate
