"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_workspace as _support
from backend.test_workspace import (
    Bootstrap,
    Path,
    ROOT,
    WindowFixture,
    chat,
    json,
    settings,
    sys,
)


class Bootstrap(_support.Bootstrap):
# TEST-TIER-BEGIN tests/backend/test_workspace.py::Bootstrap.test_readonly_inventory_defaults_freshness_and_failure
    async def test_readonly_inventory_defaults_freshness_and_failure(self) -> None:
        folder = self.frame.home / "repos/sylvan-stack/readonly"
        folder.mkdir(parents=True)
        for name in ("zeta", "alpha", ".hidden"):
            (folder / name / ".git").mkdir(parents=True)
        (folder / "not-a-repository").mkdir()
        (folder / "outside-link").symlink_to(self.frame.root, target_is_directory=True)
        config = self.frame.home / "public-settings"
        config.mkdir()
        (config / "arbol.json").write_text(json.dumps({
            "route": {"driver": "claude", "subscription": "fictional", "model": "model-a", "private": "SECRET-FIXTURE"},
            "repositories": {"alpha": {"route": {"driver": "codex", "subscription": "fictional-b"}, "password": "SECRET-FIXTURE"}},
            "password": "SECRET-FIXTURE", "smallCallRoute": {"driver": "pi", "subscription": "private-small"}
        }))
        self.backend.workspace.settings = settings(config)
        reader, writer = await self.open()
        value = (await self.call(reader, writer, "workspace.get"))["result"]
        self.assertEqual([row["name"] for row in value["repositories"]], ["sylvan-stack", "alpha", "zeta"])
        self.assertEqual(value["repositories"][1]["folder"], str(folder / "alpha"))
        self.assertEqual(value["repositories"][1]["route"], {"driver": "codex", "subscription": "fictional-b"})
        self.assertEqual(value["repositories"][2]["route"], value["route"])
        self.assertNotIn("SECRET-FIXTURE", json.dumps(value))
        self.assertNotIn("private-small", json.dumps(value))
        self.assertNotIn("outside-link", json.dumps(value))
        (folder / "zeta/.git").rmdir()
        value = (await self.call(reader, writer, "workspace.get"))["result"]
        self.assertEqual([row["name"] for row in value["repositories"]], ["sylvan-stack", "alpha"])
        folder.rename(folder.with_name("gone"))
        failure = await self.call(reader, writer, "workspace.get")
        self.assertEqual(failure["error"]["code"], "no_answer")
        self.assertNotIn(str(self.frame.home), json.dumps(failure))
# TEST-TIER-END tests/backend/test_workspace.py::Bootstrap.test_readonly_inventory_defaults_freshness_and_failure

# TEST-TIER-BEGIN tests/backend/test_workspace.py::Bootstrap.test_first_unreplaced_prompt_is_available_outside_page_and_never_stored_as_title
    async def test_first_unreplaced_prompt_is_available_outside_page_and_never_stored_as_title(self) -> None:
        first = "😀" * 230 + "\nsecond line"
        await self.db.execute("UPDATE chats SET title=NULL WHERE id=%s", [chat(1)])
        await self.db.execute(
            "INSERT INTO exchanges(id,chat_id,number,state,trunk,build,route,working_folder,accepted_at,ended_at) "
            "SELECT lpad(to_hex(500+n),32,'0')::uuid,%s,n,'completed','trivial','1','{}','/fixture',now(),now() "
            "FROM generate_series(1,15) n", [chat(1)]
        )
        await self.db.execute(
            "INSERT INTO messages(exchange_id,position,role,text) SELECT id,0,'user',"
            "CASE WHEN number=1 THEN 'replaced prompt' WHEN number=2 THEN %s ELSE 'later prompt' END "
            "FROM exchanges WHERE chat_id=%s", [first, chat(1)]
        )
        await self.db.execute("UPDATE exchanges SET replaced_by=lpad(to_hex(502),32,'0')::uuid WHERE chat_id=%s AND number=1", [chat(1)])
        reader, writer = await self.open()
        snap = await self.subscribe(reader, writer, "first-prompt", "chat", {"chat": chat(1)})
        self.assertTrue(snap["more"])
        self.assertEqual(len(snap["exchanges"]), 12)
        self.assertEqual(snap["chat"]["exchangeCount"], 14)
        self.assertEqual(snap["chat"]["firstMessage"], first[:200])
        self.assertEqual(snap["chat"]["title"], None)
        self.assertNotIn(2, [row["number"] for row in snap["exchanges"]])
        self.assertEqual(await self.db.execute("SELECT title FROM chats WHERE id=%s", [chat(1)]), [(None,)])
        missing = await self.subscribe(reader, writer, "empty-prompt", "chat", {"chat": chat(999)})
        self.assertEqual(missing["chat"]["firstMessage"], "")
# TEST-TIER-END tests/backend/test_workspace.py::Bootstrap.test_first_unreplaced_prompt_is_available_outside_page_and_never_stored_as_title
