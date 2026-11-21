"""The read-only-source, installation-bound import command (IMP-0)."""

import fcntl
import importlib
import os
import runpy
import stat
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from arbol_backend.database import protected_thread
from arbol_backend.model import Identity, ImportOptions, Refused, private_directory
from arbol_installation.paths import installation_root, prepare_installation

from .archive import ArchiveRoot, ArchiveUnavailable
from .mapping import JsonObject, MappedSession, MappingError, map_session, segment_keys
from .readers.form import CatalogueEntry, Failed, Kind, Reader, Session, Source, Tool, reader_module
from .writer import ImportStore, rows_refused, validate_rows

_HOMES: dict[Tool, str] = {
    "claude-code": ".claude",
    "codex": ".codex",
    "kimi-code": ".kimi-code",
    "pi": ".pi/agent",
    "mimo": ".local/share/mimocode",
}
_DRIVER_STATE: dict[Tool, str] = {"claude-code": "claude", "codex": "codex"}
_OPTIONAL_KINDS = frozenset({"arbol_driver", "probe"})


@dataclass(frozen=True)
class _Run:
    store: ImportStore
    source: Source
    archive: ArchiveRoot | None

    def admit_next(self, *, dry_run: bool) -> None:
        with self.store.admission.import_read(allow_draining=dry_run):
            pass


@dataclass(frozen=True)
class _Selection:
    native: Session
    mapped: MappedSession
    keys: tuple[str, ...]
    withheld: tuple[str, ...]


def _reader(tool: Tool) -> Reader:
    return cast(Reader, importlib.import_module(reader_module(tool)))


def _attribution(native: str, kind: Kind | None) -> JsonObject:
    value: JsonObject = {"native": native}
    if kind is not None:
        value["kind"] = kind
    return value


def _error(code: str, message: str) -> JsonObject:
    return {"code": code, "message": message}


def _excluded(kind: Kind | None, options: ImportOptions) -> bool:
    return kind in _OPTIONAL_KINDS and kind not in options.include


def _select(entry: CatalogueEntry, options: ImportOptions, owner_home: Path) -> _Selection | JsonObject:
    result = entry.load()
    if isinstance(result, Failed):
        native = result.native_id if result.native_id is not None else result.file
        assert native is not None
        return {**_attribution(native, result.kind), "outcome": "failed", "error": _error(result.code, result.message)}
    info = _attribution(result.native_id, result.kind)
    if result.files_not_archived:
        info["filesNotArchived"] = result.files_not_archived
    if _excluded(result.kind, options):
        return {**info, "outcome": "excluded"}
    if not result.turns:
        return {**info, "outcome": "empty"}

    withheld = segment_keys(result.turns[-1]) if result.live else ()
    eligible = replace(result, turns=result.turns[:-1]) if result.live else result
    try:
        mapped = map_session(eligible, owner_home)
        validate_rows(mapped)
        keys = (*(segment.turn_key for segment in mapped.segments), *withheld)
        if len(set(keys)) != len(keys) or any(
            "\0" in key or not 1 <= len(key.encode("utf-8")) <= 512 for key in withheld
        ):
            raise rows_refused()
    except (MappingError, UnicodeError, Refused):
        failure = rows_refused()
        return {**info, "outcome": "failed", "error": _error(failure.code, str(failure))}
    return _Selection(result, mapped, keys, withheld)


@contextmanager
def _private_work(home: Path) -> Iterator[Path]:
    prepare_installation(home)
    parent = installation_root(home) / "imports"
    parent.mkdir(mode=0o700, exist_ok=True)
    private_directory(parent)
    folder = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(
            "import.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=folder,
        )
        try:
            file = os.fstat(descriptor)
            if (not stat.S_ISREG(file.st_mode) or file.st_uid != os.getuid()
                    or stat.S_IMODE(file.st_mode) != 0o600 or file.st_nlink != 1):
                raise Refused("invalid_input", "The installation import lock is not a private file.")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused("busy", "An import is already running for this installation.") from None
            named = os.stat("import.lock", dir_fd=folder, follow_symlinks=False)
            if not os.path.samestat(file, named) or not os.path.samestat(os.fstat(folder), parent.lstat()):
                raise Refused("busy", "The installation import lock changed while it was acquired.")
            work = parent / "tmp"
            work.mkdir(mode=0o700, exist_ok=True)
            private_directory(work)
            with TemporaryDirectory(prefix="import-", dir=work) as scratch:
                yield Path(scratch)
        finally:
            os.close(descriptor)
    finally:
        os.close(folder)


def _installed_archive(package: Path) -> ArchiveRoot:
    try:
        namespace = runpy.run_path(str(package / "database/archive_volume.py"), run_name="_arbol_import_archive_volume")
        volume = namespace["require_archive"]()
        root = volume.path(namespace["ARCHIVE_ROOT"] / "imports", allow_missing=True)
        if not isinstance(root, Path) or type(volume.device) is not int:
            raise ValueError("Invalid verified volume.")
        return ArchiveRoot(root, volume.device)
    except Exception:
        raise ArchiveUnavailable() from None


@asynccontextmanager
async def _run_scope(identity: Identity, options: ImportOptions, override: ArchiveRoot | None) -> AsyncIterator[_Run]:
    if override is not None and not identity.fixture:
        raise Refused("invalid_input", "A disposable import archive requires a private installation.")
    with _private_work(identity.home) as scratch:
        store = ImportStore(identity)
        try:
            await store.preflight(dry_run=options.dry_run)
            archive: ArchiveRoot | None = None
            if not options.dry_run:
                selected = override if override is not None else await protected_thread(
                    lambda: _installed_archive(identity.package)
                )
                await protected_thread(selected.prepare)
                archive = selected
            driver = _DRIVER_STATE.get(options.tool)
            driver_state = installation_root(identity.home) / "drivers" / driver if driver is not None else None
            source = Source(identity.home / _HOMES[options.tool], driver_state, scratch, datetime.now(UTC),
                            frozenset(options.sessions) if options.sessions else None)
            yield _Run(store, source, archive)
        finally:
            await store.database.close()
