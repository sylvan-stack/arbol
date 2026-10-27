"""Per-window file replay and shared own-Root record/process observation."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from .bridge import MAX_LINE, Error, Params, Subscription, encode
from .chat_data import encoded
from .chats import Chats
from .dispatch import Dispatch
from .event_file import Line, Scanner, completed, superseded
from .exchange_files import Folder, Folders, Record, living, processes
from .model import Identity, Refused

POLL = 0.1
BATCH = 0.05
CATALOGUE = 0.75
TARGET_BATCH = 256 * 1024


class Restart(Exception):
    pass


@dataclass
class Cursor:
    folder: Folder
    descriptor: int
    inode: tuple[int, int]
    reader: Scanner
    replayed: bool = False

    def close(self) -> None:
        os.close(self.descriptor)
        self.folder.close()

    def changed(self) -> bool:
        info = os.stat("events.jsonl", dir_fd=self.folder.descriptor, follow_symlinks=False)
        return (info.st_dev, info.st_ino) != self.inode or info.st_size < self.reader.offset


@dataclass
class Following:
    generation: int = 0
    cursors: dict[str, Cursor] = field(default_factory=dict)
    tracked: set[str] = field(default_factory=set)
    statuses: dict[str, Params] = field(default_factory=dict)
    sent_at: float = 0

    def reset(self) -> None:
        for cursor in self.cursors.values():
            cursor.close()
        self.cursors.clear()
        self.statuses.clear()


class Lines:
    def __init__(self, sub: Subscription, state: Following, exchange: str) -> None:
        self.sub, self.state, self.exchange = sub, state, exchange
        self.batch: list[Params] = []
        self.base = self.overhead()
        self.size = self.base

    def check(self) -> None:
        if not self.sub.active or self.sub.snapshots != self.state.generation:
            raise Restart()

    def event(self, lines: list[Params]) -> Params:
        return {"kind": "lines", "exchange": self.exchange, "lines": lines}

    def overhead(self) -> int:
        return len(encode({"type": "event", "id": self.sub.id, "seq": self.sub.seq + 1, "event": self.event([])}))

    async def flush(self) -> None:
        if not self.batch:
            return
        delay = self.state.sent_at + BATCH - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        self.check()
        self.sub.send(self.event(self.batch))
        self.state.sent_at = time.monotonic()
        self.batch = []
        self.base = self.overhead()
        self.size = self.base

    async def add(self, line: Line) -> None:
        self.check()
        value = line.wire()
        try:
            length = len(encoded(value))
        except (ValueError, UnicodeError, RecursionError):
            return
        if self.base + length > MAX_LINE:
            value = {"n": line.meta.n, "tooLarge": True, "bytes": line.size}
            length = len(encoded(value))
        extra = length + bool(self.batch)
        if self.batch and self.size + extra > MAX_LINE:
            await self.flush()
        self.batch.append(value)
        self.size += length + (1 if len(self.batch) > 1 else 0)
        if self.size >= TARGET_BATCH:
            await self.flush()


class Live:
    def __init__(self, identity: Identity, chats: Chats, dispatch: Dispatch) -> None:
        self.identity, self.chats, self.dispatch = identity, chats, dispatch
        self.folders = Folders(identity)
        self.records: dict[str, Record] = {}
        self.known: dict[str, Record] = {}
        self.unreadable: set[str] = set()
        self.observed: dict[int, Any] = {}
        self.failed = False
        self.ready = asyncio.Event()
        self.stopping: dict[str, str] = {}
        self.followers: dict[Subscription, asyncio.Task[None]] = {}
        self.tasks: set[asyncio.Task[None]] = set()
        self.scan_task: asyncio.Task[None] | None = None
        self.dead: set[tuple[Any, ...]] = set()
        self.on_dead: Callable[[], None] | None = None

    def task(self, work: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(work)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def mark_stopping(self, exchange: str, chat: str) -> None:
        self.stopping[exchange] = chat
        self.chats.chat_view.topic.publish({"kind": "exchange", "exchange": {"exchange": exchange, "state": "stopping"}},
                                           params={"chat": chat})

    async def scan(self) -> None:
        try:
            names = self.folders.names()
            records: dict[str, Record] = {}
            unreadable: set[str] = set()
            secret = (self.chats.database.parameters or {}).get("password", "")
            for exchange in names:
                try:
                    records[exchange] = self.folders.read(exchange, secrets=(secret,))
                except FileNotFoundError:
                    pass
                except (OSError, Refused):
                    unreadable.add(exchange)
                await asyncio.sleep(0)
            observed = await processes({record.pid for record in records.values()})
            dead = {(id, record.pid, record.started, record.accepted, bool(record.end)) for id, record in records.items()
                    if not living(record, observed)}
            new_dead = bool(dead - self.dead)
            self.dead = dead
            self.known = {**{id: value for id, value in self.known.items() if id in unreadable}, **records}
            self.records, self.unreadable, self.observed, self.failed = records, unreadable, observed, False
            self.folders.forget(set(names))
            if new_dead and self.on_dead:
                self.on_dead()
        except (OSError, Refused):
            self.failed = True
        except Exception:
            self.failed = True
        finally:
            self.ready.set()

    def check(self, sub: Subscription, state: Following) -> None:
        if not sub.active or sub.snapshots != state.generation:
            raise Restart()

    def status(self, sub: Subscription, state: Following, value: Params) -> None:
        self.check(sub, state)
        id = value["exchange"]
        if state.statuses.get(id) != value:
            sub.send({"kind": "exchange", "exchange": value})
            state.statuses[id] = value

    def open_cursor(self, exchange: str) -> Cursor:
        folder = self.folders.open(exchange)
        try:
            fd = folder.open("events.jsonl")
        except BaseException:
            folder.close()
            raise
        info = os.fstat(fd)
        return Cursor(folder, fd, (info.st_dev, info.st_ino), Scanner(fd))

    async def stream(self, sub: Subscription, state: Following, exchange: str, cursor: Cursor) -> None:
        lines = Lines(sub, state, exchange)
        next_record = 0.0
        def checkpoint() -> None:
            nonlocal next_record
            self.check(sub, state)
            if time.monotonic() >= next_record:
                try:
                    secret = (self.chats.database.parameters or {}).get("password", "")
                    record = self.folders.read(exchange, secrets=(secret,))
                except FileNotFoundError as error:
                    raise Restart() from error
                status = record.status(living(record, self.observed), stopping=exchange in self.stopping)
                if status is not None:
                    self.status(sub, state, status)
                next_record = time.monotonic() + POLL
        cursor.reader.checkpoint = checkpoint
        if not cursor.replayed:
            cutoff, blocks = await completed(cursor.descriptor, os.fstat(cursor.descriptor).st_size, checkpoint=checkpoint)
            self.check(sub, state)
            async for line in cursor.reader.lines(limit=cutoff):
                if not superseded(line, blocks):
                    await lines.add(line)
            cursor.replayed = True
        async for line in cursor.reader.lines():
            await lines.add(line)
        await lines.flush()

    def missing(self, exchange: str) -> bool:
        try:
            folder = self.folders.open(exchange)
        except FileNotFoundError:
            return True
        else:
            folder.close()
            return False

    async def row_states(self, chat: str, ids: set[str]) -> dict[str, tuple[str, int, Any]]:
        if not ids:
            return {}
        async with self.chats.reader.session() as (session, _):
            rows = await session.execute("SELECT id,state,number,replaced_by FROM exchanges WHERE chat_id=%s "
                                         "AND id=ANY(%s::uuid[])", [chat, sorted(ids)])
        return {str(id): (state, number, replaced) for id, state, number, replaced in rows}

    async def saved(self, chat: str, exchange: str) -> Params | None:
        async with self.chats.reader.session() as (session, layout):
            rows = await session.execute("SELECT number,state,replaced_by FROM exchanges WHERE id=%s AND chat_id=%s",
                                         [exchange, chat])
            if not rows or rows[0][1] == "open":
                return None
            if rows[0][2] is not None:
                return {}  # The normal snapshot has hidden this replaced Exchange already.
            saved, _ = await self.chats.reader.exchanges(session, layout, chat, before=rows[0][0]+1, limit=1)
            return saved[0] if saved and saved[0]["exchange"] == exchange else None

    async def step(self, sub: Subscription, state: Following) -> None:
        params = sub.params
        snapshot = await self.chats.chat_view.snapshot(params)
        self.check(sub, state)
        if self.failed:
            raise Error("no_answer")
        if any(self.known[id].chat == params["chat"] for id in self.unreadable if id in self.known):
            raise Error("no_answer")
        rows = {row["exchange"]: row for row in snapshot.event["exchanges"]}
        ids = ({id for id, record in self.records.items() if record.chat == params["chat"]} | state.tracked
               | {id for id, chat in self.stopping.items() if chat == params["chat"]})
        actual = await self.row_states(params["chat"], ids)
        self.check(sub, state)
        for exchange, chat in list(self.stopping.items()):
            if chat == params["chat"] and exchange in actual and actual[exchange][0] != "open":
                self.stopping.pop(exchange, None)
            elif chat == params["chat"] and (exchange not in rows or rows[exchange]["state"] == "open"):
                self.status(sub, state, {"exchange": exchange, "state": "stopping"})
        secret = (self.chats.database.parameters or {}).get("password", "")
        for exchange, observed in list(self.records.items()):
            if observed.chat != params["chat"]:
                continue
            row = rows.get(exchange)
            if exchange in actual and actual[exchange][0] != "open":
                self.stopping.pop(exchange, None)
                if cursor := state.cursors.pop(exchange, None):
                    cursor.close()
                continue  # Includes old ended rows outside the snapshot's newest twelve.
            try:
                record = self.folders.read(exchange, secrets=(secret,))
            except FileNotFoundError:
                continue
            alive = living(record, self.observed)
            status = record.status(alive, stopping=exchange in self.stopping)
            if record.end is not None:
                self.stopping.pop(exchange, None)
            if status is None:
                continue
            if row is None:
                status = {"exchange": exchange, "state": "accepting"}
            self.status(sub, state, status)
            if row is None or record.accepted is None:
                continue
            state.tracked.add(exchange)
            cursor = state.cursors.get(exchange)
            try:
                if cursor is not None and cursor.changed():
                    self.check(sub, state)
                    sub.send(snapshot.event)
                    raise Restart()
                if cursor is None:
                    cursor = self.open_cursor(exchange)
                    state.cursors[exchange] = cursor
                await self.stream(sub, state, exchange, cursor)
            except FileNotFoundError:
                pass  # Confirm the committed rows after publication/removal races below.
        for exchange in list(state.tracked):
            if not self.missing(exchange):
                continue
            row = await self.saved(params["chat"], exchange)
            self.check(sub, state)
            if row is not None:
                if row:
                    sub.send({"kind": "saved", "exchange": row})
                state.tracked.remove(exchange)
                state.statuses.pop(exchange, None)
                self.stopping.pop(exchange, None)
                if cursor := state.cursors.pop(exchange, None):
                    cursor.close()

    async def follow(self, sub: Subscription) -> None:
        state = Following()
        try:
            await self.ready.wait()
            while sub.active:
                if not sub.ready:
                    await asyncio.sleep(0.01)
                    continue
                if state.generation != sub.snapshots:
                    state.reset()
                    state.generation = sub.snapshots
                try:
                    await self.step(sub, state)
                except Restart:
                    continue
                await asyncio.sleep(POLL)
        except asyncio.CancelledError:
            raise
        except (OSError, Refused) as error:
            sub.connection.end(sub, error if isinstance(error, Refused) else Error("no_answer"))
        except Exception:
            sub.connection.end(sub, Error("no_answer"))
        finally:
            state.reset()

    async def monitor(self) -> None:
        next_scan = 0.0
        watching = False
        while True:
            listeners = set(self.chats.chat_view.topic.listeners)
            if listeners and not watching:
                self.ready.clear()
                self.dead.clear()
                next_scan = 0
            watching = bool(listeners)
            if listeners and time.monotonic() >= next_scan and (self.scan_task is None or self.scan_task.done()):
                self.scan_task = self.task(self.scan())
                next_scan = time.monotonic() + CATALOGUE
            for sub in listeners:
                if sub not in self.followers:
                    self.followers[sub] = self.task(self.follow(sub))
            for sub in set(self.followers) - listeners:
                self.followers.pop(sub).cancel()
            await asyncio.sleep(0.05)

    def start(self) -> None:
        self.task(self.monitor())

    async def close(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.followers.clear()
