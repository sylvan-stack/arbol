# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Own-Root CLI boundary, coalescing and uncertain mutations, with private PostgreSQL only."""

from __future__ import annotations

__all__ = [
    "Backend", "CHAT", "CHILD", "COPY", "Cluster", "Database", "Delegation", "Frame", "LIMITS", "Params", "Path",
    "ROOT", "TEST_ROOT", "UUID", "asyncio", "decode", "encode", "identity", "json", "os", "parse", "shlex",
    "signal", "subprocess", "sys", "time", "unittest",
]
import asyncio
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Params, decode, encode  # noqa: E402
from arbol_backend.database import Database  # noqa: E402
from arbol_backend.model import identity, parse  # noqa: E402
from arbol_backend.process import LIMITS  # noqa: E402
from arbol_backend.server import Backend  # noqa: E402
from backend.support import TEST_ROOT, Cluster, Frame  # noqa: E402

CHAT = str(UUID(int=100))
COPY = str(UUID(int=101))

# This disposable global-program stand-in writes only the explicitly named private database.
# It does not model Root migration policy: that belongs to the independently qualified Root scripts.
CHILD = r'''import json,os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv.pop(1))
import psycopg
base=Path(sys.argv.pop(1))
config=json.loads((base/'migration.json').read_text())
args=sys.argv[1:]
fd=os.open(base/'calls.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
os.write(fd,(json.dumps({'program':'arbol-roots','args':args,'pid':os.getpid(),'home':os.environ.get('HOME')})+'\n').encode());os.close(fd)
if args==['list']:
 print(json.dumps(config['catalogue']),flush=True);sys.exit(0)
assert args[:2]==['migrate',config['root']]
mode='check' if args[2:]==['--check'] else 'chat'
behavior=config.get(mode,{})
time.sleep(behavior.get('sleep',0))
if behavior.get('sql'):
 with psycopg.connect(config['database'],autocommit=True) as connection:
  connection.execute(behavior['sql'])
if 'raw' in behavior:print(behavior['raw'],flush=True)
else:print(json.dumps(behavior['output']),flush=True)
sys.exit(behavior.get('status',0))
'''


class Delegation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.frame = Frame()
        self.cluster = await asyncio.to_thread(Cluster)
        self.frame.record.update(status="working", grewFrom="older")
        self.frame.save_root()
        self.selected = identity(ROOT, parse(self.frame.options(self.cluster.address)), home=self.frame.home)
        self.db = Database(self.selected)
        await self.db.execute((ROOT / "tests/backend/own-layout.sql").read_text())
        await self.db.execute("INSERT INTO chats VALUES(%s,'original','2026-10-27T00:00:00Z')", [CHAT])
        await self.db.execute("INSERT INTO migrated_chats VALUES(%s,'older',%s,0,now(),false)", [CHAT, CHAT])
        await self.db.execute("INSERT INTO drafts VALUES(%s,%s,NULL,'keep this Draft',4,NULL,NULL,now())", [str(UUID(int=4)), CHAT])
        await self.db.execute("INSERT INTO chat_settings VALUES(%s,NULL,'/private/keep',now())", [CHAT])
        await self.db.execute("INSERT INTO chat_marks VALUES(%s,true,NULL,now())", [CHAT])
        self.config: Params = {
            "root": TEST_ROOT, "database": self.cluster.address,
            "catalogue": [{**self.frame.record, "current": True}],
            "check": {"output": self.check_result()}, "chat": {"output": self.import_result()},
        }
        self.configure()
        script = ("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -I -c " + shlex.quote(CHILD)
                  + " " + shlex.quote(str(ROOT / "runtime/site-packages")) + " " + shlex.quote(str(self.frame.bin)) + ' "$@"\n')
        (self.frame.bin / "arbol-roots").write_text(script)
        (self.frame.bin / "arbol-roots").chmod(0o700)
        self.backend: Backend | None = None
        self.running: asyncio.Task[int] | None = None
        self.writers: list[asyncio.StreamWriter] = []
        self.children: list[subprocess.Popen[bytes]] = []
        self.counter = 0
        self.pending: dict[asyncio.StreamReader, list[Params]] = {}

    def configure(self) -> None:
        (self.frame.bin / "migration.json").write_text(json.dumps(self.config))

    def check_result(self) -> Params:
        return {"root": TEST_ROOT, "rootBuild": "1", "mode": "check", "fromRoot": "older", "checked": 1, "stale": []}

    def import_result(self, action: str = "replaced") -> Params:
        return {"root": TEST_ROOT, "rootBuild": "1", "mode": "chat", "fromRoot": "older", "chat": CHAT,
                "fromChat": CHAT, "resultChat": CHAT if action == "replaced" else COPY, "action": action,
                "endedThrough": 0, "snapshotAt": "2026-10-27T01:00:00Z"}

    async def start(self) -> Backend:
        self.backend = Backend(self.selected)
        self.running = asyncio.create_task(self.backend.run())
        for _ in range(200):
            if (self.frame.root / "backend.sock").exists():
                return self.backend
            await asyncio.sleep(0.01)
        raise AssertionError("Private backend did not become ready.")

    async def settle_check(self, backend: Backend) -> None:
        async with asyncio.timeout(3):
            while backend.migration.check_task is None:
                await asyncio.sleep(0.01)
            await backend.migration.check_task

    def calls(self, mode: str | None = None) -> list[Params]:
        rows = [row for row in self.frame.calls() if row["program"] == "arbol-roots" and row["args"][:1] == ["migrate"]]
        return [row for row in rows if mode is None or ("--check" in row["args"]) == (mode == "check")]

    async def open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_unix_connection(str(self.frame.root / "backend.sock"))
        self.writers.append(writer)
        self.pending[reader] = []
        self.assertEqual((await self.read(reader))["type"], "hello")
        return reader, writer

    async def read(self, reader: asyncio.StreamReader) -> Params:
        return decode(await asyncio.wait_for(reader.readuntil(b"\n"), 3))

    async def until(self, reader: asyncio.StreamReader, kind: str, id: str) -> Params:
        for index, message in enumerate(self.pending[reader]):
            if message["type"] == kind and message["id"] == id:
                return self.pending[reader].pop(index)
        async with asyncio.timeout(3):
            while True:
                value = await self.read(reader)
                if value["type"] == kind and value["id"] == id:
                    return value
                self.pending[reader].append(value)

    async def call(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, method: str,
                   params: Params | None = None) -> Params:
        self.counter += 1
        id = "c" + str(self.counter)
        writer.write(encode({"type": "call", "id": id, "method": method, "params": params or {}}))
        await writer.drain()
        return await self.until(reader, "reply", id)

    async def subscribe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, id: str,
                        topic: str, params: Params | None = None) -> Params:
        writer.write(encode({"type": "subscribe", "id": id, "topic": topic, "params": params or {}}))
        await writer.drain()
        return await self.until(reader, "event", id)

    async def asyncTearDown(self) -> None:
        for writer in self.writers:
            writer.close()
        if self.backend:
            self.children += [child.process for child in self.backend.programs.running.values()]
            self.backend.stopped.set()
        if self.running:
            await asyncio.wait_for(self.running, 2)
        for child in self.children:
            try:
                await asyncio.to_thread(child.wait, timeout=3)
            except subprocess.TimeoutExpired:
                # Exact stand-in child only, owned by this test, after the assertions.
                os.killpg(child.pid, signal.SIGKILL)
                await asyncio.to_thread(child.wait, timeout=2)
        await self.db.close()
        await asyncio.to_thread(self.cluster.close)
        self.frame.close()


# Archived complete imports; restore needed names in their original scope, not at this file tail.
