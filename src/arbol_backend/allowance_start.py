"""One tools-disabled completion to start an allowance, without a chat or working folder."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import tempfile
import time
from datetime import UTC, datetime

from .bridge import Params
from .exchange_admission import GENERATION_ENV
from .model import Refused
from .process import Child, Programs


def pending_window(driver: str, account: Params) -> bool:
    family = account.get("family")
    if account.get("state") != "signed_in" or (driver, family) not in {
        ("claude", "anthropic"), ("codex", "chatgpt"),
        ("pi", "chatgpt"), ("pi", "kimi-coding"), ("pi", "zai"),
    }:
        return False
    report = account.get("lastUsage", {})
    windows = report.get("windows", []) if report.get("outcome") == "ok" else []
    for window in windows:
        if window.get("windowMinutes") != 300:
            continue
        reset = window.get("resetsAt")
        if reset:
            if datetime.fromisoformat(reset) <= datetime.now(UTC):
                return True
        elif window.get("usedPercent") == 0:
            return True
    # Pi's ChatGPT quota is supplied by Seqoya's separate saved allowance reading.
    # It has no Driver quota endpoint; the caller detects its pending window.
    return driver == "pi" and family == "chatgpt" and not windows


async def stop(child: Child) -> None:
    if child.process.poll() is None:
        try:
            child.process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 15
        while child.process.poll() is None and time.monotonic() < deadline:
            child.read()
            await asyncio.sleep(.05)
        if child.process.poll() is None:
            Programs.kill(child)
    await asyncio.to_thread(child.process.wait)


async def start_window(programs: Programs, driver: str, subscription: str) -> None:
    """Keep the caller's admission permit until the Driver and its cleanup end."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("PG") and key not in
           {"ARBOL_ROOT", "ARBOL_CHAT", "ARBOL_EXCHANGE_RUNTIME_DIR", "ARBOL_EXCHANGE_BIN_DIR", GENERATION_ENV}}
    env["HOME"] = str(programs.identity.home)
    env["PATH"] = str(programs.identity.bin_dir) + os.pathsep + env.get("PATH", "/usr/bin:/bin")
    arguments = [str(programs.identity.bin_dir / ("arbol-" + driver + "-driver")),
                 "run", "--subscription", subscription, "--tools", "none", "Reply only OK."]
    with tempfile.TemporaryFile(mode="w+b") as output:
        process = subprocess.Popen(arguments, cwd=programs.identity.folder, env=env, close_fds=True,
                                   start_new_session=True, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.DEVNULL)
        child = Child(process, False, output)
        try:
            async with asyncio.timeout(25):
                while True:
                    child.read()
                    if child.overflow:
                        raise Refused("no_answer", "The allowance request returned too much output.")
                    if process.poll() is not None and child.eof:
                        break
                    await asyncio.sleep(.02)
            events = [json.loads(line) for line in child.data.splitlines()]
            if (process.returncode != 0 or not events or not all(isinstance(event, dict) for event in events)
                    or events[-1].get("type") != "finished" or events[-1].get("outcome") != "completed"
                    or sum(event.get("type") == "finished" for event in events) != 1
                    or any(event.get("type") in ("tool_started", "ask_opened") for event in events)):
                raise Refused("no_answer", "The provider could not confirm the allowance request.")
        finally:
            # A repeated cancellation must not release writer admission before cleanup.
            cleanup = asyncio.create_task(stop(child))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
            cleanup.result()
