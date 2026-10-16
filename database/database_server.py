"""What the installation and the probe of Arbol's database server share (ARC-0, ARC-1, ARC-D64).

The server is Arbol's own PostgreSQL 17, installed with Homebrew and run from a data folder of its own by a
launch agent of the owner's account. It listens on 127.0.0.1 at PORT and on a socket in a private folder that only
the installation uses. Its role ROLE has its password in the Keychain item SERVICE, and `~/.arbol/database.json`
holds the address and nothing else.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAJOR = 17
HOST = "127.0.0.1"
PORT = 5433
ROLE = "arbol"
SERVICE = "com.sylvan-stack.arbol.database"
LABEL = "com.sylvan-stack.arbol.database"
BIN = Path("/opt/homebrew/opt/postgresql@17/bin")
PROGRAMS = ("initdb", "pg_ctl", "createdb", "psql", "pg_dump")
SECURITY = "/usr/bin/security"
LAUNCHCTL = "/bin/launchctl"
LSOF = "/usr/sbin/lsof"
SOCKET_PATH_LIMIT = 103
SETTINGS_MARK = "# Arbol's database server (install_database_server.py, ARC-D64)."


@dataclass(frozen=True)
class Places:
    """The files of the server, all reached from one home folder."""

    home: Path

    @property
    def folder(self) -> Path:
        return self.home / "Library" / "Application Support" / "Arbol" / "database"

    @property
    def data(self) -> Path:
        return self.folder / "data"

    @property
    def socket(self) -> Path:
        return self.folder / "socket"

    @property
    def launchd_log(self) -> Path:
        return self.folder / "launchd.log"

    @property
    def backups(self) -> Path:
        return self.folder / "backups"

    @property
    def plist(self) -> Path:
        return self.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"

    @property
    def settings(self) -> Path:
        return self.home / ".arbol" / "database.json"


def address() -> str:
    """The address of `~/.arbol/database.json` (ARC-1): role, host and port, never a password."""
    return f"postgresql://{ROLE}@{HOST}:{PORT}"


def environment(home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """A minimal environment, so that no `PG…` variable of the caller's shell reaches a program."""
    values = {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C"}
    values.update(extra or {})
    return values


def run(command: list[str], home: Path, *, timeout: float = 60, input_text: str | None = None,
        extra: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Runs a program with the minimal environment and returns its result without judging it."""
    return subprocess.run(command, input=input_text, capture_output=True, text=True, timeout=timeout,
                          env=environment(home, extra), cwd=cwd or home,
                          stdin=None if input_text is not None else subprocess.DEVNULL, check=False)


def major_version(program: str, home: Path) -> tuple[int | None, str]:
    """The major version a PostgreSQL program reports, such as 17 for `psql (PostgreSQL) 17.11 (Homebrew)`."""
    result = run([program, "--version"], home, timeout=30)
    text = result.stdout.strip()
    try:
        number = text.split(")", 1)[1].split()[0]
        return int(number.split(".")[0]), number
    except (IndexError, ValueError):
        return None, text


def postmaster_pid(data: Path) -> int | None:
    """The process number of the server that runs on the data folder, from its `postmaster.pid`."""
    try:
        pid = int((data / "postmaster.pid").read_text(encoding="utf-8").split("\n", 1)[0])
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return pid
    return pid
