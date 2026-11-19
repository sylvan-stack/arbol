"""Read saved Claude Code sessions and their archive files (IMP-1)."""

from __future__ import annotations

import json
import re
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .form import Failed, SessionFailure, Source


@dataclass(frozen=True)
class SessionFile:
    path: Path

    @property
    def native_id(self) -> str:
        return self.path.stem

    @property
    def directory(self) -> Path:
        return self.path.with_suffix("")


def _inside(root: Path, path: Path) -> Path | None:
    resolved = path.resolve()
    return resolved if resolved.is_relative_to(root) else None


def _unreadable(home: Path, path: Path) -> SessionFailure:
    return SessionFailure("unreadable_session", f"{path.relative_to(home)}: could not be read.")


def _regular(home: Path, path: Path) -> Path:
    try:
        resolved = _inside(home, path)
        if resolved is not None and stat.S_ISREG(resolved.stat().st_mode):
            return resolved
    except (OSError, RuntimeError, ValueError):
        pass
    raise _unreadable(home, path)


def _discover(home: Path, source: Source) -> Iterator[SessionFile | Failed]:
    projects = home / "projects"
    try:
        if _inside(home, projects) is None:
            raise _unreadable(home, projects)
        folders = sorted(projects.iterdir())
    except FileNotFoundError:
        return
    except (OSError, RuntimeError, SessionFailure):
        yield Failed.of(_unreadable(home, projects), file="projects")
        return
    for folder in folders:
        try:
            if _inside(home, folder) is None or not stat.S_ISDIR(folder.stat().st_mode):
                continue
            paths = sorted(folder.iterdir())
        except (OSError, RuntimeError):
            yield Failed.of(_unreadable(home, folder), file=folder.relative_to(home).as_posix())
            continue
        files = [SessionFile(path) for path in paths if path.suffix == ".jsonl"]
        if any(source.wants(file.native_id) for file in files):
            yield from files


_NATIVE_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)


def _map_entries(root: Path, directory: Path) -> Iterator[Path]:
    try:
        if _inside(root, directory) is not None:
            yield from directory.iterdir()
    except (OSError, RuntimeError):
        pass


def _driver_ids(state: Path | None) -> set[str]:
    if state is None:
        return set()
    try:
        root = state.resolve()
    except (OSError, RuntimeError):
        return set()

    native_ids = set()
    for subscription in _map_entries(root, root / "subscriptions"):
        for entry in _map_entries(root, subscription / "chats"):
            if entry.suffix != ".json":
                continue
            try:
                value = json.loads(_regular(root, entry).read_bytes())
            except (OSError, ValueError, RecursionError, SessionFailure):
                continue
            conversation = value.get("conversation") if isinstance(value, dict) else None
            if isinstance(conversation, str) and _NATIVE_ID.fullmatch(conversation):
                native_ids.add(conversation)
    return native_ids
