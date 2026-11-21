"""Installation-bound provenance reads and per-session import transactions."""

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Literal
from uuid import UUID, uuid4

from psycopg import DataError, IntegrityError
from psycopg.types.json import Jsonb

from arbol_backend.database import Database, Session, protected_thread
from arbol_backend.exchange_admission import Admission
from arbol_backend.model import Identity, Refused, route

from .archive import ArchiveRoot, PublishedArchive
from .mapping import MappedSegment, MappedSession
from .readers.form import Tool

FINGERPRINT_REVISION = 5
_json = partial(json.dumps, ensure_ascii=False, allow_nan=False)
type ImportOutcome = Literal["imported", "extended", "rearchived", "unchanged", "deferred"]


@dataclass(frozen=True)
class Previous:
    chat: UUID
    manifest: str
    fingerprint: str | None
    keys: frozenset[str]


@dataclass(frozen=True)
class WritePlan:
    outcome: ImportOutcome
    segments: tuple[MappedSegment, ...] = ()
    archive: PublishedArchive | None = None
    repair: str | None = None


def rows_refused() -> Refused:
    return Refused("rows_refused", "The saved Chat Session could not be represented in the import tables.")


def validate_rows(mapped: MappedSession) -> None:
    def valid_key(value: str, limit: int) -> bool:
        return "\0" not in value and 1 <= len(value.encode("utf-8")) <= limit

    try:
        if not valid_key(mapped.native_id, 256):
            raise rows_refused()
        turn_keys: set[str] = set()
        for segment in mapped.segments:
            if (not valid_key(segment.turn_key, 512) or segment.turn_key in turn_keys
                    or not segment.working_folder.startswith("/") or not route(segment.route).get("driver")):
                raise rows_refused()
            turn_keys.add(segment.turn_key)
            positions = [row.position for row in segment.messages]
            positions.extend(call.position for call in segment.calls)
            if (sorted(positions) != list(range(len(positions))) or not segment.messages
                    or segment.messages[0].position != 0):
                raise rows_refused()
            if any((row.position == 0) != (row.role == "user") for row in segment.messages):
                raise rows_refused()
            seen: set[str] = set()
            for call in segment.calls:
                if (not call.call_id or call.call_id in seen or
                        (call.parent_call_id is not None and call.parent_call_id not in seen)):
                    raise rows_refused()
                seen.add(call.call_id)
    except (UnicodeError, ValueError):
        raise rows_refused() from None


def _schema_refusal() -> Refused:
    return Refused("incompatible_schema", "The installed schema does not include the import fingerprint migration.")


def _database_refusal() -> Refused:
    return Refused("database_unavailable", "The import could not confirm the installation database operation.")


async def _previous(session: Session, tool: Tool, native_id: str, keys: Iterable[str]) -> Previous | None:
    rows = await session.execute(
        "SELECT chat_id, manifest, files_fingerprint FROM public.chat_imports WHERE tool = %s AND native_id = %s",
        (tool, native_id),
    )
    if not rows:
        return None
    chat, manifest, fingerprint = rows[0]
    selected = list(keys)
    matches = await session.execute(
        "SELECT turn_key FROM public.exchange_imports WHERE chat_id = %s AND turn_key = ANY(%s::text[])",
        (chat, selected),
    ) if selected else []
    return Previous(chat, manifest, fingerprint, frozenset(row[0] for row in matches))


async def _create_chat(
    session: Session, mapped: MappedSession, archive: PublishedArchive, taken: datetime,
) -> UUID:
    chat = uuid4()
    await session.execute("INSERT INTO public.chats (id, title, created_at) VALUES (%s,%s,%s)",
                          (chat, mapped.title, mapped.created_at))
    await session.execute(
        "INSERT INTO public.chat_marks (chat_id, ongoing, archived_at, updated_at) VALUES (%s,FALSE,%s,%s)",
        (chat, taken, taken),
    )
    await session.execute(
        "INSERT INTO public.chat_imports "
        "(chat_id, tool, native_id, kind, tool_version, origin, manifest, files_fingerprint, first_imported, last_imported) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (chat, mapped.tool, mapped.native_id, mapped.kind, mapped.tool_version, Jsonb(mapped.origin, dumps=_json),
         archive.manifest, archive.fingerprint, taken, taken),
    )
    return chat


async def _write_segment(session: Session, chat: UUID, number: int, segment: MappedSegment) -> None:
    exchange = uuid4()
    error = None if segment.error is None else Jsonb(segment.error, dumps=_json)
    await session.execute(
        "INSERT INTO public.exchanges "
        "(id, chat_id, number, state, error, trunk, build, route, small_call_route, working_folder, accepted_at, ended_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (exchange, chat, number, segment.state, error, segment.trunk, segment.build, Jsonb(segment.route, dumps=_json),
         segment.small_call_route, segment.working_folder, segment.accepted_at, segment.ended_at),
    )
    run = segment.run_for(exchange)
    await session.execute(
        "INSERT INTO public.runs (exchange_id, run_id, kind, outcome, usage, error, started, ended_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (run.exchange_id, run.run_id, run.kind, run.outcome, Jsonb(run.usage, dumps=_json), error, run.started, run.ended_at),
    )
    for message in segment.messages:
        await session.execute(
            "INSERT INTO public.messages (exchange_id, position, role, text) VALUES (%s,%s,%s,%s)",
            (exchange, message.position, message.role, message.text),
        )
    for call in segment.calls:
        await session.execute(
            "INSERT INTO public.tool_calls "
            "(exchange_id, position, run_id, call_id, parent_call_id, name, input, ok, result, error, truncated, interrupted) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (exchange, call.position, run.run_id, call.call_id, call.parent_call_id, call.name,
             Jsonb(call.input, dumps=_json), call.ok, None if call.result is None else Jsonb(call.result, dumps=_json),
             call.error, call.truncated, call.interrupted),
        )
    await session.execute(
        "INSERT INTO public.exchange_imports (exchange_id, chat_id, turn_key, trigger) VALUES (%s,%s,%s,%s)",
        (exchange, chat, segment.turn_key, segment.trigger),
    )


async def _write_plan(
    session: Session, mapped: MappedSession, prior: Previous | None, plan: WritePlan, taken: datetime,
) -> UUID | None:
    archive = plan.archive
    if prior is None:
        if archive is None:
            return None
        chat = await _create_chat(session, mapped, archive, taken)
    else:
        chat = prior.chat
        if archive is not None:
            await session.execute(
                "UPDATE public.chat_imports SET manifest = %s, files_fingerprint = %s, last_imported = %s "
                "WHERE chat_id = %s",
                (archive.manifest, archive.fingerprint, taken, chat),
            )
        elif plan.repair is not None:
            await session.execute("UPDATE public.chat_imports SET files_fingerprint = %s WHERE chat_id = %s",
                                  (plan.repair, chat))
    if plan.segments:
        last = await session.execute("SELECT COALESCE(MAX(number),0) FROM public.exchanges WHERE chat_id = %s", (chat,))
        for number, segment in enumerate(plan.segments, start=last[0][0] + 1):
            await _write_segment(session, chat, number, segment)
    return chat


class ImportStore:
    def __init__(self, identity: Identity) -> None:
        self.admission = Admission(identity.folder)
        self.database = Database(identity, admission=self.admission, application=True)

    def _require_fingerprint(self) -> None:
        schema = self.database.schema
        if schema.version != 1 or schema.revision is None or schema.revision < FINGERPRINT_REVISION:
            raise _schema_refusal()

    @asynccontextmanager
    async def _read(self, *, allow_draining: bool) -> AsyncIterator[Session]:
        try:
            async with self.database.import_read(allow_draining=allow_draining) as session:
                self._require_fingerprint()
                yield session
        except Refused as error:
            if error.code in {"schema_incompatible", "schema_uninitialized"}:
                raise _schema_refusal() from None
            if error.code == "timeout":
                raise _database_refusal() from None
            raise

    async def preflight(self, *, dry_run: bool) -> None:
        async with self._read(allow_draining=dry_run):
            pass

    async def previous(self, tool: Tool, native_id: str, keys: Iterable[str]) -> Previous | None:
        async with self._read(allow_draining=True) as session:
            return await _previous(session, tool, native_id, keys)

    async def apply(
        self, mapped: MappedSession, keys: Iterable[str], taken: datetime, binding: ArchiveRoot,
        decide: Callable[[Previous | None], Awaitable[WritePlan]],
    ) -> tuple[UUID | None, WritePlan]:
        """Keep replay decisions, durable archive publication and corresponding rows under one permit."""
        try:
            async with self.database.permit(), self.database.connection() as session:
                self._require_fingerprint()
                await session.execute("BEGIN")
                await session.execute("SET LOCAL arbol.importing = 'on'")
                prior = await _previous(session, mapped.tool, mapped.native_id, keys)
                plan = await decide(prior)
                chat = await _write_plan(session, mapped, prior, plan, taken)
                await protected_thread(binding.verify)
                try:
                    await session.execute("COMMIT")
                except Refused:
                    raise _database_refusal() from None
                return chat, plan
        except Refused as error:
            if error.code in {"schema_incompatible", "schema_uninitialized"}:
                raise _schema_refusal() from None
            if isinstance(error.__cause__, (DataError, IntegrityError)):
                raise rows_refused() from None
            if error.code == "timeout":
                raise _database_refusal() from None
            raise
