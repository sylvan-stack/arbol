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

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C1
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C1: MIM-A1 local default/relabel and explicit second-production-account refusal
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C1": "MIM-A1 local default/relabel and explicit second-production-account refusal",
#         "C1": local_records,
#
# async def local_records(home: ScenarioHome) -> None:
#     families = parse((await home.call(["subscriptions", "families"]))["stdout"])
#     equal("Exactly the native Xiaomi family", [r["id"] for r in families], ["xiaomi"])
#     equal("Native login semantics", families[0]["auth"], "vendor_login")
#     initial = await account(home)
#     equal("Initial binding is unsigned", initial["state"], "signed_out")
#     await failure(
#         home,
#         ["subscriptions", "create", "--family", "xiaomi", "--label", "Second", "--id", "xiaomi-2"],
#         "invalid_input",
#     )
#     changed = await home.json(["subscriptions", "update", "xiaomi", "--label", "Relabelled"])
#     equal("Local label changes", changed.result["label"], "Relabelled")
#     equal(
#         "No native authentication for local records",
#         [r for r in await home.received() if r.get("stage") != "install"],
#         [],
#     )
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C2
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C2: real pending attachment, replacement, five-minute scaled expiry and device-code refusal
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C2": "real pending attachment, replacement, five-minute scaled expiry and device-code refusal",
#         "C2": pending,
#
# async def pending(home: ScenarioHome, killed: bool = False) -> None:
#     await options(home, "pending", authDelayMs=10000)
#     active = home.start(["subscriptions", "sign-in", "xiaomi"])
#     try:
#
#         async def seen() -> bool:
#             return any(r.get("stage") == "authentication" for r in await home.received())
#
#         await wait_for("Real pending native attachment", seen)
#         current = await account(home)
#         equal("Pending is visible", current["state"], "signing_in")
#         await failure(home, ["subscriptions", "sign-in", "xiaomi", "--by-code"], "unsupported")
#         if killed:
#             active.child.kill("SIGKILL")
#             await active.done
#             equal("Dead attempt is recovered", (await account(home))["state"], "signed_out")
#         else:
#             await options(home, "replacement")
#             await signed(home)
#             replaced = await active.done
#             equal("Old attachment is fenced", json.loads(replaced["stdout"])["error"]["code"], "in_use")
#     finally:
#         await active.dispose()
#     if not killed:
#         home.env["ARBOL_TEST_TIME_SCALE"] = "60"
#         await options(home, "pending", authDelayMs=10000)
#         expired = home.start(["subscriptions", "sign-in", "xiaomi"])
#         try:
#             reply = await expired.done
#             equal("Expired attempt cannot publish late success", json.loads(reply["stdout"])["error"]["code"], "in_use")
#             equal("Five-minute scaled attempt expires", (await account(home))["state"], "signed_out")
#         finally:
#             await expired.dispose()
#             home.env["ARBOL_TEST_TIME_SCALE"] = "1"
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C3
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C3: MIM-A2 malformed native-owned credential refuses without deletion
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C3": "MIM-A2 malformed native-owned credential refuses without deletion",
#         "C3": malformed,
#
# async def malformed(home: ScenarioHome) -> None:
#     paths = json.loads(Path(home.tool, "fixture-paths.json").read_text())
#     file = Path(paths["authFile"])
#     value = json.loads(file.read_text())
#     value["xiaomi"]["key"] = "invalid-é"
#     file.write_text(json.dumps(value))
#     before = file.read_bytes()
#     result = await home.json(["subscriptions", "sign-in", "xiaomi"])
#     equal("Malformed native key refuses", result.result["error"]["code"], "invalid_input")
#     equal("Native credentials remain untouched", file.read_bytes().hex(), before.hex())
#     equal("No authenticated request", [r for r in await home.received() if r.get("stage") != "install"], [])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C4
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C4: rejection/attention state and fresh-check repair
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C4": "rejection/attention state and fresh-check repair",
#         "C4": rejection,
#
# async def rejection(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, "rejected", authRejected=True)
#     await failure(home, ["subscriptions", "check", "xiaomi"], "credential_rejected")
#     equal("Rejection changes binding state", (await account(home))["state"], "needs_attention")
#     await options(home, "repair")
#     await home.json(["subscriptions", "check", "xiaomi"])
#     equal("Fresh successful check repairs binding", (await account(home))["state"], "signed_in")
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C5
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C5: native-owned destructive refusal leaves active run untouched
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C5": "native-owned destructive refusal leaves active run untouched",
#         "C5": active_refusal,
#
# async def active_refusal(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, "active", silent=True)
#     active = home.start(
#         ["run", "--control", "--request", str(request_file(home, runId="active-refusal", workingDirectory=home.home))]
#     )
#     try:
#         await event(active, "started")
#         for operation in ("remove", "sign-out"):
#             for extra in ([], ["--force"]):
#                 await failure(home, ["subscriptions", operation, "xiaomi", *extra], "invalid_input")
#                 equal("Native-owned refusal leaves live work running", active.done.done(), False)
#         active.send({"type": "stop"})
#         stream(await active.done, "cancelled")
#         equal("Binding remains attached", (await account(home))["state"], "signed_in")
#     finally:
#         await active.dispose()
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C9
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C9: native instructions plus additive caller context and unchanged source
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C9": "native instructions plus additive caller context and unchanged source",
#         "C9": context,
#
# async def context(home: ScenarioHome, skill: bool = False) -> None:
#     work = Path(home.home, "project")
#     work.mkdir()
#     extra = Path(home.home, "extra")
#     extra.mkdir()
#     instructions = work / "AGENTS.md"
#     instructions.write_text("OWNER_INSTRUCTION_SENTINEL\n")
#     before = instructions.read_bytes()
#     values: dict[str, Any] = {
#         "expect": {"owner": "OWNER_INSTRUCTION_SENTINEL", "caller": "CALLER_CONTEXT_SENTINEL", "additional": str(extra)}
#     }
#     if skill:
#         directory = work / ".mimocode/skills/shared-fixture"
#         directory.mkdir(parents=True)
#         (work / ".mimocode/.gitignore").write_text("node_modules\npackage.json\nbun.lock\nbun.lockb\n")
#         file = directory / "SKILL.md"
#         file.write_text(
#             "---\nname: shared-fixture\ndescription: A synthetic qualification skill\n---\nSKILL_BODY_SENTINEL\n"
#         )
#         values["calls"] = [{"name": "skill", "arguments": {"name": "shared-fixture"}}]
#     await signed(home)
#     await options(home, **values)
#     records = await request(
#         home,
#         workingDirectory=str(work),
#         systemPrompt="CALLER_CONTEXT_SENTINEL",
#         additionalDirectories=[str(extra)],
#         tools="all" if skill else "none",
#     )
#     equal(
#         "Native system retains owner and additive caller context",
#         (await inputs(home))[0]["checks"]["expect"],
#         {"owner": True, "caller": True, "additional": True},
#     )
#     equal("Owner instructions are unchanged", instructions.read_bytes().hex(), before.hex())
#     if skill:
#         check(
#             "Actual native skill result survives",
#             "SKILL_BODY_SENTINEL" in json.dumps(records),
#             "native skill body",
#             records,
#         )
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C10
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C10: fragmented native UTF-8, exact ID/labels and complete blocks
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C10": "fragmented native UTF-8, exact ID/labels and complete blocks",
#         "C10": plain,
#
# async def plain(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, fragmentBytes=7, text="Visible 👋 complete block")
#     records = await request(home, labels={"check": home.id}, runId="exact-request-id")
#     equal("Exact requested ID", records[-1]["runId"], "exact-request-id")
#     equal("Caller labels survive every event", all(r.get("labels") == {"check": home.id} for r in records), True)
#     equal(
#         "Only complete text block", [r["text"] for r in records if r["type"] == "text"], ["Visible 👋 complete block"]
#     )
#     equal("Native request observed once", len(await inputs(home)), 1)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C11
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C11: actual native shell command/result and paired public calls
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C11": "actual native shell command/result and paired public calls",
#         "C11": shell,
#
# async def shell(home: ScenarioHome, large: bool = False, failed: bool = False) -> None:
#     await signed(home)
#     command = (
#         "printf native-shell-result; exit 7"
#         if failed
#         else ("python3 -c \"print('é' * 130000)\"" if large else "printf native-shell-result")
#     )
#     await options(
#         home,
#         "tools",
#         calls=[{"name": "bash", "arguments": {"command": command, "description": "Synthetic shared shell"}}],
#         prefixText="before-native-tool" if not large and not failed else "",
#     )
#     records = await request(home, tools="all", workingDirectory=home.home)
#     started = [r for r in records if r["type"] == "tool_started"]
#     finished = [r for r in records if r["type"] == "tool_finished"]
#     equal("One native shell call", len(started), 1)
#     equal("Tool calls balance", [r["callId"] for r in started], [r["callId"] for r in finished])
#     equal("Original command is preserved", started[0]["input"]["command"], command)
#     if large:
#         equal("Native or common truncation is disclosed", finished[0].get("truncated"), True)
#         check(
#             "Result is bounded",
#             len(json.dumps(finished[0], ensure_ascii=False).encode()) <= 205500,
#             "bounded result",
#             finished[0],
#         )
#     elif failed:
#         equal("Failed shell remains a tool result", finished[0]["ok"], False)
#     else:
#         check(
#             "Real shell output is retained",
#             "native-shell-result" in json.dumps(finished[0]),
#             "native shell result",
#             finished[0],
#         )
#         first = next(i for i, row in enumerate(records) if row["type"] == "tool_started")
#         last = next(i for i, row in enumerate(records) if row["type"] == "tool_finished")
#         equal("Complete native prose precedes tool admission", any(r["type"] == "text" and "before-native-tool" in r["text"] for r in records[:first]), True)
#         equal("Complete native prose follows tool completion", any(r["type"] == "text" for r in records[last + 1:]), True)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C13
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C13: native usage and absence of fabricated monetary cost
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C13": "native usage and absence of fabricated monetary cost",
#         "C13": usage,
#
# async def usage(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(
#         home,
#         usage={
#             "prompt_tokens": 17,
#             "completion_tokens": 11,
#             "total_tokens": 28,
#             "prompt_tokens_details": {"cached_tokens": 3},
#             "completion_tokens_details": {"reasoning_tokens": 5},
#         },
#     )
#     records = await request(home)
#     reports = [r for r in records if r["type"] == "usage"]
#     check("Native usage is reported", bool(reports), "native usage event", records)
#     equal("Inclusive input tokens", reports[-1]["usage"]["inputTokens"], 17)
#     equal("Inclusive output tokens", reports[-1]["usage"]["outputTokens"], 11)
#     check("No fabricated cost", "cost" not in reports[-1], "cost absent", reports[-1])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C15
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C15: control cancellation during actual shell work and bounded balanced cleanup
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C15": "control cancellation during actual shell work and bounded balanced cleanup",
#         "C15": stop,
#
# async def stop(home: ScenarioHome, mode: str = "control") -> None:
#     await signed(home)
#     await options(
#         home,
#         "active",
#         calls=[{"name": "bash", "arguments": {"command": "sleep 60", "description": "Owned sleeping shell"}}],
#     )
#     path = request_file(home, tools="all", workingDirectory=home.home, runId="stopped")
#     active = home.start(["run", "--control", "--request", str(path)])
#     try:
#         await event(active, "tool_started")
#         started = time.monotonic()
#         if mode == "signal":
#             active.child.kill("SIGTERM")
#         elif mode == "eof":
#             active.child.stdin.end()
#         else:
#             active.send({"type": "stop"})
#         reply = await active.done
#         check("Cancelled process exits coherently", reply["status"] == 2, 2, reply)
#         records = list(stream(reply, "cancelled"))
#         check("Bounded cleanup", time.monotonic() - started <= 15, "<=15s", time.monotonic() - started)
#         equal(
#             "Interrupted tool is balanced",
#             len([r for r in records if r["type"] == "tool_started"]),
#             len([r for r in records if r["type"] == "tool_finished"]),
#         )
#         equal("Run reservation retired", parse((await home.call(["runs", "list"]))["stdout"]), [])
#     finally:
#         await active.dispose()
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C16
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C16: idempotent public stop for unknown and retired runs
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C16": "idempotent public stop for unknown and retired runs",
#         "C16": idempotent,
#
# async def idempotent(home: ScenarioHome) -> None:
#     await home.call(["runs", "stop", "unknown"])
#     await home.call(["runs", "stop", "unknown"])
#     await signed(home)
#     await request(home, runId="ended")
#     equal("Stop of completed run", (await home.call(["runs", "stop", "ended"]))["status"], 0)
#     equal("No stale active runs", parse((await home.call(["runs", "list"]))["stdout"]), [])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C17
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C17: signal/EOF cleanup during actual shell work
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C17": "signal/EOF cleanup during actual shell work",
#         "C17": signal_and_eof,
#
# async def signal_and_eof(home: ScenarioHome) -> None:
#     await stop(home, "signal")
#     await stop(home, "eof")
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C19
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C19: actual empty tool set and ephemeral run retirement
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C19": "actual empty tool set and ephemeral run retirement",
#         "C19": tools_off,
#
# async def tools_off(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, text="ready")
#     await request(home)
#     equal("Actual native model tool set is empty", (await inputs(home))[-1]["checks"]["tools"], [])
#     equal("No public active runs after ephemeral cleanup", parse((await home.call(["runs", "list"]))["stdout"]), [])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C20
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C20: large multibyte native shell result stays bounded
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C20": "large multibyte native shell result stays bounded",
#         "C20": lambda h: shell(h, True),
#
# async def shell(home: ScenarioHome, large: bool = False, failed: bool = False) -> None:
#     await signed(home)
#     command = (
#         "printf native-shell-result; exit 7"
#         if failed
#         else ("python3 -c \"print('é' * 130000)\"" if large else "printf native-shell-result")
#     )
#     await options(
#         home,
#         "tools",
#         calls=[{"name": "bash", "arguments": {"command": command, "description": "Synthetic shared shell"}}],
#         prefixText="before-native-tool" if not large and not failed else "",
#     )
#     records = await request(home, tools="all", workingDirectory=home.home)
#     started = [r for r in records if r["type"] == "tool_started"]
#     finished = [r for r in records if r["type"] == "tool_finished"]
#     equal("One native shell call", len(started), 1)
#     equal("Tool calls balance", [r["callId"] for r in started], [r["callId"] for r in finished])
#     equal("Original command is preserved", started[0]["input"]["command"], command)
#     if large:
#         equal("Native or common truncation is disclosed", finished[0].get("truncated"), True)
#         check(
#             "Result is bounded",
#             len(json.dumps(finished[0], ensure_ascii=False).encode()) <= 205500,
#             "bounded result",
#             finished[0],
#         )
#     elif failed:
#         equal("Failed shell remains a tool result", finished[0]["ok"], False)
#     else:
#         check(
#             "Real shell output is retained",
#             "native-shell-result" in json.dumps(finished[0]),
#             "native shell result",
#             finished[0],
#         )
#         first = next(i for i, row in enumerate(records) if row["type"] == "tool_started")
#         last = next(i for i, row in enumerate(records) if row["type"] == "tool_finished")
#         equal("Complete native prose precedes tool admission", any(r["type"] == "text" and "before-native-tool" in r["text"] for r in records[:first]), True)
#         equal("Complete native prose follows tool completion", any(r["type"] == "text" for r in records[last + 1:]), True)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C25
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C25: native permission handling through production hooks
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C25": "native permission handling through production hooks",
#         "C25": permission,
#
# async def permission(home: ScenarioHome) -> None:
#     # Native irreversible-delete confirmation remains distinct from question asks.
#     victim = Path(home.home, "delete-me")
#     victim.write_text("disposable")
#     await signed(home)
#     await options(
#         home,
#         calls=[
#             {
#                 "name": "bash",
#                 "arguments": {"command": "rm " + str(victim), "description": "Synthetic forced delete confirmation"},
#             }
#         ],
#     )
#     records = await request(home, tools="all", workingDirectory=home.home)
#     equal("Recognized native delete permission is approved", victim.exists(), False)
#     equal("Permission is never a public question", len([r for r in records if r["type"] == "ask_opened"]), 0)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C26
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C26: native structured failure classification
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C26": "native structured failure classification",
#         "C26": classification,
#
# async def classification(home: ScenarioHome) -> None:
#     for status, kind, code in [
#         (400, "context_length_exceeded", "context_exceeded"),
#         (413, "fixture_error", "context_exceeded"),
#         (403, "invalid_api_key", "credential_rejected"),
#         (403, "permission_denied", "vendor_error"),
#         (404, "fixture_error", "vendor_error"),
#         (422, "fixture_error", "vendor_error"),
#         (500, "fixture_error", "vendor_unavailable"),
#         (503, "context_length_exceeded", "vendor_unavailable"),
#     ]:
#         await signed(home)
#         await options(home, status=status, errorCode=kind, error="rate authentication misleading prose")
#         before = len(await inputs(home))
#         records = await request(home, "failed")
#         problem = records[-1]["error"]
#         equal("Structured native classification", problem["code"], code)
#         equal("Native fields outrank message wording", problem["detail"]["basis"], "fields")
#         equal("Retry policy is explicit", problem["retryable"], code == "vendor_unavailable")
#         equal("One provider attempt per refusal", len(await inputs(home)) - before, 1)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C27
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C27: first rate rejection stops native retry
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C27": "first rate rejection stops native retry",
#         "C27": lambda h: errors(h, 429),
#
# async def errors(home: ScenarioHome, status: int) -> None:
#     await signed(home)
#     await options(home, "error", status=status, retryAfter="2", error="Synthetic refusal")
#     records = await request(home, "failed")
#     code = "credential_rejected" if status == 401 else "rate_limited" if status == 429 else "vendor_unavailable"
#     equal("First native error is retained", records[-1]["error"]["code"], code)
#     if status == 429:
#         equal("Explicit vendor wait uses seconds", records[-1]["error"].get("retryAfterSeconds"), 2)
#     equal("Only credential rejection marks the binding", (await account(home))["state"], "needs_attention" if status == 401 else "signed_in")
#     await asyncio.sleep(2.2)
#     equal("No advertised native retry escaped abort", len(await inputs(home)), 1)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C30
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C30: observed run tokens never fabricate native allowance windows or polling
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C30": "observed run tokens never fabricate native allowance windows or polling",
#         "C30": latest_allowance,
#
# async def latest_allowance(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, usage={"prompt_tokens": 17, "completion_tokens": 11, "total_tokens": 28})
#     records = await request(home)
#     equal("Actual token usage is retained", records[-1]["usage"]["inputTokens"], 17)
#     before = len(await home.received())
#     allowance = (await home.json(["subscriptions", "usage", "xiaomi"])).result
#     equal("Run tokens do not fabricate quota windows", [allowance["outcome"], allowance["windows"]], ["unsupported", []])
#     equal("Unsupported allowance starts no native operation", len(await home.received()), before)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C31
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C31: unqualified native binary/profile refusal
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C31": "unqualified native binary/profile refusal",
#         "C31": native_refusal,
#
# async def native_refusal(home: ScenarioHome) -> None:
#     await signed(home)
#     file = Path(home.tool, "fixture-manifest.json")
#     manifest = json.loads(file.read_text())
#     for target, code in [
#         (str(Path(home.tool, "missing-native")), "tool_missing"),
#         (str(Path(home.tool, "fake-native")), "tool_unsupported"),
#     ]:
#         fake = Path(home.tool, "fake-native")
#         fake.write_text('#!/bin/sh\ntouch "' + home.tool + '/must-not-execute"\n')
#         fake.chmod(0o700)
#         manifest["binary"] = target
#         file.write_text(json.dumps(manifest))
#         records = await request(home, "failed")
#         equal("Native profile refusal", records[-1]["error"]["code"], code)
#         equal("Unqualified code was never started", Path(home.tool, "must-not-execute").exists(), False)
#     equal("Native binary refusals spend no inference", await inputs(home), [])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C32
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C32: enabled release CLI plus synthetic native development orchestration without real-provider calls
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C32": "enabled release CLI plus synthetic native development orchestration without real-provider calls",
#         "C32": development,
#
# async def development(home: ScenarioHome) -> None:
#     identity = (await home.json(["info"])).result
#     equal("Mimo contract identity", [identity["driver"], identity["contract"]], ["mimo", 2])
#     equal("Qualified public execution is enabled", identity["capabilities"], {"inference": True, "nativeAttachment": True})
#     await home.json(
#         ["subscriptions", "create", "--family", "xiaomi", "--label", "Synthetic test", "--id", "test-xiaomi"]
#     )
#     refused = await home.json(["dev", "build-check"])
#     equal("Unsigned test binding refuses", refused.result["error"]["code"], "not_signed_in")
#     await signed(home, "test-xiaomi")
#     await options(home, "build-check", devChecks=True)
#     before = len(await inputs(home))
#     build = await home.json(["dev", "build-check"])
#     equal("Single-message synthetic Build orchestration", build.process["status"], 0)
#     equal("One actual native provider call", len(await inputs(home)) - before, 1)
#     equal("Build disables every native tool route", (await inputs(home))[-1]["checks"]["tools"], [])
#     await options(home, "live-check", devChecks=True)
#     old = home.timeout_ms
#     home.timeout_ms = 120000
#     try:
#         live = await home.json(["dev", "live-check"])
#     finally:
#         home.timeout_ms = old
#     check("Extended synthetic native orchestration", live.process["status"] == 0, "successful native stages", live.result)
#     equal("Five stages attempted", live.result["turnsAttempted"], 5)
#     equal("Spend stays explicit unknown", live.result["spend"], "unknown")
#     await options(home, "probe")
#     before = len(await inputs(home))
#     probe = await home.json(["dev", "probe"])
#     check("No-prompt probe completes", probe.process["status"] == 0, "successful no-prompt report", probe.result)
#     equal("Probe spends no model requests", len(await inputs(home)), before)
#     # Initial stdin request and following control must share one unbuffered stream.
#     await signed(home)
#     await options(home, silent=True)
#     active = home.start(["run", "--request", "-", "--control"])
#     try:
#         active.child.stdin.write(
#             json.dumps(
#                 {"tools": "none", "history": [], "input": {"role": "user", "text": "stdin-frame"}, "runId": "stdin-run"}
#             )
#             + "\n"
#             + '{"type":"stop"}\n'
#         )
#         records = list(stream(await active.done, "cancelled"))
#         equal("Stdin request ID survives following control", records[-1]["runId"], "stdin-run")
#     finally:
#         await active.dispose()
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C33
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C33: no-control native question is refused before execution
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C33": "no-control native question is refused before execution",
#         "C33": lambda h: questions(h, False),
#
# async def questions(home: ScenarioHome, controlled: bool = True) -> None:
#     await signed(home)
#     await options(home, calls=[{"name": "question", "arguments": QUESTION}])
#     path = request_file(home, tools="all", workingDirectory=home.home)
#     if not controlled:
#         records = list(stream(await home.call(["run", "--request", str(path)])))
#         equal("Unattended questions never open a public ask", len([r for r in records if r["type"] == "ask_opened"]), 0)
#         check(
#             "No-control refusal reaches the model tool result",
#             "Nobody is connected" in json.dumps(records),
#             "refusal result",
#             records,
#         )
#         return
#     active = home.start(["run", "--control", "--request", str(path)])
#     try:
#         ask = await event(active, "ask_opened")
#         answer = {
#             "type": "answer",
#             "askId": ask["askId"],
#             "answer": {"type": "answers", "answers": {"q2": ["X", "Y"], "q1": ["B"]}},
#         }
#         active.send({"type": "answer", "askId": ask["askId"], "answer": {"type": "answers", "answers": {"q1": ["A"]}}})
#         await event(active, "control_refused")
#         active.send(answer)
#         active.send(answer)
#         records = list(stream(await active.done))
#         equal("One public ask", len([r for r in records if r["type"] == "ask_opened"]), 1)
#         equal("One ask closure", len([r for r in records if r["type"] == "ask_closed"]), 1)
#         equal(
#             "Malformed control is refused once; duplicate valid answer is idempotent",
#             len([r for r in records if r["type"] == "control_refused"]),
#             1,
#         )
#         results = json.dumps([r for r in records if r["type"] == "tool_finished"])
#         check(
#             "Ordered native answer values are returned",
#             "B" in results and "X" in results and "Y" in results,
#             "ordered answer result",
#             results,
#         )
#     finally:
#         await active.dispose()
#
#     await options(home, calls=[{"name": "question", "arguments": QUESTION}])
#     declined = home.start(["run", "--control", "--request", str(request_file(home, tools="all", workingDirectory=home.home))])
#     try:
#         ask = await event(declined, "ask_opened")
#         declined.send({"type": "answer", "askId": ask["askId"], "answer": {"type": "decline"}})
#         closed = list(stream(await declined.done, "cancelled"))
#         equal("Caller decline closes the ask once", len([r for r in closed if r["type"] == "ask_closed"]), 1)
#     finally:
#         await declined.dispose()
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C35
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C35: ordinary failed native shell continues with balanced result
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C35": "ordinary failed native shell continues with balanced result",
#         "C35": lambda h: shell(h, failed=True),
#
# async def shell(home: ScenarioHome, large: bool = False, failed: bool = False) -> None:
#     await signed(home)
#     command = (
#         "printf native-shell-result; exit 7"
#         if failed
#         else ("python3 -c \"print('é' * 130000)\"" if large else "printf native-shell-result")
#     )
#     await options(
#         home,
#         "tools",
#         calls=[{"name": "bash", "arguments": {"command": command, "description": "Synthetic shared shell"}}],
#         prefixText="before-native-tool" if not large and not failed else "",
#     )
#     records = await request(home, tools="all", workingDirectory=home.home)
#     started = [r for r in records if r["type"] == "tool_started"]
#     finished = [r for r in records if r["type"] == "tool_finished"]
#     equal("One native shell call", len(started), 1)
#     equal("Tool calls balance", [r["callId"] for r in started], [r["callId"] for r in finished])
#     equal("Original command is preserved", started[0]["input"]["command"], command)
#     if large:
#         equal("Native or common truncation is disclosed", finished[0].get("truncated"), True)
#         check(
#             "Result is bounded",
#             len(json.dumps(finished[0], ensure_ascii=False).encode()) <= 205500,
#             "bounded result",
#             finished[0],
#         )
#     elif failed:
#         equal("Failed shell remains a tool result", finished[0]["ok"], False)
#     else:
#         check(
#             "Real shell output is retained",
#             "native-shell-result" in json.dumps(finished[0]),
#             "native shell result",
#             finished[0],
#         )
#         first = next(i for i, row in enumerate(records) if row["type"] == "tool_started")
#         last = next(i for i, row in enumerate(records) if row["type"] == "tool_finished")
#         equal("Complete native prose precedes tool admission", any(r["type"] == "text" and "before-native-tool" in r["text"] for r in records[:first]), True)
#         equal("Complete native prose follows tool completion", any(r["type"] == "text" for r in records[last + 1:]), True)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C36
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C36: native keyed question validation and exactly-once answers
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C36": "native keyed question validation and exactly-once answers",
#         "C36": questions,
#
# async def questions(home: ScenarioHome, controlled: bool = True) -> None:
#     await signed(home)
#     await options(home, calls=[{"name": "question", "arguments": QUESTION}])
#     path = request_file(home, tools="all", workingDirectory=home.home)
#     if not controlled:
#         records = list(stream(await home.call(["run", "--request", str(path)])))
#         equal("Unattended questions never open a public ask", len([r for r in records if r["type"] == "ask_opened"]), 0)
#         check(
#             "No-control refusal reaches the model tool result",
#             "Nobody is connected" in json.dumps(records),
#             "refusal result",
#             records,
#         )
#         return
#     active = home.start(["run", "--control", "--request", str(path)])
#     try:
#         ask = await event(active, "ask_opened")
#         answer = {
#             "type": "answer",
#             "askId": ask["askId"],
#             "answer": {"type": "answers", "answers": {"q2": ["X", "Y"], "q1": ["B"]}},
#         }
#         active.send({"type": "answer", "askId": ask["askId"], "answer": {"type": "answers", "answers": {"q1": ["A"]}}})
#         await event(active, "control_refused")
#         active.send(answer)
#         active.send(answer)
#         records = list(stream(await active.done))
#         equal("One public ask", len([r for r in records if r["type"] == "ask_opened"]), 1)
#         equal("One ask closure", len([r for r in records if r["type"] == "ask_closed"]), 1)
#         equal(
#             "Malformed control is refused once; duplicate valid answer is idempotent",
#             len([r for r in records if r["type"] == "control_refused"]),
#             1,
#         )
#         results = json.dumps([r for r in records if r["type"] == "tool_finished"])
#         check(
#             "Ordered native answer values are returned",
#             "B" in results and "X" in results and "Y" in results,
#             "ordered answer result",
#             results,
#         )
#     finally:
#         await active.dispose()
#
#     await options(home, calls=[{"name": "question", "arguments": QUESTION}])
#     declined = home.start(["run", "--control", "--request", str(request_file(home, tools="all", workingDirectory=home.home))])
#     try:
#         ask = await event(declined, "ask_opened")
#         declined.send({"type": "answer", "askId": ask["askId"], "answer": {"type": "decline"}})
#         closed = list(stream(await declined.done, "cancelled"))
#         equal("Caller decline closes the ask once", len([r for r in closed if r["type"] == "ask_closed"]), 1)
#     finally:
#         await declined.dispose()
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C40
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C40: unsigned and invalid request refusals before native inference
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C40": "unsigned and invalid request refusals before native inference",
#         "C40": refusal,
#
# async def refusal(home: ScenarioHome) -> None:
#     for command in ("check", "models"):
#         await failure(home, ["subscriptions", command, "xiaomi"], "not_signed_in")
#     records = await request(home, "failed")
#     equal("Unsigned run one final", len(records), 1)
#     equal("Unsigned error", records[-1]["error"]["code"], "not_signed_in")
#     equal("Unsigned refusal makes no inference", await inputs(home), [])
#     await signed(home)
#     for fields in ({"tools": "all"}, {"serviceTier": "unoffered"}, {"limits": {"totalSeconds": True}},
#                    {"input": {"role": "assistant", "text": "invalid-current-role"}}, {"model": "unknown-model"},
#                    {"effort": "unoffered-effort"}):
#         invalid = await request(home, "failed", **fields)
#         equal("Malformed or unoffered request refuses", invalid[-1]["error"]["code"], "invalid_input")
#     equal("Invalid requests spend no inference", await inputs(home), [])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C41
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C41: authenticated native catalog and explicit allowance applicability
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C41": "authenticated native catalog and explicit allowance applicability",
#         "C41": metadata,
#
# async def metadata(home: ScenarioHome) -> None:
#     unsigned = await home.json(["subscriptions", "usage", "xiaomi"])
#     equal("Unsigned allowance", unsigned.result["outcome"], "needs_sign_in")
#     await signed(home)
#     equal(
#         "Unknown native allowance",
#         (await home.json(["subscriptions", "usage", "xiaomi"])).result["outcome"],
#         "unsupported",
#     )
#     models = (await home.json(["subscriptions", "models", "xiaomi"])).result
#     check("Authenticated native catalog", any(m["id"] == MODEL for m in models["models"]), MODEL, models)
#     equal("Catalog makes no inference", await inputs(home), [])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/archived/conformance/scenarios/mimo.py::run::C43
# Reason: Reviewed native/stand-in scenario and invoked helpers: routine CRUD, field mapping, happy-path/refusal combinations or repeated orchestration; retained cancellation, history, isolation, credential and recovery scenarios supply the distinct consequential integration evidence. Case reviewed: C43: unwritable run state has one pre-start failure
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/conformance/scenarios/mimo.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
# # Original scope/dispatch rows:
#     "C43": "unwritable run state has one pre-start failure",
#         "C43": state_failure,
#
# async def state_failure(home: ScenarioHome) -> None:
#     await signed(home)
#     file = Path(home.home, "state-is-a-file")
#     file.write_text("owner bytes")
#     reply = await home.call(["--state-dir", str(file), "run", "--run-id", "failed-state", "synthetic"])
#     records = list(stream(reply, "failed"))
#     equal("Exactly one pre-start final", len(records), 1)
#     equal("Original state file survives", file.read_text(), "owner bytes")
#     equal("No inference before state refusal", await inputs(home), [])
# LOW-TIER-SOURCE-END
# LOW-TIER-END
