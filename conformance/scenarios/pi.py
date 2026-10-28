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


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c1
# async def run_c1(home: ScenarioHome) -> None:
#     from .c1 import run as local_records
#     await local_records(home)
#     equal("Local commands do not resolve credentials", len([
#         r for r in await home.received() if r.get("stage") in ("credential-export", "authentication", "input")
#     ]), 0)
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c1
async def run_c1(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c2
# async def run_c2(home: ScenarioHome) -> None:
#     for family in ("zai", "deepseek"):
#         await signed(home, family)
#         result = await home.json(["subscriptions", "get", family])
#         equal("Native key family", result.result["auth"], "key")
#         equal("Usable attachment", result.result["state"], "signed_in")
#         again = await home.json(["subscriptions", "sign-in", family, "--by-code"])
#         equal("No device code for a native-owned key", again.result["error"]["code"], "unsupported")
#     await options(home, "pending", authDelayMs=5000)
#     pending = home.start(["subscriptions", "sign-in", "zai"])
#     try:
#         async def authenticating() -> bool:
#             return any(r.get("stage") == "authentication" and r["part"] == "pending" for r in await home.received())
#         await wait_for("First attachment is pending", authenticating)
#         await options(home, "replacement")
#         await signed(home)
#         reply = await pending.done
#         equal("Replaced attempt refuses", json.loads(reply["stdout"])["error"]["code"], "in_use")
#     finally:
#         await pending.dispose()
#     home.env["ARBOL_TEST_TIME_SCALE"] = "1000"
#     await options(home, "expiry", authDelayMs=400)
#     expired = await home.json(["subscriptions", "sign-in", "zai"])
#     equal("Expired attachment refuses", expired.result["error"]["code"], "tool_failed")
#     equal("Expired attachment is signed out", (await home.json(["subscriptions", "get", "zai"])).result["state"],
#           "signed_out")
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c2
async def run_c2(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c3
# async def run_c3(home: ScenarioHome) -> None:
#     path = Path(home.tool, "credentials.json")
#     keys = json.loads(path.read_text())
#     keys["zai-coding-plan"][0]["value"]["key"] = "invalid-é"
#     path.write_text(json.dumps(keys))
#     credential_before = path.read_text()
#     result = await home.json(["subscriptions", "sign-in", "zai"])
#     equal("Malformed native key refused", result.result["error"]["code"], "not_signed_in")
#     equal("Native credential is not deleted", path.read_text(), credential_before)
#     equal("Malformed key never reaches provider", len([
#         r for r in await home.received() if r.get("stage") == "authentication"
#     ]), 0)
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c3
async def run_c3(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c5_c6
# async def run_c5_c6(home: ScenarioHome) -> None:
#     case = home.id
#     if case == "C5":
#         await signed(home)
#         await options(home, "active", failure="silent")
#         active = active_run(home, runId="held")
#         try:
#             seen = await input_(home, "active")
#             for operation in ("sign-out", "remove"):
#                 for force in ([], ["--force"]):
#                     result = await home.json(["subscriptions", operation, "zai", *force])
#                     equal("Native-owned binding refuses destructive operation",
#                           result.result["error"]["code"], "invalid_input")
#                     equal("Refusal does not stop the current run", active.done.done(), False)
#             active.send({"type": "stop"})
#             stream(await active.done, "cancelled")
#             await gone(seen["pid"])
#             equal("Binding still usable", (await home.json(["subscriptions", "get", "zai"])).result["state"],
#                   "signed_in")
#         finally:
#             await active.dispose()
#     else:
#         await options(home, "pending", authDelayMs=10000)
#         pending = home.start(["subscriptions", "sign-in", "zai"])
#         try:
#             async def authenticating() -> bool:
#                 return any(r.get("stage") == "authentication" for r in await home.received())
#             await wait_for("Authentication is pending", authenticating)
#             other = await home.json(["subscriptions", "update", "deepseek", "--label", "Independent"])
#             equal("Other Subscription is not locked", other.result["label"], "Independent")
#             pending.child.kill("SIGKILL")
#             await pending.done
#             equal("Dead attachment is recovered as signed out",
#                   (await home.json(["subscriptions", "get", "zai"])).result["state"], "signed_out")
#             state = Path((await home.json(["info"])).result["stateDirectory"])
#             equal("Pending record removed", (state / "subscriptions/zai/sign-in.json").exists(), False)
#         finally:
#             await pending.dispose()
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c5_c6
async def run_c5_c6(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c10
# async def run_c10(home: ScenarioHome) -> None:
#     await signed(home)
#     records = await request(home)
#     equal("Started precedes content", records[0]["type"], "started")
#     equal("Default subscription", records[0]["subscriptionId"], "zai")
#     equal("Default model", records[0]["model"], "glm-5.3-flash")
#     equal("Single final block", [r["text"] for r in records if r["type"] == "text"], ["Answer"])
#     equal("One native request", len(await native_inputs(home)), 1)
#     check("Only the captured native key reaches Pi", (await native_inputs(home))[0]["checks"]["credentialMatched"],
#           True, await native_inputs(home))
#     await signed(home, "deepseek")
#     catalog = (await home.json(["subscriptions", "models", "deepseek"])).result
#     selected = next(m for m in catalog["models"] if len(m["efforts"]) > 1)
#     effort = selected["efforts"][0]
#     await home.settings({"defaultSubscription": "deepseek", "subscriptions": {
#         "deepseek": {"defaultModel": selected["id"], "defaultEffort": effort}}})
#     records = await request(home)
#     equal("Configured subscription", records[0]["subscriptionId"], "deepseek")
#     equal("Configured model", records[0]["model"], selected["id"])
#     equal("Configured effort", records[0]["effort"], effort)
#     records = await request(home, subscriptionId="zai", model="glm-5.3-flash", effort="low")
#     equal("Request overrides default", records[0]["subscriptionId"], "zai")
#     equal("Explicit effort", records[0]["effort"], "low")
#     await options(home, "authoritative", delta="wrong provisional text", text="wrong original final",
#                   finalRewrite="Rewritten\u2028line\u2029paragraph")
#     records = await request(home)
#     equal("Native final hook is authoritative", [r["text"] for r in records if r["type"] == "text"],
#           ["Rewritten\u2028line\u2029paragraph"])
#     settings = Path(home.home, ".arbol/arbol-pi-driver.json")
#     settings.unlink()
#     settings.mkdir()
#     records = await request(home, outcome="failed")
#     equal("Unreadable settings refuse", records[-1]["error"]["code"], "invalid_input")
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c10
async def run_c10(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c12
# async def run_c12(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, "terminal-error", failure="invalid")
#     records = await request(home, outcome="failed")
#     equal("Native error cannot become success", records[-1]["error"]["code"], "invalid_input")
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c12
async def run_c12(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c4
# async def run_c4(home: ScenarioHome) -> None:
#     for family in ("zai", "deepseek"):
#         await options(home, "attach")
#         await signed(home, family)
#         await options(home, "rejected-check", authStatus=401)
#         result = await home.json(["subscriptions", "check", family])
#         equal("Rejected check", result.result["error"]["code"], "credential_rejected")
#         account = (await home.json(["subscriptions", "get", family])).result
#         equal("Rejected check marks account unusable", account["state"], "needs_attention")
#         check("Repair remedy", bool(account["problem"].get("remedy")), True, account)
#         await options(home, "repair")
#         await signed(home, family)
#         await options(home, "rejected-run", failure="auth")
#         records = await request(home, subscriptionId=family, outcome="failed")
#         equal("Rejected run", records[-1]["error"]["code"], "credential_rejected")
#         equal("Run marks account unusable", (await home.json(["subscriptions", "get", family])).result["state"],
#               "needs_attention")
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c4
async def run_c4(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c7
# async def run_c7(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, "redaction", failure="auth", partial=True)
#     records = await request(home, outcome="failed", workingDirectory=home.home)
#     secret = SECRET + "-zai"
#     check("Public errors redact the resolved key", secret not in json.dumps(records), True, records[-1])
#     state_info = (await home.json(["info"])).result
#     for root in (Path(state_info["stateDirectory"]), Path(home.home, ".pi/agent/sessions")):
#         for path in root.rglob("*"):
#             if path.is_file():
#                 check("No persisted key in " + str(path.relative_to(home.home)),
#                       secret.encode() not in path.read_bytes(), True, str(path))
#     check("No secret in native observations", secret not in Path(home.tool, "received.jsonl").read_text(),
#           True, "native observations")
#     await options(home, "repair")
#     await signed(home)
#     await options(home, "echo", tool="result", echoSecret=True)
#     echoed = await request(home, tools="all", workingDirectory=home.home)
#     check("Text, deltas, errors and tool data redact key", secret not in json.dumps(echoed), True, "echoed events")
#     plain = await home.call(["run", "--output", "text", "--tools", "all", "--cwd", home.home, "echo"])
#     equal("Text-mode echo succeeds", plain["status"], 0)
#     check("Plain output and diagnostics redact key", secret not in plain["stdout"] + plain["stderr"], True, "text output")
#     for root in (Path(state_info["stateDirectory"]), Path(home.home, ".pi/agent/sessions")):
#         for path in root.rglob("*"):
#             if path.is_file():
#                 check("Native messages are redacted before persistence", secret.encode() not in path.read_bytes(),
#                       True, str(path))
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c7
async def run_c7(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c8
# async def run_c8(home: ScenarioHome) -> None:
#     home.env.update({key: "inherited-credential-sentinel" for key in (
#         "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDECODE", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
#         "DEEPSEEK_API_KEY", "ZAI_API_KEY", "NODE_OPTIONS", "PI_CODING_AGENT_DIR",
#     )})
#     await signed(home)
#     await request(home)
#     for record in await native_inputs(home):
#         names = record["environment"]
#         check("Provider credentials are absent from native environment",
#               not any(name.startswith(("ANTHROPIC_", "OPENAI_", "CLAUDE", "CODEX_", "DEEPSEEK_", "ZAI_"))
#                       or name == "NODE_OPTIONS" for name in names), True, names)
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c8
async def run_c8(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c11
# async def run_c11(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, "shell", tool="shell", command="printf EARLY; (sleep .1; printf LATE) &")
#     history = [{"type": "message", "role": "user", "text": "earlier"},
#                {"type": "tool_call", "name": "shell", "input": {"command": "false", "cwd": home.home},
#                 "result": {"output": "prior failure", "exitCode": 7}, "ok": False, "truncated": True}]
#     records = await request(home, tools="all", workingDirectory=home.home, history=history)
#     kinds = [r["type"] for r in records]
#     check("Final prose precedes execution", kinds.index("text") < kinds.index("tool_started"), True, kinds)
#     calls = [r for r in records if r["type"] == "tool_started"]
#     equal("Native Bash is public shell", calls[0]["name"], "shell")
#     equal("Plain command", calls[0]["input"]["command"], "printf EARLY; (sleep .1; printf LATE) &")
#     ends = [r for r in records if r["type"] == "tool_finished"]
#     equal("One terminal call", len(ends), 1)
#     equal("Late output retained", ends[0]["result"], {"output": "EARLYLATE", "exitCode": 0})
#     messages = (await native_inputs(home))[0]["checks"]["messages"]
#     imported = next(m for m in messages if m["role"] == "toolResult")
#     equal("Historical shell becomes native Bash", imported["toolName"], "bash")
#     equal("Historical error is preserved", imported["isError"], True)
#     check("Historical exit code reaches context", "exit code: 7" in imported["content"][0]["text"], True, imported)
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c11
async def run_c11(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c13
# async def run_c13(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, "totals", tool="result")
#     records = await request(home, tools="all", workingDirectory=home.home)
#     usages = [r["usage"] for r in records if r["type"] == "usage"]
#     equal("Response usage is cumulative", [u["inputTokens"] for u in usages], [17, 34])
#     equal("Final input includes both responses", records[-1]["usage"]["inputTokens"], 34)
#     equal("Cached input is a subset", records[-1]["usage"]["cachedInputTokens"], 6)
#     check("Estimated cost is not billed cost", "cost" not in records[-1]["usage"], True, records[-1])
#     await options(home, "unknown-child-scope", tool="child")
#     records = await request(home, tools="all", workingDirectory=home.home)
#     equal("Unknown aggregate input is omitted", "inputTokens" in records[-1]["usage"], False)
#     check("Unknown aggregate usage is explained", any(r.get("code") == "usage_incomplete" for r in records),
#           True, records[-1])
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c13
async def run_c13(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c14
# async def run_c14(home: ScenarioHome) -> None:
#     await signed(home)
#     base = {"chatSessionId": "opaque/../chat", "workingDirectory": home.home}
#     state = Path((await home.json(["info"])).result["stateDirectory"])
#     mapped = state / "subscriptions/zai/chats" / (hashlib.sha256(base["chatSessionId"].encode()).hexdigest() + ".json")
#     history: list[dict[str, Any]] = []
#
#     async def turn(words: str, continuity: str, reason: str | None = None, **fields: Any) -> list[JSObject]:
#         nonlocal history
#         records = await request(home, **{**base, "history": history,
#                                         "input": {"role": "user", "text": words}, **fields})
#         equal("History continuity", records[0]["continuity"], continuity)
#         equal("History reason", records[0].get("rebuildReason"), reason)
#         history = append(history, words, records)
#         return records
#
#     await turn("first", "fresh")
#     original = json.loads(mapped.read_text())
#     second = await turn("second", "resumed")
#     equal("Restored history usage is excluded", second[-1]["usage"]["inputTokens"], 17)
#     equal("Same native conversation", json.loads(mapped.read_text())["conversation"], original["conversation"])
#     await turn("third", "resumed", systemPrompt="changed-system")
#     check("Changed system prompt is appended", "changed-system" in json.dumps((await native_inputs(home))[-1]["checks"]),
#           True, "system prompt")
#     history[0]["text"] = "edited-user"
#     history.insert(1, {"type": "tool_call", "name": "shell", "input": {"command": "false"},
#                        "result": {"output": "earlier", "exitCode": 9}, "ok": False})
#     await turn("edited", "rebuilt", "history_differs")
#     checks = (await native_inputs(home))[-1]["checks"]
#     check("Rebuild imported tool result", any(m.get("role") == "toolResult" and m.get("isError")
#                                             for m in checks["messages"]), True, checks)
#     history[-1]["text"] = "replaced-answer"
#     await turn("replaced", "rebuilt", "history_differs")
#     other = Path(home.home, "other")
#     other.mkdir()
#     base["workingDirectory"] = str(other)
#     await turn("moved", "rebuilt", "working_folder_changed")
#     Path(json.loads(mapped.read_text())["sessionPath"]).unlink()
#     await turn("gone", "rebuilt", "conversation_gone")
#     current = json.loads(mapped.read_text())
#     check("Map contains no conversation text", all(words not in mapped.read_text()
#           for words in ("edited-user", "replaced-answer")), True, current)
#     equal("Private map permissions", mapped.stat().st_mode & 0o777, 0o600)
#     await options(home, "held-history", failure="silent")
#     held = active_run(home, **base, history=history, runId="held-history")
#     try:
#         await input_(home, "held-history")
#         equal("Held run resumes", (await event(held, "started"))["continuity"], "resumed")
#         await options(home, "peer")
#         await turn("peer", "rebuilt", "in_use")
#         newer = mapped.read_text()
#         held.send({"type": "stop"})
#         stream(await held.done, "cancelled")
#         equal("Old cancellation preserves newer map", mapped.read_text(), newer)
#     finally:
#         await held.dispose()
#     await options(home, "failure", failure="invalid")
#     failed = await request(home, **base, history=history, outcome="failed")
#     equal("Failed run continued", failed[0]["continuity"], "resumed")
#     equal("Failed continuation map removed", mapped.exists(), False)
#     await options(home, "unmapped")
#     await turn("new", "rebuilt", "first_run")
#     changed = Path(json.loads(mapped.read_text())["sessionPath"])
#     with changed.open("a") as output:
#         output.write('{"type":"custom","customType":"external-edit"}\n')
#     await turn("native-edit", "rebuilt", "resume_refused")
#     await turn("anonymous", "rebuilt", "no_chat_session", chatSessionId=None)
#     await signed(home, "deepseek")
#     await turn("other-subscription", "rebuilt", "first_run", subscriptionId="deepseek")
#     def png(red: int) -> str:
#         def chunk(kind: bytes, data: bytes) -> bytes:
#             return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
#         raw = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
#         raw += chunk(b"IDAT", zlib.compress(bytes([0, red, 0, 0]))) + chunk(b"IEND", b"")
#         return base64.b64encode(raw).decode()
#
#     images = [{"mediaType": "image/png", "data": png(red)} for red in (0, 127, 255)]
#     image_history = [
#         {"type": "message", "role": "user", "text": "earlier-user", "images": [images[0]]},
#         {"type": "message", "role": "assistant", "text": "earlier-assistant", "images": [images[1]]},
#         {"type": "tool_call", "name": "foreign", "input": {"x": 1}, "result": {"y": 2}, "ok": True},
#     ]
#     records = await request(home, history=image_history,
#                             input={"role": "user", "text": "current-user", "images": [images[2]]})
#     equal("Unsupported native projection uses one visible fallback",
#           len([r for r in records if r["type"] == "notice" and r["code"] == "history_text_fallback"]), 1)
#     projected = next(m for m in (await native_inputs(home))[-1]["checks"]["messages"] if m["role"] == "user")
#     equal("Fallback preserves all image bytes in order", [b["data"] for b in projected["content"] if b["type"] == "image"],
#           [image["data"] for image in images])
#     fallback_text = projected["content"][0]["text"]
#     equal("Exact labelled fallback", fallback_text,
#           'Earlier conversation, for context:\n\n[User]\nearlier-user\n[Images: 1]\n'
#           '[Assistant]\nearlier-assistant\n[Images: 1]\n[Tool call: foreign]\n{"x":1}\n[Tool result]\n{"y":2}\n'
#           '\nNew message:\n\ncurrent-user')
#     before = len(await native_inputs(home))
#     records = await request(home, outcome="failed",
#                             input={"role": "user", "text": "bad image",
#                                    "images": [{"mediaType": "image/png", "data": "YQ=="}]})
#     equal("Native image loss refuses", records[-1]["error"]["code"], "invalid_input")
#     equal("Invalid image never reaches the provider", len(await native_inputs(home)), before)
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c14
async def run_c14(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c15_c17
# async def run_c15_c17(home: ScenarioHome) -> None:
#     case = home.id
#     await signed(home)
#     if case == "C15":
#         for part, stage, startup_values in (
#             ("credential-stop", "credential-export", {"credentialDelayMs": 10000}),
#             ("startup-stop", "session", {"startupHang": True}),
#         ):
#             await options(home, part, **startup_values)
#             active = active_run(home)
#             try:
#                 async def reached(part: str = part, stage: str = stage) -> bool:
#                     return any(r["part"] == part and r["stage"] == stage for r in await home.received())
#                 await wait_for("Startup phase reached", reached)
#                 start = time.monotonic()
#                 active.send({"type": "stop"})
#                 startup_records = stream(await active.done, "cancelled")
#                 check("Startup cancellation is prompt", time.monotonic() - start < 5, True, startup_records)
#                 equal("Startup stop never submits a prompt",
#                       len([r for r in await native_inputs(home) if r["part"] == part]), 0)
#                 for observed in [r for r in await home.received() if r["part"] == part and r["stage"] == stage]:
#                     await gone(observed["pid"])
#             finally:
#                 await active.dispose()
#     variants = ("text", "tool", "question", "child", "stubborn") if case == "C15" else (
#         "normal", "SIGINT", "SIGTERM", "input", "output")
#     for part in variants:
#         pidfile = Path(home.tool, "shell-" + part + ".pid")
#         command = f"sleep 1000 & printf '%s' $! > '{pidfile}'; wait"
#         values: dict[str, Any] = {"tool": "shell", "command": command}
#         target = "tool_started"
#         if part == "normal":
#             values["command"] = f"sleep .2 & printf '%s' $! > '{pidfile}'; printf late"
#         elif part == "text":
#             values = {"delta": "partial", "holdAfterDelta": True}
#             target = "text_delta"
#         elif part == "question":
#             values = {"tool": "question"}
#             target = "ask_opened"
#         elif part == "child":
#             values = {"tool": "child", "childHang": True}
#         elif part == "stubborn":
#             values["command"] = f"trap '' TERM; {command}"
#         await options(home, part, **values)
#         active = active_run(home, tools="all", workingDirectory=home.home)
#         try:
#             seen = await input_(home, part)
#             await event(active, target)
#             if part == "child":
#                 async def child_started(part: str = part) -> bool:
#                     return len([r for r in await native_inputs(home) if r["part"] == part]) >= 2
#                 await wait_for("Child provider is active", child_started)
#             if part not in ("text", "question", "child"):
#                 async def shell_started(pidfile: Path = pidfile) -> bool:
#                     return pidfile.exists() and bool(pidfile.read_text().strip())
#                 await wait_for("Background shell starts", shell_started)
#             start = time.monotonic()
#             if part in ("SIGINT", "SIGTERM"):
#                 active.child.kill(part)
#             elif part == "input":
#                 active.child.stdin.end()
#             elif part == "output":
#                 active.child.stdout.destroy()
#                 active.send({"type": "unrecognized"})
#             elif part != "normal":
#                 active.send({"type": "stop"})
#             reply = await active.done
#             if part == "output":
#                 equal("Broken output cancels", reply["status"], 2)
#             else:
#                 records = list(stream(reply, "completed" if part == "normal" else "cancelled"))
#                 if part != "normal":
#                     check("Stop finishes within fifteen seconds", time.monotonic() - start < 15, True, records[-1])
#                 for call in [r for r in records if r["type"] == "tool_started"]:
#                     equal("Every call ends once", len([r for r in records if r["type"] == "tool_finished"
#                                                       and r["callId"] == call["callId"]]), 1)
#                 if part == "question":
#                     equal("Question withdrawn", next(r for r in records if r["type"] == "ask_closed")["reason"],
#                           "withdrawn")
#             await gone(seen["pid"])
#             if pidfile.exists():
#                 await gone(int(pidfile.read_text()))
#             for child in [r for r in await native_inputs(home) if r["part"] == part]:
#                 await gone(child["pid"])
#         finally:
#             await active.dispose()
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c15_c17
async def run_c15_c17(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c16
# async def run_c16(home: ScenarioHome) -> None:
#     await signed(home)
#     await request(home, runId="ended")
#     for run_id in ("ended", "unknown"):
#         reply = await home.call(["runs", "stop", run_id])
#         equal("Idempotent stop exit", reply["status"], 0)
#         equal("Idempotent stop output", reply["stdout"], "")
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c16
async def run_c16(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c18
# async def run_c18(home: ScenarioHome) -> None:
#     await signed(home)
#     for part in ("failure", "slow-reader"):
#         await options(home, part, **({"delayMs": 1500, "failure": "invalid"} if part == "failure" else {"flood": True}))
#         held = active_run(home)
#         try:
#             await input_(home, part)
#             if part == "slow-reader":
#                 held.child.stdout.pause()
#             await options(home, "peer")
#             records = await request(home)
#             equal("Peer completes independently", records[-1]["outcome"], "completed")
#             if part == "slow-reader":
#                 held.child.stdout.resume()
#                 held.send({"type": "stop"})
#                 result = await held.done
#                 check("Slow reader reaches a terminal outcome", result["status"] in (1, 2), True, result["status"])
#             else:
#                 stream(await held.done, "failed")
#         finally:
#             await held.dispose()
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c18
async def run_c18(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c19
# async def run_c19(home: ScenarioHome) -> None:
#     await signed(home)
#     records = await request(home, tools="none")
#     equal("Tools-off single text", len([r for r in records if r["type"] == "text"]), 1)
#     equal("Effective tool set is empty", (await native_inputs(home))[0]["checks"]["tools"], [])
#     state = Path((await home.json(["info"])).result["stateDirectory"])
#     equal("No private run folder remains", sorted(p.name for p in (state / "tmp").iterdir()), [])
#     check("No persistent ephemeral history", not list(Path(home.home, ".pi/agent/sessions").rglob("*.jsonl")),
#           True, "ephemeral history")
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c19
async def run_c19(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c20
# async def run_c20(home: ScenarioHome) -> None:
#     await signed(home)
#     for part, value in (("text", {"resultBytes": 300 * 1024}), ("unicode", {"result": "é" * 200 * 1024}),
#                         ("structure", {"structured": True, "resultBytes": 300 * 1024})):
#         await options(home, part, tool="result", **value)
#         records = await request(home, tools="all", workingDirectory=home.home)
#         end = next(r for r in records if r["type"] == "tool_finished")
#         equal("Large result flagged", end["truncated"], True)
#         length = len(json.dumps(end["result"], ensure_ascii=False, separators=(",", ":")).encode())
#         check("Public result bounded", length <= 200 * 1024, "<= 200 KiB", length)
#     await options(home, "rewritten", tool="result", toolRewrite=True, result="Authoritative tool result")
#     records = await request(home, tools="all", workingDirectory=home.home)
#     end = next(r for r in records if r["type"] == "tool_finished")
#     equal("Final tool snapshot replaces provisional output", end["result"],
#           {"content": [{"type": "text", "text": "Authoritative tool result"}]})
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c20
async def run_c20(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c25
# async def run_c25(home: ScenarioHome) -> None:
#     await signed(home)
#     for approval in (True, False):
#         await options(home, "approve" if approval else "cancel", tool="permission", approval=approval)
#         records = await request(home, tools="all", workingDirectory=home.home)
#         equal("Permission is not a user question", len([r for r in records if r["type"] == "ask_opened"]), 0)
#         answers = [r for r in await home.received() if r.get("stage") == "answers"][-1]
#         equal("Adapter receives the expected answer", answers["checks"]["values"], ["A"] if approval else [None])
#         if not approval:
#             check("Unapprovable permission produces notice", any(r["type"] == "notice" for r in records),
#                   True, records)
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c25
async def run_c25(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c26_c27_c28
# async def run_c26_c27_c28(home: ScenarioHome) -> None:
#     case = home.id
#     rows = [("auth", "credential_rejected"), ("rate", "rate_limited"), ("invalid", "invalid_input"),
#             ("unavailable", "vendor_unavailable"), ("malformed", "tool_failed"), ("huge", "tool_failed"),
#             ("eof", "tool_failed")]
#     if case == "C27":
#         rows = [("rate", "rate_limited")]
#     elif case == "C28":
#         rows = [("auth", "credential_rejected")]
#     for failure, expected in rows:
#         await options(home, "attach")
#         await signed(home)
#         before = len(await native_inputs(home))
#         await options(home, failure, failure=failure)
#         records = await request(home, outcome="failed", limits={"totalSeconds": 8})
#         equal("Native classification", records[-1]["error"]["code"], expected)
#         equal("Closed retryability", records[-1]["error"]["retryable"], expected in ("rate_limited", "vendor_unavailable"))
#         if failure in ("auth", "rate"):
#             equal("First failure stops native retry", len(await native_inputs(home)) - before, 1)
#         if failure == "rate":
#             equal("Provider minutes remain minutes", records[-1]["error"]["retryAfterSeconds"], 300)
#     if case == "C27":
#         await options(home, "no-wait", failure="rate", errorMessage="Rate limit exceeded")
#         before = len(await native_inputs(home))
#         records = await request(home, outcome="failed")
#         equal("Unknown wait is absent", "retryAfterSeconds" in records[-1]["error"], False)
#         equal("Unknown-wait rejection is not retried", len(await native_inputs(home)), before + 1)
#     if case == "C26":
#         for part, values, expected in (
#             ("context", {"failure": "context"}, "context_exceeded"),
#             ("unknown", {"failure": "other", "errorMessage": "Unclassified provider refusal"}, "vendor_error"),
#             ("fields", {"failure": "other", "errorMessage": "Invalid API key", "status": 503}, "vendor_unavailable"),
#         ):
#             await options(home, part, **values)
#             records = await request(home, outcome="failed")
#             equal("Every error mapping row", records[-1]["error"]["code"], expected)
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c26_c27_c28
async def run_c26_c27_c28(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c30_c41
# async def run_c30_c41(home: ScenarioHome) -> None:
#     unsigned = await home.json(["subscriptions", "usage", "deepseek"])
#     equal("Unsigned usage", unsigned.result["outcome"], "needs_sign_in")
#     for family in ("zai", "deepseek"):
#         await signed(home, family)
#         before = len(await native_inputs(home))
#         usage = await home.json(["subscriptions", "usage", family])
#         equal("Unsupported account allowance is explicit", usage.result["outcome"], "unsupported")
#         equal("No invented allowance windows", usage.result["windows"], [])
#         catalog = await home.json(["subscriptions", "models", family])
#         equal("Catalog comes from the native tool", catalog.result["source"], "tool")
#         check("Nonempty native catalog", bool(catalog.result["models"]), True, catalog.result)
#         equal("Usage/catalog do not infer", len(await native_inputs(home)), before)
#         await request(home, subscriptionId=family)
#         equal("Token counts do not invent account allowance",
#               (await home.json(["subscriptions", "usage", family])).result["outcome"], "unsupported")
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c30_c41
async def run_c30_c41(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c31
# async def run_c31(home: ScenarioHome) -> None:
#     await signed(home)
#     await home.part("missing", missing=True)
#     records = await request(home, outcome="failed")
#     equal("Missing executable", records[-1]["error"]["code"], "tool_missing")
#     await options(home, "old", toolVersion="0.0.1")
#     info = await home.json(["info"])
#     equal("Old native version reported", info.result["tool"]["version"], "0.0.1")
#     equal("Old native version unsupported", info.result["tool"]["supported"], False)
#     records = await request(home, outcome="failed")
#     equal("Old native version refused", records[-1]["error"]["code"], "tool_unsupported")
#     equal("No inference for incompatible native profile", len(await native_inputs(home)), 0)
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c31
async def run_c31(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c39
# async def run_c39(home: ScenarioHome) -> None:
#     for family in ("zai", "deepseek"):
#         await signed(home, family)
#         records = await request(home, subscriptionId=family)
#         equal("Selected family", records[0]["subscriptionId"], family)
#         observed = (await native_inputs(home))[-1]
#         equal("Only selected key used", observed["checks"]["credentialMatched"], True)
#         equal("Only selected provider used", observed["checks"]["provider"], family)
#         for operation in ("sign-out", "remove"):
#             result = await home.json(["subscriptions", operation, family, "--force"])
#             equal("Native-owned credential remains native-owned", result.result["error"]["code"], "invalid_input")
#         equal("Refusal preserves binding", (await home.json(["subscriptions", "get", family])).result["state"],
#               "signed_in")
#     path = Path(home.tool, "credentials.json")
#     store = json.loads(path.read_text())
#     second = {"id": "fixture-second", "integrationID": "zai-coding-plan", "active": False,
#               "value": {"type": "key", "key": "fixture-secondary-key-SECRET"}}
#     store["zai-coding-plan"].append(second)
#     path.write_text(json.dumps(store))
#     await home.settings({"subscriptions": {"other": {"settings": {"credentialId": "fixture-second"}}}})
#     await home.json(["subscriptions", "create", "--family", "zai", "--id", "other", "--label", "Other"])
#     await signed(home, "other")
#     await request(home, subscriptionId="other")
#     equal("Explicit same-family credential", (await native_inputs(home))[-1]["checks"]["credentialId"], "fixture-second")
#     for entry in store["zai-coding-plan"]:
#         entry["active"] = entry["id"] == "fixture-second"
#     path.write_text(json.dumps(store))
#     await request(home)
#     equal("Active switch does not repin", (await native_inputs(home))[-1]["checks"]["credentialId"], "fixture-zai")
#     store["zai-coding-plan"][0]["value"]["key"] = "fixture-rotated-key-SECRET"
#     path.write_text(json.dumps(store))
#     await request(home)
#     equal("Same-ID rotation uses current key", (await native_inputs(home))[-1]["checks"]["credentialMatched"], True)
#     store["zai-coding-plan"] = [second]
#     path.write_text(json.dumps(store))
#     before = len(await native_inputs(home))
#     records = await request(home, outcome="failed")
#     equal("Removed pinned identity refuses", records[-1]["error"]["code"], "not_signed_in")
#     equal("Removed pin never falls back to active key", len(await native_inputs(home)), before)
#     await request(home, subscriptionId="other")
#     equal("Other binding stays independent", (await native_inputs(home))[-1]["checks"]["credentialId"], "fixture-second")
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c39
async def run_c39(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c40
# async def run_c40(home: ScenarioHome) -> None:
#     before = len(await native_inputs(home))
#     records = await request(home, outcome="failed")
#     equal("Unsigned run refuses", records[-1]["error"]["code"], "not_signed_in")
#     catalog = await home.json(["subscriptions", "models", "zai"])
#     equal("Unsigned catalog refuses", catalog.result["error"]["code"], "not_signed_in")
#     await signed(home)
#     for fields in ({"workingDirectory": home.home + "/missing"}, {"model": "unknown-fuzzy"},
#                    {"effort": "unrecognised"}, {"serviceTier": "priority"},
#                    {"model": "glm-4.7", "input": {"role": "user", "text": "image",
#                                                  "images": [{"mediaType": "image/png", "data": "YQ=="}]}}):
#         records = await request(home, outcome="failed", runId="refused-id", **fields)
#         equal("Invalid request refuses", records[-1]["error"]["code"],
#               "unsupported" if "serviceTier" in fields else "invalid_input")
#         equal("Refused request keeps its identity", records[-1]["runId"], "refused-id")
#         equal("No prompt-derived output", records[-1]["producedOutput"], False)
#     equal("No refused request was submitted", len(await native_inputs(home)), before)
#     await options(home, "held-id", failure="silent")
#     active = active_run(home, runId="duplicate")
#     try:
#         await input_(home, "held-id")
#         records = await request(home, runId="duplicate", outcome="failed")
#         equal("Duplicate run refuses", records[-1]["error"]["code"], "in_use")
#         equal("Duplicate run preserves requested identity", records[-1]["runId"], "duplicate")
#         active.send({"type": "stop"})
#         stream(await active.done, "cancelled")
#     finally:
#         await active.dispose()
#     await options(home, "bad-check", authStatus=401)
#     await home.json(["subscriptions", "check", "zai"])
#     await options(home, "repair-check")
#     repaired = await home.json(["subscriptions", "check", "zai"])
#     equal("Check repairs attention state", repaired.result["state"], "signed_in")
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c40
async def run_c40(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c43
# async def run_c43(home: ScenarioHome) -> None:
#     await signed(home)
#     state = Path((await home.json(["info"])).result["stateDirectory"])
#     (state / "runs").rmdir()
#     (state / "runs").write_text("unwritable directory fixture")
#     records = await request(home, outcome="failed")
#     equal("State refusal is internal", records[-1]["error"]["code"], "internal")
#     equal("One final event before any start", len(records), 1)
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c43
async def run_c43(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c29
# async def run_c29(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, "silent", failure="silent")
#     records = await request(home, outcome="failed", limits={"idleSeconds": .15})
#     equal("Idle deadline", records[-1]["error"]["code"], "limit_reached")
#     equal("Idle limit is identified", records[-1]["error"]["detail"]["limit"], "idle")
#     await options(home, "idle-off", delayMs=350)
#     await request(home, limits={"idleSeconds": 0})
#     await options(home, "heartbeats", heartbeatMs=50)
#     await request(home, limits={"idleSeconds": .15})
#     for part in ("shell", "question"):
#         await options(home, part, tool=part, command="sleep .35; printf complete")
#         active = active_run(home, tools="all", workingDirectory=home.home, limits={"idleSeconds": .1})
#         try:
#             if part == "question":
#                 ask = await event(active, "ask_opened")
#                 await asyncio.sleep(.3)
#                 equal("Question suspends idle", active.done.done(), False)
#                 active.send({"type": "answer", "askId": ask["askId"],
#                              "answer": {"type": "answers", "answers": {"choice": ["A"]}}})
#             stream(await active.done)
#         finally:
#             await active.dispose()
#     await options(home, "total-busy", tool="shell", command="sleep 10")
#     records = await request(home, tools="all", workingDirectory=home.home, outcome="failed",
#                             limits={"idleSeconds": .1, "totalSeconds": 1.5})
#     equal("Total limit applies while busy", records[-1]["error"]["detail"]["limit"], "total")
#     home.env["ARBOL_TEST_TIME_SCALE"] = "10"
#     await options(home, "startup", startupHang=True)
#     records = await request(home, outcome="failed")
#     equal("Startup deadline", records[-1]["error"]["code"], "limit_reached")
#     equal("Startup limit is identified", records[-1]["error"]["detail"]["limit"], "start")
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c29
async def run_c29(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c33
# async def run_c33(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, "unattended", tool="question")
#     records = await request(home, tools="all", workingDirectory=home.home)
#     check("Unattended question gives notice", any(r["type"] == "notice" for r in records), True, records)
#     messages = (await native_inputs(home))[-1]["checks"]["messages"]
#     check("Model receives unattended cancellation", "Nobody is attached" in json.dumps(messages), True, messages)
#     await options(home, "active-control", failure="silent")
#     active = active_run(home, runId="listed")
#     try:
#         await input_(home, "active-control")
#         listed = json.loads((await home.call(["runs", "list"]))["stdout"])
#         equal("Other process sees active run", [r["runId"] for r in listed], ["listed"])
#         active.send({"type": "unknown"})
#         await event(active, "control_refused")
#         equal("Malformed control does not stop run", active.done.done(), False)
#         equal("External stop succeeds", (await home.call(["runs", "stop", "listed"]))["status"], 0)
#         stream(await active.done, "cancelled")
#     finally:
#         await active.dispose()
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c33
async def run_c33(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c35
# async def run_c35(home: ScenarioHome) -> None:
#     await signed(home)
#     for part in ("failed", "child"):
#         await options(home, part, tool=part)
#         records = await request(home, tools="all", workingDirectory=home.home, limits={"idleSeconds": .1})
#         calls = [r for r in records if r["type"] == "tool_started"]
#         for call in calls:
#             equal("Each tool finishes exactly once", len([r for r in records if r["type"] == "tool_finished"
#                                                           and r["callId"] == call["callId"]]), 1)
#         if part == "failed":
#             end = next(r for r in records if r["type"] == "tool_finished")
#             equal("Ordinary tool failure is reported", end["ok"], False)
#         else:
#             child = next(r for r in records if r["type"] == "text" and r.get("parentCallId"))
#             equal("Child attribution", child["parentCallId"], calls[0]["callId"])
#             equal("Root answer excludes child", [r["text"] for r in records
#                                                  if r["type"] == "text" and not r.get("parentCallId")],
#                   ["Before", "After"])
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c35
async def run_c35(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c36
# async def run_c36(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, "two", tool="question", questionCount=2)
#     active = active_run(home, tools="all", workingDirectory=home.home)
#     try:
#         first, second = await event(active, "ask_opened"), await event(active, "ask_opened", 2)
#         active.send({"type": "answer", "askId": first["askId"], "answer": {"type": "answers", "answers": {}}})
#         await event(active, "control_refused")
#         for ask, label in ((second, "B"), (first, "A")):
#             active.send({"type": "answer", "askId": ask["askId"],
#                          "answer": {"type": "answers", "answers": {"choice": [label]}}})
#             await event(active, "ask_closed", 1 if ask is second else 2)
#             if ask is second:
#                 active.send({"type": "answer", "askId": ask["askId"], "answer": {"type": "decline"}})
#         records = list(stream(await active.done))
#         equal("Answers close in reverse order", [r["askId"] for r in records if r["type"] == "ask_closed"],
#               [second["askId"], first["askId"]])
#         equal("Duplicate answers are ignored", len([r for r in records if r["type"] == "control_refused"]), 1)
#     finally:
#         await active.dispose()
#     for part in ("decline", "withdraw"):
#         await options(home, part, tool="question", withdrawMs=200 if part == "withdraw" else 0, delayMs=150)
#         active = active_run(home, tools="all", workingDirectory=home.home)
#         try:
#             ask = await event(active, "ask_opened")
#             if part == "decline":
#                 active.send({"type": "answer", "askId": ask["askId"], "answer": {"type": "decline"}})
#                 stream(await active.done, "cancelled")
#             else:
#                 closed = await event(active, "ask_closed")
#                 equal("Native withdrawal reason", closed["reason"], "withdrawn")
#                 active.send({"type": "answer", "askId": ask["askId"], "answer": {"type": "decline"}})
#                 await event(active, "control_refused")
#                 stream(await active.done)
#         finally:
#             await active.dispose()
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c36
async def run_c36(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c38
# async def run_c38(home: ScenarioHome) -> None:
#     await signed(home)
#     base = {"workingDirectory": home.home, "chatSessionId": "recover"}
#     first = await request(home, **base)
#     history = append([], "fixture prompt", first)
#     state = Path((await home.json(["info"])).result["stateDirectory"])
#     mapped = state / "subscriptions/zai/chats" / (hashlib.sha256(b"recover").hexdigest() + ".json")
#     await options(home, "killed", tool="shell", command="sleep 1000 & wait")
#     active = active_run(home, **base, history=history, tools="all", runId="killed")
#     try:
#         seen = await input_(home, "killed")
#         await event(active, "tool_started")
#         active.child.kill("SIGKILL")
#         await active.done
#         replies = await asyncio.gather(home.call(["runs", "list"]), home.call(["runs", "list"]))
#         for reply in replies:
#             equal("Concurrent recovery succeeds", json.loads(reply["stdout"]), [])
#         await gone(seen["pid"])
#         for path in (mapped, state / "runs/killed.json", state / "tmp/killed"):
#             equal("Recovered path removed", path.exists(), False)
#     finally:
#         await active.dispose()
#     created = await asyncio.gather(*(home.json(["subscriptions", "create", "--family", "zai", "--label", label])
#                                      for label in ("One", "Two")))
#     equal("Concurrent creations both succeed", [r.process["status"] for r in created], [0, 0])
#     check("Concurrent creations have distinct IDs", created[0].result["id"] != created[1].result["id"], True, created)
#     empty = Path(home.home, "empty-state")
#     equal("Empty state works", (await home.call(["info", "--state-dir", str(empty)]))["status"], 0)
#     (empty / "format").write_text("999\n")
#     newer = await home.json(["info", "--state-dir", str(empty)])
#     equal("Newer format refuses", newer.result["error"]["code"], "state_newer")
#     equal("Newer format preserved", (empty / "format").read_text(), "999\n")
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c38
async def run_c38(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c42
# async def run_c42(home: ScenarioHome) -> None:
#     await signed(home)
#     await options(home, "partial-failure", tool="hang", failDuringTool=True)
#     records = await request(home, tools="all", workingDirectory=home.home, outcome="failed")
#     equal("Text emitted before failure", [r["text"] for r in records if r["type"] == "text"], ["Before"])
#     equal("Prior usage retained", records[-1]["usage"]["inputTokens"], 17)
#     equal("Output flag retained", records[-1]["producedOutput"], True)
#     calls = [r for r in records if r["type"] == "tool_started"]
#     equal("Unfinished call retained", records[-1]["unfinishedCalls"], [calls[0]["callId"]])
#     equal("No prompt replay", len(await native_inputs(home)), 1)
#     return
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c42
async def run_c42(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c9_c37
# async def run_c9_c37(home: ScenarioHome) -> None:
#     await signed(home)
#     agent = Path(home.home, ".pi/agent")
#     files = [agent / "settings.json", agent / "auth.json", agent / "models.json", agent / "AGENTS.md"]
#     files[1].write_text("{}\n")
#     files[2].write_text('{"providers":{}}\n')
#     files[3].write_text("OWNER_INSTRUCTION_SENTINEL\n")
#     if home.id == "C37":
#         skill = agent / "skills/fixture-skill/SKILL.md"
#         skill.parent.mkdir(parents=True)
#         skill.write_text("---\nname: fixture-skill\ndescription: OWNER_SKILL_SENTINEL\n---\nSkill body\n")
#         files.append(skill)
#         server = Path(home.tool, "mcp.py")
#         server.write_text(
#             "import json,os,sys\nfrom pathlib import Path\n"
#             "Path('mcp.pid').write_text(str(os.getpid()))\n"
#             "for line in sys.stdin:\n"
#             " r=json.loads(line)\n"
#             " if 'id' not in r: continue\n"
#             " result={'protocolVersion':r.get('params',{}).get('protocolVersion'),'capabilities':{'tools':{}},"
#             "'serverInfo':{'name':'fixture','version':'1'}} if r['method']=='initialize' else "
#             "{'tools':[{'name':'echo','description':'Owner MCP','inputSchema':{'type':'object','properties':{}}}]}\n"
#             " print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}),flush=True)\n")
#         # Use the fixture launcher's own Python, already available in its isolated PATH.
#         config = agent / "mcp.json"
#         config.write_text(json.dumps({"mcpServers": {"fixture": {
#             "command": "python3", "args": [str(server)], "cwd": home.tool, "exposure": "direct",
#         }}}))
#         files.extend([config, server, agent / "extensions/contract.ts"])
#     snapshot = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
#     await options(home, "owner", ownerHook=home.id == "C37")
#     await request(home, tools="all", workingDirectory=home.home, systemPrompt="CALLER_APPEND_SENTINEL")
#     observed = (await native_inputs(home))[-1]
#     encoded = json.dumps(observed["checks"])
#     for sentinel in ("OWNER_INSTRUCTION_SENTINEL", "CALLER_APPEND_SENTINEL"):
#         check("Native prompt preserves " + sentinel, sentinel in encoded, True, encoded)
#     session = next(r for r in await home.received() if r["stage"] == "session")
#     equal("Native HOME is the owner fixture", session["checks"]["home"], home.home)
#     if home.id == "C37":
#         for sentinel in ("OWNER_SKILL_SENTINEL", "OWNER_HOOK_SENTINEL", "mcp__fixture__echo"):
#             check("Configured native feature reaches provider: " + sentinel, sentinel in encoded, True, encoded)
#         await gone(int(Path(home.tool, "mcp.pid").read_text()))
#     for path, before in snapshot.items():
#         equal("Owner content preserved: " + path.name, path.read_text(), before[0].decode())
#         equal("Owner modification time preserved: " + path.name, path.stat().st_mtime_ns, before[1])
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c9_c37
async def run_c9_c37(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run_c32
# async def run_c32(home: ScenarioHome) -> None:
#     from .info import inspect_info
#     identity: dict[str, Any] | None = None
#     for override in (None, str(Path(home.home, "explicit-state"))):
#         identity_result = await home.json(["info", *(["--state-dir", override] if override else [])])
#         info, tool, name = inspect_info(identity_result.result)
#         equal("Driver identity", name, "pi")
#         equal("Contract version", info["contract"], 2)
#         equal("State format", info["dataFormat"], 1)
#         equal("State directory", info["stateDirectory"],
#               override or str(Path(home.home, "Library/Application Support/Arbol/drivers/pi")))
#         equal("Settings file", info["settingsFile"], str(Path(home.home, ".arbol/arbol-pi-driver.json")))
#         check("Semantic package version", bool(re.fullmatch(r"\d+\.\d+\.\d+", info["version"])), True, info)
#         check("Build identity format", bool(re.fullmatch(r"0|[1-9a-f][0-9a-f]*", info["build"])), True, info)
#         equal("Qualified native version", tool["version"], "1.1.0")
#         equal("Native tool supported", tool["supported"], True)
#         current = {key: info[key] for key in ("driver", "version", "build", "contract")}
#         if identity is not None:
#             equal("Identity is independent of state override", current, identity)
#         identity = current
#     await signed(home)
#     info = (await home.json(["info"])).result
#     system = Path(home.tool, "system.txt")
#     system.write_text("CLI_APPEND_SENTINEL")
#     extra = Path(home.home, "extra")
#     extra.mkdir()
#     path = request_file(home)
#     reply = await home.call([
#         "run", "--request", str(path), "--subscription", "zai", "--model", "glm-5.3-flash", "--effort", "low",
#         "--system-prompt-file", str(system), "--cwd", home.home, "--add-dir", str(extra), "--tools", "all",
#         "--chat-session", "cli", "--run-id", "cli-run", "--output", "events", "--label", "one=1", "--label", "two=2",
#         "--state-dir", info["stateDirectory"], "override",
#     ])
#     records = list(stream(reply))
#     equal("Build identity is consistent", records[0]["driverBuild"], info["build"])
#     equal("Exact request identity", records[0]["runId"], "cli-run")
#     equal("Labels survive", records[0]["labels"], {"one": "1", "two": "2"})
#     seen = (await native_inputs(home))[-1]
#     for text in ("CLI_APPEND_SENTINEL", str(extra), "override"):
#         check("CLI field reaches native context", text in json.dumps(seen["checks"]), True, text)
#     stdin = home.start(["run", "--request", "-", "--control"])
#     try:
#         stdin.send({"input": {"role": "user", "text": "stdin"}, "tools": "none"})
#         stdin.send({"type": "unknown"})
#         stream(await stdin.done)
#         equal("Buffered request does not swallow control", len([r for r in stdin.lines
#                                                                 if r.get("type") == "control_refused"]), 1)
#     finally:
#         await stdin.dispose()
#     text_reply = await home.call(["run", "--output=text", "plain"])
#     equal("Text exit status", text_reply["status"], 0)
#     equal("Text output", text_reply["stdout"], "Answer")
#     for bad in (["unknown"], ["info", "--unknown"], ["info", "--state-dir"], ["run", "--unknown"],
#                 ["subscriptions", "sign-in", "zai", "--key-file", str(path)],
#                 ["subscriptions", "sign-in", "zai", "--secret=NEVER_ECHO_THIS"],
#                 ["subscriptions", "export", "zai"]):
#         result = await home.call(bad)
#         equal("Invalid command exit", result["status"], 1)
#         equal("Typed invalid command", json.loads(result["stdout"])["error"]["code"], "invalid_input")
#         check("Rejected secret option is not echoed", "NEVER_ECHO_THIS" not in result["stdout"], True, result)
#     for operation in ("build-check", "live-check"):
#         refused = await home.json(["dev", operation])
#         equal("Missing test binding refuses", refused.result["error"]["code"], "not_found")
#     for family in ("zai", "deepseek"):
#         await home.json(["subscriptions", "create", "--family", family, "--id", "test-" + family, "--label", "Test"])
#         if family == "zai":
#             refused = await home.json(["dev", "build-check"])
#             equal("Unsigned test binding refuses", refused.result["error"]["code"], "not_signed_in")
#         await signed(home, "test-" + family)
#     await options(home, "development", devChecks=True)
#     before = len(await native_inputs(home))
#     build = await home.json(["dev", "build-check"])
#     equal("Build check passes", build.process["status"], 0)
#     equal("One build inference", build.result["inferenceRequests"], 1)
#     equal("Exactly one provider call", len(await native_inputs(home)), before + 1)
#     equal("Build check disables tools", (await native_inputs(home))[-1]["checks"]["tools"], [])
#     previous_timeout = home.timeout_ms
#     try:
#         # This one command performs twelve actual native startup/cleanup cycles.
#         home.timeout_ms = max(previous_timeout, 60000)
#         live = await home.json(["dev", "live-check"])
#     finally:
#         home.timeout_ms = previous_timeout
#     equal("Live orchestration passes synthetic native providers", live.process["status"], 0)
#     equal("Both families each receive six qualification turns", live.result["inferenceRequests"], 12)
#     state = Path(info["stateDirectory"])
#     account_file = state / "subscriptions/test-zai/record.json"
#     account = json.loads(account_file.read_text())
#     account["lastUsage"] = {"outcome": "ok", "windows": [{"usedPercent": 100}]}
#     account_file.write_text(json.dumps(account))
#     before = len(await native_inputs(home))
#     for operation in ("build-check", "live-check"):
#         refused = await home.json(["dev", operation])
#         equal("Known exhausted quota refuses", refused.result["error"]["code"], "rate_limited")
#     equal("No inference under exhausted quota", len(await native_inputs(home)), before)
#     probe = await home.json(["dev", "probe"])
#     equal("Probe has no inference", probe.result["inferenceRequests"], 0)
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run_c32
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


# TEST-TIER-DISABLED-BEGIN conformance/scenarios/pi.py::run
# async def run(home: ScenarioHome) -> None:
#     handler = VARIANTS.get(home.id)
#     if handler is None:
#         raise ScenarioError(f"Pi variant {home.id} is not implemented; no coverage is claimed.")
#     await handler(home)
# TEST-TIER-DISABLED-END conformance/scenarios/pi.py::run
async def run(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/pi.py:5
# import asyncio
# TEST-TIER-IMPORTS-END conformance/scenarios/pi.py:5
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/pi.py:6
# import base64
# TEST-TIER-IMPORTS-END conformance/scenarios/pi.py:6
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/pi.py:7
# import hashlib
# TEST-TIER-IMPORTS-END conformance/scenarios/pi.py:7
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/pi.py:10
# import re
# TEST-TIER-IMPORTS-END conformance/scenarios/pi.py:10
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/pi.py:11
# import struct
# TEST-TIER-IMPORTS-END conformance/scenarios/pi.py:11
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/pi.py:12
# import time
# TEST-TIER-IMPORTS-END conformance/scenarios/pi.py:12
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/pi.py:14
# import zlib
# TEST-TIER-IMPORTS-END conformance/scenarios/pi.py:14
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/pi.py:18
# from ..check import ScenarioError, check, equal
# TEST-TIER-IMPORTS-END conformance/scenarios/pi.py:18
# TEST-TIER-IMPORTS-BEGIN conformance/scenarios/pi.py:23
# from .stops import gone, input_, some_line, wait_for
# TEST-TIER-IMPORTS-END conformance/scenarios/pi.py:23
