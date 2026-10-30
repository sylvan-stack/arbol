"""Explicit retained database outage with actual installed services and bounded restoration.

Uses the qualified Root drill service controller, never a runtime dependency.
Keep proof private and inspect failed receipts before a deliberately new attempt.
"""

import asyncio
import json
import os
import select
import sys
import time
import uuid
from pathlib import Path
from typing import Any

SOURCE = Path(__file__).resolve().parents[1]
ROOT_DRILLS = Path.home() / "repos/sylvan-stack/readonly/arbol-root/roots/sapling/drills"
sys.path[:0] = [str(SOURCE), str(SOURCE / "src"), str(ROOT_DRILLS)]
from drill_support import Inspector, Places  # noqa: E402
from sapling_outage import Installed, stopped  # noqa: E402

from arbol_backend.exchange_files import processes  # noqa: E402
from tools.backend_journeys import Bridge, Frame, private_json, require  # noqa: E402

require(
    os.environ.get("ARBOL_INSTALLED_FAULT_PROOF") == "1", "A retained database outage requires its explicit switch."
)
P = Path.home() / ".local/share/arbol-backend-evidence/SYL-257"
OUT = P / "retained-database"
OUT.mkdir(mode=0o700, exist_ok=False)
R = Path.home() / "Library/Application Support/Arbol/roots/sapling"
C = P / "fault-driver"
frame = Frame(OUT)
frame.bin = P / "installed-session/bin"
ins = Inspector(Places.owner(), psql="/opt/homebrew/opt/postgresql@17/bin/psql")
service = Installed(Places.owner(), ins)
proof: dict[str, Any] = {}
req: dict[str, Any] | None = None
b: Bridge | None = None


async def until(check: Any, seconds: float = 25) -> Any:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        await asyncio.sleep(0.1)
    raise RuntimeError("Actual recovery observation deadline expired")


async def cue(expected: str, seconds: float = 240) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if select.select([sys.stdin], [], [], 0)[0]:
            require(sys.stdin.readline().strip() == expected, "Unexpected private drill command.")
            return
        await asyncio.sleep(0.1)
    raise RuntimeError("Private drill command expired")


async def connect() -> Bridge:
    return await Bridge.connect(R / "backend.sock")


async def subscribe(topic: str, params: dict[str, Any]) -> str:
    assert b is not None
    key = str(uuid.uuid4())
    b.writer.write((json.dumps({"type": "subscribe", "id": key, "topic": topic, "params": params}) + "\n").encode())
    await b.writer.drain()
    return key


async def close() -> None:
    try:
        if b is not None:
            await b.close()
    except (ConnectionError, BrokenPipeError):
        pass


async def run() -> None:
    global req, b
    roots = frame.command("arbol-roots", "list")
    require(next(x for x in roots if x["current"])["root"] == "jensen", "Current Root changed.")
    for r in roots:
        x = frame.command("arbol-root", "--root", r["root"], "list")
        require(not x["exchanges"] and not x["unreadable"], "Foreign work prevents service interruption.")
    for driver in ("arbol-claude-driver", "arbol-codex-driver", "claude", "codex"):
        runs = Path.home() / "Library/Application Support/Arbol/drivers" / driver / "runs"
        require(runs.is_dir() and not list(runs.iterdir()), "A foreign native Driver run prevents an outage.")
    private_json(OUT / "preflight.json", roots)
    req = {
        "chat": str(uuid.uuid4()),
        "exchange": str(uuid.uuid4()),
        "message": "SYL-257 actual reconnect/database recovery; controlled no-vendor input.",
        "route": {"driver": "journey-fixture", "subscription": "private-fixture", "model": "hold"},
        "workingFolder": str(Path.home() / "repos/sylvan-stack/readonly/arbol-trunk"),
    }
    private_json(OUT / "request.json", req)
    control = C / (req["exchange"] + ".1")
    b = await connect()
    reply = await b.call("chat.send", req)
    private_json(OUT / "accepted.json", reply)
    require("result" in reply, "The controlled outage start refused.")
    await until(lambda: (C / (req["exchange"] + ".1") / "process.json").exists())
    await subscribe("chat", {"chat": req["chat"]})
    await subscribe("attention", {})
    print(json.dumps({"outageReady": True, "chat": req["chat"], "exchange": req["exchange"]}), flush=True)
    await cue("outage")
    private_json(OUT / "before-outage-events.json", b.events)
    with stopped(
        stop=service.stop, restore=service.restore, healthy=service.healthy, receipt=OUT / "service-restored.json"
    ):
        await until(lambda: any("database_unreachable" in json.dumps(e) for e in b.events))
        (control / "text").write_text("Text while the real database is away. ")
        (control / "text").chmod(0o600)
        await until(lambda: any("Text while the real database is away." in json.dumps(e) for e in b.events))
        print("Database stopped; actual live text continues and attention is present.", flush=True)
        refused = {
            **req,
            "chat": str(uuid.uuid4()),
            "exchange": str(uuid.uuid4()),
            "message": "Must be refused while actual database is stopped.",
        }
        private_json(OUT / "refused-request.json", refused)
        reply = await b.call("chat.send", refused)
        private_json(OUT / "database-away-send-refusal.json", reply)
        require(reply.get("error", {}).get("code") == "database_unavailable", "Database-away send must refuse.")
        require(not (R / "exchanges" / refused["exchange"]).exists(), "A refused send created a Trunk.")
        (control / "finish").write_text("finish\n")
        (control / "finish").chmod(0o600)

        async def ended() -> Any:
            value = json.loads((R / "exchanges" / req["exchange"] / "record.json").read_text())
            pid = value["process"]["pid"]
            seen = (await processes({pid}))[pid]
            return value if value.get("end") and seen is None else None

        deadline = time.monotonic() + 90
        value = None
        while time.monotonic() < deadline and not value:
            value = await ended()
            await asyncio.sleep(0.25)
        require(value, "Trunk did not leave an unsaved end during outage.")
        assert value is not None
        private_json(OUT / "unsaved-record.json", value)
        proof["unsaved"] = value["end"]
        await until(
            lambda: any(
                e.get("event", {}).get("kind") == "exchange" and e["event"]["exchange"].get("state") == "unsaved"
                for e in b.events
            )
        )
        print(
            "Actual Trunk ended with database away; unsaved state observed. Type restore after UI proof (30s automatic restoration bound).",
            flush=True,
        )
        try:
            await cue("restore", 30)
        except RuntimeError:
            proof["automaticRestore"] = True
    print("Actual database restored; awaiting saved reconciliation.", flush=True)

    def canonical() -> Any:
        for row in reversed(b.events):
            event = row.get("event", {})
            items = (
                [event["exchange"]]
                if event.get("kind") == "saved"
                else event.get("exchanges", [])
                if event.get("kind") == "snapshot"
                else []
            )
            for item in items:
                if item["exchange"] == req["exchange"] and item["state"] != "open":
                    return item
        return None

    saved = await until(canonical, 50)
    require(saved["state"] == "completed", "Recovered saved state changed.")
    proof["saved"] = saved

    # Read-only independent once-only acceptance/run proof after healthy restoration.
    proof["sql"] = ins.read(
        "SELECT json_build_object('exchanges',(SELECT count(*) FROM exchanges WHERE id='"
        + req["exchange"]
        + "'),'runs',(SELECT count(*) FROM runs WHERE exchange_id='"
        + req["exchange"]
        + "'),'drafts',(SELECT json_agg(row_to_json(d)) FROM drafts d WHERE chat_id='"
        + req["chat"]
        + "'))"
    )
    require(
        proof["sql"]["exchanges"] == 1 and proof["sql"]["runs"] == 1, "Ambiguous recovery must own one Exchange/run."
    )
    private_json(OUT / "result.json", proof)
    print(
        json.dumps(
            {
                "retainedRecoveryPassed": True,
                "realServiceRestored": service.healthy(),
                "singleExchangeAndRun": True,
                "vendorRequests": 0,
            }
        ),
        flush=True,
    )


try:
    asyncio.run(run())
except BaseException as e:
    private_json(OUT / "failure.json", {"error": type(e).__name__, "message": str(e)})
    raise
finally:
    if b is not None:
        private_json(OUT / "wire-events.json", b.events)
    if not service.healthy():
        service.restore()
    if req and (R / "exchanges" / req["exchange"]).exists():
        import subprocess

        subprocess.run(
            [str(P / "installed-session/bin/arbol-root"), "--root", "sapling", "stop", req["exchange"]],
            capture_output=True,
            timeout=95,
        )
