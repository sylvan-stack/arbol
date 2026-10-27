"""Explicit browser-only stand-in: no Root manager, database, Driver or inference."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import os
import signal
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

TOOL = Path(__file__).resolve().parents[2] / "tools/bridge_relay.py"
spec = importlib.util.spec_from_file_location("browser_test_relay", TOOL)
assert spec and spec.loader
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)
ROOT = {"root": "t1", "name": "Fixture Root", "status": "working", "current": True}


class Fixture:
    def __init__(self, scenario: dict[str, Any], record: Path | None = None):
        self.scenario = scenario
        self.record = record
        self.windows: dict[asyncio.StreamWriter, dict[str, dict[str, Any]]] = {}
        self.tasks: set[asyncio.Task[None]] = set()
        self.drafts: dict[str, dict[str, Any]] = dict(scenario.get("drafts", {}))
        self.draft_revision = int(scenario.get("draftRevision", 9007199254740993))
        self.paste_dir: Path | None = None
        self.accepted: dict[str, dict[str, Any]] = {}
        self.requests: dict[str, dict[str, Any]] = {}

    async def chat_changed(self, chat: str) -> None:
        for writer, subscriptions in tuple(self.windows.items()):
            for id, subscription in tuple(subscriptions.items()):
                if subscription["topic"] == "chat" and subscription["params"].get("chat") == chat:
                    subscription["seq"] += 1
                    await self.send(writer, {"type": "event", "id": id, "seq": subscription["seq"],
                                             "event": self.scenario["chats"][chat]})

    async def start_message(self, params: dict[str, Any]) -> dict[str, Any]:
        exchange, chat = params["exchange"], params["chat"]
        if exchange in self.accepted:
            if self.requests[exchange] != params:
                return {"error": {"code": "invalid_input", "message": "Changed request"}}
            return {**self.accepted[exchange], "duplicate": True}
        chats = self.scenario.setdefault("chats", {})
        snapshot = chats.get(chat)
        if snapshot and any(row["state"] not in ("completed", "failed", "cancelled", "interrupted") for row in snapshot["exchanges"]):
            return {"error": {"code": "chat_busy", "message": "Another message of this chat is running"}}
        selected = params.get("draft", {})
        scope = {"folder": selected["folder"]} if "folder" in selected else {"chat": chat}
        draft = self.drafts.get(self.draft_key(scope))
        if selected and (draft is None or draft["revision"] != selected["revision"] or draft["text"] != params["message"]):
            return {"error": {"code": "draft_conflict", "message": "Changed elsewhere", "draft": draft}}
        at = datetime.now(UTC).isoformat()
        if snapshot is None:
            snapshot = {"kind": "snapshot", "chat": {"chat": chat, "title": None, "firstMessage": params["message"][:200],
                        "createdAt": at, "exchangeCount": 0, "usage": {"inputTokens": 0, "outputTokens": 0}},
                        "exchanges": [], "more": False, "settings": {}, "marks": {"ongoing": True}, "draft": None}
            chats[chat] = snapshot
        number = snapshot["chat"]["exchangeCount"] + 1
        snapshot["chat"]["exchangeCount"] = number
        snapshot["marks"]["ongoing"] = True
        snapshot["exchanges"].append({"exchange": exchange, "number": number, "state": "open", "route": params["route"],
            "workingFolder": params["workingFolder"], "acceptedAt": at,
            "items": [{"kind": "message", "role": "user", "position": 0, "text": params["message"]}], "runs": []})
        self.requests[exchange] = params
        self.accepted[exchange] = {"accepted": True, "duplicate": False, "chat": chat, "exchange": exchange, "number": number}
        if self.record:
            with os.fdopen(os.open(self.record, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "w") as out:
                out.write(json.dumps({"method": "fixture.start", "chat": chat, "exchange": exchange}) + "\n")
        if selected:
            self.drafts.pop(self.draft_key(scope), None)
            await self.draft_changed(scope)
        await self.chat_changed(chat)
        return self.accepted[exchange]

    @staticmethod
    def draft_key(params: dict[str, Any]) -> str:
        return "chat:" + str(params["chat"]) if "chat" in params else "folder:" + str(params["folder"])

    async def start_again(self, params: dict[str, Any]) -> dict[str, Any]:
        exchange = params["newExchange"]
        if exchange in self.accepted:
            if self.requests[exchange] != params:
                return {"error": {"code": "invalid_input", "message": "Changed retry request"}}
            return {**self.accepted[exchange], "duplicate": True}
        for chat, snapshot in self.scenario.get("chats", {}).items():
            previous = next((row for row in snapshot["exchanges"] if row["exchange"] == params["exchange"]), None)
            if previous is None:
                continue
            if any(row["state"] not in ("completed", "failed", "cancelled", "interrupted") for row in snapshot["exchanges"]):
                return {"error": {"code": "chat_busy", "message": "Another message of this chat is running"}}
            row = {"exchange": exchange, "number": previous["number"], "state": "open", "route": params["route"],
                   "workingFolder": previous["workingFolder"], "acceptedAt": datetime.now(UTC).isoformat(),
                   "items": [item for item in previous["items"] if item["kind"] == "message" and item["role"] == "user"], "runs": []}
            snapshot["exchanges"] = [row if item is previous else item for item in snapshot["exchanges"]]
            snapshot["marks"]["ongoing"] = True
            self.requests[exchange] = params
            self.accepted[exchange] = {"accepted": True, "duplicate": False, "chat": chat, "exchange": exchange, "number": previous["number"]}
            if self.record:
                with os.fdopen(os.open(self.record, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "w") as out:
                    out.write(json.dumps({"method": "fixture.start", "chat": chat, "exchange": exchange, "replaces": previous["exchange"]}) + "\n")
            await self.chat_changed(chat)
            return self.accepted[exchange]
        return {"error": {"code": "not_found", "message": "The replaced Exchange is unavailable"}}

    async def draft_changed(self, params: dict[str, Any]) -> None:
        current = self.drafts.get(self.draft_key(params))
        for writer, subscriptions in tuple(self.windows.items()):
            for id, subscription in tuple(subscriptions.items()):
                if subscription["topic"] == "draft" and subscription["params"] == params:
                    subscription["seq"] += 1
                    await self.send(writer, {"type": "event", "id": id, "seq": subscription["seq"],
                                             "event": {"kind": "draft", "draft": current}})

    async def send(self, writer: asyncio.StreamWriter, value: dict[str, Any]) -> None:
        if writer.is_closing():
            return
        try:
            writer.write((json.dumps(value, ensure_ascii=False) + "\n").encode())
            await writer.drain()
        except OSError:
            pass  # A disconnected window must not prevent another window's publication.

    async def client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.tasks.add(task)
        self.windows[writer] = {}
        try:
            await self.send(
                writer, {"type": "hello", "bridge": 1, "root": ROOT, "build": self.scenario.get("build", "development")}
            )
            while line := await reader.readline():
                message = json.loads(line)
                if message["type"] == "subscribe":
                    sub = {"topic": message["topic"], "params": message.get("params", {}), "seq": 1}
                    self.windows[writer][message["id"]] = sub
                    event = self.scenario.get("topics", {}).get(
                        message["topic"],
                        {"kind": "snapshot", "root": ROOT}
                        if message["topic"] == "root"
                        else {"kind": "snapshot", "items": []},
                    )
                    if message["topic"] == "chat":
                        chat = message.get("params", {}).get("chat", "")
                        event = self.scenario.get("chats", {}).get(
                            chat,
                            {
                                "kind": "snapshot",
                                "chat": {
                                    "chat": chat,
                                    "title": None,
                                    "firstMessage": "",
                                    "exchangeCount": 0,
                                    "usage": {"inputTokens": 0, "outputTokens": 0},
                                },
                                "exchanges": [],
                                "more": False,
                                "settings": {},
                                "marks": {"ongoing": False},
                                "draft": None,
                            },
                        )
                    elif message["topic"] == "draft":
                        event = {"kind": "snapshot", "draft": self.drafts.get(self.draft_key(sub["params"]))}
                    elif message["topic"] == "chats" and "chats" not in self.scenario.get("topics", {}):
                        event = {"kind": "snapshot", "chats": []}
                    await self.send(writer, {"type": "event", "id": message["id"], "seq": 1, "event": event})
                    if message["topic"] == "chat":
                        for replay in self.scenario.get("replay", {}).get(sub["params"].get("chat"), []):
                            sub["seq"] += 1
                            await self.send(writer, {"type": "event", "id": message["id"], "seq": sub["seq"], "event": replay})
                elif message["type"] == "unsubscribe":
                    self.windows[writer].pop(message["id"], None)
                elif message["type"] == "call":
                    method = message["method"]
                    value: Any
                    if self.record:
                        with os.fdopen(os.open(self.record, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "w") as out:
                            out.write(
                                json.dumps(
                                    {
                                        "method": method,
                                        "beforeNumber": message.get("params", {}).get("beforeNumber"),
                                        "limit": message.get("params", {}).get("limit"),
                                        "exchange": message.get("params", {}).get("exchange"),
                                        "position": message.get("params", {}).get("position"),
                                        **({"params": message.get("params", {})} if method.startswith(("draft.", "accounts.")) or method in ("chat.settings", "chat.send", "exchange.stop", "exchange.sendAgain", "exchange.answer", "chat.rename", "chat.mark") else {}),
                                        **({"characters": len(message["params"]["text"])} if method == "paste.save" else {}),
                                    }
                                )
                                + "\n"
                            )
                    failures = self.scenario.get("callErrors", {}).get(method, [])
                    failure = failures.pop(0) if failures else None
                    reply_delays = self.scenario.get("replyDelays", {}).get(method, 0)
                    reply_delay = reply_delays.pop(0) if isinstance(reply_delays, list) and reply_delays else reply_delays if not isinstance(reply_delays, list) else 0
                    delay = self.scenario.get("delays", {}).get(method, 0)
                    if delay:
                        await asyncio.sleep(delay)
                    if failure:
                        await self.send(writer, {"type": "reply", "id": message["id"], "error": failure})
                        continue
                    if method == "subscriptions.check":
                        value = {
                            "subscriptions": [{"id": id, "seq": s["seq"]} for id, s in self.windows[writer].items()]
                        }
                    elif method == "workspace.get" and method not in self.scenario.get("calls", {}):
                        value = {
                            "repositories": [{"name": "sylvan-stack", "folder": "/fictional/readonly", "route": {}}],
                            "route": {},
                        }
                    elif method == "accounts.list" and method not in self.scenario.get("calls", {}):
                        value = {"drivers": []}
                    elif method == "accounts.models" and "catalogs" in self.scenario:
                        params = message["params"]
                        value = self.scenario["catalogs"].get(params["driver"] + ":" + params["subscription"], {"models": []})
                    elif method == "chat.settings":
                        params = message["params"]
                        snapshot = self.scenario.get("chats", {}).get(params["chat"])
                        if snapshot is None:
                            await self.send(writer, {"type": "reply", "id": message["id"], "error": {"code": "not_found", "message": "Chat not found"}})
                            continue
                        snapshot["settings"] = {**snapshot.get("settings", {}), **{k: v for k, v in params.items() if k != "chat"}}
                        settings_value = snapshot["settings"]
                        for peer, subscriptions in tuple(self.windows.items()):
                            for id, subscription in tuple(subscriptions.items()):
                                if subscription["topic"] == "chat" and subscription["params"].get("chat") == params["chat"]:
                                    subscription["seq"] += 1
                                    await self.send(peer, {"type": "event", "id": id, "seq": subscription["seq"], "event": {"kind": "settings", "settings": settings_value}})
                        value = {}
                    elif method == "chat.exchanges" and "exchangePages" in self.scenario:
                        value = self.scenario["exchangePages"].get(
                            str(message.get("params", {}).get("beforeNumber")), {"exchanges": [], "more": False}
                        )
                    elif method in ("chat.rename", "chat.mark"):
                        params = message["params"]
                        snapshot = self.scenario.get("chats", {}).get(params["chat"])
                        if snapshot is None:
                            await self.send(writer, {"type": "reply", "id": message["id"], "error": {"code": "not_found", "message": "No such chat"}})
                            continue
                        if method == "chat.rename":
                            snapshot["chat"]["title"] = str(params["title"]).strip() or None if params["title"] is not None else None
                            value = {"title": snapshot["chat"]["title"]}
                            event = {"kind": "title", "title": value["title"]}
                        else:
                            marks = snapshot["marks"]
                            if "ongoing" in params:
                                marks["ongoing"] = params["ongoing"]
                            if "archived" in params:
                                if params["archived"]:
                                    marks["archivedAt"] = datetime.now(UTC).isoformat()
                                else:
                                    marks.pop("archivedAt", None)
                            value = dict(marks)
                            event = {"kind": "marks", "marks": dict(marks)}
                        for peer, subscriptions in tuple(self.windows.items()):
                            for id, sub in tuple(subscriptions.items()):
                                if sub["topic"] == "chat" and sub["params"].get("chat") == params["chat"]:
                                    sub["seq"] += 1
                                    await self.send(peer, {"type": "event", "id": id, "seq": sub["seq"], "event": event})
                    elif method == "root.get":
                        value = {"root": ROOT, "layoutComplete": True}
                    elif method == "chat.send":
                        value = await self.start_message(message["params"])
                        if "error" in value:
                            await self.send(writer, {"type": "reply", "id": message["id"], "error": value["error"]})
                            continue
                        if self.scenario.get("dropSendReplies", 0):
                            self.scenario["dropSendReplies"] -= 1
                            return
                    elif method == "exchange.stop":
                        value = self.scenario.get("calls", {}).get(method, {"ended": "cancelled"})
                    elif method == "exchange.sendAgain":
                        value = await self.start_again(message["params"])
                        if "error" in value:
                            await self.send(writer, {"type": "reply", "id": message["id"], "error": value["error"]})
                            continue
                        if self.scenario.get("dropSendReplies", 0):
                            self.scenario["dropSendReplies"] -= 1
                            return
                    elif method == "draft.get":
                        value = self.drafts.get(self.draft_key(message["params"]))
                    elif method == "paste.save":
                        assert self.paste_dir is not None
                        path = self.paste_dir / (str(uuid4()) + ".txt")
                        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as out:
                            out.write(message["params"]["text"])
                        value = {"path": str(path)}
                    elif method == "draft.save":
                        params = message["params"]
                        key = self.draft_key(params)
                        current = self.drafts.get(key)
                        if params["baseRevision"] != (current["revision"] if current else None):
                            await self.send(writer, {"type": "reply", "id": message["id"],
                                                     "error": {"code": "draft_conflict", "message": "Changed elsewhere",
                                                               "draft": current}})
                            continue
                        if params["text"]:
                            self.draft_revision += 1
                            self.drafts[key] = {**{k: params[k] for k in ("chat", "folder") if k in params},
                                                "text": params["text"], "revision": self.draft_revision}
                            value = {"revision": self.draft_revision}
                        else:
                            self.drafts.pop(key, None)
                            value = {"removed": True}
                        await self.draft_changed({k: params[k] for k in ("chat", "folder") if k in params})
                    else:
                        value = self.scenario.get("calls", {}).get(method, {})
                    if method in ("chat.rename", "chat.mark") and self.scenario.get("dropMetadataReplies", 0):
                        self.scenario["dropMetadataReplies"] -= 1
                        return
                    if reply_delay:
                        await asyncio.sleep(reply_delay)
                    await self.send(writer, {"type": "reply", "id": message["id"], "result": value})
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            self.windows.pop(writer, None)
            self.tasks.discard(task)
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def command(self, value: dict[str, Any]) -> None:
        if value["kind"] == "disconnect":
            for writer in tuple(self.windows):
                writer.close()
        elif value["kind"] == "scenario":
            self.scenario.update(value["value"])
        elif value["kind"] == "publish":
            if value["topic"] == "chat" and value["event"].get("kind") == "saved":
                saved = value["event"]["exchange"]
                for snapshot in self.scenario.get("chats", {}).values():
                    snapshot["exchanges"] = [saved if row["exchange"] == saved["exchange"] else row for row in snapshot["exchanges"]]
            for writer, subs in tuple(self.windows.items()):
                for id, s in tuple(subs.items()):
                    if s["topic"] == value["topic"]:
                        s["seq"] += value.get("advance", 1)
                        await self.send(writer, {"type": "event", "id": id, "seq": s["seq"], "event": value["event"]})
        elif value["kind"] == "draft":
            key = self.draft_key(value["scope"])
            if value["draft"] is None:
                self.drafts.pop(key, None)
            else:
                self.drafts[key] = value["draft"]
                self.draft_revision = max(self.draft_revision, value["draft"]["revision"])
            if not value.get("silent"):
                await self.draft_changed(value["scope"])


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--scenario")
    parser.add_argument("--record", type=Path)
    parser.add_argument("--build")
    parser.add_argument("--registry-dir")
    args = parser.parse_args()
    scenario = json.loads(Path(args.scenario).read_text()) if args.scenario else {}
    if args.build:
        scenario["build"] = args.build
    elif os.environ.get("ELMA_TEST_BUILD"):
        scenario["build"] = os.environ["ELMA_TEST_BUILD"]
    bundle = Path(os.environ.get("ELMA_TEST_BUNDLE", args.bundle))
    fixture = Fixture(scenario, args.record)
    with tempfile.TemporaryDirectory(prefix="eb-", dir="/tmp") as folder:
        fixture.paste_dir = Path(folder) / "Private Root" / "pastes"
        fixture.paste_dir.mkdir(parents=True, mode=0o700)
        socket = Path(folder) / "b.sock"
        backend = await asyncio.start_unix_server(fixture.client, path=socket, limit=relay.LIMIT)
        selection = argparse.Namespace(root="t1", registry_dir=args.registry_dir, root_dir=folder, bundle=None, socket=None)
        host = relay.Relay(relay.paths(selection)[0] if args.registry_dir else bundle, socket,
                           refresh=(lambda: relay.paths(selection)[0]) if args.registry_dir else None)
        await host.start()
        print("http://" + host.host + "/?token=" + host.token, flush=True)
        stop = asyncio.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        async def commands() -> None:
            while line := await reader.readline():
                await fixture.command(json.loads(line))

        controller = asyncio.create_task(commands())
        try:
            await stop.wait()
        finally:
            controller.cancel()
            await asyncio.gather(controller, return_exceptions=True)
            await host.close()
            backend.close()
            await backend.wait_closed()
            for task in tuple(fixture.tasks):
                task.cancel()
            await asyncio.gather(*fixture.tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
