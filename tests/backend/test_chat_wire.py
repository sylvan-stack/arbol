"""Real Bridge requests and multiple windows against a disposable Root/database."""

from __future__ import annotations

import asyncio
import json
import stat
import sys
import time
import unittest
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Params, decode, encode  # noqa: E402
from arbol_backend.database import Database  # noqa: E402
from arbol_backend.model import identity, parse  # noqa: E402
from arbol_backend.server import Backend  # noqa: E402
from backend.support import Cluster, Frame  # noqa: E402


def chat(n: int) -> str:
    return str(UUID(int=n))


class Windows(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.frame = Frame()
        self.cluster = await asyncio.to_thread(Cluster)
        self.frame.record["status"] = "working"
        self.frame.save_root()
        self.frame.behavior = {"arbol-roots": {"output": [{**self.frame.record, "current": True}]}}
        for driver in ("claude", "codex", "pi"):
            self.frame.behavior["arbol-" + driver + "-driver"] = {"output": [{"id": "private"}]}
        self.frame.configure()
        selected = identity(ROOT, parse(self.frame.options(self.cluster.address)), home=self.frame.home)
        self.db = Database(selected)
        await self.db.execute((ROOT / "tests/backend/own-layout.sql").read_text())
        await self.db.execute(
            "INSERT INTO chats SELECT lpad(to_hex(n),32,'0')::uuid,'chat '||n,"
            "'2026-10-27T00:00:00Z'::timestamptz+n*interval '1 microsecond' FROM generate_series(1,201) n"
        )
        self.backend = Backend(selected)
        self.running = asyncio.create_task(self.backend.run())
        self.writers: list[asyncio.StreamWriter] = []
        self.pending: dict[asyncio.StreamReader, list[Params]] = defaultdict(list)
        self.seq: dict[tuple[asyncio.StreamReader, str], int] = {}
        self.next_id = 0
        for _ in range(100):
            if (self.frame.root / "backend.sock").exists():
                break
            await asyncio.sleep(0.01)
        assert self.backend.chats.catalogues.task
        await self.backend.chats.catalogues.task

    async def asyncTearDown(self) -> None:
        for writer in self.writers:
            writer.close()
        self.backend.stopped.set()
        await asyncio.wait_for(self.running, 2)
        await self.db.close()
        await asyncio.to_thread(self.cluster.close)
        self.frame.close()

    async def read(self, reader: asyncio.StreamReader, seconds: float = 3) -> Params:
        async with asyncio.timeout(seconds):
            message = decode(await reader.readuntil(b"\n"))
        if message["type"] == "event":
            key = (reader, message["id"])
            self.assertEqual(message["seq"], self.seq.get(key, 0) + 1)
            self.seq[key] = message["seq"]
        return message

    async def until(self, reader: asyncio.StreamReader, match: Callable[[Params], bool]) -> Params:
        for index, message in enumerate(self.pending[reader]):
            if match(message):
                return self.pending[reader].pop(index)
        async with asyncio.timeout(3):
            while True:
                message = await self.read(reader)
                if match(message):
                    return message
                self.pending[reader].append(message)

    async def open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_unix_connection(str(self.frame.root / "backend.sock"), limit=16 * 1024 * 1024)
        self.writers.append(writer)
        self.assertEqual((await self.read(reader))["type"], "hello")
        return reader, writer

    async def send(self, writer: asyncio.StreamWriter, message: Params) -> None:
        writer.write(encode(message))
        await writer.drain()

    async def call(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, method: str,
                   params: Params | None = None) -> Params:
        self.next_id += 1
        id = "call-" + str(self.next_id)
        await self.send(writer, {"type": "call", "id": id, "method": method, "params": params or {}})
        return await self.until(reader, lambda value: value["type"] == "reply" and value["id"] == id)

    async def subscribe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, id: str,
                        topic: str, params: Params | None = None) -> Params:
        await self.send(writer, {"type": "subscribe", "id": id, "topic": topic, "params": params or {}})
        result = await self.until(reader, lambda value: value.get("id") == id)
        self.assertEqual((result["type"], result["seq"], result["event"]["kind"]), ("event", 1, "snapshot"))
        event = result["event"]
        assert isinstance(event, dict)
        return event

    async def event(self, reader: asyncio.StreamReader, id: str, kind: str) -> Params:
        result = await self.until(reader, lambda value: value["type"] == "event" and value["id"] == id
                                  and value["event"]["kind"] == kind)
        event = result["event"]
        assert isinstance(event, dict)
        return event

    async def test_default_and_explicit_pages_use_the_same_exact_millisecond_cursor(self) -> None:
        """chats.page-cursor"""
        reader, writer = await self.open()
        first = (await self.call(reader, writer, "chats.page"))["result"]["chats"]
        self.assertEqual(len(first), 100)
        self.assertEqual([row["chat"] for row in first], [chat(n) for n in range(201, 101, -1)])
        self.assertTrue(all(row["activityAt"] == "2026-10-27T00:00:00.000Z" for row in first))
        cursor = {key: first[-1][key] for key in ("activityAt", "chat")}
        rest = (await self.call(reader, writer, "chats.page", {"before": cursor, "limit": 200}))["result"]["chats"]
        self.assertEqual([row["chat"] for row in rest], [chat(n) for n in range(101, 0, -1)])
        self.assertEqual(len({row["chat"] for row in first + rest}), 201)
        snapshot = await self.subscribe(reader, writer, "list", "chats")
        self.assertEqual(snapshot["chats"], first)
        for params in ({"limit": True}, {"limit": 201}, {"before": {"chat": "../../x", "activityAt": "bad"}},
                       {"before": {"chat": chat(1), "activityAt": "2026-10-27T00:00:00.000001Z"}}):
            self.assertEqual((await self.call(reader, writer, "chats.page", params))["error"]["code"], "invalid_input")

    async def test_title_changes_reach_two_windows_and_preserve_other_chat_tables(self) -> None:
        """chats.title-windows"""
        first, first_writer = await self.open()
        second, second_writer = await self.open()
        await self.subscribe(first, first_writer, "a", "chat", {"chat": chat(1)})
        await self.subscribe(second, second_writer, "a", "chat", {"chat": chat(1)})
        result = await self.call(first, first_writer, "chat.rename", {"chat": chat(1), "title": "  Build script  "})
        self.assertEqual(result["result"], {"title": "Build script"})
        for reader in (first, second):
            self.assertEqual((await self.event(reader, "a", "title"))["title"], "Build script")
        self.assertEqual(await self.db.execute("SELECT title FROM chats WHERE id=%s", [chat(1)]), [("Build script",)])
        for title in ("🦫" * 240, "  \t ", None):
            result = await self.call(first, first_writer, "chat.rename", {"chat": chat(1), "title": title})
            self.assertEqual(result["result"]["title"], title if title and title.strip() else None)
        for params in ({"chat": chat(1), "title": "x" * 241}, {"chat": "../../x", "title": "x"},
                       {"chat": chat(1), "title": "\0"}, {"chat": chat(1)}):
            self.assertEqual((await self.call(first, first_writer, "chat.rename", params))["error"]["code"], "invalid_input")
        self.assertEqual((await self.call(first, first_writer, "chat.rename", {"chat": chat(999), "title": "x"}))["error"]["code"],
                         "not_found")
        self.assertEqual(await self.db.execute("SELECT count(*) FROM exchanges"), [(0,)])
        self.assertEqual(await self.db.execute("SELECT count(*) FROM drafts"), [(0,)])

    async def test_independent_partial_settings_and_marks_preserve_each_other(self) -> None:
        """chats.atomic-settings; chats.atomic-marks"""
        first, first_writer = await self.open()
        second, second_writer = await self.open()
        await self.subscribe(first, first_writer, "a", "chat", {"chat": chat(1)})
        await self.subscribe(second, second_writer, "a", "chat", {"chat": chat(1)})
        chosen = {"driver": "claude", "subscription": "private", "model": "test", "effort": "high", "key": "ignored"}
        route_reply, folder_reply = await asyncio.gather(
            self.call(first, first_writer, "chat.settings", {"chat": chat(1), "route": chosen}),
            self.call(second, second_writer, "chat.settings", {"chat": chat(1), "workingFolder": str(self.frame.root)}),
        )
        self.assertEqual((route_reply["result"], folder_reply["result"]), ({}, {}))
        rows = await self.db.execute("SELECT route,working_folder FROM chat_settings WHERE chat_id=%s", [chat(1)])
        self.assertEqual(rows[0][0], {key: value for key, value in chosen.items() if key != "key"})
        self.assertEqual(rows[0][1], str(self.frame.root))
        for reader in (first, second):
            event = await self.until(reader, lambda value: value["type"] == "event" and value["id"] == "a"
                                     and value["event"]["kind"] == "settings"
                                     and "route" in value["event"]["settings"]
                                     and "workingFolder" in value["event"]["settings"])
            self.assertEqual(event["event"]["settings"]["workingFolder"], str(self.frame.root))
        mark_one, mark_two = await asyncio.gather(
            self.call(first, first_writer, "chat.mark", {"chat": chat(1), "ongoing": True}),
            self.call(second, second_writer, "chat.mark", {"chat": chat(1), "archived": True}),
        )
        self.assertNotIn("error", mark_one)
        self.assertNotIn("error", mark_two)
        rows = await self.db.execute("SELECT ongoing,archived_at FROM chat_marks WHERE chat_id=%s", [chat(1)])
        self.assertTrue(rows[0][0])
        archived_at = rows[0][1]
        await self.call(first, first_writer, "chat.mark", {"chat": chat(1), "archived": True})
        self.assertEqual((await self.db.execute("SELECT archived_at FROM chat_marks WHERE chat_id=%s", [chat(1)]))[0][0], archived_at)
        result = await self.call(first, first_writer, "chat.mark", {"chat": chat(1), "archived": False})
        self.assertEqual(result["result"], {"ongoing": True})
        calls = len(self.frame.calls())
        result = await self.call(first, first_writer, "chat.settings", {"chat": chat(1), "route": {**chosen, "subscription": "unknown"}})
        self.assertEqual(result["error"]["code"], "invalid_input")
        self.assertEqual(len(self.frame.calls()), calls)
        for params in ({"chat": chat(1), "ongoing": 1}, {"chat": chat(1)}, {"chat": "bad", "archived": True}):
            self.assertEqual((await self.call(first, first_writer, "chat.mark", params))["error"]["code"], "invalid_input")
        page = (await self.call(second, second_writer, "chats.page", {"limit": 200}))["result"]["chats"]
        self.assertEqual(len(page), 200)
        self.assertNotIn("ignored", json.dumps(page))

    async def test_late_older_write_reply_cannot_publish_stale_settings(self) -> None:
        """chats.mutation-publication-order"""
        subscriber, subscriber_writer = await self.open()
        first, first_writer = await self.open()
        second, second_writer = await self.open()
        await self.subscribe(subscriber, subscriber_writer, "chat", "chat", {"chat": chat(1)})
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.backend.database.execute
        async def delayed(sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
            rows = await original(sql, params)
            if sql.startswith("INSERT INTO chat_settings") and params is not None and params[1] is None:
                entered.set()
                await release.wait()
            return rows
        with mock.patch.object(self.backend.database, "execute", delayed):
            first_call = asyncio.create_task(self.call(first, first_writer, "chat.settings", {
                "chat": chat(1), "route": {"driver": "claude", "subscription": "private", "model": "test"}}))
            await entered.wait()
            result = await self.call(second, second_writer, "chat.settings", {
                "chat": chat(1), "workingFolder": str(self.frame.root)})
            self.assertEqual(result["result"], {})
            latest = await self.event(subscriber, "chat", "settings")
            self.assertEqual(latest["settings"]["workingFolder"], str(self.frame.root))
            self.assertEqual(latest["settings"]["route"]["model"], "test")
            release.set()
            self.assertEqual((await first_call)["result"], {})
        await asyncio.sleep(0.1)
        await self.call(subscriber, subscriber_writer, "subscriptions.check")
        for message in self.pending[subscriber]:
            if message["type"] == "event" and message["event"]["kind"] == "settings":
                self.assertEqual(message["event"]["settings"]["workingFolder"], str(self.frame.root))

    async def test_external_older_title_and_archive_are_observed_within_a_second(self) -> None:
        """chats.external-observation; chats.archive-list"""
        reader, writer = await self.open()
        await self.subscribe(reader, writer, "list", "chats")
        await self.subscribe(reader, writer, "old", "chat", {"chat": chat(1)})
        started = time.monotonic()
        await self.db.execute("UPDATE chats SET title='external' WHERE id=%s", [chat(1)])
        changed = await self.event(reader, "list", "changed")
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(changed["chats"][0]["chat"], chat(1))
        self.assertEqual(changed["chats"][0]["title"], "external")
        self.assertEqual((await self.event(reader, "old", "title"))["title"], "external")
        started = time.monotonic()
        result = await self.call(reader, writer, "chat.mark", {"chat": chat(201), "archived": True})
        self.assertIn("archivedAt", result["result"])
        changed = await self.event(reader, "list", "changed")
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(changed["chats"][0]["chat"], chat(201))
        self.assertTrue(changed["chats"][0]["archived"])
        rows = (await self.call(reader, writer, "chats.page", {"limit": 200}))["result"]["chats"]
        self.assertEqual(len(rows), 200)
        self.assertNotIn(chat(201), [row["chat"] for row in rows])

    async def test_layout_attention_and_contract_reads_without_own_tables(self) -> None:
        """chats.layout-wire"""
        reader, writer = await self.open()
        await self.db.execute("DROP TABLE drafts")
        result = await self.call(reader, writer, "root.get")
        self.assertFalse(result["result"]["layoutComplete"])
        attention = await self.subscribe(reader, writer, "attention", "attention")
        self.assertEqual([item["kind"] for item in attention["items"]], ["layout_incomplete"])
        snapshot = await self.subscribe(reader, writer, "a", "chat", {"chat": chat(1)})
        self.assertIsNone(snapshot["draft"])
        result = await self.call(reader, writer, "chat.mark", {"chat": chat(1), "ongoing": True})
        self.assertEqual(result["error"]["code"], "layout_incomplete")
        self.assertIn("result", await self.call(reader, writer, "chat.rename", {"chat": chat(1), "title": "still readable"}))
        await self.db.execute((ROOT / "tests/backend/own-layout.sql").read_text())
        result = await self.call(reader, writer, "root.get")
        self.assertTrue(result["result"]["layoutComplete"])
        self.assertEqual((await self.event(reader, "attention", "closed"))["id"], "layout_incomplete")

    async def test_wire_paste_keeps_exact_utf8_and_no_other_request_fields(self) -> None:
        """chats.paste-wire"""
        reader, writer = await self.open()
        value = "é\0🦫\n" * 2500
        result = await self.call(reader, writer, "paste.save", {"text": value, "folder": "/ignored", "key": "private-secret"})
        path = Path(result["result"]["path"])
        self.assertEqual(path.parent, self.frame.root / "pastes")
        self.assertEqual(path.read_bytes(), value.encode("utf-8"))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        result = await self.call(reader, writer, "paste.save", {"text": "x" * 9999})
        self.assertEqual(result["error"]["code"], "invalid_input")
        self.assertEqual(len(list(path.parent.iterdir())), 1)

    async def test_one_stalled_chat_does_not_hold_another_chat_or_call(self) -> None:
        """chats.observer-isolation"""
        reader, writer = await self.open()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.backend.chats.chat_view.loader
        async def delayed(params: Params) -> Params:
            if params["chat"] == chat(1):
                entered.set()
                await release.wait()
            return await original(params)
        self.backend.chats.chat_view.loader = delayed
        await self.send(writer, {"type": "subscribe", "id": "slow", "topic": "chat", "params": {"chat": chat(1)}})
        await entered.wait()
        started = time.monotonic()
        await self.subscribe(reader, writer, "fast", "chat", {"chat": chat(2)})
        self.assertEqual((await self.call(reader, writer, "subscriptions.check"))["type"], "reply")
        self.assertLess(time.monotonic() - started, 0.75)
        ended = await self.until(reader, lambda value: value["type"] == "ended" and value["id"] == "slow")
        self.assertEqual(ended["error"]["code"], "timeout")
        self.assertTrue(any(sub.id == "fast" for sub in self.backend.chats.chat_view.topic.listeners))
        release.set()


if __name__ == "__main__":
    unittest.main()
