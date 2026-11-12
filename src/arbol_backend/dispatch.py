"""Shared bounded starts, idempotent identifiers and conditional Draft completion."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bridge import SOURCES, Error, Params, Registry, uuid_id
from .chats import Chats
from .database import protected_thread
from .drafts import MAX_REVISION, Drafts, content, folder
from .migration import message
from .model import BUILD_ID, Identity, Refused, Settings
from .process import Programs
from .requests import Request, Requests
from .validation import integer

RETRY_SECONDS = 15.0
TOTAL_SECONDS = 120.0
RUNTIME_CODES = {"unknown_trunk", "no_fit", "schema_invalid", "schema_incompatible", "schema_uninitialized",
                 "database_unavailable", "maintenance", "trunk_unavailable"}
UNCERTAIN = {"no_answer", "in_progress"}


def selected_trunk(params: Params) -> Params:
    code = params.get("trunk", "trivial")
    if (not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9]{0,31}", code)
            or code in ("run", "settle", "list")):
        raise Error("invalid_input")
    return {} if code == "trivial" else {"trunk": code}


class Forwarded(Error):
    def __init__(self, code: str, source: str, explanation: str) -> None:
        super().__init__(code, source=source)
        self.args = (explanation,)


@dataclass
class Entry:
    fingerprint: str
    chat: str = ""
    task: asyncio.Task[Params | Error] | None = None
    request: Request | None = None
    marked: Params | None = None
    dispatched: bool = False
    uncertain: bool = False
    reply_known: bool = False
    receipt: Params | None = None


class Dispatch:
    def __init__(self, identity: Identity, programs: Programs, chats: Chats, drafts: Drafts,
                 registry: Registry, settings: Settings, *, retry: float = RETRY_SECONDS,
                 total: float = TOTAL_SECONDS) -> None:
        self.identity, self.programs, self.chats, self.drafts = identity, programs, chats, drafts
        self.settings, self.retry, self.total = settings, retry, total
        self.files = Requests(identity)
        self.entries: dict[str, Entry] = {}
        self.startup: asyncio.Task[None] | None = None
        self.maintenance: asyncio.Task[None] | None = None
        registry.method("chat.send", self.send, self.send_params)
        registry.method("exchange.sendAgain", self.send, self.again_params)

    async def send_params(self, params: Params) -> Params:
        result: Params = {"chat": uuid_id(params.get("chat")), "exchange": uuid_id(params.get("exchange")),
                          "message": content(params.get("message"), message=True),
                          "workingFolder": folder(params.get("workingFolder"))}
        if not Path(result["workingFolder"]).is_dir():
            raise Error("invalid_input")
        if "draft" in params:
            selected = params["draft"]
            if not isinstance(selected, dict):
                raise Error("invalid_input")
            result["draft"] = {"revision": integer(selected.get("revision"), 1, MAX_REVISION)}
            if "folder" in selected:
                result["draft"]["folder"] = folder(selected["folder"])
                if result["draft"]["folder"] != result["workingFolder"]:
                    raise Error("invalid_input")
        result.update(selected_trunk(params))
        result["route"] = await self.chats.catalogues.route(params.get("route"))
        return result

    async def again_params(self, params: Params) -> Params:
        previous, exchange = uuid_id(params.get("exchange")), uuid_id(params.get("newExchange"))
        if previous == exchange:
            raise Error("invalid_input")
        trunk = selected_trunk(params)
        route = await self.chats.catalogues.route(params.get("route"))
        async with self.chats.reader.session() as (session, _):
            rows = await session.execute("SELECT chat_id,working_folder FROM exchanges WHERE id=%s", [previous])
        if not rows:
            raise Error("not_found")
        path = folder(rows[0][1])
        if not Path(path).is_dir():
            raise Error("invalid_input")
        return {"chat": uuid_id(str(rows[0][0])), "exchange": exchange, "replaces": previous,
                "route": route, "workingFolder": path, **trunk}

    def active(self, exchange: str) -> bool:
        child = self.programs.running.get(("start", exchange))
        return child is not None and child.process.poll() is None

    def cleanup(self, exchange: str, entry: Entry) -> None:
        if entry.reply_known and entry.request is not None and not self.active(exchange):
            try:
                entry.request.remove()
            except OSError:
                pass  # Startup can recover an owned request after a filesystem failure.
            entry.request = None

    async def clean_startup(self) -> None:
        try:
            async with self.chats.database.permit():
                await protected_thread(self.files.clean)
        except (OSError, Refused):
            pass  # Ready remains available; a send reports inaccessible storage safely.

    async def maintain(self) -> None:
        while True:
            for exchange, entry in list(self.entries.items()):
                if entry.task is not None and entry.task.done():
                    if entry.reply_known and entry.request is not None and not self.active(exchange):
                        try:
                            async with self.chats.database.permit():
                                self.cleanup(exchange, entry)
                        except Refused:
                            pass
                    if len(self.entries) > 1024 and not self.active(exchange):
                        if entry.request is not None:
                            os.close(entry.request.folder)  # Leave uncertain requests for an exact retry.
                            entry.request = None
                        self.entries.pop(exchange, None)
            await asyncio.sleep(0.1)

    def start(self) -> None:
        if self.startup is None:
            self.startup = asyncio.create_task(self.clean_startup())
            self.maintenance = asyncio.create_task(self.maintain())

    async def send(self, params: Params) -> Params:
        self.start()
        assert self.startup is not None
        await asyncio.shield(self.startup)
        fingerprint = hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False,
                                               separators=(",", ":")).encode("utf-8")).hexdigest()
        exchange = params["exchange"]
        entry = self.entries.get(exchange)
        if entry is None:
            entry = Entry(fingerprint, chat=params["chat"])
            self.entries[exchange] = entry
        elif fingerprint != entry.fingerprint:
            raise Error("invalid_input")
        if entry.receipt is not None:
            return {**entry.receipt, "duplicate": True}
        if entry.task is None or entry.task.done():
            entry.task = asyncio.create_task(self.run(params, entry))
        result = await asyncio.shield(entry.task)
        if isinstance(result, Error):
            raise result
        return result

    def result(self, value: Any, params: Params) -> Params:
        if not isinstance(value, dict):
            raise Error("no_answer")
        if "error" in value:
            error = value["error"]
            if (not isinstance(error, dict) or not isinstance(error.get("code"), str)
                    or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error["code"])
                    or not isinstance(error.get("message"), str)):
                raise Error("no_answer")
            code = error["code"]
            source = error.get("source", "runtime" if code in RUNTIME_CODES else "trunk")
            if code == "schema_invalid":
                code = "schema_incompatible"
            if not isinstance(source, str) or source not in SOURCES:
                raise Error("no_answer")
            secret = (self.chats.database.parameters or {}).get("password", "")
            explanation = message(error["message"], secrets=(secret,),
                                  fallback="The start command refused the message; its diagnostic is not safe to display.")
            raise Forwarded(code, source, explanation)
        try:
            if (value.get("accepted") is not True or type(value.get("duplicate")) is not bool
                    or uuid_id(value.get("exchange")) != params["exchange"]
                    or uuid_id(value.get("chat")) != params["chat"]
                    or "root" in value):
                raise Error("no_answer")
            trunk, build = value.get("trunk"), value.get("build")
            if (not isinstance(trunk, str) or not re.fullmatch(r"[a-z][a-z0-9]{0,31}", trunk)
                    or not isinstance(build, str) or (build != "0" and not BUILD_ID.fullmatch(build))
                    or not value["duplicate"] and trunk != params.get("trunk", "trivial")):
                raise Error("no_answer")
            number = integer(value.get("number"), 1, 2147483647)
        except Refused as error:
            raise Error("no_answer") from error
        return {"accepted": True, "duplicate": value["duplicate"], "exchange": params["exchange"],
                "chat": params["chat"], "number": number, "trunk": trunk, "build": build}

    async def run(self, params: Params, entry: Entry) -> Params | Error:
        try:
            async with self.chats.database.permit():
                return await self.dispatch(params, entry)
        except Refused as error:
            return error if isinstance(error, Error) else Error(error.code)

    async def dispatch(self, params: Params, entry: Entry) -> Params | Error:
        exchange = params["exchange"]
        try:
            await self.drafts.accepted(exchange, params["chat"])
            if entry.marked is None:
                entry.marked = await self.drafts.mark(params, repeated=entry.dispatched)
            request = {name: params[name] for name in ("chat", "route", "workingFolder")}
            if "message" in params:
                request["message"] = params["message"]
            if self.settings.small_call_route is not None:
                request["smallCallRoute"] = self.settings.small_call_route
            deadline = time.monotonic() + self.total
            next_attempt = time.monotonic()
            while time.monotonic() < deadline:
                if self.active(exchange) or time.monotonic() < next_attempt:
                    await asyncio.sleep(min(0.01, max(0, deadline - time.monotonic())))
                    continue
                self.cleanup(exchange, entry)
                if entry.request is not None:
                    # Revalidate the same pathname before retry, without removing uncertain recovery input.
                    os.close(entry.request.folder)
                    entry.request = None
                entry.reply_known = False
                try:
                    entry.request = self.files.write(exchange, request)
                except Refused:
                    if not entry.dispatched:
                        await self.drafts.finish(params, entry.marked, accepted=False)
                        entry.marked = None
                    raise
                args = ["start"]
                if "trunk" in params:
                    args.append(params["trunk"])
                args += ["--exchange", exchange, "--request", entry.request.path]
                if "replaces" in params:
                    args += ["--replaces", params["replaces"]]
                entry.dispatched = True
                try:
                    async with asyncio.timeout(max(0, deadline - time.monotonic())):
                        reply = await self.programs.call("arbol-exchanges", args, kind="start", key=exchange)
                    result = self.result(reply, params)
                    entry.receipt, entry.reply_known = result, True
                except TimeoutError:
                    entry.uncertain = True
                    return Error("no_answer")
                except Refused as error:
                    if error.code not in UNCERTAIN:
                        if not entry.uncertain:
                            entry.reply_known = True
                            try:
                                await self.drafts.finish(params, entry.marked, accepted=False)
                            except Refused:
                                pass  # The saved mark remains recoverable when the DB is unavailable.
                            entry.dispatched, entry.marked = False, None
                        return error if isinstance(error, Error) else Error(error.code)
                    entry.uncertain = True
                    next_attempt = time.monotonic() + self.retry
                    continue
                finally:
                    self.cleanup(exchange, entry)
                try:
                    await self.drafts.finish(params, entry.marked, accepted=True)
                except Refused:
                    pass  # A known acceptance is never changed into a refusal by local cleanup failure.
                return result
            return Error("no_answer")
        except Refused as error:
            return error if isinstance(error, Error) else Error(error.code)
        except asyncio.CancelledError:
            raise
        except Exception:
            return Error("no_answer")
        finally:
            self.cleanup(exchange, entry)

    async def close(self) -> None:
        tasks: list[asyncio.Task[Any]] = [entry.task for entry in self.entries.values() if entry.task is not None]
        tasks += [task for task in (self.startup, self.maintenance) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for entry in self.entries.values():
            if entry.request is not None:
                # Preserve unresolved requests and release our descriptor without a write.
                os.close(entry.request.folder)
                entry.request = None
        self.entries.clear()
