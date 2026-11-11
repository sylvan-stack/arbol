"""Apply provider events to one agent record (AGR-1.1 to AGR-1.4)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

from .model import (
    AgentRecord,
    Call,
    End,
    LastEvent,
    Owner,
    object_value,
    text_value,
    timestamp,
)
from .owner import Processes
from .records import TOOLS, Store

COMMON_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "Stop",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
    "SessionEnd",
}
CLAUDE_EVENTS = COMMON_EVENTS | {
    "Notification",
    "Elicitation",
    "ElicitationResult",
    "PostToolUseFailure",
    "PermissionDenied",
    "StopFailure",
}
CODEX_EVENTS = COMMON_EVENTS | {"Interrupt"}
KIMI_LIFE_EVENTS = {"SessionHeartbeat", "TaskStarted", "UserPromptQueued", "Notification"}
KIMI_EVENTS = COMMON_EVENTS | KIMI_LIFE_EVENTS | {
    "Interrupt",
    "PermissionResult",
    "PostToolUseFailure",
    "StopFailure",
    "TurnStarted",
}
EVENTS = {"claude-code": CLAUDE_EVENTS, "codex": CODEX_EVENTS, "kimi-code": KIMI_EVENTS}
KIMI_SESSION = re.compile(r"session_([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})", re.IGNORECASE | re.ASCII)
ASKING_TOOLS = {
    "claude-code": {"AskUserQuestion", "ExitPlanMode"},
    "codex": {"request_user_input"},
    "kimi-code": {"AskUserQuestion", "ExitPlanMode"},
}
CALL_END_EVENTS = {"PostToolUse", "PostToolUseFailure", "PermissionDenied"}
TURN_END_EVENTS = {"Stop", "StopFailure", "Interrupt"}
LIFE_ONLY_EVENTS = {"SubagentStart", "SubagentStop", "PreCompact", "PostCompact"}


def optional_event_text(event: dict[str, object], key: str) -> str | None:
    value = event.get(key)
    return value if isinstance(value, str) else None


def adopt(processes: Processes, tool: str, pid: int) -> tuple[Owner, str | None]:
    return Owner(pid, processes.started(pid)), processes.entrypoint(tool, pid)


def refresh(record: AgentRecord, at: str, turn_wait: Literal["message", "driver"] | None = None) -> None:
    previous = record.waitingFor
    if any(call.asks for call in record.calls):
        target = "answer"
    elif record.calls:
        target = "tool"
    else:
        target = turn_wait or ("message" if previous == "message" else "driver")
    if record.calls:
        record.toolName = record.calls[-1].name
    else:
        record.toolName = None
    if target != previous:
        record.since = at
    record.waitingFor = target


def mark_last(record: AgentRecord, asks: bool, tool_name: str | None = None) -> None:
    for call in reversed(record.calls):
        if tool_name is None or call.name == tool_name:
            call.asks = asks
            return


def apply_call_event(record: AgentRecord, event: dict[str, object], name: str, tool: str) -> None:
    id_field = "tool_call_id" if tool == "kimi-code" else "tool_use_id"
    if name == "PreToolUse":
        identifier = text_value(event, id_field)
        tool_name = text_value(event, "tool_name")
        record.calls = [call for call in record.calls if call.id != identifier]
        record.calls.append(Call(identifier, tool_name, tool_name in ASKING_TOOLS[tool]))
    elif name in CALL_END_EVENTS:
        identifier = text_value(event, id_field)
        record.calls = [call for call in record.calls if call.id != identifier]
    elif tool == "kimi-code" and name in {"PermissionRequest", "PermissionResult"}:
        permission_call = optional_event_text(event, id_field)
        for call in record.calls:
            if call.id == permission_call:
                call.asks = name == "PermissionRequest"
                break
    elif name == "PermissionRequest":
        mark_last(record, True, text_value(event, "tool_name"))
    elif name == "ElicitationResult":
        mark_last(record, False)
    elif name == "Elicitation":
        mark_last(record, True)
    elif name == "Notification":
        notification = optional_event_text(event, "notification_type")
        if notification in {"permission_prompt", "elicitation_dialog"}:
            mark_last(record, True)


def subagent(record: AgentRecord, event: dict[str, object], name: str, tool: str, at: str) -> None:
    apply_call_event(record, event, name, tool)
    refresh(record, at)
    record.lastEvent = LastEvent(name, at)


def handle(tool: str, value: dict[str, object], location: Path | None = None) -> None:
    if tool not in TOOLS or "ARBOL_ROOT" in os.environ:
        return
    event = object_value(value)
    name = text_value(event, "hook_event_name")
    session = text_value(event, "session_id")
    if name not in EVENTS[tool]:
        return
    kimi = tool == "kimi-code"
    if kimi:
        matched = KIMI_SESSION.fullmatch(session)
        if matched is None:
            return
        session = "session-" + matched[1]

    store = Store(location)
    store.path(tool, session)
    processes = Processes()
    at = timestamp()
    with store.locked():
        record = store.read(tool, session)
        existing = record is not None
        candidate = processes.candidate(tool, record.owner.pid if record is not None else None)
        compact = not kimi and name == "SessionStart" and optional_event_text(event, "source") == "compact"
        agent_id = event.get("agent_id")
        is_subagent = agent_id is not None and (not kimi or agent_id != "main")

        if record is None:
            owner, entrypoint = adopt(processes, tool, candidate)
            record = AgentRecord.fresh(tool, session, owner, entrypoint, at)
        elif compact:
            if record.end is None or candidate != record.owner.pid:
                record.lastEvent = LastEvent(name, at)
                store.write(record)
            return
        elif not is_subagent:
            if candidate != record.owner.pid:
                if name == "SessionStart" or record.end is not None or not processes.alive(record.owner):
                    record.owner, record.entrypoint = adopt(processes, tool, candidate)
                    record.end = None
                elif name == "SessionEnd":
                    return
            elif name == "SessionStart":
                record.entrypoint = processes.entrypoint(tool, candidate, record.entrypoint)
            elif record.end is not None:
                return
        elif record.end is not None:
            return

        if is_subagent:
            subagent(record, event, name, tool, at)
            store.write(record)
            return

        notification = optional_event_text(event, "notification_type") if name == "Notification" and not kimi else None
        life_only = name in LIFE_ONLY_EVENTS or (kimi and name in KIMI_LIFE_EVENTS) or (
            name == "Notification" and notification not in {"idle_prompt", "permission_prompt", "elicitation_dialog"}
        )
        if existing and life_only:
            record.lastEvent = LastEvent(name, at)
            store.write(record)
            return

        working_folder = optional_event_text(event, "cwd")
        if working_folder is not None:
            record.workingFolder = working_folder

        model = optional_event_text(event, "model")
        if name == "SessionStart" or (tool == "codex" and model is not None and not life_only):
            record.model = model

        turn_wait: Literal["message", "driver"] | None = None
        if name == "SessionStart":
            record.transcript = None if kimi else optional_event_text(event, "transcript_path")
            record.background = None
            record.calls.clear()
            turn_wait = "message"
            record.end = None
        elif name in {"UserPromptSubmit", "TurnStarted"}:
            transcript = None if kimi else optional_event_text(event, "transcript_path")
            if transcript is not None:
                record.transcript = transcript
            turn_wait = "driver"
        elif name in TURN_END_EVENTS:
            record.calls.clear()
            turn_wait = "message"
            if tool == "claude-code":
                tasks = event.get("background_tasks")
                record.background = len(tasks) if isinstance(tasks, list) else 0
        elif notification == "idle_prompt":
            record.calls.clear()
            turn_wait = "message"
        elif name == "SessionEnd":
            if kimi:
                record.calls.clear()
                turn_wait = "message"
            record.end = End(at, optional_event_text(event, "reason") or "other")
        elif not life_only:
            apply_call_event(record, event, name, tool)

        refresh(record, at, turn_wait)
        record.lastEvent = LastEvent(name, at)
        store.write(record)
