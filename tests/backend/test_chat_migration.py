"""Own-Root CLI boundary, coalescing and uncertain mutations, with private PostgreSQL only."""

from __future__ import annotations

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

    async def test_comparison_coalesces_and_does_not_delay_local_reads_or_poll(self) -> None:
        """chats.migration-check-coalescing"""
        self.config["check"] = {"sleep": 0.4, "output": {**self.check_result(), "stale": [CHAT]},
                                "sql": "UPDATE migrated_chats SET stale=true"}
        self.configure()
        backend = await self.start()
        first, first_writer = await self.open()
        second, second_writer = await self.open()
        initial = await self.subscribe(first, first_writer, "list", "chats")
        self.assertFalse(initial["event"]["chats"][0]["migration"]["stale"])
        started = time.monotonic()
        one, two = await asyncio.gather(self.call(first, first_writer, "chats.page"),
                                       self.call(second, second_writer, "chats.page"))
        self.assertIn("result", one)
        self.assertIn("result", two)
        self.assertLess(time.monotonic() - started, 0.3)
        await self.settle_check(backend)
        changed = await self.until(first, "event", "list")
        self.assertTrue(changed["event"]["chats"][0]["migration"]["stale"])
        await asyncio.sleep(0.3)
        self.assertEqual(len(self.calls("check")), 1)
        self.assertTrue(all(row["home"] == str(self.frame.home) for row in self.calls()))

    async def test_failed_comparison_keeps_last_known_and_later_success_clears_attention(self) -> None:
        """chats.migration-unavailable"""
        await self.db.execute("UPDATE migrated_chats SET stale=true")
        self.config["check"] = {"status": 1, "output": {"error": {"code": "busy", "message": "Comparison is busy; saved marks stay last-known."}}}
        self.configure()
        backend = await self.start()
        await self.settle_check(backend)
        reader, writer = await self.open()
        attention = await self.subscribe(reader, writer, "attention", "attention")
        self.assertEqual(attention["event"]["items"][0]["id"], "migration_unavailable")
        self.assertIn("saved marks stay last-known", attention["event"]["items"][0]["message"])
        self.assertTrue((await self.db.execute("SELECT stale FROM migrated_chats"))[0][0])
        self.config["check"] = {"output": self.check_result(), "sql": "UPDATE migrated_chats SET stale=false"}
        self.configure()
        self.assertIn("result", await self.call(reader, writer, "chats.page"))
        await self.settle_check(backend)
        self.assertEqual((await self.until(reader, "event", "attention"))["event"],
                         {"kind": "closed", "id": "migration_unavailable"})
        self.assertEqual(len(self.calls("check")), 2)

    async def test_reimport_maps_both_actions_and_preserves_unrelated_local_input(self) -> None:
        """chats.reimport-results; chats.reimport-local-input"""
        backend = await self.start()
        await self.settle_check(backend)
        reader, writer = await self.open()
        before = [await self.db.execute("SELECT to_jsonb(t)::text FROM " + table + " t")
                  for table in ("drafts", "chat_settings", "chat_marks")]
        await self.subscribe(reader, writer, "chat", "chat", {"chat": CHAT})
        for action in ("replaced", "copied"):
            self.config["chat"] = {"output": {**self.import_result(action), "apiKey": "private-secret"},
                                    "sql": "UPDATE migrated_chats SET stale=false" if action == "replaced" else
                                    "INSERT INTO chats SELECT '" + COPY + "'::uuid,title,created_at FROM chats WHERE id='" + CHAT + "'; "
                                    "INSERT INTO migrated_chats SELECT '" + COPY + "'::uuid,from_root,from_chat,ended_through,migrated_at,false "
                                    "FROM migrated_chats WHERE chat_id='" + CHAT + "'"}
            self.configure()
            reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
            self.assertEqual(reply["result"], {"chat": CHAT if action == "replaced" else COPY,
                                              "previousChat": CHAT, "action": action, "fromRoot": "older", "fromChat": CHAT})
            self.assertNotIn("private-secret", str(reply))
            after = [await self.db.execute("SELECT to_jsonb(t)::text FROM " + table + " t")
                     for table in ("drafts", "chat_settings", "chat_marks")]
            self.assertEqual(after, before)
        copied = await backend.chats.reader.chat({"chat": COPY})
        self.assertIsNone(copied["draft"])
        self.assertFalse(copied["chat"]["migration"]["stale"])
        self.assertEqual(len(self.calls("chat")), 2)

    async def test_two_calls_share_one_unresolved_import(self) -> None:
        """chats.reimport-coalescing"""
        self.config["chat"]["sleep"] = 0.25
        self.configure()
        backend = await self.start()
        await self.settle_check(backend)
        first, first_writer = await self.open()
        second, second_writer = await self.open()
        replies = await asyncio.gather(self.call(first, first_writer, "chat.reimport", {"chat": CHAT}),
                                       self.call(second, second_writer, "chat.reimport", {"chat": CHAT}))
        self.assertEqual(replies[0]["result"], replies[1]["result"])
        self.assertEqual(len(self.calls("chat")), 1)

    async def test_invalid_copy_and_malformed_result_never_trigger_an_automatic_retry(self) -> None:
        """chats.reimport-validation"""
        backend = await self.start()
        await self.settle_check(backend)
        reader, writer = await self.open()
        for value in ("../../x", "ABCDEFAB-1234-4234-8234-123456789012", None):
            reply = await self.call(reader, writer, "chat.reimport", {"chat": value})
            self.assertEqual(reply["error"]["code"], "invalid_input")
        reply = await self.call(reader, writer, "chat.reimport", {"chat": str(UUID(int=999))})
        self.assertEqual(reply["error"]["code"], "not_found")
        self.assertFalse(self.calls("chat"))
        self.config["chat"]["output"]["root"] = "wrongroot"
        self.configure()
        reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
        self.assertEqual((reply["error"]["code"], reply["error"]["source"]), ("no_answer", "roots"))
        await asyncio.sleep(0.3)
        self.assertEqual(len(self.calls("chat")), 1)

    async def test_forwarded_refusal_keeps_code_source_and_only_a_bounded_safe_message(self) -> None:
        """chats.migration-errors"""
        backend = await self.start()
        await self.settle_check(backend)
        reader, writer = await self.open()
        assert backend.database.parameters is not None
        backend.database.parameters["password"] = "opaque-private-value"
        for message in ("The selected copy is busy.", "password=private-secret", "Rejected opaque-private-value", "x" * 2000):
            self.config["chat"] = {"status": 1, "output": {"error": {"code": "busy", "message": message}}}
            self.configure()
            reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
            self.assertEqual((reply["error"]["code"], reply["error"]["source"]), ("busy", "roots"))
            self.assertNotIn("private-secret", str(reply))
            self.assertNotIn("opaque-private-value", str(reply))
            self.assertLessEqual(len(reply["error"]["message"].encode()), 1024)
            if message == "The selected copy is busy.":
                self.assertEqual(reply["error"]["message"], message)

    async def test_timeout_tracks_late_mutation_and_shutdown_does_not_kill_it(self) -> None:
        """chats.reimport-uncertain"""
        await self.db.execute("UPDATE migrated_chats SET stale=true")
        self.config["chat"] = {"sleep": 0.4, "output": self.import_result(), "sql": "UPDATE migrated_chats SET stale=false"}
        self.configure()
        backend = await self.start()
        backend.programs.limits["reimport"] = 0.05
        self.assertEqual((LIMITS["reimport"], LIMITS["migrate-check"]), (90, 90))
        await self.settle_check(backend)
        reader, writer = await self.open()
        reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
        self.assertEqual(reply["error"]["code"], "no_answer")
        child = backend.programs.running[("reimport", CHAT)]
        self.assertIsNone(child.process.poll())
        self.children.append(child.process)
        reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
        self.assertEqual(reply["error"]["code"], "no_answer")
        started = time.monotonic()
        backend.stopped.set()
        assert self.running
        await asyncio.wait_for(self.running, 2)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(await asyncio.to_thread(child.process.wait, timeout=2), 0)
        self.assertFalse((await self.db.execute("SELECT stale FROM migrated_chats"))[0][0])
        self.assertEqual(len(self.calls("chat")), 1)

    async def test_missing_provenance_columns_are_layout_incomplete_without_any_compare(self) -> None:
        """chats.provenance-layout"""
        await self.db.execute("ALTER TABLE migrated_chats DROP COLUMN stale")
        backend = await self.start()
        await self.settle_check(backend)
        reader, writer = await self.open()
        result = await self.call(reader, writer, "root.get")
        self.assertFalse(result["result"]["layoutComplete"])
        rows = (await self.call(reader, writer, "chats.page"))["result"]["chats"]
        self.assertNotIn("migration", rows[0])
        reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
        self.assertEqual(reply["error"]["code"], "layout_incomplete")
        self.assertFalse(self.calls())
        self.assertIn("layout_incomplete", backend.chats.attention.items)


if __name__ == "__main__":
    unittest.main()
