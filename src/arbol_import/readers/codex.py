"""Read Codex session rollouts for the Arbol importer (IMP-1)."""

from __future__ import annotations

import re
import stat
from collections.abc import Generator, Iterator
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .form import SessionFailure, unknown_record
from .lines import file_records

type Object = dict[str, Any]

_ROLLOUT = re.compile(r"(?:sessions/[0-9]{4}/[0-9]{2}/[0-9]{2}|archived_sessions)/rollout-[^/]+\.jsonl(?:\.zst)?")
_NATIVE_ID = re.compile(r"[A-Za-z0-9_-]+")
_ORIGIN_FIELDS = ("originator", "source", "thread_source", "cwd")


def _id(value: object) -> str | None:
    return value if isinstance(value, str) and _NATIVE_ID.fullmatch(value) else None


def _time(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            at = datetime.fromisoformat(value)
            if at.utcoffset() is not None:
                return at.astimezone(UTC)
        except (ValueError, OverflowError):
            pass
    return None


def _inside(root: Path, path: Path) -> Path | None:
    try:
        target = path.resolve(strict=True)
        if target.is_relative_to(root):
            return target
    except (OSError, RuntimeError, ValueError):
        pass
    return None


@dataclass
class Rollout:
    relative: str
    mtime_ns: int = 0
    native_id: str | None = None
    parent: str | None = None
    created_at: datetime | None = None
    version: str | None = None
    role: str | None = None
    history_start: int | None = None
    origin: Object = field(default_factory=dict)
    failure: SessionFailure | None = None
    outside: bool = False


def _rollout_target(home: Path, relative: str) -> Path:
    try:
        target = (home / relative).resolve(strict=True)
        if (
            target.is_relative_to(home)
            and _ROLLOUT.fullmatch(target.relative_to(home).as_posix())
            and target.name.endswith(".zst") == relative.endswith(".zst")
            and stat.S_ISREG(target.stat().st_mode)
        ):
            return target
    except (OSError, RuntimeError, ValueError):
        pass
    raise SessionFailure("unreadable_session", f"{relative}: the rollout could not be read.")


def _records(home: Path, relative: str) -> Generator[tuple[int, Any]]:
    target = _rollout_target(home, relative)
    try:
        yield from file_records(home, target.relative_to(home).as_posix())
    except RecursionError:
        raise SessionFailure("unreadable_session", f"{relative}: a line could not be decoded.") from None


def _header(rollout: Rollout, row: object, line: int) -> None:
    where = f"{rollout.relative}:{line}"
    if not isinstance(row, dict) or row.get("type") != "session_meta" or not isinstance(row.get("payload"), dict):
        unknown_record("session_meta", where, conversation=True)
        return
    meta: Object = row["payload"]
    rollout.native_id = _id(meta.get("id"))
    rollout.created_at = _time(meta.get("timestamp"))
    source = meta.get("source")
    for name in _ORIGIN_FIELDS:
        value = meta.get(name)
        if isinstance(value, str) or (name == "source" and isinstance(value, dict)):
            rollout.origin[name] = value
    version = meta.get("cli_version")
    rollout.version = version if isinstance(version, str) else None
    agent = source.get("subagent") if isinstance(source, dict) else None
    spawn = agent.get("thread_spawn") if isinstance(agent, dict) else None
    if not isinstance(spawn, dict):
        spawn = {}
    role = meta.get("agent_role", meta.get("agent_type", spawn.get("agent_role", spawn.get("agent_type"))))
    rollout.role = role if isinstance(role, str) else None
    parents = [meta.get("parent_thread_id"), spawn.get("parent_thread_id")]
    if meta.get("attached_thread") is True:
        parents.append(meta.get("forked_from_id"))
    parent_ids = {native_id for value in parents if (native_id := _id(value)) is not None}
    rollout.parent = next(iter(parent_ids)) if len(parent_ids) == 1 else None
    cutoff = meta.get("subagent_history_start_ordinal")
    if type(cutoff) is int and cutoff >= 0:
        rollout.history_start = cutoff
    if (
        rollout.native_id is None
        or rollout.created_at is None
        or len(parent_ids) > 1
        or rollout.native_id in parent_ids
        or any(value is not None and _id(value) is None for value in parents)
        or (isinstance(agent, dict) and "thread_spawn" in agent and _id(spawn.get("parent_thread_id")) is None)
        or (source is not None and not isinstance(source, (str, dict)))
        or (cutoff is not None and rollout.history_start is None)
        or any(meta.get(name) is not None and not isinstance(meta[name], str)
               for name in ("originator", "thread_source", "cwd", "cli_version"))
        or (role is not None and rollout.role is None)
    ):
        unknown_record("session_meta", where, conversation=True)


def _discover(home: Path) -> Iterator[Rollout]:
    patterns = ("sessions/[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/rollout-*.jsonl*",
                "archived_sessions/rollout-*.jsonl*")
    for pattern in patterns:
        for path in sorted(home.glob(pattern)):
            relative = path.relative_to(home).as_posix()
            if not _ROLLOUT.fullmatch(relative):
                continue
            rollout = Rollout(relative)
            try:
                target = path.resolve(strict=True)
                if not target.is_relative_to(home):
                    rollout.outside = True
                    yield rollout
                    continue
                if not stat.S_ISREG(target.stat().st_mode):
                    continue
                rollout.mtime_ns = _rollout_target(home, relative).stat().st_mtime_ns
                with closing(_records(home, relative)) as records:
                    first = next(records, None)
                if first is None:
                    continue
                _header(rollout, first[1], first[0])
            except SessionFailure as failure:
                rollout.failure = failure
            except (OSError, RuntimeError, ValueError):
                rollout.failure = SessionFailure("unreadable_session", f"{relative}: the rollout could not be read.")
            yield rollout
