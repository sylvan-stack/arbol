"""Exact Draft CAS and conditional send recovery; no contract history writes."""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from .bridge import Error, Params, Registry, uuid_id
from .chat_data import draft
from .chats import Chats
from .validation import integer, text
from .views import View

MAX_TEXT = 1024 * 1024
MAX_REVISION = 9223372036854775807
COLUMNS = "chat_id,folder,text,revision,sent_as,sent_request,updated_at"


def content(value: object, *, message: bool = False) -> str:
    result = text(value, nonempty=message)
    if len(result.encode("utf-8")) > MAX_TEXT:
        raise Error("invalid_input")
    return result


def folder(value: object) -> str:
    result = text(value)
    if not os.path.isabs(result):
        raise Error("invalid_input")
    return os.path.normpath(result)


async def scope(params: Params) -> Params:
    if ("chat" in params) == ("folder" in params):
        raise Error("invalid_input")
    return {"chat": uuid_id(params["chat"])} if "chat" in params else {"folder": folder(params["folder"])}


async def save_params(params: Params) -> Params:
    result = await scope(params)
    if "baseRevision" not in params:
        raise Error("invalid_input")
    base = params["baseRevision"]
    return {**result, "text": content(params.get("text")),
            "baseRevision": None if base is None else integer(base, 1, MAX_REVISION)}


def column(params: Params) -> str:
    return "chat_id" if "chat" in params else "folder"


def value(params: Params) -> str:
    return str(params["chat"] if "chat" in params else params["folder"])


class Conflict(Error):
    def __init__(self, current: Params | None) -> None:
        super().__init__("draft_conflict")
        self.current = current

    def wire(self) -> Params:
        return {**super().wire(), "draft": self.current}


class Drafts:
    def __init__(self, chats: Chats, registry: Registry) -> None:
        self.chats, self.database = chats, chats.database
        self.view = View(self.load, self.publish, scope)
        chats.extra_views["draft"] = self.view
        registry.topics["draft"] = self.view.topic
        registry.method("draft.get", self.get, scope)
        registry.method("draft.save", self.save, save_params)
        chats.chat_view.loader = self.chat
        chats.list_view.loader = self.summaries

    def publish(self, old: Params | None, new: Params, params: Params) -> None:
        if old is not None and old != new:
            self.view.topic.publish({"kind": "draft", "draft": new["draft"]}, params=params)

    def invalidate(self, params: Params) -> None:
        self.view.invalidate(params)
        if "chat" in params:
            self.chats.invalidate(params["chat"])

    def changed(self, params: Params) -> None:
        self.invalidate(params)
        if any(sub.params == params for sub in self.view.topic.listeners):
            self.chats.task(self.chats.refresh(self.view, params))
        if "chat" in params:
            self.chats.changed(params["chat"])

    async def current(self, params: Params) -> Params | None:
        async with self.chats.reader.session() as (session, layout):
            if not layout.own:
                raise Error("layout_incomplete")
            rows = await session.execute(f"SELECT {COLUMNS} FROM drafts WHERE {column(params)}=%s", [value(params)])
            return draft(rows[0] if rows else None)

    async def reconcile(self, params: Params | None = None) -> None:
        # Observe candidates in one READ ONLY moment; the later write rechecks every identity.
        async with self.chats.reader.session() as (session, layout):
            if not layout.own:
                return
            where = f" AND d.{column(params)}=%s" if params is not None else ""
            rows = await session.execute(
                "SELECT d.chat_id,d.folder,d.revision,d.sent_as,d.sent_request FROM drafts d "
                "JOIN exchanges e ON e.id=d.sent_as "
                "WHERE d.sent_request->>'chat'=e.chat_id::text "
                "AND (d.chat_id IS NULL OR d.chat_id=e.chat_id)" + where,
                [value(params)] if params is not None else None,
            )
        for chat, path, revision, sent, request in rows:
            key = {"chat": str(chat)} if chat is not None else {"folder": path}
            self.invalidate(key)
            try:
                removed = await self.database.execute(
                    "WITH removed AS (DELETE FROM drafts d USING exchanges e WHERE "
                    f"d.{column(key)}=%s AND d.revision=%s AND d.sent_as=%s AND d.sent_request=%s "
                    "AND e.id=d.sent_as AND d.sent_request->>'chat'=e.chat_id::text "
                    "AND (d.chat_id IS NULL OR d.chat_id=e.chat_id) RETURNING e.chat_id) "
                    "INSERT INTO chat_marks(chat_id,ongoing,updated_at) SELECT chat_id,true,clock_timestamp() "
                    "FROM removed ON CONFLICT(chat_id) DO UPDATE SET ongoing=true,updated_at=clock_timestamp() "
                    "RETURNING chat_id", [value(key), revision, sent, Jsonb(request)],
                )
            finally:
                self.invalidate(key)
            if removed:
                self.changed(key)
                for (id,) in removed:
                    self.chats.invalidate(str(id))
                    self.chats.changed(str(id))

    async def load(self, params: Params) -> Params:
        await self.reconcile(params)
        return {"kind": "snapshot", "draft": await self.current(params)}

    async def get(self, params: Params) -> Params | None:
        return (await self.view.snapshot(params)).event["draft"]  # type: ignore[no-any-return]

    async def chat(self, params: Params) -> Params:
        await self.reconcile({"chat": params["chat"]})
        return await self.chats.reader.chat(params)

    async def summaries(self, params: Params) -> Params:
        await self.reconcile()
        return await self.chats.reader.summaries(params)

    async def save(self, params: Params) -> Params:
        key = await scope(params)
        await self.chats.own_layout()
        base, body = params["baseRevision"], params["text"]
        self.invalidate(key)
        try:
            if body == "":
                if base is None:
                    if current := await self.current(key):
                        raise Conflict(current)
                    return {"removed": True}
                rows = await self.database.execute(
                    f"DELETE FROM drafts WHERE {column(key)}=%s AND revision=%s RETURNING revision", [value(key), base])
            elif base is None:
                select = "SELECT %s,id,NULL,%s,nextval('drafts_revision'),clock_timestamp() FROM chats WHERE id=%s" if "chat" in key else (
                    "VALUES(%s,NULL,%s,%s,nextval('drafts_revision'),clock_timestamp())")
                args: list[Any] = [uuid4(), body, key["chat"]] if "chat" in key else [uuid4(), key["folder"], body]
                rows = await self.database.execute(
                    "INSERT INTO drafts(id,chat_id,folder,text,revision,updated_at) " + select +
                    f" ON CONFLICT({column(key)}) DO NOTHING RETURNING revision", args)
                if not rows and "chat" in key and await self.current(key) is None:
                    raise Error("not_found")
            else:
                rows = await self.database.execute(
                    "UPDATE drafts SET text=%s,revision=nextval('drafts_revision'),sent_as=NULL,sent_request=NULL,"
                    f"updated_at=clock_timestamp() WHERE {column(key)}=%s AND revision=%s RETURNING revision",
                    [body, value(key), base])
            if not rows:
                raise Conflict(await self.current(key))
        finally:
            self.changed(key)
        return {"removed": True} if body == "" else {"revision": int(rows[0][0])}

    async def accepted(self, exchange: str, chat: str) -> bool:
        rows = await self.database.execute("SELECT chat_id FROM exchanges WHERE id=%s", [exchange])
        if rows and str(rows[0][0]) != chat:
            raise Error("invalid_input")
        return bool(rows)

    async def mark(self, params: Params, *, repeated: bool = False) -> Params | None:
        selected = params.get("draft")
        if selected is None:
            return None
        key = {"folder": selected["folder"]} if "folder" in selected else {"chat": params["chat"]}
        # A known acceptance must remain replayable after the original Draft is gone/newer.
        if repeated or await self.accepted(params["exchange"], params["chat"]):
            return None
        await self.chats.own_layout()
        request = {name: params[name] for name in ("chat", "route", "workingFolder")}
        if "folder" in key:
            if key["folder"] != params["workingFolder"]:
                raise Error("invalid_input")
            if await self.database.execute("SELECT id FROM chats WHERE id=%s", [params["chat"]]):
                raise Error("invalid_input")
        self.invalidate(key)
        try:
            rows = await self.database.execute(
                "UPDATE drafts SET sent_as=%s,sent_request=%s "
                f"WHERE {column(key)}=%s AND revision=%s AND text=%s "
                "AND (sent_as IS NULL OR (sent_as=%s AND sent_request=%s)) RETURNING revision",
                [params["exchange"], Jsonb(request), value(key), selected["revision"], params["message"],
                 params["exchange"], Jsonb(request)])
            if not rows:
                raise Conflict(await self.current(key))
        finally:
            self.changed(key)
        return {**key, "revision": selected["revision"], "request": request}

    async def finish(self, params: Params, marked: Params | None, *, accepted: bool) -> None:
        if accepted:
            # Recovery also handles rows marked by an earlier backend, with its original revision.
            selected = params.get("draft", {})
            key = ({"folder": selected["folder"]} if "folder" in selected else {"chat": params["chat"]})
            await self.reconcile(key)
            await self.chats.mark({"chat": params["chat"], "ongoing": True})
        elif marked is not None:
            key = await scope(marked)
            self.invalidate(key)
            try:
                await self.database.execute(
                    "UPDATE drafts SET sent_as=NULL,sent_request=NULL "
                    f"WHERE {column(key)}=%s AND revision=%s AND sent_as=%s AND sent_request=%s",
                    [value(key), marked["revision"], params["exchange"], Jsonb(marked["request"])])
            finally:
                self.changed(key)
