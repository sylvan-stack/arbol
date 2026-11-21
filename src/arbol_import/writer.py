"""Installation-bound provenance reads and per-session import transactions."""

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from arbol_backend.database import Database, Session
from arbol_backend.exchange_admission import Admission
from arbol_backend.model import Identity, Refused

from .readers.form import Tool

FINGERPRINT_REVISION = 5


@dataclass(frozen=True)
class Previous:
    chat: UUID
    manifest: str
    fingerprint: str | None
    keys: frozenset[str]


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
