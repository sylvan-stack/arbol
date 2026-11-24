"""Operator transitions for the installation's durable schema-change fence."""

from __future__ import annotations

import asyncio
import fcntl
import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal
from uuid import uuid4

from arbol_installation.admission import TOKEN, AdmissionRefusal, ExclusiveLayoutLease
from arbol_installation.exchange_release import verify_authorization
from arbol_installation.paths import INSTALLATION_LAYOUT

from .database import Database, credentials
from .exchange_admission import (
    DATABASE_WRITER_LOCK,
    GATE,
    OWNER,
    SHA256,
    WRITERS,
    Source,
    State,
    checked_source,
    directory,
    lock,
    prepare_directory,
    read_state,
    runtime_folder,
    write_state,
)
from .exchange_context import Context, Refusal
from .exchange_listing import drained_inventory
from .model import Refused
from .note_files import NoteFiles


@contextmanager
def operation(runtime: Path) -> Iterator[int]:
    # Snapshot, migration, recovery and reopen use the same operator lock.
    # Nothing about closing this descriptor changes the recorded phase.
    with ExitStack() as locks:
        try:
            folder = locks.enter_context(directory(runtime))
            locks.enter_context(lock(folder, OWNER, fcntl.LOCK_EX))
        except (OSError, ValueError):
            raise Refusal("maintenance", "Cannot take ownership of the installation maintenance operation.") from None
        yield folder


@contextmanager
def gate(folder: int, *, idle: bool = False) -> Iterator[None]:
    with ExitStack() as locks:
        try:
            locks.enter_context(lock(folder, GATE, fcntl.LOCK_EX))
            if idle:
                locks.enter_context(lock(folder, WRITERS, fcntl.LOCK_EX))
        except BlockingIOError:
            raise Refusal("maintenance_busy", "Writer admission is busy; wait for admitted operations to finish.") from None
        except (OSError, ValueError):
            raise Refusal("maintenance", "Cannot verify the installation admission locks.") from None
        yield


def current(folder: int, *, layout: int = INSTALLATION_LAYOUT) -> State:
    try:
        return read_state(folder, layout=layout)
    except (OSError, ValueError, RecursionError):
        raise Refusal("maintenance", "The durable maintenance state is unreadable.") from None


def bound(state: State, source: Source, session: str) -> None:
    if state.source != source or state.session != session or state.phase == "normal":
        raise Refusal("maintenance", "The maintenance session does not own this database target.")


def begin_maintenance(source: Source, *, runtime: Path | None = None) -> str:
    """Close ordinary admission, or recover the session ID after a lost reply."""
    source = checked_source(source)
    runtime = runtime or runtime_folder()
    prepare_directory(runtime)
    with operation(runtime) as folder, gate(folder):
        try:
            state = read_state(folder)
        except FileNotFoundError:
            state = None  # First activation is closed until verification.
        except (OSError, ValueError, RecursionError):
            raise Refusal("maintenance", "The durable maintenance state is unreadable.") from None
        if state is not None:
            if state.source != source:
                raise Refusal("maintenance", "The database does not match this installation's recorded target.")
            if state.session is not None:
                return state.session
        session = uuid4().hex
        # Normal -> draining closes only ordinary admission. Already-admitted
        # controlled dispatch can still reach its child in this generation.
        generation = state.generation if state else uuid4().hex
        write_state(folder, State("draining", generation, source, session, state.release if state else None,
                                  state.exchange_authorization if state else None))
        return session


async def inspect_database(context: Context, source: Source, *, idle: bool) -> dict[str, int]:
    # Inspect the installed connection, never a backend-only database override.
    identity = replace(context.identity, database=None)
    database = Database(identity)
    try:
        async with asyncio.timeout(20):
            return await inspect_connection(database, source, idle=idle)
    except TimeoutError:
        raise Refusal("database_unavailable", "PostgreSQL did not complete the maintenance proof.") from None
    finally:
        await database.close()


async def inspect_connection(database: Database, source: Source, *, idle: bool) -> dict[str, int]:
    if "PGSERVICE" in os.environ:
        raise Refusal("database_unavailable", "Unset PGSERVICE before verifying the installation database.")
    target = await credentials(database.identity)
    if (target["host"], int(target["port"]), target["dbname"]) != (source["host"], source["port"], source["database"]):
        raise Refusal("maintenance", "The configured installation does not match the maintenance target.")
    database.parameters = {
        **target, "hostaddr": "" if target["host"].startswith("/") else target["host"],
        "passfile": os.devnull, "sslmode": "disable", "gssencmode": "disable", "target_session_attrs": "any",
    }
    async with database.session() as connection:
        if idle:
            result = await connection.execute(
                "SELECT pg_catalog.pg_try_advisory_lock(%s::bigint)", [DATABASE_WRITER_LOCK])
            if result != [(True,)]:
                raise Refusal("maintenance_busy", "PostgreSQL still holds a writer connection.")
        rows = await connection.execute(
            "SELECT oid FROM pg_catalog.pg_database WHERE datname = pg_catalog.current_database()")
        if (connection.connection.info.dbname != source["database"]
                or rows != [(source["databaseOid"],)]):
            raise Refusal("maintenance", "PostgreSQL did not confirm the maintenance target.")
        if idle:
            # The autocommit statement takes its snapshot after the SQL
            # writer latch; it cannot miss a just-finished acceptance.
            rows = await connection.execute(
                "SELECT id::text FROM public.exchanges WHERE state = 'open' LIMIT 1")
            if rows:
                raise Refusal("maintenance_busy", "PostgreSQL still has an open Exchange, even if no folder is listed.")
        pair = database.schema.pair()
        if pair is None:
            raise Refusal("schema_incompatible", "Cannot verify the installed schema during maintenance.")
        return pair


def freeze(context: Context, source: Source, session: str) -> str:
    """Close controlled admission and prove both inventories before granting exclusive access."""
    with operation(context.identity.folder) as folder, gate(folder, idle=True):
        state = current(folder)
        bound(state, checked_source(source), session)
        if state.phase == "draining":
            drained_inventory(context)
            try:
                NoteFiles(context.identity).require_empty()
            except (OSError, ValueError, Refused):
                raise Refusal("maintenance_busy", "Recovery note custody is not empty or cannot be verified.") from None
            asyncio.run(inspect_database(context, source, idle=True))
            write_state(folder, State("exclusive", uuid4().hex, state.source, session, state.release,
                                      state.exchange_authorization))
        else:
            os.fsync(folder)
        return session


@contextmanager
def exclusive_upgrade(source: Source, session: str, *, runtime: Path | None = None) -> Iterator[str]:
    """ASD-2/3 adapter: borrow a frozen session without changing or reopening it."""
    with operation(runtime or runtime_folder()) as folder:
        state = current(folder)
        bound(state, checked_source(source), session)
        if state.phase != "exclusive":
            raise Refusal("maintenance", "Freeze the drained installation before changing its schema.")
        os.fsync(folder)
        yield session


@dataclass(frozen=True)
class GuardedSelection:
    """Selection established by the operator while its deployment locks remain held.

    The verifier must prove the actual prior or qualified format-2 successor,
    its archive and recovery evidence, and the selected installed artifacts.
    ``incumbent_release`` is the historical admission digest, which need not
    identify the actual prior deployed payload. For a successor, authorization
    is the digest of the compact policy staged under the admission locks.
    """

    role: Literal["prior", "successor"]
    source: Source
    session: str
    generation: str
    incumbent_release: str | None
    release: str
    authorization: str | None


def _reopen_directory(lease: ExclusiveLayoutLease, runtime: Path) -> int:
    try:
        return lease.require(runtime)
    except (AdmissionRefusal, OSError, ValueError):
        raise Refusal("maintenance", "Cannot verify the held installation admission locks.") from None


def reopen(context: Context, source: Source, session: str, *, release: str, schema: dict[str, int],
           verify_release: Callable[[], str] | None = None,
           verify_selection: Callable[[int, State], AbstractContextManager[GuardedSelection]] | None = None,
           lease: ExclusiveLayoutLease | None = None, layout: int = INSTALLATION_LAYOUT,
           generation: str | None = None) -> None:
    """Reopen after verification, with a guarded path for changing releases.

    The selection verifier receives a borrowed admission directory descriptor
    and the closed state under OWNER, GATE and WRITERS. Its context manager
    must retain all deployment selection locks through the state write. It
    verifies the archive, qualification, recovery and actual installed files,
    and stages successor authorization before yielding its exact selection.
    The descriptor is borrowed and must not be closed by the verifier.

    A move or rollback can supply its already-held exclusive lease and the
    marker's layout. The caller retains ownership of that lease.
    """
    if SHA256.fullmatch(release) is None:
        raise Refusal("maintenance", "Reopening requires a verified release digest.")
    if (verify_release is None) == (verify_selection is None):
        raise Refusal("maintenance", "Choose exactly one release verification path.")
    if (type(layout) is not int or layout not in (1, INSTALLATION_LAYOUT)
            or (layout != INSTALLATION_LAYOUT and lease is None)):
        raise Refusal("maintenance", "Reopening the historical layout requires its held exclusive lease.")
    if generation is not None and (lease is None or not isinstance(generation, str) or TOKEN.fullmatch(generation) is None):
        raise Refusal("maintenance", "A recorded reopen generation requires the held exclusive lease.")
    source = checked_source(source)
    runtime = context.identity.folder
    operator = operation(runtime) if lease is None else nullcontext(_reopen_directory(lease, runtime))
    with operator as folder:
        state = current(folder, layout=layout)
        bound(state, source, session)
        idle = state.phase == "exclusive"
        if lease is not None and not idle:
            raise Refusal("maintenance", "Reopening through a held layout lease requires exclusive maintenance.")
        if generation == state.generation:
            raise Refusal("maintenance", "Reopening requires a fresh admission generation.")
        if verify_selection is None:
            first = idle and state.release is None and state.exchange_authorization is None
            if release != state.release and not first:
                raise Refusal("maintenance", "Changing the Exchange release requires its guarded transition.")
            # Allow accepted work to progress while verifying during drainage.
            assert verify_release is not None
            if verify_release() != release:
                raise Refusal("maintenance", "The installed release did not pass verification.")
        elif not idle:
            raise Refusal("maintenance", "A guarded transition requires exclusive maintenance.")

        admission = gate(folder, idle=idle) if lease is None else nullcontext()
        with admission:
            if current(folder, layout=layout) != state:
                raise Refusal("maintenance", "The maintenance state changed during verification.")

            def finish(authorization: str | None) -> None:
                if authorization is not None:
                    try:
                        verify_authorization(folder, authorization, release)
                    except (OSError, ValueError, TypeError, KeyError, RecursionError):
                        raise Refusal("maintenance", "The active Exchange authorization cannot be verified.") from None
                if idle:
                    drained_inventory(context)
                    try:
                        NoteFiles(context.identity).require_empty()
                    except (OSError, ValueError, Refused):
                        raise Refusal("maintenance_busy", "Recovery note custody is not empty or cannot be verified.") from None
                if asyncio.run(inspect_database(context, source, idle=idle)) != schema:
                    raise Refusal("schema_incompatible", "The installed schema does not match the verified release.")
                if lease is not None and (_reopen_directory(lease, runtime) != folder
                                          or current(folder, layout=layout) != state):
                    raise Refusal("maintenance", "The held maintenance state changed before reopening.")
                write_state(folder, State("normal", generation or uuid4().hex, state.source, None, release, authorization),
                            layout=layout)

            if verify_selection is None:
                finish(state.exchange_authorization)
            else:
                with verify_selection(folder, state) as selection:
                    if (not isinstance(selection, GuardedSelection)
                            or selection.role not in ("prior", "successor")
                            or selection.source != source or selection.session != session
                            or selection.generation != state.generation
                            or selection.incumbent_release != state.release
                            or selection.release != release or state.release is None
                            or current(folder, layout=layout) != state):
                        raise Refusal("maintenance", "The guarded release selection does not match this session.")
                    if selection.role == "prior":
                        if state.exchange_authorization is not None or selection.authorization is not None:
                            raise Refusal("maintenance", "Prior rollback is unavailable after successor activation.")
                    elif (not isinstance(selection.authorization, str)
                          or SHA256.fullmatch(selection.authorization) is None):
                        raise Refusal("maintenance", "The successor requires its compact authorization digest.")
                    finish(selection.authorization)
