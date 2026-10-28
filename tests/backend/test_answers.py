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

# TEST-TIER-DISABLED-BEGIN tests/backend/test_answers.py::Answering.test_listed_single_multiple_continue_decline_and_one_write
#     async def test_listed_single_multiple_continue_decline_and_one_write(self) -> None:
#         """answers.form; answers.one-write; answers.no-free-text"""
#         values: list[tuple[Params, Params]] = [(form(), {"type": "answers", "answers": {"q": ["first"]}}),
#             (form(multiple=True), {"type": "answers", "answers": {"q": ["first", "second"]}}),
#             (form(options=[]), {"type": "answers", "answers": {"q": []}}),
#             (form(options=[]), {"type": "answers", "answers": {}}),
#             (form(), {"type": "decline"})]
#         for question, answer in values:
#             trunk = await self.make()
#             trunk.event("ask_opened", askId="ask", ask=question)
#             write = os.write
#             with mock.patch("arbol_backend.answers.os.write", wraps=write) as append:
#                 self.assertEqual(await self.answer(trunk, answer), {})
#                 self.assertEqual(append.call_count, 1)
#             raw = (trunk.folder / "control").read_bytes()
#             self.assertTrue(raw.endswith(b"\n"))
#             self.assertEqual(json.loads(raw), {"type": "answer", "askId": "ask", "answer": answer})
#         r, w = await self.open()
#         reply = await self.call(r, w, "exchange.answer", {"exchange": trunk.exchange, "askId": "ask", "answer": {"type": "decline"}})
#         self.assertEqual(reply["result"], {})
# TEST-TIER-DISABLED-END tests/backend/test_answers.py::Answering.test_listed_single_multiple_continue_decline_and_one_write

# TEST-TIER-DISABLED-BEGIN tests/backend/test_answers.py::Answering.test_unknown_choices_wrong_cardinality_extra_keys_and_current_asks
#     async def test_unknown_choices_wrong_cardinality_extra_keys_and_current_asks(self) -> None:
#         """answers.invalid-form; answers.current-ask"""
#         trunk = await self.make()
#         trunk.event("ask_opened", askId="ask", ask=form())
#         selections: list[dict[str, list[str]]] = [{"q": ["free text"]}, {"q": []}, {"q": ["first", "second"]}, {"q": ["first", "first"]},
#                          {"q": ["first"], "unknown": []}, {}]
#         for selected in selections:
#             await self.refused(trunk, {"type": "answers", "answers": selected}, "invalid_input")
#         await self.refused(trunk, {"type": "decline"}, "not_found", ask="never-opened")
#         trunk.event("ask_closed", askId="ask")
#         await self.refused(trunk, {"type": "decline"}, "not_found")
#         trunk.event("ask_opened", askId="ask", ask=form())
#         trunk.event("finished", ok=True)
#         await self.refused(trunk, {"type": "decline"}, "not_found")
#         trunk.event("ask_opened", askId="ask", ask=form())
#         trunk.end()
#         await self.refused(trunk, {"type": "decline"}, "ended")
# TEST-TIER-DISABLED-END tests/backend/test_answers.py::Answering.test_unknown_choices_wrong_cardinality_extra_keys_and_current_asks

# TEST-TIER-DISABLED-BEGIN tests/backend/test_answers.py::Answering.test_observed_delivery_is_idempotent_and_nested_asks_are_independent
#     async def test_observed_delivery_is_idempotent_and_nested_asks_are_independent(self) -> None:
#         """answers.observed-delivery; answers.nested-asks"""
#         trunk = await self.make()
#         trunk.event("ask_opened", askId="ask", ask=form())
#         trunk.event("ask_opened", askId="nested", parentCallId="nested-tool", ask=form())
#         trunk.event("ask_closed", askId="nested", parentCallId="nested-tool")
#         trunk.n += 1
#         trunk.append((json.dumps({"n": trunk.n, "answer": {"type": "answer", "askId": "ask", "answer": {"type": "decline"}}})+"\n").encode())
#         trunk.event("ask_closed", askId="ask")
#         self.assertEqual(await self.answer(trunk, {"type": "decline"}), {})
#         self.assertEqual((trunk.folder / "control").read_bytes(), b"")
#         trunk.event("ask_opened", askId="ask", ask=form())
#         await self.answer(trunk, {"type": "answers", "answers": {"q": ["second"]}})
#         self.assertEqual(len((trunk.folder / "control").read_text().splitlines()), 1)
# TEST-TIER-DISABLED-END tests/backend/test_answers.py::Answering.test_observed_delivery_is_idempotent_and_nested_asks_are_independent

# TEST-TIER-DISABLED-BEGIN tests/backend/test_answers.py::Answering.test_publication_wait_rename_timeout_and_neither_folder
#     async def test_publication_wait_rename_timeout_and_neither_folder(self) -> None:
#         """answers.publication; answers.ended"""
#         self.assertEqual(PUBLICATION_SECONDS, 15)
#         trunk = await self.make(staged=True)
#         trunk.event("ask_opened", askId="ask", ask=form())
#         self.backend.controls.answers.wait = 0.3
#         task = asyncio.create_task(self.answer(trunk, {"type": "decline"}))
#         await asyncio.sleep(0.06)
#         self.assertFalse(task.done())
#         trunk.publish()
#         self.assertEqual(await task, {})
#         staging = await self.make(staged=True)
#         self.backend.controls.answers.wait = 0.05
#         await self.refused(staging, {"type": "decline"}, "no_answer")
#         trunk.remove()
#         await self.refused(trunk, {"type": "decline"}, "ended")
# TEST-TIER-DISABLED-END tests/backend/test_answers.py::Answering.test_publication_wait_rename_timeout_and_neither_folder

# TEST-TIER-DISABLED-BEGIN tests/backend/test_answers.py::Answering.test_syntax_and_64k_limit_before_files_and_short_write_is_not_retried
#     async def test_syntax_and_64k_limit_before_files_and_short_write_is_not_retried(self) -> None:
#         """answers.byte-limit; answers.short-write; answers.syntax-before-effects"""
#         trunk = await self.make()
#         trunk.event("ask_opened", askId="ask", ask=form())
#         base = {"exchange": trunk.exchange, "askId": "x", "answer": {"type": "decline"}}
#         size = len((await answer_params(base))["_line"])
#         exact = await answer_params({**base, "askId": "x"*(1+CONTROL_BYTES-size)})
#         self.assertEqual(len(exact["_line"]), CONTROL_BYTES)
#         for value in ({**base, "askId": "x"*(2+CONTROL_BYTES-size)}, {**base, "exchange": "../escape"},
#                       {**base, "askId": "bad\x00id"}, {**base, "answer": {"type": "text", "text": "free"}}):
#             with mock.patch.object(self.backend.controls.answers.folders, "open", side_effect=AssertionError("file effect")):
#                 with self.assertRaises(Error):
#                     await answer_params(value)
#         with mock.patch("arbol_backend.answers.os.write", return_value=1) as write:
#             await self.refused(trunk, {"type": "decline"}, "no_answer")
#             self.assertEqual(write.call_count, 1)
# TEST-TIER-DISABLED-END tests/backend/test_answers.py::Answering.test_syntax_and_64k_limit_before_files_and_short_write_is_not_retried

# TEST-TIER-DISABLED-BEGIN tests/backend/test_answers.py::Answering.test_never_create_or_follow_control_and_reject_replaced_identity
#     async def test_never_create_or_follow_control_and_reject_replaced_identity(self) -> None:
#         """answers.file-identity; answers.no-create"""
#         trunk = await self.make()
#         trunk.event("ask_opened", askId="ask", ask=form())
#         control = trunk.folder / "control"
#         control.unlink()
#         await self.refused(trunk, {"type": "decline"}, "no_answer")
#         self.assertFalse(control.exists())
#         target = self.frame.base / "unrelated"
#         target.write_bytes(b"untouched")
#         target.chmod(0o600)
#         control.symlink_to(target)
#         with self.assertRaises(Error):
#             await self.answer(trunk, {"type": "decline"})
#         self.assertEqual(target.read_bytes(), b"untouched")
#         control.unlink()
#         os.mkfifo(control, 0o600)
#         with self.assertRaises(Error):
#             await asyncio.wait_for(self.answer(trunk, {"type": "decline"}), 0.5)
#         control.unlink()
#         control.touch(mode=0o600)
#         verify = self.backend.controls.answers.verify
#         def replaced(folder: Any, fd: int) -> None:
#             control.rename(trunk.folder / "old-control")
#             control.touch(mode=0o600)
#             verify(folder, fd)
#         with mock.patch.object(self.backend.controls.answers, "verify", side_effect=replaced):
#             await self.refused(trunk, {"type": "decline"}, "no_answer")
#         self.assertEqual((trunk.folder / "old-control").read_bytes(), b"")
# TEST-TIER-DISABLED-END tests/backend/test_answers.py::Answering.test_never_create_or_follow_control_and_reject_replaced_identity

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_answers.py:5
# import asyncio
# TEST-TIER-IMPORTS-END tests/backend/test_answers.py:5
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_answers.py:6
# import json
# TEST-TIER-IMPORTS-END tests/backend/test_answers.py:6
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_answers.py:7
# import os
# TEST-TIER-IMPORTS-END tests/backend/test_answers.py:7
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_answers.py:11
# from unittest import mock
# TEST-TIER-IMPORTS-END tests/backend/test_answers.py:11
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_answers.py:17
# from arbol_backend.answers import CONTROL_BYTES, PUBLICATION_SECONDS, answer_params  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_answers.py:17
