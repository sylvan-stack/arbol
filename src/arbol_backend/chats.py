"""Bridge chat views and Root-local changes; the Trunk remains the history writer."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from .bridge import MAX_LINE, Error, Params, Registry, Snapshot, uuid_id
from .chat_data import Reader, encoded
from .database import Database
from .metadata import Attention, iso
from .model import Identity, Refused
from .process import Programs
from .roots import Roots
from .validation import Catalogues, chat, integer, save_paste, text
from .views import View


async def page_params(params: Params) -> Params:
    result: Params = {"limit": integer(params.get("limit", 100), 1, 200)}
    if "before" in params:
        before = params["before"]
        if not isinstance(before, dict):
            raise Error("invalid_input")
        id = uuid_id(before.get("chat"))
        value = text(before.get("activityAt"))
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None or iso(parsed) != value:
                raise ValueError("Noncanonical cursor time.")
        except ValueError as error:
            raise Error("invalid_input") from error
        result["before"] = {"activityAt": value, "chat": id}
    return result


async def exchange_params(params: Params) -> Params:
    return {**await chat(params), "beforeNumber": integer(params.get("beforeNumber"), 1, 2147483647),
            "limit": integer(params.get("limit", 12), 1, 50)}


async def tool_params(params: Params) -> Params:
    return {"exchange": uuid_id(params.get("exchange")), "position": integer(params.get("position"), 1, 2147483647)}


async def rename_params(params: Params) -> Params:
    result = await chat(params)
    if "title" not in params:
        raise Error("invalid_input")
    title = params["title"]
    if title is not None:
        title = text(title, nonempty=False).strip() or None
        if title is not None and len(title) > 240:
            raise Error("invalid_input")
    return {**result, "title": title}


async def mark_params(params: Params) -> Params:
    result = await chat(params)
    for key in ("ongoing", "archived"):
        if key in params:
            if type(params[key]) is not bool:
                raise Error("invalid_input")
            result[key] = params[key]
    if len(result) == 1:
        raise Error("invalid_input")
    return result


async def paste_params(params: Params) -> Params:
    value = params.get("text")
    if not isinstance(value, str) or len(value) < 10000:
        raise Error("invalid_input")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise Error("invalid_input") from error
    return {"text": value}


class Chats:
    def __init__(self, identity: Identity, database: Database, programs: Programs, roots: Roots,
                 registry: Registry, *, lineage: bool = False) -> None:
        self.identity, self.database, self.roots = identity, database, roots
        self.attention = Attention()
        self.reader = Reader(database, self.attention, lineage=lineage)
        self.catalogues = Catalogues(identity, programs)
        self.list_view = View(self.reader.summaries, self.list_changed)
        self.chat_view = View(self.reader.chat, self.chat_changed, chat)
        self.list_view.topic.snapshot = self.list_snapshot
        self.attention.topic.snapshot = self.attention_snapshot
        registry.topics.update(chats=self.list_view.topic, chat=self.chat_view.topic, attention=self.attention.topic)
        registry.method("chats.page", self.page, page_params)
        registry.method("chat.exchanges", self.reader.page_exchanges, exchange_params)
        registry.method("toolCall.get", self.reader.tool, tool_params)
        registry.method("chat.rename", self.rename, rename_params)
        registry.method("chat.settings", self.settings, self.catalogues.settings)
        registry.method("chat.mark", self.mark, mark_params)
        registry.method("paste.save", self.paste, paste_params)
        self.roots.complete = self.reader.complete
        self.tasks: set[asyncio.Task[None]] = set()
        self.observers: dict[tuple[str, str], asyncio.Task[None]] = {}
        self.on_list_open: Callable[[], None] | None = None
        self.extra_views: dict[str, View] = {}

    def task(self, work: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(work)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def list_changed(self, old: Params | None, new: Params, params: Params) -> None:
        if old is None:
            return
        previous = {row["chat"]: row for row in old["chats"]}
        current = {row["chat"]: row for row in new["chats"]}
        if previous.keys() - current.keys():
            self.list_view.topic.publish({"kind": "snapshot", "chats": self.visible(new)[0:100]})
            return
        batch: list[Params] = []
        size = 32
        for row in new["chats"]:
            if previous.get(row["chat"]) == row:
                continue
            length = len(encoded(row)) + 1
            if batch and size + length > MAX_LINE - 512:
                self.list_view.topic.publish({"kind": "changed", "chats": batch})
                batch, size = [], 32
            batch.append(row)
            size += length
        if batch:
            self.list_view.topic.publish({"kind": "changed", "chats": batch})

    def chat_changed(self, old: Params | None, new: Params, params: Params) -> None:
        if old is None:
            return
        old_info = {key: value for key, value in old["chat"].items() if key != "title"}
        new_info = {key: value for key, value in new["chat"].items() if key != "title"}
        if old_info != new_info or old["exchanges"] != new["exchanges"] or old["more"] != new["more"]:
            self.chat_view.topic.publish(new, params=params)
            return
        for kind in ("settings", "marks", "draft"):
            if old[kind] != new[kind]:
                self.chat_view.topic.publish({"kind": kind, kind: new[kind]}, params=params)
        if old["chat"]["title"] != new["chat"]["title"]:
            self.chat_view.topic.publish({"kind": "title", "title": new["chat"]["title"]}, params=params)

    @staticmethod
    def visible(state: Params) -> list[Params]:
        return [row for row in state["chats"] if not row.get("archived")]

    async def list_snapshot(self, params: Params) -> Snapshot:
        if self.on_list_open:
            self.on_list_open()
        snapshot = await self.list_view.snapshot({})
        return Snapshot(snapshot.version, {"kind": "snapshot", "chats": self.visible(snapshot.event)[:100]})

    async def page(self, params: Params) -> Params:
        if self.on_list_open and "before" not in params:
            self.on_list_open()
        snapshot = await self.list_view.snapshot({})
        rows = self.visible(snapshot.event)
        if before := params.get("before"):
            rows = [row for row in rows if (row["activityAt"], row["chat"]) < (before["activityAt"], before["chat"])]
        return {"chats": rows[:params["limit"]]}

    async def attention_snapshot(self, params: Params) -> Snapshot:
        await self.reader.complete()
        return await self.attention.snapshot(params)

    def invalidate(self, chat: str | None = None) -> None:
        self.list_view.invalidate({})
        self.chat_view.invalidate({"chat": chat} if chat is not None else None)

    async def refresh(self, view: View, params: Params) -> None:
        try:
            await view.snapshot(params)
        except Refused as error:
            view.topic.fail(error, params=params)

    def changed(self, chat: str) -> None:
        params = {"chat": chat}
        if self.list_view.topic.listeners:
            self.task(self.refresh(self.list_view, {}))
        if any(sub.params == params for sub in self.chat_view.topic.listeners):
            self.task(self.refresh(self.chat_view, params))

    async def own_layout(self) -> None:
        if not await self.reader.complete():
            raise Error("layout_incomplete")

    async def rename(self, params: Params) -> Params:
        self.invalidate(params["chat"])
        try:
            rows = await self.database.execute("UPDATE chats SET title=%s WHERE id=%s RETURNING title",
                                               [params["title"], params["chat"]])
        finally:
            self.invalidate(params["chat"])
        if not rows:
            raise Error("not_found")
        self.changed(params["chat"])
        return {"title": rows[0][0]}

    async def settings(self, params: Params) -> Params:
        await self.own_layout()
        has_route, has_folder = "route" in params, "workingFolder" in params
        self.invalidate(params["chat"])
        try:
            rows = await self.database.execute(
                "INSERT INTO chat_settings(chat_id,route,working_folder,updated_at) "
                "SELECT id,%s,%s,clock_timestamp() FROM chats WHERE id=%s "
                "ON CONFLICT(chat_id) DO UPDATE SET "
                "route=CASE WHEN %s THEN EXCLUDED.route ELSE chat_settings.route END,"
                "working_folder=CASE WHEN %s THEN EXCLUDED.working_folder ELSE chat_settings.working_folder END,"
                "updated_at=clock_timestamp() RETURNING route,working_folder",
                [Jsonb(params["route"]) if has_route else None, params.get("workingFolder"), params["chat"],
                 has_route, has_folder],
            )
        finally:
            self.invalidate(params["chat"])
        if not rows:
            raise Error("not_found")
        self.changed(params["chat"])
        return {}

    async def mark(self, params: Params) -> Params:
        await self.own_layout()
        self.invalidate(params["chat"])
        try:
            rows = await self.database.execute(
                "INSERT INTO chat_marks(chat_id,ongoing,archived_at,updated_at) "
                "SELECT id,%s,CASE WHEN %s THEN clock_timestamp() END,clock_timestamp() FROM chats WHERE id=%s "
                "ON CONFLICT(chat_id) DO UPDATE SET ongoing=CASE WHEN %s THEN EXCLUDED.ongoing ELSE chat_marks.ongoing END,"
                "archived_at=CASE WHEN %s THEN CASE WHEN %s THEN coalesce(chat_marks.archived_at,EXCLUDED.archived_at) "
                "ELSE NULL END ELSE chat_marks.archived_at END,updated_at=clock_timestamp() RETURNING ongoing,archived_at",
                [params.get("ongoing", False), params.get("archived", False), params["chat"],
                 "ongoing" in params, "archived" in params, params.get("archived", False)],
            )
        finally:
            self.invalidate(params["chat"])
        if not rows:
            raise Error("not_found")
        result: Params = {"ongoing": rows[0][0]}
        if rows[0][1] is not None:
            result["archivedAt"] = iso(rows[0][1])
        self.changed(params["chat"])
        return result

    async def paste(self, params: Params) -> Params:
        path = await asyncio.to_thread(save_paste, self.identity, params["text"])
        return {"path": path}

    async def observe(self, view: View, params: Params) -> None:
        try:
            while any(sub.params == params for sub in view.topic.listeners):
                try:
                    async with asyncio.timeout(0.75):
                        await view.snapshot(params)
                except TimeoutError:
                    view.topic.fail(Error("timeout"), params=params)
                    return
                except Refused as error:
                    view.topic.fail(error, params=params)
                    return
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            raise
        except Exception:
            view.topic.fail(Error("database_unavailable"), params=params)

    async def monitor(self) -> None:
        while True:
            for name, view in (("chats", self.list_view), ("chat", self.chat_view), *self.extra_views.items()):
                params_by_key = {view.key(sub.params): sub.params for sub in view.topic.listeners}
                for key, params in params_by_key.items():
                    identity = (name, key)
                    if identity not in self.observers or self.observers[identity].done():
                        self.observers[identity] = self.task(self.observe(view, params))
                for identity, task in list(self.observers.items()):
                    if identity[0] == name and task.done() and identity[1] not in params_by_key:
                        self.observers.pop(identity)
                view.forget_unwatched()
            await asyncio.sleep(0.1)

    async def initial(self) -> None:
        try:
            await self.reader.complete()
        except Refused:
            pass
        if self.on_list_open:
            self.on_list_open()

    def start(self) -> None:
        self.catalogues.start()
        self.task(self.initial())
        self.task(self.monitor())

    async def close(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.list_view.close()
        await self.chat_view.close()
        await self.catalogues.close()
        for view in self.extra_views.values():
            await view.close()
