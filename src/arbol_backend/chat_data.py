"""Read contract-v1 chats using own SQL and one consistent read-only snapshot."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from .bridge import Error, Params, uuid_id
from .database import Database, Session
from .metadata import Attention, Layout, inspect, iso
from .model import ROOT_ID

TOOL_BYTES = 8192


def route(value: Any) -> Params:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in ("driver", "subscription", "model", "effort")
            if isinstance(value.get(key), str)}


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def preview(value: Any) -> tuple[Any, bool]:
    raw = encoded(value)
    if len(raw) <= TOOL_BYTES:
        return value, False
    candidate = raw[:TOOL_BYTES].decode("utf-8", errors="ignore")
    low, high = 0, len(candidate)
    while low < high:
        middle = (low + high + 1) // 2
        if len(encoded(candidate[:middle])) <= TOOL_BYTES:
            low = middle
        else:
            high = middle - 1
    return candidate[:low], True


def metadata(value: Any) -> Any:
    """Drop credential fields from producer metadata; transcript/tool payloads are untouched."""
    if isinstance(value, dict):
        secret_names = {"key", "apikey", "jevkey", "password", "authorization", "accesstoken", "refreshtoken", "secret", "token"}
        return {key: metadata(item) for key, item in value.items()
                if "".join(c for c in key.lower() if c.isalnum()) not in secret_names}
    if isinstance(value, list):
        return [metadata(item) for item in value]
    return value


def provenance(root: Any, chat: Any, stale: Any) -> Params | None:
    if root is None:
        return None
    if not isinstance(root, str) or not ROOT_ID.fullmatch(root) or type(stale) is not bool:
        raise Error("layout_incomplete")
    return {"fromRoot": root, "fromChat": uuid_id(str(chat)), "stale": stale}


def draft(row: tuple[Any, ...] | None) -> Params | None:
    if row is None:
        return None
    chat, folder, text, revision, sent, request, updated = row
    result: Params = {"text": text, "revision": int(revision), "updatedAt": iso(updated)}
    result["chat" if chat is not None else "folder"] = str(chat) if chat is not None else folder
    if sent is not None:
        result["sentAs"] = str(sent)
        if isinstance(request, dict):
            # Pending dispatch data has only these public fields, never arbitrary configuration.
            result["sentRequest"] = {"chat": str(request.get("chat", "")), "route": route(request.get("route")),
                                     "workingFolder": request.get("workingFolder", "")}
    return result


class Reader:
    def __init__(self, database: Database, attention: Attention, *, lineage: bool = False) -> None:
        self.database, self.attention, self.lineage = database, attention, lineage

    @asynccontextmanager
    async def session(self) -> AsyncIterator[tuple[Session, Layout]]:
        async with self.database.session(snapshot=True) as session:
            layout = await inspect(session, lineage=self.lineage)
            if layout.complete:
                self.attention.close("layout_incomplete")
            else:
                self.attention.open("layout_incomplete", "The Root lacks required backend or provenance tables; apply its Root layout.")
            yield session, layout

    async def complete(self) -> bool:
        async with self.session() as (_, layout):
            return layout.complete

    async def summaries(self, params: Params) -> Params:
        async with self.session() as (session, layout):
            local = ("EXISTS(SELECT 1 FROM drafts d WHERE d.chat_id=c.id),coalesce(cm.ongoing,false),cm.archived_at"
                     if layout.own else "false,false,NULL::timestamptz")
            migration = "mc.from_root,mc.from_chat,mc.stale" if layout.provenance and self.lineage else "NULL::text,NULL::uuid,NULL::boolean"
            rows = await session.execute(
                "SELECT c.id,c.title,c.created_at,e.id,e.number,e.state,e.error,e.route,e.working_folder,"
                "e.accepted_at,e.ended_at,coalesce((SELECT left(m.text,200) FROM exchanges first "
                "JOIN messages m ON m.exchange_id=first.id AND m.position=0 "
                "WHERE first.chat_id=c.id AND first.replaced_by IS NULL ORDER BY first.number LIMIT 1),''),"
                + local + "," + migration + " FROM chats c "
                "LEFT JOIN LATERAL (SELECT * FROM exchanges WHERE chat_id=c.id AND replaced_by IS NULL "
                "ORDER BY number DESC LIMIT 1) e ON true "
                + ("LEFT JOIN chat_marks cm ON cm.chat_id=c.id " if layout.own else "")
                + ("LEFT JOIN migrated_chats mc ON mc.chat_id=c.id " if layout.provenance and self.lineage else "")
            )
            summaries: list[Params] = []
            for row in rows:
                (chat, title, created, exchange, number, state, error, saved_route, folder, accepted, ended,
                 first, has_draft, ongoing, archived, from_root, from_chat, stale) = row
                activity: datetime = max(accepted, ended) if ended else accepted or created
                value: Params = {"chat": str(chat), "title": title, "firstMessage": first,
                                 "activityAt": iso(activity), "hasDraft": has_draft, "ongoing": ongoing}
                if exchange is not None:
                    value["last"] = {"exchange": str(exchange), "number": number,
                                     "state": "accepting" if state == "open" else state}
                    if error is not None:
                        value["last"]["error"] = metadata(error)
                    value["route"] = route(saved_route)
                    value["workingFolder"] = folder
                if archived is not None:
                    value["archived"] = True
                if migration_info := provenance(from_root, from_chat, stale):
                    value["migration"] = migration_info
                summaries.append(value)
            summaries.sort(key=lambda row: (row["activityAt"], row["chat"]), reverse=True)
            return {"kind": "snapshot", "chats": summaries}

    async def exchanges(self, session: Session, layout: Layout, chat: str,
                        *, before: int | None = None, limit: int = 12) -> tuple[list[Params], bool]:
        rows = await session.execute(
            "SELECT id,number,state,error,route,working_folder,accepted_at,ended_at FROM exchanges "
            "WHERE chat_id=%s AND replaced_by IS NULL AND (%s::integer IS NULL OR number<%s) "
            "ORDER BY number DESC LIMIT %s", [chat, before, before, limit + 1],
        )
        more = len(rows) > limit
        selected = list(reversed(rows[:limit]))
        if not selected:
            return [], more
        ids = [str(row[0]) for row in selected]
        messages = await session.execute(
            "SELECT m.exchange_id,m.position,m.role,m.text FROM messages m JOIN exchanges e ON e.id=m.exchange_id "
            "WHERE m.exchange_id=ANY(%s::uuid[]) AND (e.state<>'open' OR m.position=0) ORDER BY m.position", [ids],
        )
        tools = await session.execute(
            "SELECT t.exchange_id,t.position,t.name,"
            "CASE WHEN octet_length(t.input::text)>8192 THEN to_jsonb(left(t.input::text,8192)) ELSE t.input END,"
            "t.ok,CASE WHEN octet_length(t.result::text)>8192 THEN to_jsonb(left(t.result::text,8192)) ELSE t.result END,"
            "t.error,t.truncated,t.interrupted,t.ask,t.answer,"
            "octet_length(t.input::text)>8192,coalesce(octet_length(t.result::text)>8192,false) "
            "FROM tool_calls t JOIN exchanges e ON e.id=t.exchange_id "
            "WHERE t.exchange_id=ANY(%s::uuid[]) AND t.parent_call_id IS NULL AND e.state<>'open' ORDER BY t.position",
            [ids],
        )
        runs = await session.execute(
            "SELECT exchange_id,kind,outcome,usage,started FROM runs WHERE exchange_id=ANY(%s::uuid[]) "
            "ORDER BY ended_at,run_id", [ids],
        )
        notes = await session.execute(
            "SELECT exchange_id,kind,at FROM exchange_notes WHERE exchange_id=ANY(%s::uuid[])", [ids]
        ) if layout.own else []
        by_id: dict[str, Params] = {}
        result: list[Params] = []
        for id, number, state, error, saved_route, folder, accepted, ended in selected:
            exchange: Params = {"exchange": str(id), "number": number, "state": state, "route": route(saved_route),
                                "workingFolder": folder, "acceptedAt": iso(accepted), "items": [], "runs": []}
            if error is not None:
                exchange["error"] = metadata(error)
            if ended is not None:
                exchange["endedAt"] = iso(ended)
            by_id[str(id)] = exchange
            result.append(exchange)
        for id, position, role, text in messages:
            by_id[str(id)]["items"].append({"position": position, "kind": "message", "role": role, "text": text})
        for id, position, name, input, ok, output, error, truncated, interrupted, ask, answer, sql_input_cut, sql_output_cut in tools:
            cut_input, input_cut = preview(input)
            tool: Params = {"position": position, "kind": "tool", "name": name, "input": cut_input,
                            "ok": ok, "truncated": truncated, "interrupted": interrupted}
            output_cut = False
            if output is not None:
                tool["result"], output_cut = preview(output)
            for key, value in (("error", error), ("ask", ask), ("answer", answer)):
                if value is not None:
                    tool[key] = value
            if input_cut or output_cut or sql_input_cut or sql_output_cut:
                tool["cut"] = True
            by_id[str(id)]["items"].append(tool)
        for id, kind, outcome, usage, started in runs:
            run = {"kind": kind, "outcome": outcome, "usage": metadata(usage)}
            if started is not None:
                run["started"] = metadata(started)
            by_id[str(id)]["runs"].append(run)
        for id, kind, at in notes:
            by_id[str(id)]["note"] = {"exchange": str(id), "kind": kind, "at": iso(at)}
        for exchange in result:
            exchange["items"].sort(key=lambda item: item["position"])
        return result, more

    async def chat(self, params: Params) -> Params:
        chat = params["chat"]
        async with self.session() as (session, layout):
            headers = await session.execute("SELECT title,created_at FROM chats WHERE id=%s", [chat])
            counts = await session.execute(
                "SELECT count(*) FROM exchanges WHERE chat_id=%s AND replaced_by IS NULL", [chat]
            )
            usage = await session.execute(
                "SELECT r.usage FROM runs r JOIN exchanges e ON e.id=r.exchange_id WHERE e.chat_id=%s", [chat]
            )
            totals = {"inputTokens": 0, "outputTokens": 0}
            for (value,) in usage:
                for key in totals:
                    if isinstance(value, dict) and type(value.get(key)) is int and value[key] >= 0:
                        totals[key] += value[key]
            info: Params = {"chat": chat, "title": headers[0][0] if headers else None,
                            "exchangeCount": counts[0][0], "usage": totals}
            if headers:
                info["createdAt"] = iso(headers[0][1])
            if layout.provenance and self.lineage:
                rows = await session.execute("SELECT from_root,from_chat,stale FROM migrated_chats WHERE chat_id=%s", [chat])
                if rows and (migration := provenance(*rows[0])):
                    info["migration"] = migration
            exchanges, more = await self.exchanges(session, layout, chat)
            local: Params = {"draft": None, "settings": {}, "marks": {"ongoing": False}}
            if layout.own:
                rows = await session.execute(
                    "SELECT chat_id,folder,text,revision,sent_as,sent_request,updated_at FROM drafts WHERE chat_id=%s", [chat]
                )
                local["draft"] = draft(rows[0] if rows else None)
                rows = await session.execute("SELECT route,working_folder FROM chat_settings WHERE chat_id=%s", [chat])
                if rows:
                    if rows[0][0] is not None:
                        local["settings"]["route"] = route(rows[0][0])
                    if rows[0][1] is not None:
                        local["settings"]["workingFolder"] = rows[0][1]
                rows = await session.execute("SELECT ongoing,archived_at FROM chat_marks WHERE chat_id=%s", [chat])
                if rows:
                    local["marks"] = {"ongoing": rows[0][0]}
                    if rows[0][1] is not None:
                        local["marks"]["archivedAt"] = iso(rows[0][1])
            return {"kind": "snapshot", "chat": info, "exchanges": exchanges, "more": more, **local}

    async def page_exchanges(self, params: Params) -> Params:
        async with self.session() as (session, layout):
            exchanges, more = await self.exchanges(session, layout, params["chat"],
                                                   before=params["beforeNumber"], limit=params["limit"])
            return {"exchanges": exchanges, "more": more}

    async def tool(self, params: Params) -> Params:
        async with self.session() as (session, _):
            rows = await session.execute(
                "SELECT t.input,t.result,t.error FROM tool_calls t JOIN exchanges e ON e.id=t.exchange_id "
                "WHERE t.exchange_id=%s AND t.position=%s AND t.parent_call_id IS NULL "
                "AND e.replaced_by IS NULL AND e.state<>'open'", [params["exchange"], params["position"]],
            )
            if not rows:
                raise Error("not_found")
            input, output, error = rows[0]
            result: Params = {"input": input}
            if output is not None:
                result["result"] = output
            if error is not None:
                result["error"] = error
            return result
