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
