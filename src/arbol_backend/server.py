"""Own one Root backend and isolate its Bridge connections and asynchronous work."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import stat
from collections.abc import Coroutine
from typing import Any

from .bridge import MAX_LINE, Connection, Registry
from .chats import Chats
from .controls import Controls
from .database import Database
from .discovery import Discovery
from .dispatch import Dispatch
from .drafts import Drafts
from .health import Health
from .lifetime import Lifetime
from .listings import Listings
from .live import Live
from .migration import Migration
from .model import Identity, Refused, root_record, settings
from .notes import Notes
from .process import Programs
from .roots import Roots
from .settling import Settling
from .stuck import Stuck


class Backend:
    def __init__(self, identity: Identity) -> None:
        self.identity = identity
        self.settings = settings(identity.settings)
        self.programs = Programs(identity)
        self.database = Database(identity)
        self.record = root_record(identity.folder, identity.root)
        self.registry = Registry()
        self.roots = Roots(identity, self.programs, self.database)
        self.roots.register(self.registry)
        self.chats = Chats(identity, self.database, self.programs, self.roots, self.registry,
                           lineage=isinstance(self.record.get("grewFrom"), str))
        self.health = Health(self.database, self.chats.attention)
        self.drafts = Drafts(self.chats, self.registry)
        self.dispatch = Dispatch(identity, self.programs, self.chats, self.drafts, self.registry, self.settings)
        self.live = Live(identity, self.chats, self.dispatch)
        self.notes = Notes(identity, self.database, self.chats, self.live)
        self.controls = Controls(self.programs, self.dispatch, self.live, self.registry)
        self.settling = Settling(self.programs, self.database, self.live)
        self.listings = Listings(self.programs, self.database)
        self.stuck = Stuck(identity, self.listings, self.controls, self.notes, self.chats.attention)
        self.listings.on_rows = self.listed
        self.listings.on_failed = self.stuck.failed
        self.settling.read_listing = self.listings.get
        self.discovery = Discovery(self.roots, self.listings, self.registry)
        self.migration = Migration(identity, self.programs, self.chats, self.registry, self.record)
        self.windows: set[asyncio.StreamWriter] = set()
        self.tasks: set[asyncio.Task[None]] = set()
        self.stopped = asyncio.Event()

    def listed(self, root: str, value: dict[str, Any]) -> None:
        self.settling.listed(root, value)
        self.stuck.observe(root, value)

    def task(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(work)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.windows.add(writer)
        try:
            await Connection(reader, writer, self.registry).run(self.roots.hello)
        finally:
            self.windows.discard(writer)

    async def initial_database(self) -> None:
        try:
            await self.database.execute("SELECT 1")
        except Refused:
            # The later database-away/attention Beat supplies publication and recovery.
            pass

    async def initial_catalogue(self) -> None:
        try:
            await self.discovery.get({})
        except Refused:
            pass

    async def initial_work(self) -> None:
        self.settling.start()

    async def monitor(self) -> None:
        while True:
            await asyncio.sleep(4)
            self.programs.reap()
            if self.windows:
                try:
                    await self.roots.refresh()
                    self.record = root_record(self.identity.folder, self.identity.root)
                except Refused as error:
                    self.roots.topic.fail(error)

    async def run(self) -> int:
        loop = asyncio.get_running_loop()
        lifetime = Lifetime(self.identity.folder)
        listening = lifetime.acquire()
        server: asyncio.Server | None = None
        stdin_registered = False
        try:
            for name in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(name, self.stopped.set)
            try:
                if stat.S_ISFIFO(os.fstat(0).st_mode):

                    def stdin_ready() -> None:
                        try:
                            if not os.read(0, 65536):
                                self.stopped.set()
                        except OSError:
                            self.stopped.set()

                    loop.add_reader(0, stdin_ready)
                    stdin_registered = True
            except OSError:
                pass

            def connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                if self.stopped.is_set():
                    writer.close()
                    return
                self.task(self.connection(reader, writer))

            server = await asyncio.start_unix_server(connected, sock=listening, cleanup_socket=False, limit=MAX_LINE - 1)
            print(
                json.dumps(
                    {
                        "ready": True,
                        "root": self.identity.root,
                        "build": self.identity.build,
                        "socket": str(lifetime.path),
                        "pid": os.getpid(),
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
            self.health.start()
            self.dispatch.start()
            self.chats.start()
            self.live.start()
            self.notes.start()
            self.task(self.initial_work())
            self.task(self.initial_catalogue())
            self.stuck.start()
            self.task(self.monitor())
            await self.stopped.wait()
            return 0
        finally:
            if stdin_registered:
                loop.remove_reader(0)
            for name in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(name)
            if server is not None:
                server.close()
                server.close_clients()
            for writer in list(self.windows):
                writer.close()
            for task in list(self.tasks):
                task.cancel()
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            if server is not None:
                await server.wait_closed()
            await self.stuck.close()
            await self.health.close()
            await self.controls.close()
            await self.discovery.close()
            await self.settling.close()
            await self.listings.close()
            await self.notes.close()
            await self.live.close()
            await self.dispatch.close()
            await self.migration.close()
            await self.chats.close()
            await self.roots.close()
            await self.database.close()
            self.programs.close()
            lifetime.close()
