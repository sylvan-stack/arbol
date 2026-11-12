"""Operator transitions for the installation's durable schema-change fence."""

from __future__ import annotations

import asyncio
import fcntl
import os
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

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


def current(folder: int) -> State:
    try:
        return read_state(folder)
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
        write_state(folder, State("draining", generation, source, session, state.release if state else None))
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
            asyncio.run(inspect_database(context, source, idle=True))
            write_state(folder, State("exclusive", uuid4().hex, state.source, session, state.release))
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


def reopen(context: Context, source: Source, session: str, *, release: str, schema: dict[str, int],
           verify_release: Callable[[], str]) -> None:
    """Reopen only after verifying the deployed release and reading back its exact schema.

    The caller verifies the installed artifacts, data invariants and retirement
    of incompatible writer paths. It returns the digest of that verified
    release. Rescheduling during drainage requires the unchanged prior release.
    """
    if SHA256.fullmatch(release) is None:
        raise Refusal("maintenance", "Reopening requires a verified release digest.")
    with operation(context.identity.folder) as folder:
        state = current(folder)
        bound(state, checked_source(source), session)
        idle = state.phase == "exclusive"
        if not idle and release != state.release:
            raise Refusal("maintenance", "Only the unchanged prior release can resume during drainage.")
        # Keep the operator lock but allow accepted work to progress while the
        # operator verifies the unchanged release during drainage.
        if verify_release() != release:
            raise Refusal("maintenance", "The installed release did not pass verification.")
        with gate(folder, idle=idle):
            if idle:
                drained_inventory(context)
            if asyncio.run(inspect_database(context, source, idle=idle)) != schema:
                raise Refusal("schema_incompatible", "The installed schema does not match the verified release.")
            write_state(folder, State("normal", uuid4().hex, state.source, None, release))
