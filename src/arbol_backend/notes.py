"""Recover write-ahead stuck notes into the installation database idempotently."""

from __future__ import annotations

import asyncio
from functools import partial

from .bridge import Params
from .chats import Chats
from .database import Database, protected_thread
from .live import Live
from .metadata import iso, now
from .model import Identity, Refused
from .note_files import NOTE_VERSION, Note, NoteFiles

NOTE_SECONDS = 5.0


class Notes:
    def __init__(self, identity: Identity, database: Database, chats: Chats, live: Live,
                 *, seconds: float = NOTE_SECONDS) -> None:
        self.files = NoteFiles(identity)
        self.database, self.chats, self.live, self.seconds = database, chats, live, seconds
        self.pending = False
        self.worker: asyncio.Task[None] | None = None
        self.closed = False

    async def record(self, exchange: str, chat: str, *, at: str | None = None) -> Params:
        async with self.database.permit("controlled"):
            return await self.record_admitted(exchange, chat, at=at)

    async def record_admitted(self, exchange: str, chat: str, *, at: str | None = None) -> Params:
        note = await protected_thread(partial(self.files.put, {"version": NOTE_VERSION,
            "exchange": exchange, "chat": chat, "kind": "ended_stuck", "at": at if at is not None else now()}))
        self.request()
        return note.wire

    async def persist(self, note: Note) -> tuple[Params | None, bool]:
        value = note.value
        async with asyncio.timeout(self.seconds):
            async with self.database.session() as session:
                rows = await session.execute("SELECT chat_id,state FROM exchanges WHERE id=%s", [value["exchange"]])
                if rows and (str(rows[0][0]) != value["chat"] or rows[0][1] not in ("open", "interrupted")):
                    return None, True  # An actual different saved end cannot acquire this note.
                if not rows or rows[0][1] == "open":
                    return None, False
                await session.execute(
                    "INSERT INTO exchange_notes(exchange_id,kind,at) "
                    "SELECT id,%s,%s FROM exchanges WHERE id=%s AND chat_id=%s AND state='interrupted' "
                    "ON CONFLICT(exchange_id,kind) DO NOTHING", [value["kind"], value["at"], value["exchange"], value["chat"]])
                saved = await session.execute(
                    "SELECT n.kind,n.at FROM exchange_notes n JOIN exchanges e ON e.id=n.exchange_id "
                    "WHERE n.exchange_id=%s AND e.chat_id=%s AND e.state='interrupted'",
                    [value["exchange"], value["chat"]])
                if saved and saved[0][0] == "ended_stuck":
                    return {"exchange": value["exchange"], "kind": "ended_stuck", "at": iso(saved[0][1])}, False
                return None, False

    def request(self) -> None:
        if self.closed:
            return
        self.pending = True
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self.flush())

    async def flush(self) -> None:
        while self.pending:
            self.pending = False
            try:
                names = await asyncio.to_thread(self.files.names)
            except (OSError, Refused):
                continue
            for exchange in names:
                try:
                    async with self.database.permit("controlled"):
                        await self.flush_note(exchange)
                except (OSError, Refused, ValueError, RecursionError):
                    pass  # A refused or unreadable write-ahead note stays pending.
                await asyncio.sleep(0)

    async def flush_note(self, exchange: str) -> None:
        # Reading can heal a crash link; the same permit covers repair, SQL and removal.
        note = await protected_thread(partial(self.files.read, exchange))
        wire, blocked = None, False
        if not self.database.away:
            try:
                wire, blocked = await self.persist(note)
            except (TimeoutError, Refused):
                pass  # Keep the write-ahead file after an uncertain SQL outcome.
        if blocked:
            self.live.notes.pop(exchange, None)
            return
        if wire is not None:
            self.chats.invalidate(note.value["chat"])
        self.live.note(note.value["chat"], wire or note.wire, committed=wire is not None)
        if wire is not None:
            await protected_thread(partial(self.files.remove, note))
            self.chats.changed(note.value["chat"])

    def start(self) -> None:
        self.request()

    async def close(self) -> None:
        self.closed = True
        if self.worker is not None:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
