"""The probe of Arbol's database server (ARC-0.25, SYL-156).

It checks that the programs of PostgreSQL 17 are found in a newly opened terminal and can make a throwaway
server, as the Root Contract's suite does (RCT-4). It prints a JSON report and leaves nothing behind. The password
of the Keychain item is never printed.

    uv run --no-sync python database/probe_database_server.py

It ends with the exit status 0 when every check passed and 1 when one failed.
"""

from __future__ import annotations

import argparse
import getpass
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from database_server import LSOF, MAJOR, PROGRAMS, Places, major_version, postmaster_pid, run

MARKER = "@@arbol-probe"
THROWAWAY_ROLE = "probe"
THROWAWAY_PORT = 5432

Detail = dict[str, Any]


@dataclass
class Context:
    places: Places
    restart: bool
    programs: dict[str, str] = field(default_factory=dict)


class Failed(Exception):
    """A check found something wrong; its message says what."""


def check_programs(context: Context) -> Detail:
    """A newly opened terminal finds the five programs, and each is PostgreSQL 17."""
    home = context.places.home
    script = "; ".join(f'print -r -- "{MARKER} {name} $(whence -p {name})"' for name in PROGRAMS)
    user = getpass.getuser()
    shell = subprocess.run(["/usr/bin/env", "-i", f"HOME={home}", f"USER={user}", f"LOGNAME={user}",
                            "TERM=xterm-256color", "/bin/zsh", "-l", "-i", "-c", script],
                           capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, cwd=home,
                           check=False)
    found: dict[str, str] = {}
    for line in shell.stdout.splitlines():
        if line.startswith(MARKER + " "):
            parts = line.split(" ", 2)
            if len(parts) == 3 and parts[2]:
                found[parts[1]] = parts[2]
    detail: Detail = {}
    problems: list[str] = []
    for name in PROGRAMS:
        path = found.get(name)
        if path is None:
            problems.append(f"{name} is not on the search path of a new terminal")
            detail[name] = None
            continue
        major, version = major_version(path, home)
        detail[name] = {"path": path, "version": version}
        if major != MAJOR:
            problems.append(f"{name} is version {version}, not {MAJOR}")
    context.programs = found
    if problems:
        raise Failed("; ".join(problems))
    return detail


def check_throwaway_server(context: Context) -> Detail:
    """`initdb` makes a server in a temporary folder that listens only on a socket; it is stopped and removed."""
    tools = context.programs
    if any(name not in tools for name in PROGRAMS):
        raise Failed("the programs were not all found")
    home = context.places.home
    work = Path(tempfile.mkdtemp(prefix="arbol-probe-"))
    sockets = Path(tempfile.mkdtemp(prefix="arbol-probe-", dir="/tmp"))
    data = work / "data"
    detail: Detail = {}

    def must(command: list[str], what: str, timeout: float = 120) -> str:
        result = run(command, home, timeout=timeout)
        if result.returncode != 0:
            raise Failed(f"{what} ended with {result.returncode}: {(result.stderr or result.stdout).strip()}")
        return result.stdout

    connect = ["--host", str(sockets), "--port", str(THROWAWAY_PORT), "--username", THROWAWAY_ROLE]
    try:
        must([tools["initdb"], "--pgdata", str(data), "--username", THROWAWAY_ROLE, "--auth", "trust",
              "--encoding", "UTF8", "--no-locale", "--no-instructions"], "initdb")
        with (data / "postgresql.conf").open("a", encoding="utf-8") as settings:
            settings.write("\n# The probe's throwaway server: a socket only, in its own folder.\n"
                           "listen_addresses = ''\n"
                           f"unix_socket_directories = '{sockets}'\n"
                           f"port = {THROWAWAY_PORT}\n")
        must([tools["pg_ctl"], "--pgdata", str(data), "--log", str(work / "server.log"), "--wait",
              "--timeout", "60", "start"], "pg_ctl start")
        pid = postmaster_pid(data)
        if pid is None:
            raise Failed("the throwaway server has no running postmaster")
        network = run([LSOF, "-nP", "-a", "-p", str(pid), "-i"], home)
        detail["networkSockets"] = [line for line in network.stdout.splitlines()[1:] if line]
        socket_file = sockets / f".s.PGSQL.{THROWAWAY_PORT}"
        detail["socket"] = socket_file.is_socket()
        must([tools["createdb"], *connect, "probe"], "createdb")
        detail["answer"] = must([tools["psql"], "--no-psqlrc", *connect, "--dbname", "probe", "--tuples-only",
                                 "--no-align", "--command", "select 1"], "psql").strip()
        must([tools["pg_dump"], *connect, "--schema-only", "probe"], "pg_dump")
        detail["pgDump"] = True
        if detail["networkSockets"]:
            raise Failed("the throwaway server listens on a network address")
        if not detail["socket"] or detail["answer"] != "1":
            raise Failed("the throwaway server did not answer on its socket")
    finally:
        if (data / "postmaster.pid").exists():
            run([tools["pg_ctl"], "--pgdata", str(data), "--mode", "fast", "--wait", "--timeout", "60", "stop"],
                home, timeout=90)
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(sockets, ignore_errors=True)
        detail["removed"] = not work.exists() and not sockets.exists()
    if not detail["removed"]:
        raise Failed("the throwaway server's folders were not removed")
    return detail


CHECKS: list[tuple[str, Callable[[Context], Detail]]] = [
    ("programs", check_programs),
    ("throwaway-server", check_throwaway_server),
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--restart", action="store_true",
                        help="also stop the installed server's process and see launchd start it again")
    options = parser.parse_args(argv)
    context = Context(places=Places(Path.home()), restart=options.restart)
    report: list[Detail] = []
    for name, check in CHECKS:
        entry: Detail = {"check": name}
        try:
            entry["detail"] = check(context)
            entry["passed"] = True
        except Failed as problem:
            entry["passed"] = False
            entry["problem"] = str(problem)
        except (OSError, subprocess.SubprocessError) as problem:
            entry["passed"] = False
            entry["problem"] = f"{type(problem).__name__}: {problem}"
        report.append(entry)
    passed = all(entry["passed"] for entry in report)
    print(json.dumps({"passed": passed, "checks": report}, indent=2, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
