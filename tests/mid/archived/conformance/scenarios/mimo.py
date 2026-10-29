"""MIM-A1/A2 shared applicability through the shipped Mimo fixture entry.

No Driver module is imported. Native observations come from the fixture log;
common events and mutations come only from public subprocesses.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ..check import check, equal
from ..harness import ScenarioHome
from ..js import JSObject, parse
from ..process import invoke
from .runs import stream
from .stops import some_line, wait_for

MODEL = "arbol-mimo-fixture"
KEY = "arbol-mimo-fixture-disposable-only"


async def prepare(home: ScenarioHome) -> None:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in ("HOME", "USER", "LOGNAME", "PATH", "SHELL", "TERM", "TMPDIR", "LANG", "TZ", "ARBOL_MIMO_TEST_CANDIDATE")
    }
    result = await invoke(
        home.command,
        ["dev", "stand-in", home.tool, "--", "install"],
        cwd=home.home,
        env=environment,
        timeout_ms=home.timeout_ms,
        signal_=home.signal,
    )
    equal("Install synthetic native context", result["status"], 0)
    value = json.loads(result["stdout"])
    check("Pinned fixture native", value["nativeVersion"] in ("0.1.16", "0.1.16-arbol4"), "explicit native pin", value["nativeVersion"])
    Path(home.tool, "fixture-paths.json").write_text(json.dumps(value))
    home.command = [*home.command, "dev", "stand-in", home.tool, "--", "driver"]
    home.env["PATH"] = value["helperPath"] + ":" + home.env["PATH"]
    home.env["SHELL"] = "/bin/bash"
    home.env["ARBOL_TEST_TIME_SCALE"] = "1"
    home.timeout_ms = max(home.timeout_ms, 30000)


async def options(home: ScenarioHome, part: str = "plain", **values: Any) -> None:
    await home.part(part)
    Path(home.tool, "options.json").write_text(json.dumps(values))


async def signed(home: ScenarioHome, subscription: str = "xiaomi") -> None:
    value = await home.json(["subscriptions", "sign-in", subscription])
    equal("Attachment succeeds", value.process["status"], 0)
    equal("Attachment is complete", value.result["step"], "done")


def request_file(home: ScenarioHome, **fields: Any) -> Path:
    path = Path(home.tool, "request-" + uuid.uuid4().hex + ".json")
    path.write_text(
        json.dumps(
            {"tools": "none", "history": [], "input": {"role": "user", "text": "Synthetic caller prompt"}, **fields}
        )
    )
    return path


async def request(home: ScenarioHome, outcome: str = "completed", **fields: Any) -> Any:
    reply = await home.call(["run", "--request", str(request_file(home, **fields))])
    expected = 0 if outcome == "completed" else 1 if outcome == "failed" else 2
    check("Native run exit", reply["status"] == expected, expected, reply)
    return list(stream(reply, outcome))


async def inputs(home: ScenarioHome) -> list[JSObject]:
    return [r for r in await home.received() if r.get("stage") == "input"]


async def event(active: Any, kind: str, count: int = 1) -> JSObject:
    await wait_for(
        kind, some_line(active.lines, lambda _: len([e for e in active.lines if e.get("type") == kind]) >= count), 20000
    )
    return JSObject([e for e in active.lines if e.get("type") == kind][count - 1])


async def failure(home: ScenarioHome, args: list[str], code: str) -> None:
    reply = await home.json(args)
    equal("Typed refusal exit", reply.process["status"], 1)
    equal("Typed refusal code", reply.result["error"]["code"], code)


async def account(home: ScenarioHome, identifier: str = "xiaomi") -> JSObject:
    rows = parse((await home.call(["subscriptions", "list"]))["stdout"])
    return JSObject(next(row for row in rows if row["id"] == identifier))


async def pending(home: ScenarioHome, killed: bool = False) -> None:
    await options(home, "pending", authDelayMs=10000)
    active = home.start(["subscriptions", "sign-in", "xiaomi"])
    try:

        async def seen() -> bool:
            return any(r.get("stage") == "authentication" for r in await home.received())

        await wait_for("Real pending native attachment", seen)
        current = await account(home)
        equal("Pending is visible", current["state"], "signing_in")
        await failure(home, ["subscriptions", "sign-in", "xiaomi", "--by-code"], "unsupported")
        if killed:
            active.child.kill("SIGKILL")
            await active.done
            equal("Dead attempt is recovered", (await account(home))["state"], "signed_out")
        else:
            await options(home, "replacement")
            await signed(home)
            replaced = await active.done
            equal("Old attachment is fenced", json.loads(replaced["stdout"])["error"]["code"], "in_use")
    finally:
        await active.dispose()
    if not killed:
        home.env["ARBOL_TEST_TIME_SCALE"] = "60"
        await options(home, "pending", authDelayMs=10000)
        expired = home.start(["subscriptions", "sign-in", "xiaomi"])
        try:
            reply = await expired.done
            equal("Expired attempt cannot publish late success", json.loads(reply["stdout"])["error"]["code"], "in_use")
            equal("Five-minute scaled attempt expires", (await account(home))["state"], "signed_out")
        finally:
            await expired.dispose()
            home.env["ARBOL_TEST_TIME_SCALE"] = "1"


async def errors(home: ScenarioHome, status: int) -> None:
    await signed(home)
    await options(home, "error", status=status, retryAfter="2", error="Synthetic refusal")
    records = await request(home, "failed")
    code = "credential_rejected" if status == 401 else "rate_limited" if status == 429 else "vendor_unavailable"
    equal("First native error is retained", records[-1]["error"]["code"], code)
    if status == 429:
        equal("Explicit vendor wait uses seconds", records[-1]["error"].get("retryAfterSeconds"), 2)
    equal("Only credential rejection marks the binding", (await account(home))["state"], "needs_attention" if status == 401 else "signed_in")
    await asyncio.sleep(2.2)
    equal("No advertised native retry escaped abort", len(await inputs(home)), 1)


async def asynchronous_error(home: ScenarioHome) -> None:
    await signed(home)
    await options(home, streamError=True)
    records = await request(home, "failed")
    check("Successful HTTP cannot hide a native stream error", records[-1]["error"]["code"] == "vendor_error", "vendor_error", records)
    equal("Async refusal is never replayed", len(await inputs(home)), 1)


async def concurrent(home: ScenarioHome) -> None:
    # Start from stable owner discovery. Otherwise the first native process may
    # create its project ignore while its sibling is still capturing resources;
    # refusing that changed capture is the separate F8 boundary.
    native_config = Path(home.home, ".mimocode")
    native_config.mkdir()
    (native_config / ".gitignore").write_text("node_modules\npackage.json\npackage-lock.json\nbun.lock\n.gitignore\n.cron-lock\nscheduled_tasks.json")
    await signed(home)
    await options(home, delayMs=500)
    first, second = await asyncio.gather(
        request(home, runId="one", workingDirectory=home.home), request(home, runId="two", workingDirectory=home.home)
    )
    equal("Concurrent IDs remain isolated", sorted([first[-1]["runId"], second[-1]["runId"]]), ["one", "two"])
    equal("Both actual native turns ran", len(await inputs(home)), 2)
    await options(home, text=base64.b64encode(os.urandom(150000)).decode())
    slow = home.start(["run", "--request", str(request_file(home, runId="slow", workingDirectory=home.home))])
    slow.child.stdout.pause()
    try:
        async def observed() -> bool:
            return len(await inputs(home)) >= 3
        await wait_for("Slow peer reached actual provider", observed, 20000)
        await options(home, status=503)
        bad = await request(home, "failed", runId="failed-peer", workingDirectory=home.home)
        equal("Failed sibling is isolated", bad[-1]["error"]["code"], "vendor_unavailable")
        await options(home, text="independent-success")
        good = await request(home, runId="good-peer", workingDirectory=home.home)
        equal("A blocked reader cannot block a sibling", good[-1]["outcome"], "completed")
    finally:
        slow.child.stdout.resume()
        await slow.dispose()


async def secrets(home: ScenarioHome) -> None:
    await signed(home)
    await options(home, text="Visible " + KEY + " end", fragmentBytes=3)
    records = await request(home)
    wire = json.dumps(records)
    equal("Complete secret removed from common output", KEY in wire, False)
    check("Redaction is visible", "[REDACTED]" in wire, "redacted marker", records)
    reply = await home.call(["run", "--output", "text", "synthetic prompt"])
    equal("Text mode exits successfully", reply["status"], 0)
    equal("Text mode does not reveal the key", KEY in reply["stdout"] + reply["stderr"], False)
    state = Path((await home.json(["info"])).result["stateDirectory"])
    for file in state.rglob("*.json"):
        equal("Driver state never stores credential bytes", KEY.encode() in file.read_bytes(), False)


async def environment(home: ScenarioHome) -> None:
    await signed(home)
    home.env["OPENAI_API_KEY"] = "synthetic-competing-provider"
    home.env["CODEX_HOME"] = "synthetic-competing-home"
    command = 'printf "%s|%s" "${OPENAI_API_KEY-unset}" "${CODEX_HOME-unset}"'
    await options(
        home, calls=[{"name": "bash", "arguments": {"command": command, "description": "Inspect filtered environment"}}]
    )
    records = await request(home, tools="all", workingDirectory=home.home)
    check(
        "Competing provider inputs do not reach native commands",
        "unset|unset" in json.dumps(records),
        "unset|unset",
        records,
    )
    equal("Other provider value absent", "synthetic-competing-provider" in json.dumps(records), False)


async def context(home: ScenarioHome, skill: bool = False) -> None:
    work = Path(home.home, "project")
    work.mkdir()
    extra = Path(home.home, "extra")
    extra.mkdir()
    instructions = work / "AGENTS.md"
    instructions.write_text("OWNER_INSTRUCTION_SENTINEL\n")
    before = instructions.read_bytes()
    values: dict[str, Any] = {
        "expect": {"owner": "OWNER_INSTRUCTION_SENTINEL", "caller": "CALLER_CONTEXT_SENTINEL", "additional": str(extra)}
    }
    if skill:
        directory = work / ".mimocode/skills/shared-fixture"
        directory.mkdir(parents=True)
        (work / ".mimocode/.gitignore").write_text("node_modules\npackage.json\nbun.lock\nbun.lockb\n")
        file = directory / "SKILL.md"
        file.write_text(
            "---\nname: shared-fixture\ndescription: A synthetic qualification skill\n---\nSKILL_BODY_SENTINEL\n"
        )
        values["calls"] = [{"name": "skill", "arguments": {"name": "shared-fixture"}}]
    await signed(home)
    await options(home, **values)
    records = await request(
        home,
        workingDirectory=str(work),
        systemPrompt="CALLER_CONTEXT_SENTINEL",
        additionalDirectories=[str(extra)],
        tools="all" if skill else "none",
    )
    equal(
        "Native system retains owner and additive caller context",
        (await inputs(home))[0]["checks"]["expect"],
        {"owner": True, "caller": True, "additional": True},
    )
    equal("Owner instructions are unchanged", instructions.read_bytes().hex(), before.hex())
    if skill:
        check(
            "Actual native skill result survives",
            "SKILL_BODY_SENTINEL" in json.dumps(records),
            "native skill body",
            records,
        )


async def history(home: ScenarioHome) -> None:
    work = Path(home.home, "project")
    work.mkdir()
    await signed(home)
    await options(home, text="first-reply")
    first = await request(
        home, workingDirectory=str(work), chatSessionId="shared-history", input={"role": "user", "text": "first-user"}
    )
    equal("First conversation is fresh", next(r for r in first if r["type"] == "started")["continuity"], "fresh")
    prior = [
        {"type": "message", "role": "user", "text": "first-user"},
        {"type": "message", "role": "assistant", "text": "first-reply"},
    ]
    await options(
        home, "history", text="second-reply", expect={"earlierUser": "first-user", "earlierReply": "first-reply"}
    )
    second = await request(
        home,
        workingDirectory=str(work),
        chatSessionId="shared-history",
        history=prior,
        input={"role": "user", "text": "second-user"},
    )
    check("Resume diagnostics", next(r for r in second if r["type"] == "started")["continuity"] == "resumed", "resumed", second)
    equal(
        "Actual native request retains prior caller history",
        (await inputs(home))[-1]["checks"]["expect"],
        {"earlierUser": True, "earlierReply": True},
    )
    prior.extend([{"type":"message","role":"user","text":"second-user"}, {"type":"message","role":"assistant","text":"second-reply"}])
    await options(home, "fork")
    forked = await request(
        home,
        workingDirectory=str(work),
        chatSessionId="shared-history",
        history=prior,
        systemPrompt="Changed caller prompt",
        input={"role": "user", "text": "forked-user"},
    )
    equal(
        "Changed prompt rebuilds instead of unsafe reuse",
        next(r for r in forked if r["type"] == "started")["continuity"],
        "rebuilt",
    )
    equal("Rebuild reason is visible", next(r for r in forked if r["type"]=="started")["rebuildReason"], "system_prompt_changed")


QUESTION = {
    "questions": [
        {
            "question": "Choose one",
            "header": "First",
            "options": [{"label": "A", "description": "First"}, {"label": "B", "description": "Second"}],
            "multiple": False,
        },
        {
            "question": "Choose several",
            "header": "Second",
            "options": [{"label": "X", "description": "First"}, {"label": "Y", "description": "Second"}],
            "multiple": True,
        },
    ]
}


async def clocks(home: ScenarioHome) -> None:
    await signed(home)
    for name, limits in [
        ("idle", {"idleSeconds": 0.2, "totalSeconds": 10}),
        ("total", {"idleSeconds": 0, "totalSeconds": 4}),
    ]:
        await options(home, silent=True)
        started = time.monotonic()
        records = await request(home, "failed", workingDirectory=home.home, limits=limits)
        equal("Limit classification", records[-1]["error"]["code"], "limit_reached")
        equal("Independent limit kind", records[-1]["error"]["detail"]["limit"], name)
        if name == "total":
            check(
                "Request total is not shortened by native fixed-wait scale",
                time.monotonic() - started >= 4,
                ">=4 seconds",
                time.monotonic() - started,
            )
    await options(
        home,
        calls=[
            {
                "name": "bash",
                "arguments": {
                    "command": "sleep .5; printf idle-was-paused",
                    "description": "Pause idle during actual work",
                },
            }
        ],
    )
    records = await request(
        home, tools="all", workingDirectory=home.home, limits={"idleSeconds": 0.2, "totalSeconds": 15}
    )
    check("Actual native tool work suspends idle", "idle-was-paused" in json.dumps(records), "shell result", records)


async def recovery(home: ScenarioHome) -> None:
    await signed(home)
    await options(
        home,
        calls=[
            {
                "name": "bash",
                "arguments": {"command": "sleep 60", "description": "Native owned work surviving controller death"},
            }
        ],
    )
    active = home.start(
        [
            "run",
            "--control",
            "--request",
            str(request_file(home, tools="all", workingDirectory=home.home, runId="killed",
                             input={"role": "user", "text": "KILLED_OWNER_PROMPT_SENTINEL"})),
        ]
    )
    try:
        await event(active, "tool_started")
        active.child.kill("SIGKILL")
        await active.done
        first, second = await asyncio.gather(home.call(["runs", "list"]), home.call(["runs", "list"]))
        # One competing cleaner may report in_use; the eventual public inventory must be empty.
        check(
            "A recovery owner completed",
            first["status"] == 0 or second["status"] == 0,
            "one cleaner completes",
            [first, second],
        )
        equal(
            "Killed run is retired after independent cleanup", parse((await home.call(["runs", "list"]))["stdout"]), []
        )
        equal("Recovery never resubmits the provider prompt", len(await inputs(home)), 1)
        await options(home, expect={"old": "KILLED_OWNER_PROMPT_SENTINEL", "new": "NEW_OWNER_PROMPT_SENTINEL"})
        await request(home, workingDirectory=home.home, input={"role": "user", "text": "NEW_OWNER_PROMPT_SENTINEL"})
        equal("Fresh native startup cannot adopt the old queue", (await inputs(home))[-1]["checks"]["expect"], {"old": False, "new": True})
        equal("Only the new prompt is submitted after recovery", len(await inputs(home)), 2)
    finally:
        await active.dispose()


async def partial_failure(home: ScenarioHome) -> None:
    await signed(home)
    await options(
        home,
        calls=[
            {
                "name": "bash",
                "arguments": {"command": "printf retained-tool-result", "description": "Tool before provider failure"},
            }
        ],
        prefixText="retained-early-text",
        afterCallsStatus=503,
        usage={"prompt_tokens": 17, "completion_tokens": 11, "total_tokens": 28},
    )
    records = await request(home, "failed", tools="all", workingDirectory=home.home)
    check(
        "Early complete prose survives later failure",
        any(r.get("type") == "text" and "retained-early-text" in r.get("text", "") for r in records),
        "early prose",
        records,
    )
    equal("Observed usage survives the later failure", records[-1]["usage"]["inputTokens"], 17)
    equal(
        "Started native tool closes exactly once",
        len([r for r in records if r["type"] == "tool_started"]),
        len([r for r in records if r["type"] == "tool_finished"]),
    )
    equal("Failed follow-up is not retried", len(await inputs(home)), 2)


async def account_isolation(home: ScenarioHome) -> None:
    await signed(home)
    await home.json(["subscriptions", "create", "--family", "xiaomi", "--label", "Separate synthetic test", "--id", "test-xiaomi"])
    await signed(home, "test-xiaomi")
    await home.json(["subscriptions", "update", "test-xiaomi", "--label", "Test relabel"])
    equal("Test label does not change production binding", (await account(home))["label"], "Xiaomi MiMo")
    await failure(home, ["subscriptions", "create", "--family", "xiaomi", "--label", "Forbidden second production", "--id", "xiaomi-2"], "invalid_input")
    paths = json.loads(Path(home.tool, "fixture-paths.json").read_text())
    auth = Path(paths["authFile"])
    original = auth.read_bytes()
    changed = json.loads(original)
    changed["xiaomi"]["metadata"]["uid"] = "changed-synthetic-account"
    auth.write_text(json.dumps(changed))
    before = len(await inputs(home))
    try:
        await failure(home, ["subscriptions", "check", "xiaomi"], "not_signed_in")
        equal("A UID switch cannot silently rebind another record", (await account(home, "test-xiaomi"))["state"], "signed_in")
        equal("Account switch starts no inference", len(await inputs(home)), before)
        equal("Native auth remains owned by native", json.loads(auth.read_text()), changed)
    finally:
        auth.write_bytes(original)


SCOPES = {
    "C6": "killed pending attachment and durable attempt recovery",
    "C7": "native provider secret redaction before common output",
    "C8": "competing inherited provider configuration is stripped",
    "C12": "asynchronous provider error under HTTP success cannot become native success",
    "C14": "native continuation/rebuild and exact completed-history projection",
    "C18": "concurrent native runs, failed sibling and blocked output retain independent results",
    "C28": "first credential rejection stops native retry",
    "C29": "unscaled request total/idle limits",
    "C37": "unchanged owner instructions and actual native skill discovery",
    "C38": "killed run ownership and retained-group recovery",
    "C39": "MIM-A1 second-production refusal, isolated test record and changed-native-UID fencing",
    "C42": "failure after partial output retains closed/unfinished calls and usage",
}


async def run(home: ScenarioHome) -> None:
    handlers: dict[str, Callable[[ScenarioHome], Awaitable[None]]] = {
        "C6": lambda h: pending(h, True),
        "C7": secrets,
        "C8": environment,
        "C14": history,
        "C29": clocks,
        "C37": lambda h: context(h, True),
        "C38": recovery,
        "C42": partial_failure,
        "C12": asynchronous_error,
        "C18": concurrent,
        "C28": lambda h: errors(h, 401),
        "C39": account_isolation,
    }
    handler = handlers.get(home.id)
    if handler is None:
        raise RuntimeError(f"Mimo {home.id} is still unqualified: {SCOPES[home.id]}")
    await handler(home)
