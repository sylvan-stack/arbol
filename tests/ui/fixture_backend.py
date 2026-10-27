"""Explicit browser-only stand-in: no Root manager, database, Driver or inference."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import signal
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOL = Path(__file__).resolve().parents[2] / "tools/bridge_relay.py"
spec = importlib.util.spec_from_file_location("browser_test_relay", TOOL)
assert spec and spec.loader
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)
ROOT = {"root": "t1", "name": "Fixture Root", "status": "working", "current": True}


class Fixture:
    def __init__(self, scenario: dict[str, Any]):
        self.scenario = scenario
        self.windows: dict[asyncio.StreamWriter, dict[str, dict[str, Any]]] = {}
        self.tasks: set[asyncio.Task[None]] = set()

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
                    await self.send(writer, {"type": "event", "id": message["id"], "seq": 1, "event": event})
                elif message["type"] == "unsubscribe":
                    self.windows[writer].pop(message["id"], None)
                elif message["type"] == "call":
                    method = message["method"]
                    value: dict[str, Any]
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
                    elif method == "root.get":
                        value = {"root": ROOT, "layoutComplete": True}
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
        elif value["kind"] == "publish":
            for writer, subs in tuple(self.windows.items()):
                for id, s in tuple(subs.items()):
                    if s["topic"] == value["topic"]:
                        s["seq"] += value.get("advance", 1)
                        await self.send(writer, {"type": "event", "id": id, "seq": s["seq"], "event": value["event"]})


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--scenario")
    args = parser.parse_args()
    scenario = json.loads(Path(args.scenario).read_text()) if args.scenario else {}
    fixture = Fixture(scenario)
    with tempfile.TemporaryDirectory(prefix="eb-", dir="/tmp") as folder:
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
