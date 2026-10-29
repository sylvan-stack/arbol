# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Actual private control files qualify answers against the current Driver form."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.answers import answer_params  # noqa: E402
from arbol_backend.bridge import Error, Params  # noqa: E402
from backend.live_support import Trunk  # noqa: E402
from backend.test_chat_wire import WindowFixture, chat  # noqa: E402


def form(*, multiple: bool = False, options: list[str] | None = None) -> Params:
    return {"callId": "question-tool", "questions": [{"id": "q", "question": "Pick one", "multiple": multiple,
        "options": [{"label": label, "description": "A private choice"} for label in (options if options is not None else ["first", "second"])]}]}


class Answering(WindowFixture):
    async def make(self, **kwargs: Any) -> Trunk:
        trunk = await Trunk.make(self.frame, chat(1), **kwargs)
        trunk.value["acceptedAt"] = "2026-10-27T00:00:00Z"
        trunk.save_record()
        return trunk

    async def answer(self, trunk: Trunk, value: Params, *, ask: str = "ask") -> Params:
        return await self.backend.controls.answers.write(await answer_params({"exchange": trunk.exchange,
            "askId": ask, "answer": value}))

    async def refused(self, trunk: Trunk, value: Params, code: str, *, ask: str = "ask") -> None:
        before = (trunk.folder / "control").read_bytes() if (trunk.folder / "control").is_file() else b""
        with self.assertRaises(Error) as caught:
            await self.answer(trunk, value, ask=ask)
        self.assertEqual(caught.exception.code, code)
        if trunk.folder.exists() and (trunk.folder / "control").is_file():
            self.assertEqual((trunk.folder / "control").read_bytes(), before)


# Archived complete imports; restore needed names in their original scope, not at this file tail.
