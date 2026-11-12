"""Shared, bounded installation inventory with safe public metadata."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from typing import Any

from .bridge import Error, Params, uuid_id
from .database import Database
from .dispatch import Forwarded
from .exchange_files import timestamp
from .migration import message
from .model import BUILD_ID
from .process import Programs
from .validation import integer, text


class Listings:
    """One coalesced inventory for the Bridge, live events, settlement and stuck detection."""

    def __init__(self, programs: Programs, database: Database) -> None:
        self.programs, self.database = programs, database
        self.closed = False
        self.task: asyncio.Task[Params | Error] | None = None
        self.started = 0.0
        self.on_rows: Callable[[Params], None] | None = None
        self.on_failed: Callable[[], None] | None = None

    def checked(self, value: Any) -> Params:
        if not isinstance(value, dict) or "root" in value:
            raise Error("no_answer", source="runtime")
        if "error" in value:
            error = value["error"]
            if (not isinstance(error, dict) or not isinstance(error.get("code"), str)
                    or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error["code"])
                    or not isinstance(error.get("message"), str)):
                raise Error("no_answer", source="runtime")
            secret = (self.database.parameters or {}).get("password", "")
            code = "schema_incompatible" if error["code"] == "schema_invalid" else error["code"]
            raise Forwarded(code, "runtime", message(error["message"], secrets=(secret,),
                fallback="The Exchange runtime refused; its diagnostic is not safe to display."))
        rows, raw_unreadable = value.get("exchanges"), value.get("unreadable")
        if not isinstance(rows, list) or not isinstance(raw_unreadable, list):
            raise Error("no_answer", source="runtime")
        unreadable = [uuid_id(id) for id in raw_unreadable]
        if len(unreadable) != len(set(unreadable)):
            raise Error("no_answer", source="runtime")
        result: list[Params] = []
        seen = set(unreadable)
        for row in rows:
            if (not isinstance(row, dict) or "root" in row or type(row.get("exchangeFormat")) is not int
                    or row["exchangeFormat"] != 1 or not isinstance(row.get("process"), dict)
                    or not isinstance(row.get("signsOfLife"), dict)):
                raise Error("no_answer", source="runtime")
            exchange, chat = uuid_id(row.get("exchange")), uuid_id(row.get("chat"))
            if exchange in seen:
                raise Error("no_answer", source="runtime")
            seen.add(exchange)
            state, trunk, build = text(row.get("state")), text(row.get("trunk")), text(row.get("build"))
            if not re.fullmatch(r"[a-z][a-z0-9]{0,31}", trunk) or (build != "0" and not BUILD_ID.fullmatch(build)):
                raise Error("no_answer", source="runtime")
            process, life = row["process"], row["signsOfLife"]
            pid = integer(process.get("pid"), 1, 2147483647)
            if type(process.get("alive")) is not bool:
                raise Error("no_answer", source="runtime")
            timestamp(process.get("startedAt"))
            timestamp(life.get("since"))
            heartbeat = integer(life.get("heartbeat"), 0, 9223372036854775807)
            projected: Params = {"exchange": exchange, "chat": chat, "trunk": trunk, "build": build,
                                 "state": state, "exchangeFormat": 1,
                                 "process": {"pid": pid, "startedAt": process["startedAt"], "alive": process["alive"]},
                                 "signsOfLife": {"heartbeat": heartbeat, "waitingFor": text(life.get("waitingFor")),
                                                 "since": life["since"]}}
            if "end" in row:
                end = row["end"]
                if not isinstance(end, dict):
                    raise Error("no_answer", source="runtime")
                text(end.get("state"))
                timestamp(end.get("at"))
                projected["end"] = {"state": end["state"], "at": end["at"]}
                if "error" in end:
                    error = end["error"]
                    if not isinstance(error, dict):
                        raise Error("no_answer", source="runtime")
                    code = text(error.get("code"))
                    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) or not isinstance(error.get("message"), str):
                        raise Error("no_answer", source="runtime")
                    secret = (self.database.parameters or {}).get("password", "")
                    projected["end"]["error"] = {"code": code, "message": message(error["message"], secrets=(secret,),
                        fallback="The Exchange failed; its diagnostic is not safe to display.")}
            result.append(projected)
        return {"exchanges": result, "unreadable": unreadable}

    async def run(self) -> Params | Error:
        result: Params | Error
        try:
            reply = await self.programs.call("arbol-exchanges", ["list"], kind="list")
            result = self.checked(reply)
            if self.on_rows:
                self.on_rows(result)
            return result
        except Forwarded as error:
            result = error
        except asyncio.CancelledError:
            raise
        except Exception:
            result = Error("no_answer", source="runtime")
        if self.on_failed:
            self.on_failed()
        return result

    async def get(self, *, after: float | None = None) -> Params:
        while not self.closed:
            task = self.task
            if task is None or task.done():
                self.started = time.monotonic()
                task = self.task = asyncio.create_task(self.run())
            started = self.started
            result = await asyncio.shield(task)
            if after is not None and started < after:
                continue  # A proof for force-stop must start after the caller requested it.
            if isinstance(result, Error):
                raise result
            return result
        raise Error("ended", source="runtime")

    async def close(self) -> None:
        self.closed = True
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
