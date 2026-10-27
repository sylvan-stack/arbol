"""Delegate lineage work to the own Root's supported global command; never open its source DB."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

from .bridge import Error, Params, Registry, uuid_id
from .chats import Chats
from .model import BUILD_ID, ROOT_ID, Identity, Refused
from .process import Programs
from .validation import chat


class Forwarded(Error):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, source="roots")
        self.args = (message,)


def message(value: Any, *, secrets: tuple[str, ...] = ()) -> str:
    fallback = "The Root migration command could not confirm the operation; refresh before trying it explicitly again."
    if not isinstance(value, str) or not value.strip():
        return fallback
    if any(secret and secret in value for secret in secrets):
        return fallback
    try:
        if len(value.encode("utf-8")) > 1024:
            return fallback
    except UnicodeError:
        return fallback
    if re.search(r"\b(password|token|secret|api[-_ ]?key|jev[-_ ]?key|authorization|bearer)\b", value, re.I):
        return fallback
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        return fallback
    return value


class Migration:
    def __init__(self, identity: Identity, programs: Programs, chats: Chats, registry: Registry, record: Params) -> None:
        self.identity, self.programs, self.chats = identity, programs, chats
        self.from_root = record.get("grewFrom")
        if self.from_root is not None and (not isinstance(self.from_root, str) or not ROOT_ID.fullmatch(self.from_root)
                                           or self.from_root == identity.root):
            raise Error("invalid_input")
        self.state = record["status"]
        self.check_task: asyncio.Task[Error | None] | None = None
        self.imports: dict[str, asyncio.Task[Params | Error]] = {}
        registry.method("chat.reimport", self.reimport, chat)
        chats.on_list_open = self.start_check

    def start_check(self) -> None:
        state = (self.chats.roots.current or {}).get("status", self.state)
        if self.from_root is None or state not in ("working", "failed"):
            return
        if self.check_task is not None and not self.check_task.done():
            return
        running = self.programs.running.get(("migrate-check", self.identity.root))
        if running is not None and running.process.poll() is None:
            return
        self.check_task = asyncio.create_task(self.check())

    def result(self, value: Any, mode: str, target: str | None = None, original: str | None = None) -> Params:
        if not isinstance(value, dict):
            raise Error("no_answer", source="roots")
        if "error" in value:
            error = value["error"]
            if not isinstance(error, dict) or not isinstance(error.get("code"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error["code"]):
                raise Error("no_answer", source="roots")
            password = (self.chats.database.parameters or {}).get("password", "")
            raise Forwarded(error["code"], message(error.get("message"), secrets=(password,)))
        if (value.get("root") != self.identity.root or value.get("fromRoot") != self.from_root
                or value.get("mode") != mode or not isinstance(value.get("rootBuild"), str)
                or not BUILD_ID.fullmatch(value["rootBuild"])):
            raise Error("no_answer", source="roots")
        if mode == "check":
            stale = value.get("stale")
            checked = value.get("checked")
            if (type(checked) is not int or checked < 0 or not isinstance(stale, list)
                    or len(stale) > checked or any(not isinstance(item, str) for item in stale)):
                raise Error("no_answer", source="roots")
            try:
                for id in stale:
                    uuid_id(id)
            except Refused as error:
                raise Error("no_answer", source="roots") from error
            if len(set(stale)) != len(stale):
                raise Error("no_answer", source="roots")
        else:
            if value.get("chat") != target or value.get("action") not in ("replaced", "copied"):
                raise Error("no_answer", source="roots")
            try:
                result_chat, from_chat = uuid_id(value.get("resultChat")), uuid_id(value.get("fromChat"))
                at = value.get("snapshotAt")
                if not isinstance(at, str) or datetime.fromisoformat(at).tzinfo is None:
                    raise ValueError("Missing snapshot time.")
            except (ValueError, Refused) as error:
                raise Error("no_answer", source="roots") from error
            if ((value["action"] == "replaced") != (result_chat == target) or from_chat != original
                    or type(value.get("endedThrough")) is not int or value["endedThrough"] < 0):
                raise Error("no_answer", source="roots")
        return value

    def changed(self) -> None:
        self.chats.invalidate()
        if self.chats.list_view.topic.listeners:
            self.chats.task(self.chats.refresh(self.chats.list_view, {}))
        params = {self.chats.chat_view.key(sub.params): sub.params for sub in self.chats.chat_view.topic.listeners}
        for value in params.values():
            self.chats.task(self.chats.refresh(self.chats.chat_view, value))

    async def check(self) -> Error | None:
        try:
            if not await self.chats.reader.complete():
                return Error("layout_incomplete")
            value = await self.programs.call("arbol-roots", ["migrate", self.identity.root, "--check"],
                                             kind="migrate-check")
            self.result(value, "check")
            self.chats.attention.close("migration_unavailable")
            self.changed()
            return None
        except Refused as error:
            safe = error if isinstance(error, Error) else Error("no_answer", source="roots")
            self.chats.attention.open("migration_unavailable", message(str(safe)))
            return safe
        except Exception:
            safe = Error("no_answer", source="roots")
            self.chats.attention.open("migration_unavailable", str(safe))
            return safe

    async def import_one(self, target: str) -> Params | Error:
        try:
            if self.from_root is None:
                raise Error("invalid_input")
            async with self.chats.reader.session() as (session, layout):
                if not layout.complete:
                    raise Error("layout_incomplete")
                rows = await session.execute("SELECT from_root,from_chat FROM migrated_chats WHERE chat_id=%s", [target])
                if not rows or rows[0][0] != self.from_root:
                    raise Error("not_found")
                original = uuid_id(str(rows[0][1]))
            self.chats.invalidate(target)
            try:
                value = await self.programs.call("arbol-roots", ["migrate", self.identity.root, "--chat", target],
                                                 kind="reimport")
            finally:
                self.chats.invalidate(target)
            value = self.result(value, "chat", target, original)
            self.changed()
            return {"chat": value["resultChat"], "previousChat": target, "action": value["action"],
                    "fromRoot": value["fromRoot"], "fromChat": value["fromChat"]}
        except Refused as error:
            return error if isinstance(error, Error) else Error("no_answer", source="roots")
        except Exception:
            return Error("no_answer", source="roots")

    async def reimport(self, params: Params) -> Params:
        target = params["chat"]
        task = self.imports.get(target)
        if task is None or task.done():
            task = asyncio.create_task(self.import_one(target))
            self.imports[target] = task
        result = await asyncio.shield(task)
        if isinstance(result, Error):
            raise result
        return result

    async def close(self) -> None:
        tasks = [*self.imports.values(), *([self.check_task] if self.check_task else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.imports.clear()
