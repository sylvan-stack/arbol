"""Private, locked and whole-written agent-record files (AGR-0.1 to AGR-0.3)."""

from __future__ import annotations

import fcntl
import json
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .model import AgentRecord

IDENTIFIER = re.compile(r"[A-Za-z0-9-]+")
TOOLS = {"claude-code", "codex", "kimi-code"}


def folder() -> Path:
    override = os.environ.get("ARBOL_AGENTS_DIR")
    if override:
        return Path(os.path.abspath(os.path.expanduser(override)))
    return Path.home() / "Library" / "Application Support" / "Arbol" / "agents"


class Store:
    def __init__(self, location: Path | None = None) -> None:
        self.folder = location or folder()

    def path(self, tool: str, session: str) -> Path:
        if tool not in TOOLS or IDENTIFIER.fullmatch(session) is None:
            raise ValueError("Invalid tool or session identifier.")
        return self.folder / f"{tool}-{session}.json"

    def read(self, tool: str, session: str) -> AgentRecord | None:
        try:
            value = json.loads(self.path(tool, session).read_text(encoding="utf-8"))
            record = AgentRecord.parse(value)
            if record.tool != tool or record.session != session:
                return None
            return record
        except (OSError, UnicodeError, ValueError, TypeError):
            return None

    def write(self, record: AgentRecord) -> None:
        path = self.path(record.tool, record.session)
        temporary = self.folder / f".{path.name}.{os.getpid()}.tmp"
        contents = json.dumps(record.json(), ensure_ascii=False, indent=2).encode("utf-8", "backslashreplace") + b"\n"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(contents)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(self.folder, 0o700)
        descriptor = os.open(self.folder / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.chmod(self.folder / ".lock", 0o600)
            deadline = time.monotonic() + 1
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("The agent-record lock is busy.") from None
                    time.sleep(0.01)
            yield
        finally:
            os.close(descriptor)
