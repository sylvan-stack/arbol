"""Shared bounded stops and current-form answers for this backend's own Root."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from .answers import Answers, answer_params
from .bridge import Error, Params, Registry, uuid_id
from .dispatch import Dispatch, Forwarded
from .live import Live
from .migration import message
from .model import Refused
from .process import Programs

START_WAIT = 120.0
STOP_WAIT = 90.0
ENDED = {"completed", "failed", "cancelled", "interrupted", "saved", "none"}


async def stop_params(params: Params) -> Params:
    return {"exchange": uuid_id(params.get("exchange"))}


class Controls:
    def __init__(self, programs: Programs, dispatch: Dispatch, live: Live, registry: Registry,
                 *, start_wait: float = START_WAIT, stop_wait: float = STOP_WAIT) -> None:
        self.programs, self.dispatch, self.live = programs, dispatch, live
        self.start_wait, self.stop_wait = start_wait, stop_wait
        self.answers = Answers(live.folders)
        self.tasks: dict[str, asyncio.Task[Params | Error]] = {}
        registry.method("exchange.stop", self.stop, stop_params)
        registry.method("exchange.answer", self.answers.write, answer_params)

    async def notice(self, exchange: str) -> None:
        chat = ""
        try:
            async with self.live.chats.reader.session() as (session, _):
                rows = await session.execute("SELECT chat_id,state FROM exchanges WHERE id=%s", [exchange])
            if rows:
                if rows[0][1] != "open":
                    self.live.stopping.pop(exchange, None)
                    return
                chat = str(rows[0][0])
        except Refused:
            pass  # An unavailable database must not prevent a stop.
        try:
            record = self.live.folders.read(exchange)
            if record.end is not None:
                self.live.stopping.pop(exchange, None)
                return
            chat = record.chat
        except (OSError, Refused):
            pass
        entry = self.dispatch.entries.get(exchange)
        if not chat and entry is not None:
            chat = entry.chat
        if chat:
            self.live.mark_stopping(exchange, chat)

    def result(self, value: Any, exchange: str) -> Params:
        if not isinstance(value, dict):
            raise Error("no_answer")
        if "error" in value:
            error = value["error"]
            if (not isinstance(error, dict) or not isinstance(error.get("code"), str)
                    or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error["code"])
                    or not isinstance(error.get("message"), str)):
                raise Error("no_answer")
            secret = (self.live.chats.database.parameters or {}).get("password", "")
            raise Forwarded(error["code"], "root-manager", message(error["message"], secrets=(secret,),
                fallback="The stop command refused; its diagnostic is not safe to display."))
        if (value.get("root") != self.live.identity.root or value.get("exchange") != exchange
                or not isinstance(value.get("ended"), str) or value["ended"] not in ENDED):
            raise Error("no_answer")
        return {"ended": value["ended"]}

    async def start_done(self, exchange: str) -> None:
        deadline = time.monotonic() + self.start_wait
        while True:
            entry = self.dispatch.entries.get(exchange)
            if ((entry is None or entry.task is None or entry.task.done()) and not self.dispatch.active(exchange)):
                return
            if time.monotonic() >= deadline:
                raise Error("no_answer")
            await asyncio.sleep(min(0.01, max(0, deadline-time.monotonic())))

    async def run(self, exchange: str) -> Params | Error:
        try:
            await self.notice(exchange)
            await self.start_done(exchange)
            await self.notice(exchange)  # A pending start may just have published its row/folder.
            deadline = time.monotonic() + self.stop_wait
            while True:
                self.programs.reap()
                child = self.programs.running.get(("stop", exchange))
                if child is None:
                    break
                if time.monotonic() >= deadline:
                    return Error("no_answer")
                await asyncio.sleep(min(0.01, max(0, deadline-time.monotonic())))
            async with asyncio.timeout(max(0, deadline-time.monotonic())):
                value = await self.programs.call("arbol-root", ["stop", exchange], kind="stop", key=exchange)
            result = self.result(value, exchange)
            if result["ended"] == "none":
                # none confirms no current folder; no inferred completed/cancelled state is emitted.
                self.live.stopping.pop(exchange, None)
            return result
        except TimeoutError:
            return Error("no_answer")
        except Refused as error:
            return error if isinstance(error, Error) else Error(error.code)
        except asyncio.CancelledError:
            raise
        except Exception:
            return Error("no_answer")

    async def stop(self, params: Params) -> Params:
        exchange = params["exchange"]
        task = self.tasks.get(exchange)
        if task is None or task.done():
            task = asyncio.create_task(self.run(exchange))
            self.tasks[exchange] = task
            if len(self.tasks) > 1024:
                for id, previous in list(self.tasks.items()):
                    if id != exchange and previous.done():
                        self.tasks.pop(id)
        result = await asyncio.shield(task)
        if isinstance(result, Error):
            raise result
        return result

    async def close(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
