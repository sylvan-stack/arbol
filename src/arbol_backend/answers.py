"""Validate the current live question, then append one bounded control write."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass

from .bridge import Error, Params, uuid_id
from .event_file import Scanner
from .exchange_files import Folder, Folders, private
from .model import Refused
from .validation import text

CONTROL_BYTES = 65536
PUBLICATION_SECONDS = 15.0


async def answer_params(params: Params) -> Params:
    exchange, ask = uuid_id(params.get("exchange")), text(params.get("askId"))
    value = params.get("answer")
    if not isinstance(value, dict):
        raise Error("invalid_input")
    if value.get("type") == "decline":
        answer: Params = {"type": "decline"}
    elif value.get("type") == "answers" and isinstance(value.get("answers"), dict):
        selected: dict[str, list[str]] = {}
        for id, labels in value["answers"].items():
            text(id)
            if not isinstance(labels, list) or any(not isinstance(item, str) for item in labels):
                raise Error("invalid_input")
            selected[id] = [text(item, nonempty=False) for item in labels]
            if len(set(selected[id])) != len(selected[id]):
                raise Error("invalid_input")
        answer = {"type": "answers", "answers": selected}
    else:
        raise Error("invalid_input")
    raw = (json.dumps({"type": "answer", "askId": ask, "answer": answer}, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)+"\n").encode("utf-8")
    if len(raw) > CONTROL_BYTES:
        raise Error("invalid_input")
    return {"exchange": exchange, "askId": ask, "answer": answer, "_line": raw}


@dataclass
class Question:
    form: Params | None
    delivered: bool = False


async def current(descriptor: int, ask: str) -> Question:
    active: dict[tuple[str, str], Params | None] = {}
    delivered = False
    ended = False
    async for line in Scanner(descriptor).lines():
        item = line.meta
        key = (item.run, item.parent)
        if item.kind == "end":
            active.clear()
            ended = True
        elif item.kind == "ask_opened" and item.ask == ask:
            form = line.value["event"].get("ask") if line.value is not None else None
            active[key] = form if isinstance(form, dict) else None
            delivered = False
        elif item.kind == "ask_closed" and item.ask == ask:
            active.pop(key, None)
        elif item.kind == "finished":
            active.pop(key, None)
        elif item.kind == "answer" and item.ask == ask:
            delivered = True
    if ended:
        raise Error("ended")
    if len(active) > 1:
        raise Error("invalid_input")
    if delivered:
        return Question(None, True)
    if not active:
        raise Error("not_found")
    return Question(next(iter(active.values())))


def validate(question: Question, answer: Params) -> None:
    if answer["type"] == "decline" or question.delivered:
        return
    form = question.form
    if not isinstance(form, dict) or not isinstance(form.get("questions"), list) or not form["questions"]:
        raise Error("invalid_input")
    ids: set[str] = set()
    selected = answer["answers"]
    for item in form["questions"]:
        if not isinstance(item, dict) or type(item.get("multiple")) is not bool or not isinstance(item.get("options"), list):
            raise Error("invalid_input")
        id = text(item.get("id"))
        if id in ids:
            raise Error("invalid_input")
        ids.add(id)
        labels: set[str] = set()
        for option in item["options"]:
            if not isinstance(option, dict):
                raise Error("invalid_input")
            label = text(option.get("label"), nonempty=False)
            if label in labels:
                raise Error("invalid_input")
            labels.add(label)
        choices = selected.get(id, [])
        if labels and (not choices or not item["multiple"] and len(choices) != 1):
            raise Error("invalid_input")
        if any(choice not in labels for choice in choices):
            raise Error("invalid_input")
    if set(selected) - ids:
        raise Error("invalid_input")


class Answers:
    def __init__(self, folders: Folders, *, wait: float = PUBLICATION_SECONDS) -> None:
        self.folders, self.wait = folders, wait

    async def published(self, exchange: str) -> Folder:
        deadline = time.monotonic() + self.wait
        while True:
            try:
                return self.folders.open(exchange)
            except FileNotFoundError:
                try:
                    temporary = self.folders.open(exchange, temporary=True)
                except FileNotFoundError as error:
                    raise Error("ended") from error
                temporary.close()
                if time.monotonic() >= deadline:
                    raise Error("no_answer") from None
                await asyncio.sleep(min(0.05, max(0, deadline-time.monotonic())))

    def verify(self, folder: Folder, control: int) -> None:
        current = self.folders.open(folder.exchange)
        try:
            expected, actual = os.fstat(folder.descriptor), os.fstat(current.descriptor)
            if (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino):
                raise Error("ended")
            expected = os.fstat(control)
            actual = os.stat("control", dir_fd=current.descriptor, follow_symlinks=False)
            if (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino) or not private(actual):
                raise Error("no_answer")
            if self.folders.read(folder.exchange).end is not None:
                raise Error("ended")
        finally:
            current.close()

    def storage_error(self, exchange: str) -> Error:
        for temporary in (False, True):
            try:
                folder = self.folders.open(exchange, temporary=temporary)
            except FileNotFoundError:
                continue
            except (OSError, Refused):
                return Error("no_answer")
            folder.close()
            return Error("no_answer")
        return Error("ended")

    async def write(self, params: Params) -> Params:
        folder: Folder | None = None
        events: int | None = None
        control: int | None = None
        try:
            folder = await self.published(params["exchange"])
            if self.folders.read(params["exchange"]).end is not None:
                raise Error("ended")
            events = folder.open("events.jsonl")
            question = await current(events, params["askId"])
            validate(question, params["answer"])
            if question.delivered:
                return {}
            control = folder.open("control", append=True)
            self.verify(folder, control)
            if os.write(control, params["_line"]) != len(params["_line"]):
                raise Error("no_answer")
            return {}
        except FileNotFoundError as error:
            raise self.storage_error(params["exchange"]) from error
        except (OSError, ValueError, UnicodeError) as error:
            raise Error("no_answer") from error
        finally:
            if control is not None:
                os.close(control)
            if events is not None:
                os.close(events)
            if folder is not None:
                folder.close()
