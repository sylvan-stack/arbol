"""Process identity for agent records (AGR-0.4, AGR-0.5)."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime

from .model import Owner

ENVIRONMENT = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish"}


class Processes:
    def output(self, *arguments: str) -> str:
        result = subprocess.run(
            ["/bin/ps", *arguments],
            capture_output=True,
            text=True,
            check=True,
            timeout=1,
            env=ENVIRONMENT,
        )
        return result.stdout.strip()

    def started(self, pid: int) -> str:
        printed = self.output("-o", "lstart=", "-p", str(pid))
        moment = datetime.strptime(printed, "%a %b %d %H:%M:%S %Y").astimezone()
        return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def alive(self, owner: Owner) -> bool:
        try:
            printed = self.output("-o", "lstart=", "-p", str(owner.pid))
            current = datetime.strptime(printed, "%a %b %d %H:%M:%S %Y").astimezone()
            recorded = datetime.fromisoformat(owner.startedAt.replace("Z", "+00:00"))
            return abs((current - recorded).total_seconds()) <= 2
        except (OSError, ValueError, subprocess.SubprocessError):
            return False

    def command(self, pid: int) -> str:
        return self.output("-o", "command=", "-p", str(pid))

    def parent(self, pid: int) -> int:
        return int(self.output("-o", "ppid=", "-p", str(pid)))

    def candidate(self, tool: str, known_owner: int | None) -> int:
        if tool == "claude-code":
            pid = int(os.environ["CLAUDE_PID"])
            if pid <= 0:
                raise ValueError("Invalid CLAUDE_PID.")
            return pid
        pid = os.getppid()
        if pid == known_owner:
            return pid
        command = self.command(pid)
        executable = command.split(maxsplit=1)[0].rsplit("/", 1)[-1] if command else ""
        if executable not in SHELLS:
            return pid
        return self.parent(pid)

    def entrypoint(self, tool: str, pid: int, existing: str | None = None) -> str | None:
        if tool == "claude-code":
            return os.environ.get("CLAUDE_CODE_ENTRYPOINT")
        if existing is not None:
            return existing
        command = self.command(pid)
        words = command.split()
        return "app-server" if len(words) > 1 and words[0].endswith("codex") and words[1] == "app-server" else "cli"
