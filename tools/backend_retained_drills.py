"""Explicit no-vendor retained-Root fault drill; excluded from automatic qualification."""

import asyncio
import json
import os
import signal
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE), str(SOURCE / "src")]
from arbol_backend.exchange_files import processes  # noqa: E402
from tools.backend_journeys import Bridge, Frame, private_json, require  # noqa: E402

require(os.environ.get("ARBOL_INSTALLED_FAULT_PROOF") == "1", "This retained-Root drill needs its explicit switch.")
P = Path.home() / ".local/share/arbol-backend-evidence/SYL-257"
OUT = P / "retained-faults"
OUT.mkdir(mode=0o700, exist_ok=False)
ROOT = Path.home() / "Library/Application Support/Arbol/roots/sapling"
CONTROL = P / "fault-driver"
frame = Frame(OUT)
owned = []
proof = {}
b = None


async def until(check, seconds=25):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        await asyncio.sleep(0.05)
    raise RuntimeError("Actual retained drill observation deadline expired")


async def subscribe(chat):
    key = str(uuid.uuid4())
    b.writer.write(
        (json.dumps({"type": "subscribe", "id": key, "topic": "chat", "params": {"chat": chat}}) + "\n").encode()
    )
    await b.writer.drain()
    return key


async def new(name, model="hold"):
    request = {
        "chat": str(uuid.uuid4()),
        "exchange": str(uuid.uuid4()),
        "message": "SYL-257 " + name + " controlled installed fault; no vendor request.",
        "route": {"driver": "journey-fixture", "subscription": "private-fixture", "model": model},
        "workingFolder": str(Path.home() / "repos/sylvan-stack/readonly/arbol-trunk"),
    }
    private_json(OUT / (name + "-request.json"), request)
    owned.append(request)
    reply = await b.call("chat.send", request)
    private_json(OUT / (name + "-accept.json"), reply)
    require("result" in reply, "A controlled start refused; do not replay.")
    await until(lambda: (CONTROL / (request["exchange"] + ".1") / "process.json").exists())
    record = json.loads((ROOT / "exchanges" / request["exchange"] / "record.json").read_text())
    require(record["chat"] == request["chat"], "Wrong owned chat record.")
    request["process"] = record["process"]
    request["driverProcess"] = json.loads((CONTROL / (request["exchange"] + ".1") / "process.json").read_text())
    request["driverStarted"] = (await processes({request["driverProcess"]["pid"]}))[request["driverProcess"]["pid"]]
    request["subscription"] = await subscribe(request["chat"])
    private_json(OUT / (name + "-identity.json"), {k: v for k, v in request.items() if k != "driverStarted"})
    print(json.dumps({"started": name, "chat": request["chat"], "exchange": request["exchange"]}), flush=True)
    return request


async def checked_signal(request, number):
    pid = request["process"]["pid"]
    observed = (await processes({pid}))[pid]
    require(observed == datetime.fromisoformat(request["process"]["startedAt"]), "Owned Trunk identity changed.")
    os.kill(pid, number)


def events(request):
    return [r["event"] for r in b.events if r.get("type") == "event" and r.get("id") == request["subscription"]]


async def saved(request, state, seconds=40):
    def probe():
        for e in reversed(events(request)):
            if e.get("kind") == "saved" and e.get("exchange", {}).get("exchange") == request["exchange"]:
                return e["exchange"]
            if e.get("kind") == "snapshot":
                for x in e.get("exchanges", []):
                    if x["exchange"] == request["exchange"] and x["state"] != "open":
                        return x
        return None

    value = await until(probe, seconds)
    require(value["state"] == state, "Unexpected actual saved end.")
    return value


async def clean_driver(r):
    pid = r["driverProcess"]["pid"]
    seen = (await processes({pid}))[pid]
    if seen is not None:
        require(seen == r["driverStarted"], "Driver process identity changed.")
        os.kill(pid, signal.SIGKILL)


async def run():
    global b
    roots = frame.command("arbol-roots", "list")
    require(next(x for x in roots if x["current"])["root"] == "jensen", "Current Root changed.")
    for r in roots:
        listing = frame.command("arbol-root", "--root", r["root"], "list")
        require(
            not listing["exchanges"] and not listing["unreadable"], "Foreign active work prevents controlled drills."
        )
    private_json(OUT / "preflight.json", roots)
    b = await Bridge.connect(ROOT / "backend.sock")
    try:
        stuck = await new("stuck")
        await checked_signal(stuck, signal.SIGSTOP)
        proof["stuckBegan"] = time.time()
        normal = await new("normal-stop")
        reply = await b.call("exchange.stop", {"exchange": normal["exchange"]})
        private_json(OUT / "normal-stop-reply.json", reply)
        require(
            reply.get("result", {}).get("ended") in ("cancelled", "saved"),
            "Normal stop must confirm cancelled or an already saved end.",
        )
        proof["normalStop"] = {
            "reply": reply,
            "saved": await saved(normal, "cancelled"),
            "stoppingObserved": any(
                e.get("kind") == "exchange" and e.get("exchange", {}).get("state") == "stopping" for e in events(normal)
            ),
        }
        print("Normal actual Root/Trunk stop saved cancelled.", flush=True)
        force = await new("forced-stop", "ignore-stop")
        await checked_signal(force, signal.SIGSTOP)
        reply = await b.call("exchange.stop", {"exchange": force["exchange"]})
        private_json(OUT / "forced-stop-reply.json", reply)
        proof["forcedStop"] = {"reply": reply, "saved": await saved(force, "interrupted")}
        require(reply.get("result", {}).get("ended") in ("interrupted", "saved"), "A forced stop must be interrupted.")
        print("Unobeyed actual Root/Trunk stop saved interrupted.", flush=True)
        gone = await new("gone")
        await checked_signal(gone, signal.SIGKILL)
        proof["gone"] = {"saved": await saved(gone, "interrupted", 65)}
        await clean_driver(gone)
        print("Gone actual Trunk settled interrupted.", flush=True)
        question = await new("question", "question")
        proof["question"] = question["chat"]
        private_json(OUT / "question-active.json", {k: v for k, v in question.items() if k != "driverStarted"})
        print("Question is active for actual browser answer proof. Type answered after UI finishes it.", flush=True)
        proof["stuckSaved"] = await saved(stuck, "interrupted", 150)
        proof["stuckEnded"] = time.time()
        await clean_driver(stuck)
        print("Actual unchanged heartbeat was forced and saved interrupted.", flush=True)
        key = await subscribe(stuck["chat"])
        await until(lambda: any(r.get("id") == key and r.get("event", {}).get("kind") == "snapshot" for r in b.events))
        snap = next(
            r["event"]
            for r in reversed(b.events)
            if r.get("id") == key and r.get("event", {}).get("kind") == "snapshot"
        )
        proof["stuckSnapshot"] = snap
        require(
            snap["exchanges"][0].get("note", {}).get("kind") == "ended_stuck", "A stuck end must have its saved note."
        )
        require(not proof["forcedStop"]["saved"].get("note"), "Manual force must not get a stuck note.")
        private_json(OUT / "step6-partial.json", proof)
        for r in owned:
            if r is question:
                continue
            require(not (ROOT / "exchanges" / r["exchange"]).exists(), "An ended controlled folder remains.")
        print("Waiting for question/browser verification; no vendor request.", flush=True)
        line = await asyncio.to_thread(sys.stdin.readline)
        require(line.strip() == "answered", "The question was not completed.")
        proof["questionSaved"] = await saved(question, "completed")
        private_json(OUT / "result.json", proof)
        print(json.dumps({"retainedFaultsPassed": True, "vendorRequests": 0}), flush=True)
    finally:
        private_json(OUT / "wire-events.json", b.events)
        for r in owned:
            try:
                if (ROOT / "exchanges" / r["exchange"]).exists():
                    await checked_signal(r, signal.SIGCONT)
                    await b.call("exchange.stop", {"exchange": r["exchange"]})
                await clean_driver(r)
            except Exception as e:
                print(json.dumps({"cleanupNeedsInspection": r["exchange"], "error": type(e).__name__}), flush=True)
        await b.close()


try:
    asyncio.run(run())
except BaseException as e:
    private_json(OUT / "failure.json", {"error": type(e).__name__, "message": str(e)})
    raise
