"""The read-only-source, installation-bound import command (IMP-0)."""

import asyncio
import fcntl
import importlib
import json
import os
import runpy
import stat
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from uuid import UUID

from arbol_backend.database import protected_thread
from arbol_backend.model import Identity, ImportOptions, Refused, private_directory
from arbol_installation.paths import installation_root, prepare_installation

from .archive import ArchiveRoot, ArchiveUnavailable, UnreadableInput, inspect_files, publish_session, read_manifest
from .mapping import JsonObject, MappedSession, MappingError, map_session, segment_keys
from .readers.form import CatalogueEntry, Failed, Kind, Reader, Session, Source, Tool, reader_module
from .writer import ImportOutcome, ImportStore, Previous, WritePlan, rows_refused, validate_rows

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


@dataclass
class ImportReport:
    tool: Tool
    sessions: list[JsonObject] = field(default_factory=list)
    archive_bytes: int = 0
    error: JsonObject | None = None

    def document(self) -> JsonObject:
        value: JsonObject = {
            "tool": self.tool, "sessions": list(self.sessions), "archiveBytesWritten": self.archive_bytes,
        }
        if self.error is not None:
            value["error"] = self.error
        return value

    @property
    def exit_status(self) -> int:
        return int(self.error is not None or any(row.get("outcome") == "failed" for row in self.sessions))


def _reader(tool: Tool) -> Reader:
    return cast(Reader, importlib.import_module(reader_module(tool)))


def _attribution(native: str, kind: Kind | None) -> JsonObject:
    value: JsonObject = {"native": native}
    if kind is not None:
        value["kind"] = kind
    return value


def _error(code: str, message: str) -> JsonObject:
    return {"code": code, "message": message}


def _session_attribution(session: Session) -> JsonObject:
    result = _attribution(session.native_id, session.kind)
    if session.files_not_archived:
        result["filesNotArchived"] = session.files_not_archived
    return result


def _excluded(kind: Kind | None, options: ImportOptions) -> bool:
    return kind in _OPTIONAL_KINDS and kind not in options.include


def _select(entry: CatalogueEntry, options: ImportOptions, owner_home: Path) -> _Selection | JsonObject:
    result = entry.load()
    if isinstance(result, Failed):
        native = result.native_id if result.native_id is not None else result.file
        assert native is not None
        return {**_attribution(native, result.kind), "outcome": "failed", "error": _error(result.code, result.message)}
    info = _session_attribution(result)
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


async def _plan(selection: _Selection, previous: Previous | None, run: _Run) -> WritePlan:
    saved = previous.keys if previous is not None else frozenset()
    additions = tuple(segment for segment in selection.mapped.segments if segment.turn_key not in saved)
    if not additions and any(key not in saved for key in selection.withheld):
        return WritePlan("deferred")
    try:
        home = run.source.home.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise UnreadableInput() from None
    inventory = await protected_thread(lambda: inspect_files(home, selection.native.archive_files))
    archive = run.archive
    outcome: ImportOutcome
    if additions:
        outcome = "imported" if previous is None else "extended"
    else:
        if previous is None:
            raise rows_refused()
        fingerprint = previous.fingerprint
        repaired = fingerprint is None
        if fingerprint is None:
            if archive is None:
                raise Refused("rows_refused", "Run a real import with Mercury mounted to record the saved fingerprint.")
            fingerprint = (await protected_thread(lambda: read_manifest(
                archive, previous.manifest, selection.native.tool, selection.native.native_id,
            ))).fingerprint
        if fingerprint == inventory.fingerprint:
            return WritePlan("unchanged", repair=fingerprint if repaired else None)
        outcome = "rearchived"
    if archive is None:
        return WritePlan(outcome, additions)
    written = await protected_thread(
        lambda: publish_session(archive, home, selection.native, inventory, run.source.clock),
    )
    return WritePlan(outcome, additions, written)


def _outcome(session: Session, chat: UUID | None, plan: WritePlan) -> JsonObject:
    row = _session_attribution(session)
    row["outcome"] = plan.outcome
    if chat is not None:
        row["chat"] = str(chat)
    if plan.outcome in {"imported", "extended", "rearchived"}:
        row.update({
            "exchanges": len(plan.segments),
            "messages": sum(len(segment.messages) for segment in plan.segments),
            "toolCalls": sum(len(segment.calls) for segment in plan.segments),
            "subagentFallbacks": sum(segment.fallback_count for segment in plan.segments),
        })
    return row


async def _import_one(selection: _Selection, run: _Run, report: ImportReport) -> JsonObject:
    async def decide(previous: Previous | None) -> WritePlan:
        plan = await _plan(selection, previous, run)
        if plan.archive is not None:
            report.archive_bytes += plan.archive.bytes_written
        return plan

    if run.archive is None:
        previous = await run.store.previous(selection.native.tool, selection.native.native_id, selection.keys)
        plan = await decide(previous)
        chat = previous.chat if previous is not None else None
    else:
        chat, plan = await run.store.apply(selection.mapped, selection.keys, run.source.clock, run.archive, decide)
    return _outcome(selection.native, chat, plan)


async def _process(run: _Run, options: ImportOptions, owner_home: Path) -> ImportReport:
    report = ImportReport(options.tool)
    with _reader(options.tool).catalogue(run.source) as catalogue:
        for entry in catalogue:
            try:
                run.admit_next(dry_run=options.dry_run)
                selection = _select(entry, options, owner_home)
                if isinstance(selection, _Selection):
                    try:
                        row = await _import_one(selection, run, report)
                    except UnreadableInput as error:
                        row = {**_session_attribution(selection.native), "outcome": "failed",
                               "error": _error(error.code, str(error))}
                    except Refused as error:
                        if error.code != "rows_refused":
                            raise
                        row = {**_session_attribution(selection.native), "outcome": "failed",
                               "error": _error(error.code, str(error))}
                else:
                    row = selection
                report.sessions.append(row)
            except (ArchiveUnavailable, Refused) as error:
                report.error = _error(error.code, str(error))
                report.sessions.append(_attribution(entry.native, entry.kind))
                report.sessions.extend(_attribution(pending.native, pending.kind) for pending in catalogue)
                break
    return report


async def run_import(identity: Identity, options: ImportOptions, *, archive: ArchiveRoot | None = None) -> ImportReport:
    """Run against the installed paths, or a verified disposable identity passed by qualification."""
    try:
        async with _run_scope(identity, options, archive) as run:
            return await _process(run, options, identity.home)
    except ArchiveUnavailable as error:
        raise Refused(error.code, str(error)) from None


def import_main(identity: Identity, options: ImportOptions) -> int:
    report = asyncio.run(run_import(identity, options))
    print(json.dumps(report.document(), separators=(",", ":")), flush=True)
    return report.exit_status


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
