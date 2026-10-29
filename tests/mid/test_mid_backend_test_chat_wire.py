"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_chat_wire as _support
from backend.test_chat_wire import (
    Any,
    Backend,
    Callable,
    Cluster,
    Database,
    Frame,
    Params,
    Path,
    ROOT,
    Sequence,
    UUID,
    WindowFixture,
    Windows,
    asyncio,
    chat,
    decode,
    defaultdict,
    encode,
    identity,
    json,
    mock,
    parse,
    replace,
    stat,
    sys,
    time,
    unittest,
)


class Windows(_support.Windows):
# TEST-TIER-BEGIN tests/backend/test_chat_wire.py::Windows.test_default_and_explicit_pages_use_the_same_exact_millisecond_cursor
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
# TEST-TIER-END tests/backend/test_chat_wire.py::Windows.test_default_and_explicit_pages_use_the_same_exact_millisecond_cursor

# TEST-TIER-BEGIN tests/backend/test_chat_wire.py::Windows.test_title_changes_reach_two_windows_and_preserve_other_chat_tables
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
# TEST-TIER-END tests/backend/test_chat_wire.py::Windows.test_title_changes_reach_two_windows_and_preserve_other_chat_tables

# TEST-TIER-BEGIN tests/backend/test_chat_wire.py::Windows.test_independent_partial_settings_and_marks_preserve_each_other
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
# TEST-TIER-END tests/backend/test_chat_wire.py::Windows.test_independent_partial_settings_and_marks_preserve_each_other

# TEST-TIER-BEGIN tests/backend/test_chat_wire.py::Windows.test_external_older_title_and_archive_are_observed_within_a_second
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
# TEST-TIER-END tests/backend/test_chat_wire.py::Windows.test_external_older_title_and_archive_are_observed_within_a_second

# TEST-TIER-BEGIN tests/backend/test_chat_wire.py::Windows.test_layout_attention_and_contract_reads_without_own_tables
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
# TEST-TIER-END tests/backend/test_chat_wire.py::Windows.test_layout_attention_and_contract_reads_without_own_tables

# TEST-TIER-BEGIN tests/backend/test_chat_wire.py::Windows.test_backend_needs_no_schema_or_history_write_permission
    async def test_backend_needs_no_schema_or_history_write_permission(self) -> None:
        """chats.read-only-contract; chats.no-ddl"""
        exchange = chat(990)
        await self.db.execute(
            "INSERT INTO exchanges(id,chat_id,number,state,trunk,build,route,working_folder,accepted_at,ended_at) "
            "VALUES(%s,%s,1,'completed','trivial','1','{}','/private/work',now(),now())", [exchange, chat(1)])
        await self.db.execute("INSERT INTO messages VALUES(%s,0,'user','immutable message')", [exchange])
        await self.db.execute("INSERT INTO runs(exchange_id,run_id,kind,outcome,usage,ended_at) "
                              "VALUES(%s,'r','agent','completed','{}',now())", [exchange])
        before_rows = [await self.db.execute("SELECT to_jsonb(t)::text FROM " + table + " t ORDER BY 1")
                       for table in ("exchanges", "messages", "tool_calls", "runs")]
        before_header = await self.db.execute("SELECT id,created_at FROM chats ORDER BY id")
        schema_sql = ("SELECT table_name,column_name,data_type,is_nullable,column_default FROM information_schema.columns "
                      "WHERE table_schema='public' ORDER BY table_name,ordinal_position")
        before_schema = await self.db.execute(schema_sql)
        before_indexes = await self.db.execute("SELECT indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY indexname")
        await self.db.execute("CREATE ROLE backend_app LOGIN; GRANT USAGE ON SCHEMA public TO backend_app; "
                              "GRANT SELECT ON ALL TABLES IN SCHEMA public TO backend_app; "
                              "GRANT UPDATE(title) ON chats TO backend_app; "
                              "GRANT INSERT,UPDATE,DELETE ON drafts,chat_settings,chat_marks,exchange_notes TO backend_app; "
                              "GRANT USAGE ON SEQUENCE drafts_revision TO backend_app")
        # Restart only this disposable backend, using a role that cannot change the schema/history.
        self.backend.stopped.set()
        await self.running
        selected = replace(self.backend.identity, database=self.cluster.address.replace("postgresql://bkd@", "postgresql://backend_app@"))
        self.backend = Backend(selected)
        self.running = asyncio.create_task(self.backend.run())
        for _ in range(100):
            if (self.frame.root / "backend.sock").exists():
                break
            await asyncio.sleep(0.01)
        assert self.backend.chats.catalogues.task
        await self.backend.chats.catalogues.task
        reader, writer = await self.open()
        self.assertIn("result", await self.call(reader, writer, "root.get"))
        self.assertIn("result", await self.call(reader, writer, "chats.page"))
        snapshot = await self.subscribe(reader, writer, "a", "chat", {"chat": chat(1)})
        self.assertEqual(snapshot["exchanges"][0]["items"][0]["text"], "immutable message")
        self.assertIn("result", await self.call(reader, writer, "chat.rename", {"chat": chat(1), "title": "new title"}))
        self.assertIn("result", await self.call(reader, writer, "chat.settings", {"chat": chat(1), "workingFolder": str(self.frame.root)}))
        self.assertIn("result", await self.call(reader, writer, "chat.mark", {"chat": chat(1), "ongoing": True}))
        after_rows = [await self.db.execute("SELECT to_jsonb(t)::text FROM " + table + " t ORDER BY 1")
                      for table in ("exchanges", "messages", "tool_calls", "runs")]
        self.assertEqual(after_rows, before_rows)
        self.assertEqual(await self.db.execute("SELECT id,created_at FROM chats ORDER BY id"), before_header)
        self.assertEqual(await self.db.execute(schema_sql), before_schema)
        self.assertEqual(await self.db.execute("SELECT indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY indexname"), before_indexes)
# TEST-TIER-END tests/backend/test_chat_wire.py::Windows.test_backend_needs_no_schema_or_history_write_permission

# TEST-TIER-BEGIN tests/backend/test_chat_wire.py::Windows.test_wire_paste_keeps_exact_utf8_and_no_other_request_fields
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
# TEST-TIER-END tests/backend/test_chat_wire.py::Windows.test_wire_paste_keeps_exact_utf8_and_no_other_request_fields

# TEST-TIER-BEGIN tests/backend/test_chat_wire.py::Windows.test_one_stalled_chat_does_not_hold_another_chat_or_call
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
# TEST-TIER-END tests/backend/test_chat_wire.py::Windows.test_one_stalled_chat_does_not_hold_another_chat_or_call
