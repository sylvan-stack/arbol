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

    @staticmethod
    def draft_key(params: dict[str, Any]) -> str:
        return "chat:" + str(params["chat"]) if "chat" in params else "folder:" + str(params["folder"])

    async def draft_changed(self, params: dict[str, Any]) -> None:
        current = self.drafts.get(self.draft_key(params))
        for writer, subscriptions in tuple(self.windows.items()):
            for id, subscription in tuple(subscriptions.items()):
                if subscription["topic"] == "draft" and subscription["params"] == params:
                    subscription["seq"] += 1
                    await self.send(writer, {"type": "event", "id": id, "seq": subscription["seq"],
                                             "event": {"kind": "draft", "draft": current}})

    async def send(self, writer: asyncio.StreamWriter, value: dict[str, Any]) -> None:
        writer.write((json.dumps(value, ensure_ascii=False) + "\n").encode())
        await writer.drain()

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
                                        **({"params": message.get("params", {})} if method.startswith("draft.") else {}),
                                        **({"characters": len(message["params"]["text"])} if method == "paste.save" else {}),
                                    }
                                )
                                + "\n"
                            )
                    delay = self.scenario.get("delays", {}).get(method, 0)
                    if delay:
                        await asyncio.sleep(delay)
                    failures = self.scenario.get("callErrors", {}).get(method, [])
                    if failures:
                        await self.send(writer, {"type": "reply", "id": message["id"], "error": failures.pop(0)})
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
                    elif method == "chat.exchanges" and "exchangePages" in self.scenario:
                        value = self.scenario["exchangePages"].get(
                            str(message.get("params", {}).get("beforeNumber")), {"exchanges": [], "more": False}
                        )
                    elif method == "root.get":
                        value = {"root": ROOT, "layoutComplete": True}
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
            await self.draft_changed(value["scope"])


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--scenario")
    parser.add_argument("--record", type=Path)
    parser.add_argument("--build")
    args = parser.parse_args()
    scenario = json.loads(Path(args.scenario).read_text()) if args.scenario else {}
    if args.build:
        scenario["build"] = args.build
    fixture = Fixture(scenario, args.record)
    with tempfile.TemporaryDirectory(prefix="eb-", dir="/tmp") as folder:
        fixture.paste_dir = Path(folder) / "Private Root" / "pastes"
        fixture.paste_dir.mkdir(parents=True, mode=0o700)
        socket = Path(folder) / "b.sock"
        backend = await asyncio.start_unix_server(fixture.client, path=socket, limit=relay.LIMIT)
        host = relay.Relay(Path(args.bundle), socket)
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
