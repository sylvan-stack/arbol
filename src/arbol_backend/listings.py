"""Shared bounded explicit-Root manager listings, with only public metadata projected."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from typing import Any

from .bridge import Error, Params
from .database import Database
from .dispatch import Forwarded
from .exchange_files import timestamp
from .migration import message
from .model import Refused
from .process import Programs
from .settling import listing
from .validation import text

CAPACITY = 8


class Listings:
    def __init__(self, programs: Programs, database: Database, *, capacity: int = CAPACITY) -> None:
        self.programs, self.database = programs, database
        self.capacity = asyncio.Semaphore(capacity)
        self.closed = False
        self.tasks: dict[str, asyncio.Task[Params | Error]] = {}
        self.started: dict[str, float] = {}
        self.on_rows: Callable[[str, Params], None] | None = None
        self.on_failed: Callable[[str], None] | None = None

    def checked(self, value: Any, root: str) -> Params:
        if isinstance(value, dict) and "error" in value:
            error = value["error"]
            if (not isinstance(error, dict) or not isinstance(error.get("code"), str)
                    or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error["code"])
                    or not isinstance(error.get("message"), str)):
                raise Error("no_answer")
            secret = (self.database.parameters or {}).get("password", "")
            raise Forwarded(error["code"], "root-manager", message(error["message"], secrets=(secret,),
                fallback="The Root manager refused; its diagnostic is not safe to display."))
        rows = listing(value, root)
        result: list[Params] = []
        seen: set[str] = set()
        for row in rows:
            if row["exchange"] in seen:
                raise Error("no_answer")
            seen.add(row["exchange"])
            state, waiting = text(row["state"]), text(row["signsOfLife"]["waitingFor"])
            projected: Params = {key: row[key] for key in ("root", "exchange", "chat", "trunk", "build")}
            projected["state"] = state
            projected["process"] = {key: row["process"][key] for key in ("pid", "startedAt", "alive")}
            projected["signsOfLife"] = {"heartbeat": row["signsOfLife"]["heartbeat"], "waitingFor": waiting,
                                        "since": row["signsOfLife"]["since"]}
            if "end" in row:
                end = row["end"]
                if not isinstance(end, dict):
                    raise Error("no_answer")
                text(end.get("state"))
                timestamp(end.get("at"))
                projected["end"] = {"state": end["state"], "at": end["at"]}
                if "error" in end:
                    error = end["error"]
                    if not isinstance(error, dict):
                        raise Error("no_answer")
                    code = text(error.get("code"))
                    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) or not isinstance(error.get("message"), str):
                        raise Error("no_answer")
                    secret = (self.database.parameters or {}).get("password", "")
                    projected["end"]["error"] = {"code": code, "message": message(error["message"], secrets=(secret,),
                        fallback="The Exchange failed; its diagnostic is not safe to display.")}
            result.append(projected)
        if seen & set(value["unreadable"]):
            raise Error("no_answer")
        return {"exchanges": result, "unreadable": value["unreadable"]}

    async def run(self, root: str) -> Params | Error:
        result: Params | Error
        try:
            reply = await self.programs.call("arbol-root", ["list"], kind="list", root=root)
            result = self.checked(reply, root)
            if self.on_rows:
                self.on_rows(root, result)
            return result
        except Forwarded as error:
            result = error
        except Refused:
            result = Error("no_answer", source="root-manager")
        except asyncio.CancelledError:
            raise
        except Exception:
            result = Error("no_answer", source="root-manager")
        if self.on_failed:
            try:
                self.on_failed(root)
            except Exception:
                pass
        return result

    async def get(self, root: str, *, after: float | None = None) -> Params:
        if self.closed:
            raise Error("ended", source="root-manager")
        task = self.tasks.get(root)
        if task is not None and not task.done() and after is not None and self.started.get(root, 0) < after:
            await asyncio.shield(task)
            return await self.get(root, after=after)
        if task is None or task.done():
            await self.capacity.acquire()
            if self.closed:
                self.capacity.release()
                raise Error("ended", source="root-manager")
            task = self.tasks.get(root)
            if task is not None and not task.done():
                self.capacity.release()
            else:
                self.started[root] = time.monotonic()
                task = asyncio.create_task(self.run(root))
                self.tasks[root] = task
                task.add_done_callback(lambda _: self.capacity.release())
        result = await asyncio.shield(task)
        if isinstance(result, Error):
            raise result
        return result

    def forget(self, roots: set[str]) -> None:
        for root, task in list(self.tasks.items()):
            if root not in roots and task.done():
                self.tasks.pop(root, None)
                self.started.pop(root, None)

    async def close(self) -> None:
        self.closed = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.started.clear()
