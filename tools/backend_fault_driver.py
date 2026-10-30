#!/usr/bin/env python3
"""Clearly identified no-vendor fault input for installed Root/Trunk journeys (BKD-D42)."""
from __future__ import annotations

import argparse
import json
import os
import select
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

DRIVER = "journey-fixture"
SUBSCRIPTION = "private-fixture"
MODELS = ("hold", "complete", "ignore-stop", "question")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def run(request: dict[str, Any], control: Path) -> int:
    run_id = request["runId"]
    exchange, suffix = run_id.rsplit(".", 1)
    if str(UUID(exchange)) != exchange or suffix != "1" or request.get("subscriptionId") != SUBSCRIPTION:
        raise ValueError("This fixture accepts only its own explicitly named Subscription.")
    model = request.get("model")
    if model not in MODELS:
        raise ValueError("Choose a listed controlled fixture model.")
    folder = control / run_id
    folder.mkdir(mode=0o700, exist_ok=False)
    descriptor = os.open(folder / "process.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"pid": os.getpid(), "runId": run_id, "model": model, "vendor": False}, stream)
        stream.write("\n")
    sequence = 0

    def event(kind: str, **fields: Any) -> None:
        nonlocal sequence
        sequence += 1
        emit({"runId": run_id, "seq": sequence, "at": now(), "type": kind, **fields})

    event("started", subscriptionId=SUBSCRIPTION, model=model, continuity="fresh", toolVersion="no-vendor-fixture",
          driverBuild="0")
    answer = "Controlled fault input; no vendor was contacted. "
    event("text_delta", text=answer)
    if model == "question":
        event("tool_started", callId="controlled-question", name="question", input={})
        event("ask_opened", askId="controlled-choice", ask={"callId": "controlled-question", "questions": [
            {"id": "choice", "question": "Choose the controlled fixture branch.", "multiple": False, "options": [
                {"id": "one", "label": "First branch"}, {"id": "two", "label": "Second branch"}]}]})
    deadline = time.monotonic() + 600
    text_count = 0
    answered = model != "question"
    while time.monotonic() < deadline:
        if (folder / "text").exists():
            text = (folder / "text").read_text()
            (folder / "text").unlink()
            text_count += 1
            answer += text
            event("text_delta", text=text)
        if (model == "complete" or (folder / "finish").exists()) and answered:
            event("text", text=answer + "Completed fixture answer.")
            event("finished", outcome="completed", usage={"inputTokens": 0, "outputTokens": text_count})
            return 0
        if select.select([sys.stdin], [], [], 0.05)[0]:
            line = sys.stdin.readline()
            if not line:
                time.sleep(0.05)
                continue
            command = json.loads(line)
            if command.get("type") == "stop" and model != "ignore-stop":
                event("finished", outcome="cancelled", usage={"inputTokens": 0, "outputTokens": text_count})
                return 2
            if command.get("type") == "answer" and command.get("askId") == "controlled-choice":
                event("ask_closed", askId="controlled-choice")
                event("tool_finished", callId="controlled-question", ok=True, result="Controlled answer received")
                answered = True
                event("text_delta", text="The controlled answer receipt was observed. ")
    event("finished", outcome="failed", error={"code": "internal", "message": "The controlled fixture expired."},
          usage={"inputTokens": 0, "outputTokens": text_count})
    return 1


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--control", action="store_true")
    parser.add_argument("words", nargs="*")
    args = parser.parse_args(arguments)
    words = args.words
    if words == ["info"]:
        emit({"driver": DRIVER, "contract": 2, "build": "0", "packageVersion": "0.0.0", "fixture": True})
    elif words == ["subscriptions", "families"]:
        print(json.dumps([{"id": "fixture", "label": "No-vendor journey fixture", "auth": "none"}]), flush=True)
    elif words == ["subscriptions", "list"] or words == ["subscriptions", "check", SUBSCRIPTION]:
        row = {"id": SUBSCRIPTION, "family": "fixture", "label": "Controlled no-vendor input", "auth": "none",
               "state": "signed_in", "createdAt": "2026-10-28T00:00:00Z", "updatedAt": "2026-10-28T00:00:00Z"}
        print(json.dumps([row] if words[-1] == "list" else row), flush=True)
    elif words == ["subscriptions", "models", SUBSCRIPTION]:
        emit({"source": "fixture", "fetchedAt": now(), "models": [
            {"id": model, "label": model, "isDefault": model == "hold"} for model in MODELS]})
    elif words == ["subscriptions", "usage", SUBSCRIPTION]:
        emit({"outcome": "ok", "fetchedAt": now(), "windows": [], "fixture": True})
    elif words == ["run"] and args.request and args.control:
        args.control_dir.mkdir(mode=0o700, exist_ok=True)
        return run(json.loads(args.request.read_text()), args.control_dir)
    else:
        emit({"error": {"code": "invalid_input", "message": "This no-vendor fixture supports only its listed commands."}})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
