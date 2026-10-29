# Test implementations moved to tests/mid/archived/conformance/scenarios/pi.py.
"""Native-managed-key variants of the shared scenarios, judged only through the CLI."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from ..check import equal
from ..harness import ScenarioHome
from ..js import JSObject
from ..process import invoke
from .runs import stream
from .stops import some_line, wait_for

SECRET = "fixture-selected-key-SECRET-781"


async def prepare(home: ScenarioHome) -> None:
    environment = {key: value for key, value in os.environ.items()
                   if key in ("HOME", "USER", "LOGNAME", "PATH", "SHELL", "TERM", "TMPDIR", "LANG", "TZ")}
    result = await invoke(home.command, ["dev", "stand-in", home.tool, "--", "install"],
                          cwd=home.home, env=environment, timeout_ms=home.timeout_ms, signal_=home.signal)
    equal("Install native fixture", result["status"], 0)
    configured = json.loads(result["stdout"])
    equal("Qualified native version", configured["profile"]["version"], "1.1.0")
    home.command = [*home.command, "dev", "stand-in", home.tool, "--", "driver"]
    home.env["PATH"] = configured["binPath"] + ":" + home.env["PATH"]
    # This fixture runs the actual native runtime, whose initialization is not simulated.
    home.env["ARBOL_TEST_TIME_SCALE"] = "1"


async def options(home: ScenarioHome, part: str, **values: Any) -> None:
    await home.part(part)
    Path(home.tool, "options.json").write_text(json.dumps(values))


async def signed(home: ScenarioHome, family: str = "zai") -> None:
    value = await home.json(["subscriptions", "sign-in", family])
    equal("Native attachment exit", value.process["status"], 0)
    equal("Native attachment step", value.result["step"], "done")


async def request(home: ScenarioHome, *, outcome: str = "completed", **fields: Any) -> list[JSObject]:
    path = request_file(home, **fields)
    return list(stream(await home.call(["run", "--request", str(path)]), outcome))


def request_file(home: ScenarioHome, **fields: Any) -> Path:
    value = {"input": {"role": "user", "text": "fixture prompt"}, **{k: v for k, v in fields.items() if v is not None}}
    path = Path(home.tool, f"request-{uuid.uuid4().hex}.json")
    path.write_text(json.dumps(value))
    return path


def active_run(home: ScenarioHome, **fields: Any) -> Any:
    return home.start(["run", "--control", "--request", str(request_file(home, **fields))])


async def event(active: Any, kind: str, count: int = 1) -> JSObject:
    await wait_for(kind + " arrives", some_line(active.lines, lambda _: len([
        e for e in active.lines if e.get("type") == kind]) >= count))
    return JSObject([e for e in active.lines if e.get("type") == kind][count - 1])


def append(history: list[dict[str, Any]], words: str, records: list[JSObject]) -> list[dict[str, Any]]:
    return [*history, {"type": "message", "role": "user", "text": words},
            *({"type": "message", "role": "assistant", "text": r["text"]}
              for r in records if r["type"] == "text" and not r.get("parentCallId"))]


async def native_inputs(home: ScenarioHome) -> list[JSObject]:
    return [record for record in await home.received() if record.get("stage") == "input"]


async def run_c1(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c2(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c3(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c5_c6(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c10(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c12(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c4(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c7(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c8(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c11(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c13(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c14(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c15_c17(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c16(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c18(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c19(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c20(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c25(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c26_c27_c28(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c30_c41(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c31(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c39(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c40(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c43(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c29(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c33(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c35(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c36(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c38(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c42(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c9_c37(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def run_c32(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


VARIANTS = {
    "C32": run_c32,
    "C9": run_c9_c37,
    "C37": run_c9_c37,
    "C1": run_c1,
    "C2": run_c2,
    "C3": run_c3,
    "C5": run_c5_c6,
    "C6": run_c5_c6,
    "C10": run_c10,
    "C12": run_c12,
    "C4": run_c4,
    "C7": run_c7,
    "C8": run_c8,
    "C11": run_c11,
    "C13": run_c13,
    "C14": run_c14,
    "C15": run_c15_c17,
    "C17": run_c15_c17,
    "C16": run_c16,
    "C18": run_c18,
    "C19": run_c19,
    "C20": run_c20,
    "C25": run_c25,
    "C26": run_c26_c27_c28,
    "C27": run_c26_c27_c28,
    "C28": run_c26_c27_c28,
    "C30": run_c30_c41,
    "C41": run_c30_c41,
    "C31": run_c31,
    "C39": run_c39,
    "C40": run_c40,
    "C43": run_c43,
    "C29": run_c29,
    "C33": run_c33,
    "C35": run_c35,
    "C36": run_c36,
    "C38": run_c38,
    "C42": run_c42,
}


SCOPES = {
    "C1": "both families, local creation/list/relabel/removal; no credential resolution",
    "C2": "native key attachment, unsupported device-code mode, replacement and scaled five-minute expiry",
    "C3": "malformed native-owned key refuses without deletion or authentication",
    "C4": "both families: check/run rejection, remedy and attention-state repair",
    "C5": "native-owned sign-out/removal refuses with and without force while its run remains active",
    "C6": "killed attachment recovery and independent Subscription mutation",
    "C7": "private-key echoes in events, errors, tools, stderr, text output and native session persistence",
    "C8": "inherited provider/Driver credentials and native configuration overrides are removed",
    "C9": "actual native HOME, instruction discovery, additive caller prompt and unchanged owner files",
    "C10": "native defaults, settings and request overrides, event sequence and unreadable settings",
    "C11": "final prose/tool ordering, native Bash, late output and failed historical shell projection",
    "C12": "successful RPC acceptance cannot turn a native provider failure into success",
    "C13": "cumulative current-turn/cache usage, omitted estimated cost and unknown child aggregate",
    "C14": "resume/rebuild reasons, images and exact fallback, native edits, busy histories and conditional maps",
    "C15": "stop during text, shell, question, child and TERM-ignoring work; pairing and fifteen-second bound",
    "C16": "idempotent stop of ended and unknown runs",
    "C17": "background group cleanup on completion, signals, control EOF and lost caller output",
    "C18": "simultaneous failure and slow-reader isolation on one binding",
    "C19": "actual empty native tool set and ephemeral state removal",
    "C20": "bounded text, structured and multibyte tool results with truncation flags",
    "C25": "automatic permission approval, declined meaningless permission and notice",
    "C26": "native error mapping, field precedence, context/unknown failures, malformed output and EOF",
    "C27": "stated minutes and unknown waits, no retry after the first rate rejection",
    "C28": "first rejected credential stops native retry",
    "C29": "startup/idle/total deadlines, idle disabled, heartbeats and suspended idle during tools/questions",
    "C30": "unsupported account allowance stays explicit; token counts never invent a quota report",
    "C31": "missing executable and unqualified native version refuse before inference",
    "C32": "contract-2 CLI identity/options, stdin controls, build/live orchestration and quota refusal",
    "C33": "unattended question notice to caller/model, external run listing/stop and invalid control",
    "C35": "ordinary failed tool continues, child attribution/root isolation and complete call pairing",
    "C36": "reverse answers, invalid/duplicate/withdrawn answers, decline and exactly-once delivery",
    "C37": "actual instructions, skill, extension hook and MCP discovery without changing owner configuration",
    "C38": "SIGKILL and concurrent recovery, history invalidation, simultaneous creations and state format",
    "C39": "two providers and same-family bindings, active switch, same-ID rotation and removed-pin refusal",
    "C40": "unsigned/catalog/request/duplicate-ID refusals, exact request identity and attention repair",
    "C41": "both native catalogs, unsupported allowance, unsigned usage and no inference for metadata",
    "C42": "failure after text/tool start preserves usage/output, interrupts calls and never replays",
    "C43": "unwritable run state gives one pre-start internal failure",
}


async def run(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL

# Archived complete imports; restore needed names in their original scope, not at this file tail.
