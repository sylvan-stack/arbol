"""Private writer admission for the installation, independent of PostgreSQL schema.

Keep the file protocol in sync with the independently packaged Trivial Trunk.
Lock files are permanent: replacing one could split the set of admitted writers.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

Mode = Literal["normal", "controlled"]
Source = dict[str, str | int]
DIRECTORY = "writer-admission"
STATE = "state.json"
GATE = "gate.lock"
WRITERS = "writers.lock"
OWNER = "owner.lock"
GENERATION_ENV = "ARBOL_EXCHANGE_ADMISSION_GENERATION"
# Session advisory lock held on a writing connection before it can send any
# mutations. The drain checks it too: a dead client can leave PostgreSQL
# processing its last statement or commit after the OS releases its file lease.
DATABASE_WRITER_LOCK = 0x4152424F4C575254
TOKEN = re.compile(r"[0-9a-f]{32}")
SHA256 = re.compile(r"[0-9a-f]{64}")


class AdmissionRefusal(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def runtime_folder(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library/Application Support/Arbol/runtime"


def private_dir(descriptor: int) -> None:
    info = os.fstat(descriptor)
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Admission requires an owner-only directory.")


@contextmanager
def directory(runtime: Path) -> Iterator[int]:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root = os.open(runtime, flags)
    try:
        private_dir(root)
        fd = os.open(DIRECTORY, flags, dir_fd=root)
        try:
            private_dir(fd)
            yield fd
        finally:
            os.close(fd)
    finally:
        os.close(root)


def private_file(info: os.stat_result) -> None:
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise ValueError("Admission requires a private regular file.")


@contextmanager
def lock(folder: int, name: str, mode: int) -> Iterator[int]:
    fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
    try:
        opened = os.fstat(fd)
        private_file(opened)
        fcntl.flock(fd, mode | fcntl.LOCK_NB)
        named = os.stat(name, dir_fd=folder, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise ValueError("An admission lock was replaced.")
        yield fd
    finally:
        os.close(fd)


def checked_source(value: object) -> Source:
    if not isinstance(value, dict) or value.keys() != {"host", "port", "database", "databaseOid"}:
        raise ValueError("Invalid maintenance database identity.")
    host, port, database, oid = (value[key] for key in ("host", "port", "database", "databaseOid"))
    if (not isinstance(host, str) or not host or "\0" in host
            or type(port) is not int or not 1 <= port <= 65535
            or not isinstance(database, str) or not database or "\0" in database
            or type(oid) is not int or not 1 <= oid <= 0xffffffff):
        raise ValueError("Invalid maintenance database identity.")
    return {"host": host, "port": port, "database": database, "databaseOid": oid}


@dataclass(frozen=True)
class State:
    phase: str
    generation: str
    source: Source
    session: str | None
    release: str | None


def read_state(folder: int) -> State:
    fd = os.open(STATE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
    try:
        private_file(os.fstat(fd))
        raw = os.read(fd, 8193)
        if len(raw) > 8192:
            raise ValueError("Admission state exceeds its size limit.")
    finally:
        os.close(fd)
    value = json.loads(raw)
    if (not isinstance(value, dict) or value.keys() != {"format", "state", "generation", "source", "session", "release"}
            or type(value["format"]) is not int or value["format"] != 1):
        raise ValueError("Unknown admission format.")
    phase, generation, session, release = (value[key] for key in ("state", "generation", "session", "release"))
    if (phase not in ("normal", "draining", "exclusive")
            or not isinstance(generation, str) or TOKEN.fullmatch(generation) is None
            or (session is not None and (not isinstance(session, str) or TOKEN.fullmatch(session) is None))
            or (release is not None and (not isinstance(release, str) or SHA256.fullmatch(release) is None))
            or (phase == "normal" and (session is not None or release is None))
            or (phase != "normal" and session is None)):
        raise ValueError("Unknown admission state.")
    return State(phase, generation, checked_source(value["source"]), session, release)


@dataclass
class Lease:
    state: State
    pid: int

    def require(self) -> None:
        if self.pid != os.getpid():
            raise AdmissionRefusal("maintenance", "This installation writer permit is no longer held.")


@dataclass(frozen=True)
class Admission:
    runtime: Path

    def status(self) -> tuple[str, str | None]:
        try:
            with directory(self.runtime) as folder:
                state = read_state(folder)
                for name in (GATE, WRITERS, OWNER):
                    private_file(os.stat(name, dir_fd=folder, follow_symlinks=False))
                return state.phase, state.generation
        except (OSError, ValueError, RecursionError):
            return "unknown", None

    @contextmanager
    def lease(self, mode: Mode, *, generation: str | None = None) -> Iterator[Lease]:
        with directory_lease(self.runtime, mode, generation) as lease:
            yield lease

    @contextmanager
    def permit(self, mode: Mode) -> Iterator[None]:
        with self.lease(mode):
            yield


@contextmanager
def directory_lease(runtime: Path, mode: Mode, generation: str | None) -> Iterator[Lease]:
    # Separate file descriptions let readers/writers overlap. The gate only
    # spans registration; the shared lease survives a transition to draining.
    with ExitStack() as leases:
        try:
            folder = leases.enter_context(directory(runtime))
            with lock(folder, GATE, fcntl.LOCK_SH):
                state = read_state(folder)
                private_file(os.stat(OWNER, dir_fd=folder, follow_symlinks=False))
                if (mode not in ("normal", "controlled")
                        or state.phase not in (("normal",) if mode == "normal" else ("normal", "draining"))
                        or (generation is not None and generation != state.generation)):
                    raise AdmissionRefusal("maintenance", "The installation is in maintenance or this request expired.")
                leases.enter_context(lock(folder, WRITERS, fcntl.LOCK_SH))
        except (OSError, ValueError, RecursionError):
            raise AdmissionRefusal("maintenance", "The installation writer admission is unavailable.") from None
        lease = Lease(state, os.getpid())
        try:
            yield lease
        finally:
            lease.pid = -1


def staged_state(folder: int, state: State) -> str:
    value = {"format": 1, "state": state.phase, "generation": state.generation,
             "source": state.source, "session": state.session, "release": state.release}
    name = f".{uuid4().hex}.tmp"
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps(value, separators=(",", ":")).encode())
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        os.unlink(name, dir_fd=folder)
        raise
    return name


def write_state(folder: int, state: State) -> None:
    """Publish one complete transition under the gate, never overwrite in place."""
    previous = staged_state(folder, read_state(folder)) if state.phase == "normal" else None
    name = None
    try:
        name = staged_state(folder, state)
        os.replace(name, STATE, src_dir_fd=folder, dst_dir_fd=folder)
        try:
            os.fsync(folder)
        except OSError:
            # If publishing normal failed, restore the fence before admitting
            # anyone. A missing state is also a refusal if restoration fails.
            if previous is not None:
                try:
                    os.replace(previous, STATE, src_dir_fd=folder, dst_dir_fd=folder)
                except OSError:
                    os.unlink(STATE, dir_fd=folder)
                os.fsync(folder)
            raise
    finally:
        for item in (name, previous):
            if item is not None:
                try:
                    os.unlink(item, dir_fd=folder)
                except FileNotFoundError:
                    pass


def prepare_directory(runtime: Path) -> None:
    """Explicit operator setup only. A missing state never grants admission."""
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        private_dir(root)
        try:
            os.mkdir(DIRECTORY, mode=0o700, dir_fd=root)
        except FileExistsError:
            pass
        with directory(runtime) as folder:
            if not os.path.lexists(runtime / DIRECTORY / STATE):
                for name in (OWNER, GATE, WRITERS):
                    try:
                        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
                    except FileExistsError:
                        continue
                    os.close(fd)
            os.fsync(folder)
        os.fsync(root)
    finally:
        os.close(root)

