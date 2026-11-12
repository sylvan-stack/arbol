"""Bounded UUID stops and current-form answers for the installation."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
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
class ForceCancelled(Error):
    """Internal proof cancellation, distinct from a manager's future refusal code."""

    def __init__(self) -> None:
        super().__init__("not_stuck")


Guard = Callable[[], Awaitable[bool]]
ENDED = {"completed", "failed", "cancelled", "interrupted", "saved", "none"}


async def stop_params(params: Params) -> Params:
    if "root" in params:
        raise Error("invalid_input")
    return {"exchange": uuid_id(params.get("exchange"))}


class Controls:
    def __init__(self, programs: Programs, dispatch: Dispatch, live: Live, registry: Registry,
                 *, start_wait: float = START_WAIT, stop_wait: float = STOP_WAIT) -> None:
        self.programs, self.dispatch, self.live = programs, dispatch, live
        self.start_wait, self.stop_wait = start_wait, stop_wait
        self.answers = Answers(live.folders)
        self.tasks: dict[str, asyncio.Task[Params | Error]] = {}
        self.force_tasks: dict[str, asyncio.Task[Params | Error]] = {}
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
            code = "schema_incompatible" if error["code"] == "schema_invalid" else error["code"]
            raise Forwarded(code, "runtime", message(error["message"], secrets=(secret,),
                fallback="The stop command refused; its diagnostic is not safe to display."))
        if ("root" in value or value.get("exchange") != exchange or type(value.get("forced")) is not bool
                or not isinstance(value.get("ended"), str) or value["ended"] not in ENDED):
            raise Error("no_answer")
        result: Params = {"ended": value["ended"], "forced": value["forced"]}
        if "settling" in value:
            settling = value["settling"]
            if not isinstance(settling, dict):
                raise Error("no_answer")
            state = settling.get("settled")
            if isinstance(state, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", state):
                result["settling"] = {"settled": state}
            elif isinstance(error := settling.get("error"), dict):
                code = error.get("code")
                if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
                    raise Error("no_answer")
                secret = (self.live.chats.database.parameters or {}).get("password", "")
                result["settling"] = {"error": Forwarded(code, "runtime", message(error.get("message"),
                    secrets=(secret,), fallback="The runtime could not confirm settlement.")).wire()}
            else:
                raise Error("no_answer")
        return result

    async def start_done(self, exchange: str) -> None:
        deadline = time.monotonic() + self.start_wait
        while True:
            entry = self.dispatch.entries.get(exchange)
            if ((entry is None or entry.task is None or entry.task.done()) and not self.dispatch.active(exchange)):
                return
            if time.monotonic() >= deadline:
                raise Error("no_answer")
            await asyncio.sleep(min(0.01, max(0, deadline-time.monotonic())))

    async def run(self, exchange: str, *, force: bool = False, before: Guard | None = None, chat: str = "") -> Params | Error:
        try:
            if not force:
                await self.notice(exchange)
            await self.start_done(exchange)
            if not force:
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
                if before is not None and not await before():
                    return ForceCancelled()  # Internal cancellation, never an invented end reply.
                if force and chat:
                    self.live.mark_stopping(exchange, chat)
                args = ["stop", exchange, *(["--force"] if force else [])]
                value = await self.programs.call("arbol-exchanges", args, kind="stop", key=exchange)
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
        key = exchange
        forced = self.force_tasks.get(key)
        if forced is not None and not forced.done():
            result = await asyncio.shield(forced)
            if not isinstance(result, ForceCancelled):
                if isinstance(result, Error):
                    raise result
                return result
        task = self.tasks.get(key)
        if task is None or task.done():
            task = asyncio.create_task(self.run(exchange))
            self.tasks[key] = task
            if len(self.tasks) > 1024:
                for id, previous in list(self.tasks.items()):
                    if id != key and previous.done():
                        self.tasks.pop(id)
        result = await asyncio.shield(task)
        if isinstance(result, Error):
            raise result
        return result

    async def run_force(self, exchange: str, chat: str, before: Guard) -> Params | Error:
        key = exchange
        previous = self.tasks.get(key)
        if previous is not None and not previous.done():
            result = await asyncio.shield(previous)
            if not isinstance(result, Error):
                return ForceCancelled()  # The pending manual stop confirmed an end; it was not our force.
        return await self.run(exchange, force=True, before=before, chat=chat)

    async def force(self, exchange: str, chat: str, before: Guard) -> Params:
        key = exchange
        task = self.force_tasks.get(key)
        if task is None or task.done():
            task = asyncio.create_task(self.run_force(exchange, chat, before))
            self.force_tasks[key] = task
            if len(self.force_tasks) > 1024:
                for id, previous in list(self.force_tasks.items()):
                    if id != key and previous.done():
                        self.force_tasks.pop(id)
        result = await asyncio.shield(task)
        if isinstance(result, Error):
            raise result
        return result

    async def close(self) -> None:
        tasks = [*self.tasks.values(), *self.force_tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.force_tasks.clear()
