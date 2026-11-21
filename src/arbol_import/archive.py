"""Inspect and retain byte-exact native session inputs (IMP-0.13)."""

import json
import os
import re
import stat
from collections.abc import Callable, Iterable, Iterator
from compression import zstd
from compression.zstd import ZstdError
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import uuid4

from .readers.form import ArchiveFile, ExportedRows, FileObservation, Session, Tool
from .readers.lines import open_input

_CHUNK = 1 << 20
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_DIGEST = re.compile(r"[0-9a-f]{64}")


class UnreadableInput(ValueError):
    code = "unreadable_session"

    def __init__(self) -> None:
        super().__init__("A selected native archive file is unavailable or changed during import.")


class ArchiveUnavailable(ValueError):
    code = "archive_unavailable"

    def __init__(self) -> None:
        super().__init__("The verified import archive is unavailable or failed an integrity check.")


@dataclass(frozen=True)
class ArchiveRoot:
    path: Path
    device: int

    def prepare(self) -> None:
        """Check the previously verified volume and create its private import root if needed."""
        with _archive_directory(self, create=True):
            pass

    def verify(self) -> None:
        with _archive_directory(self):
            pass


@dataclass(frozen=True)
class FileEntry:
    path: str
    sha256: str
    size: int
    mtime: datetime


@dataclass(frozen=True)
class Inventory:
    files: tuple[FileEntry, ...]

    @property
    def fingerprint(self) -> str:
        pairs = [[entry.path, entry.sha256] for entry in self.files]
        return sha256(_canonical(pairs)).hexdigest()


@dataclass(frozen=True)
class PublishedArchive:
    manifest: str
    fingerprint: str
    bytes_written: int


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(path.parts) and not path.is_absolute() and ".." not in path.parts
        and "\0" not in value and path.as_posix() == value
    )


@contextmanager
def _input(home: Path, source: ArchiveFile) -> Iterator[tuple[BinaryIO, datetime]]:
    if not _relative_path(source.path):
        raise UnreadableInput()
    if isinstance(source, ExportedRows):
        with BytesIO(source.content) as exported:
            yield exported, source.mtime
        return

    path = source.read_path or source.path
    observed = source.observation
    if observed is None or not _relative_path(path):
        raise UnreadableInput()
    with ExitStack() as opened:
        try:
            stream = opened.enter_context(open_input(home, path))
            if FileObservation.from_stat(os.fstat(stream.fileno())) != observed:
                raise UnreadableInput()
        except OSError:
            raise UnreadableInput() from None
        yield stream, observed.modified_at
        try:
            if FileObservation.from_stat(os.fstat(stream.fileno())) != observed:
                raise UnreadableInput()
        except OSError:
            raise UnreadableInput() from None


def _chunks(stream: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := stream.read(_CHUNK):
            yield chunk
    except OSError:
        raise UnreadableInput() from None


def _measure(home: Path, source: ArchiveFile, copy: Callable[[bytes], object] | None = None) -> FileEntry:
    digest = sha256()
    size = 0
    with _input(home, source) as (stream, mtime):
        for chunk in _chunks(stream):
            digest.update(chunk)
            size += len(chunk)
            if copy is not None:
                copy(chunk)
    return FileEntry(source.path, digest.hexdigest(), size, mtime)


def _inventory(entries: Iterable[FileEntry]) -> Inventory:
    by_path: dict[str, FileEntry] = {}
    for entry in entries:
        if by_path.setdefault(entry.path, entry) != entry:
            raise UnreadableInput()
    return Inventory(tuple(by_path[path] for path in sorted(by_path)))


def inspect_files(home: Path, files: Iterable[ArchiveFile]) -> Inventory:
    """Compute the replay fingerprint without opening or writing an archive."""
    return _inventory(_measure(home, source) for source in files)


@contextmanager
def _directory_at(parent: int, name: str, device: int, *, create: bool = False) -> Iterator[int]:
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    folder = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
    try:
        bound = os.fstat(folder)
        if bound.st_dev != device:
            raise ArchiveUnavailable()
        if create:
            os.fsync(parent)
        yield folder
        if not os.path.samestat(bound, os.stat(name, dir_fd=parent, follow_symlinks=False)):
            raise ArchiveUnavailable()
    finally:
        os.close(folder)


@contextmanager
def _archive_directory(binding: ArchiveRoot, *, create: bool = False) -> Iterator[int]:
    path = binding.path
    try:
        if not path.is_absolute() or not path.name or path.parent.resolve(strict=True) != path.parent:
            raise ArchiveUnavailable()
        parent = os.open(path.parent, _DIRECTORY_FLAGS)
        try:
            if os.fstat(parent).st_dev != binding.device:
                raise ArchiveUnavailable()
            with _directory_at(parent, path.name, binding.device, create=create) as folder:
                bound = os.fstat(folder)
                yield folder
                if not os.path.samestat(bound, path.lstat()):
                    raise ArchiveUnavailable()
        finally:
            os.close(parent)
    except (OSError, EOFError, ZstdError):
        raise ArchiveUnavailable() from None


@contextmanager
def _regular_at(directory: int, name: str, device: int) -> Iterator[BinaryIO]:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_dev != device:
            raise ArchiveUnavailable()
        yield stream
        if FileObservation.from_stat(os.fstat(stream.fileno())) != FileObservation.from_stat(info):
            raise ArchiveUnavailable()


@contextmanager
def _staging(directory: int) -> Iterator[tuple[str, BinaryIO]]:
    name = f".stage-{uuid4().hex}"
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            yield name, stream
    finally:
        os.unlink(name, dir_fd=directory)


def _publish(source: int, name: str, destination: int, target: str) -> bool:
    try:
        os.link(name, target, src_dir_fd=source, dst_dir_fd=destination, follow_symlinks=False)
    except FileExistsError:
        return False
    os.fsync(destination)
    return True


def _verify_object(prefix: int, leaf: str, device: int, expected: FileEntry) -> None:
    digest = sha256()
    size = 0
    with _regular_at(prefix, leaf, device) as stream, zstd.ZstdFile(stream, "rb") as decoded:
        while chunk := decoded.read(_CHUNK):
            size += len(chunk)
            if size > expected.size:
                raise ArchiveUnavailable()
            digest.update(chunk)
        if size != expected.size or digest.hexdigest() != expected.sha256:
            raise ArchiveUnavailable()


def _write_object(objects: int, device: int, home: Path, source: ArchiveFile, expected: FileEntry) -> int:
    with _staging(objects) as (name, stream):
        with zstd.ZstdFile(stream, "wb") as encoded:
            measured = _measure(home, source, encoded.write)
        if measured != expected:
            raise UnreadableInput()
        stream.flush()
        os.fsync(stream.fileno())
        size = os.fstat(stream.fileno()).st_size
        prefix, leaf = expected.sha256[:2], expected.sha256[2:]
        with _directory_at(objects, prefix, device, create=True) as destination:
            if _publish(objects, name, destination, leaf):
                return size
            _verify_object(destination, leaf, device, expected)
            os.fsync(destination)
    return 0


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ArchiveUnavailable()
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        raise ArchiveUnavailable() from None
    if stamp.utcoffset() is None:
        raise ArchiveUnavailable()
    return stamp


def _manifest_inventory(data: bytes, tool: Tool, native_id: str) -> Inventory:
    try:
        value = json.loads(data)
    except (UnicodeError, ValueError, RecursionError):
        raise ArchiveUnavailable() from None
    if (
        not isinstance(value, dict) or set(value) != {"tool", "nativeId", "takenAt", "toolVersion", "files"}
        or value["tool"] != tool or value["nativeId"] != native_id
        or (value["toolVersion"] is not None and not isinstance(value["toolVersion"], str))
        or not isinstance(value["files"], list)
    ):
        raise ArchiveUnavailable()
    _timestamp(value["takenAt"])
    files: list[FileEntry] = []
    seen: set[str] = set()
    for entry in value["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size", "mtime"}:
            raise ArchiveUnavailable()
        path, digest, size = entry["path"], entry["sha256"], entry["size"]
        if (
            not isinstance(path, str) or not _relative_path(path) or path in seen
            or not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
            or type(size) is not int or size < 0
        ):
            raise ArchiveUnavailable()
        seen.add(path)
        files.append(FileEntry(path, digest, size, _timestamp(entry["mtime"])))
    return _inventory(files)


def read_manifest(binding: ArchiveRoot, manifest: str, tool: Tool, native_id: str) -> Inventory:
    """Recover a prior fingerprint only from the exact, session-bound manifest."""
    if not _DIGEST.fullmatch(manifest):
        raise ArchiveUnavailable()
    with (
        _archive_directory(binding) as root,
        _directory_at(root, "manifests", binding.device) as manifests,
        _directory_at(manifests, manifest[:2], binding.device) as prefix,
        _regular_at(prefix, f"{manifest[2:]}.json", binding.device) as stream,
    ):
        data = stream.read()
        if sha256(data).hexdigest() != manifest:
            raise ArchiveUnavailable()
        return _manifest_inventory(data, tool, native_id)


def _write_manifest(root: int, device: int, identifier: str, data: bytes) -> int:
    with (
        _directory_at(root, "manifests", device, create=True) as manifests,
        _directory_at(manifests, identifier[:2], device, create=True) as prefix,
        _staging(prefix) as (name, stream),
    ):
        leaf = f"{identifier[2:]}.json"
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        if _publish(prefix, name, prefix, leaf):
            return len(data)
        with _regular_at(prefix, leaf, device) as existing:
            if existing.read(len(data) + 1) != data:
                raise ArchiveUnavailable()
        os.fsync(prefix)
    return 0


def publish_session(
    binding: ArchiveRoot, home: Path, session: Session, inventory: Inventory, taken_at: datetime,
) -> PublishedArchive:
    """Publish exactly the previously inspected objects and manifest before database commit."""
    by_path = {entry.path: entry for entry in inventory.files}
    sources = session.archive_files
    if (
        len(by_path) != len(inventory.files) or set(by_path) != {file.path for file in sources}
        or any(not _DIGEST.fullmatch(entry.sha256) for entry in inventory.files)
    ):
        raise UnreadableInput()
    data = _canonical({
        "tool": session.tool,
        "nativeId": session.native_id,
        "takenAt": taken_at.isoformat(),
        "toolVersion": session.tool_version,
        "files": [
            {"path": entry.path, "sha256": entry.sha256, "size": entry.size, "mtime": entry.mtime.isoformat()}
            for entry in inventory.files
        ],
    })
    identifier = sha256(data).hexdigest()
    with _archive_directory(binding, create=True) as root:
        with _directory_at(root, "objects", binding.device, create=True) as objects:
            written = sum(_write_object(objects, binding.device, home, item, by_path[item.path]) for item in sources)
        written += _write_manifest(root, binding.device, identifier, data)
    return PublishedArchive(identifier, inventory.fingerprint, written)
