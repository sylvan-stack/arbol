"""Read Kimi Code's saved session wires and identify their raw archive files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .form import SessionFailure

_SESSION = re.compile(r"session_([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")


@dataclass(frozen=True)
class _SavedSession:
    folder: Path
    workspace: str
    native_id: str

    @property
    def state(self) -> Path:
        return self.folder / "state.json"

    @property
    def main(self) -> Path:
        return self.folder / "agents/main/wire.jsonl"


def _eligible(home: Path, path: Path, *, directory: bool = False) -> bool:
    # The home itself has already been resolved. Reject aliases beneath it so an allowed
    # filename cannot point to a different session or to credentials or caches.
    try:
        return path.resolve() == path and (path.is_dir() if directory else path.is_file())
    except (OSError, ValueError, RuntimeError):
        return False


def _children(home: Path, directory: Path) -> tuple[Path, ...]:
    if not _eligible(home, directory, directory=True):
        return ()
    try:
        return tuple(sorted(directory.iterdir()))
    except OSError:
        raise SessionFailure("unreadable_session", f"{directory.relative_to(home)}: could not list the directory.") \
            from None


def _discover(home: Path) -> dict[str, _SavedSession]:
    sessions: dict[str, _SavedSession] = {}
    for workspace in _children(home, home / "sessions"):
        for folder in _children(home, workspace):
            match = _SESSION.fullmatch(folder.name)
            if match and _eligible(home, folder, directory=True):
                native_id = match[1].lower()
                sessions.setdefault(native_id, _SavedSession(folder, workspace.name, native_id))
    return sessions


def _wires(home: Path, session: _SavedSession) -> dict[str, Path]:
    if not _eligible(home, session.main):
        raise SessionFailure("unreadable_session", f"{session.main.relative_to(home)}: no eligible main wire.")
    wires = {"main": session.main}
    for agent in _children(home, session.folder / "agents"):
        wire = agent / "wire.jsonl"
        if agent.name != "main" and _eligible(home, wire):
            wires[agent.name] = wire
    return wires
