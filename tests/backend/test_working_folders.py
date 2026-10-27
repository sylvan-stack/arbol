"""Private real request/SQL receipts qualify stable folders and explicit repository moves."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import Params  # noqa: E402
from backend.dispatch_support import install, starts  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


class Folders(WindowFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        install(self.frame, self.cluster.address, [{}])
        self.backend.dispatch.retry, self.backend.dispatch.total = 0.1, 2
        self.backend.programs.limits["start"] = 0.5
        self.readonly = self.frame.base / "repos/sylvan-stack/readonly/private repo"
        self.other = self.frame.base / "Other picked folder Ω"
        self.booked = self.frame.base / "repos/sylvan-stack/fox/private repo"
        for path in (self.readonly, self.other, self.booked):
            path.mkdir(parents=True)
        self.route = {"driver": "claude", "subscription": "private", "model": "private-model"}
        self.r, self.w = await self.open()

    async def send_to(self, exchange: int, folder: Path) -> Params:
        payload = {"chat": chat(900), "exchange": chat(exchange), "message": "private folder request",
                   "route": self.route, "workingFolder": str(folder)}
        reply = await self.call(self.r, self.w, "chat.send", payload)
        self.assertIn("result", reply)
        return payload

    async def test_readonly_folder_survives_more_messages_repeat_and_external_workspace_environment(self) -> None:
        """folders.readonly-slot; folders.repeat; folders.booking-does-not-move-chat; folders.no-booking"""
        first = await self.send_to(800, self.readonly)
        await self.call(self.r, self.w, "chat.settings", {"chat": chat(900), "workingFolder": str(self.readonly)})
        with mock.patch.dict(os.environ, {"ARBOL_ROOT": self.backend.identity.root, "ARBOL_CHAT": chat(900),
                                         "ARBOL_WORKSPACE": str(self.booked)}):
            await self.send_to(801, self.readonly)
            repeated = await self.call(self.r, self.w, "chat.send", first)
            self.assertTrue(repeated["result"]["duplicate"])
        records = starts(self.frame)
        self.assertEqual([row["request"]["workingFolder"] for row in records], [str(self.readonly)]*3)
        self.assertEqual(await self.db.execute("SELECT working_folder FROM exchanges WHERE chat_id=%s ORDER BY number", [chat(900)]),
                         [(str(self.readonly),), (str(self.readonly),)])
        self.assertEqual(await self.db.execute("SELECT working_folder FROM chat_settings WHERE chat_id=%s", [chat(900)]), [(str(self.readonly),)])
        self.assertEqual(list(self.booked.iterdir()), [])
        self.assertTrue(all(row["program"] in {"arbol-roots", "arbol-root", "arbol-claude-driver", "arbol-codex-driver", "arbol-pi-driver"}
                            for row in self.frame.calls()))

    async def test_explicit_other_folder_and_repository_move_are_kept_without_rewriting_history(self) -> None:
        """folders.other-choice; folders.explicit-move; folders.history-preserved"""
        await self.send_to(800, self.readonly)
        changed = await self.call(self.r, self.w, "chat.settings", {"chat": chat(900), "workingFolder": str(self.other)})
        self.assertEqual(changed["result"], {})
        await self.send_to(801, self.other)
        await self.send_to(802, self.other)
        self.assertEqual([row["request"]["workingFolder"] for row in starts(self.frame)],
                         [str(self.readonly), str(self.other), str(self.other)])
        self.assertEqual(await self.db.execute("SELECT working_folder FROM exchanges WHERE chat_id=%s ORDER BY number", [chat(900)]),
                         [(str(self.readonly),), (str(self.other),), (str(self.other),)])
        self.assertEqual(await self.db.execute("SELECT working_folder FROM chat_settings WHERE chat_id=%s", [chat(900)]), [(str(self.other),)])

    async def test_send_again_uses_the_replaced_exchange_folder_after_a_move_and_ignores_competing_input(self) -> None:
        """folders.retry-original; folders.retry-after-move; folders.no-folder-substitution"""
        await self.send_to(800, self.readonly)
        await self.db.execute("UPDATE exchanges SET state='failed',error='{\"code\":\"private_failure\",\"message\":\"Private fixture\"}' WHERE id=%s", [chat(800)])
        await self.call(self.r, self.w, "chat.settings", {"chat": chat(900), "workingFolder": str(self.other)})
        reply = await self.call(self.r, self.w, "exchange.sendAgain", {"exchange": chat(800), "newExchange": chat(801),
            "route": self.route, "workingFolder": str(self.other), "chat": chat(999)})
        self.assertIn("result", reply)
        record = starts(self.frame)[-1]
        self.assertEqual((record["request"]["workingFolder"], record["request"]["chat"]), (str(self.readonly), chat(900)))
        self.assertNotIn("message", record["request"])
        self.assertEqual(record["args"][-2:], ["--replaces", chat(800)])
        self.assertEqual(await self.db.execute("SELECT working_folder FROM chat_settings WHERE chat_id=%s", [chat(900)]), [(str(self.other),)])
        self.assertEqual(list(self.booked.iterdir()), [])
