"""The probe of Arbol's database server (ARC-0.25, SYL-156).

It checks that the programs of PostgreSQL 17 are found in a newly opened terminal and can make a throwaway
server, as the Root Contract's suite does (RCT-4), and that the installed server answers on 127.0.0.1 at the port
of `~/.arbol/database.json` and on no other address of the Mac. With the password of the Keychain item it connects
as the role of that address, sees that the role may log in and create databases and nothing more, and makes a
database and removes it; it reads the size of the data folder and that it lies on the Mac's own disk. It prints a JSON report and leaves nothing behind. The password
of the Keychain item is never printed.

    uv run --no-sync python database/probe_database_server.py

It ends with the exit status 0 when every check passed and 1 when one failed.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import plistlib
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from database_server import BIN, LSOF, MAJOR, PROGRAMS, SECURITY, SERVICE, Places, major_version, postmaster_pid, run

MARKER = "@@arbol-probe"
THROWAWAY_ROLE = "probe"
THROWAWAY_PORT = 5432

Detail = dict[str, Any]


@dataclass
class Context:
    places: Places
    restart: bool
    programs: dict[str, str] = field(default_factory=dict)
    role: str = ""
    host: str = ""
    port: int = 0


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


def check_settings(context: Context) -> Detail:
    """`~/.arbol/database.json` holds the address and nothing else: a role, a host and a port (ARC-1)."""
    path = context.places.settings
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as problem:
        raise Failed(f"{path} cannot be read: {problem}") from problem
    if not isinstance(settings, dict) or set(settings) != {"address"} or not isinstance(settings["address"], str):
        raise Failed(f"{path} must hold only an address")
    parts = urlsplit(settings["address"])
    if (parts.scheme != "postgresql" or not parts.username or parts.password is not None or not parts.hostname
            or not parts.port or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise Failed(f"{path} does not hold a role, a host and a port, and nothing else")
    context.role, context.host, context.port = parts.username, parts.hostname, parts.port
    return {"path": str(path), "address": settings["address"]}


def interface_addresses(home: Path) -> list[str]:
    """Every address of the Mac's network interfaces, IPv4 and IPv6, as `ifconfig` lists them."""
    found: list[str] = []
    for line in run(["/sbin/ifconfig"], home).stdout.splitlines():
        words = line.split()
        if len(words) >= 2 and words[0] in ("inet", "inet6"):
            found.append(words[1])
    return found


def accepts(host: str, port: int) -> bool:
    try:
        family, kind, protocol, _, target = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0]
        with socket.socket(family, kind, protocol) as connection:
            connection.settimeout(2)
            connection.connect(target)
        return True
    except OSError:
        return False


def check_listening(context: Context) -> Detail:
    """The server of the data folder answers on 127.0.0.1 at the port and on no other address of the Mac."""
    if context.host != "127.0.0.1" or not context.port:
        raise Failed(f"the address names {context.host}:{context.port}, not 127.0.0.1")
    places = context.places
    home = places.home
    pid = postmaster_pid(places.data)
    if pid is None:
        raise Failed(f"no server runs on {places.data}")
    executable = run(["/bin/ps", "-o", "comm=", "-p", str(pid)], home).stdout.strip()
    sockets = run([LSOF, "-nP", "-a", "-p", str(pid), "-i", "-FPn"], home).stdout.splitlines()
    listens: list[str] = []
    protocol = ""
    for line in sockets:
        if line.startswith("P"):
            protocol = line[1:]
        elif line.startswith("n"):
            listens.append(f"{protocol} {line[1:]}")
    holders = run([LSOF, "-nP", f"-iTCP:{context.port}", "-sTCP:LISTEN", "-t"], home).stdout.split()
    others = [address for address in interface_addresses(home) if address != context.host]
    answered_elsewhere = [address for address in others if accepts(address, context.port)]
    ready = run([str(BIN / "pg_isready"), "--host", context.host, "--port", str(context.port), "--timeout", "5"],
                home, timeout=15).returncode == 0
    detail: Detail = {"pid": pid, "executable": executable, "listens": listens,
                      "portHolders": [int(holder) for holder in holders],
                      "otherAddressesTried": len(others), "answeredElsewhere": answered_elsewhere,
                      "answersOnLoopback": accepts(context.host, context.port) and ready}
    problems: list[str] = []
    if executable != str(BIN / "postgres"):
        problems.append(f"the process {pid} is {executable}, not {BIN / 'postgres'}")
    if listens != [f"TCP {context.host}:{context.port}"]:
        problems.append(f"the server listens on {listens}, not only on {context.host}:{context.port}")
    if detail["portHolders"] != [pid]:
        problems.append(f"port {context.port} is held by {detail['portHolders']}, not only by the server {pid}")
    if answered_elsewhere:
        problems.append(f"the port answers on other addresses of the Mac: {answered_elsewhere}")
    if not detail["answersOnLoopback"]:
        problems.append(f"the server does not answer on {context.host}:{context.port}")
    if problems:
        raise Failed("; ".join(problems))
    return detail


def keychain_password(context: Context) -> str:
    """The password of the Keychain item for the role of the address. Never printed."""
    result = run([SECURITY, "find-generic-password", "-s", SERVICE, "-a", context.role, "-w"], context.places.home,
                 timeout=10)
    if result.returncode == 44:
        raise Failed(f"the Keychain has no item {SERVICE} for the account {context.role}")
    if result.returncode != 0:
        raise Failed(f"reading the Keychain item {SERVICE} ended with {result.returncode}")
    return result.stdout.rstrip("\n")


def psql(context: Context, sql: str, password: str | None) -> tuple[int, str]:
    """Runs one statement as the role of the address, over 127.0.0.1, with the password or with none at all."""
    extra = {"PGCONNECT_TIMEOUT": "10", "PGPASSFILE": "/dev/null"}
    if password is not None:
        extra["PGPASSWORD"] = password
    target = f"postgresql://{context.role}@{context.host}:{context.port}/postgres"
    result = run([str(BIN / "psql"), "--no-psqlrc", "--tuples-only", "--no-align", "--field-separator", "|",
                  "--set", "ON_ERROR_STOP=1", "--command", sql, target], context.places.home, timeout=30, extra=extra)
    if result.returncode != 0:
        first = (result.stderr.strip().splitlines() or [""])[0]
        return result.returncode, first
    return 0, result.stdout.strip()


def check_role(context: Context) -> Detail:
    """The address with the Keychain's password connects; the role may log in and create databases, nothing more."""
    if not context.role or not context.port:
        raise Failed("the address of database.json is not known")
    password = keychain_password(context)
    status, answer = psql(context, "select current_user, r.rolcanlogin, r.rolcreatedb, r.rolsuper, "
                          "r.rolcreaterole, r.rolreplication, r.rolbypassrls, "
                          "(select count(*) from pg_auth_members m where m.member = r.oid), "
                          "current_setting('server_version') from pg_roles r where r.rolname = current_user",
                          password)
    if status != 0:
        raise Failed(f"the address with the Keychain's password does not connect: {answer}")
    fields = answer.split("|")
    if len(fields) != 9:
        raise Failed(f"unexpected answer about the role: {answer}")
    user, login, createdb, superuser, createrole, replication, bypassrls, memberships, version = fields
    without_status, without_answer = psql(context, "select 1", None)
    detail: Detail = {"connectedAs": user, "serverVersion": version, "mayLogIn": login == "t",
                      "mayCreateDatabases": createdb == "t", "superuser": superuser == "t",
                      "mayCreateRoles": createrole == "t", "replication": replication == "t",
                      "bypassesRowSecurity": bypassrls == "t", "memberOfRoles": int(memberships),
                      "refusedWithoutPassword": without_status != 0}
    problems: list[str] = []
    if user != context.role:
        problems.append(f"connected as {user}, not {context.role}")
    if not version.startswith(f"{MAJOR}."):
        problems.append(f"the server is version {version}, not {MAJOR}")
    if not (detail["mayLogIn"] and detail["mayCreateDatabases"]):
        problems.append("the role may not log in and create databases")
    if detail["superuser"] or detail["mayCreateRoles"] or detail["replication"] or detail["bypassesRowSecurity"] \
            or detail["memberOfRoles"]:
        problems.append("the role may do more than log in and create databases")
    if not detail["refusedWithoutPassword"]:
        problems.append(f"the server let the role in without a password: {without_answer}")
    name = f"arbol_probe_{secrets.token_hex(4)}"
    made = removed = False
    try:
        status, answer = psql(context, f"create database {name}", password)
        if status != 0:
            problems.append(f"the role could not make a database: {answer}")
        else:
            made = psql(context, f"select count(*) from pg_database where datname = '{name}'", password) == (0, "1")
    finally:
        status, answer = psql(context, f"drop database if exists {name}", password)
        removed = status == 0 and psql(context, f"select count(*) from pg_database where datname = '{name}'",
                                       password) == (0, "0")
    detail["databaseMade"] = made
    detail["databaseRemoved"] = removed
    if not (made and removed):
        problems.append(f"the database {name} was not made and removed")
    if problems:
        raise Failed("; ".join(problems))
    return detail


def check_data_folder(context: Context) -> Detail:
    """The data folder lies on the Mac's own disk, and its size can be read like that of any folder (ARC-0)."""
    data = context.places.data
    home = context.places.home
    size = files = 0
    for folder, _, names in os.walk(data):
        for name in names:
            try:
                size += os.lstat(os.path.join(folder, name)).st_size
                files += 1
            except FileNotFoundError:
                pass  # the server removed it meanwhile
    lines = run(["/bin/df", "-Pk", str(data)], home).stdout.splitlines()
    if len(lines) < 2:
        raise Failed(f"df cannot tell where {data} lies")
    device, _, _, available, _, mount = lines[1].split(None, 5)
    info = run(["/usr/sbin/diskutil", "info", "-plist", device], home)
    disk = plistlib.loads(info.stdout.encode("utf-8")) if info.returncode == 0 else {}
    detail: Detail = {"path": str(data), "bytes": size, "files": files, "device": device, "mountPoint": mount,
                      "internal": disk.get("Internal"), "removable": disk.get("RemovableMedia"),
                      "fileSystem": disk.get("FilesystemType"), "freeBytes": int(available) * 1024}
    if not files:
        raise Failed(f"{data} holds no files")
    if not device.startswith("/dev/disk") or detail["internal"] is not True or detail["removable"] is not False:
        raise Failed(f"{data} does not lie on the Mac's own disk: {device} at {mount}")
    return detail


CHECKS: list[tuple[str, Callable[[Context], Detail]]] = [
    ("programs", check_programs),
    ("throwaway-server", check_throwaway_server),
    ("settings", check_settings),
    ("listening", check_listening),
    ("role", check_role),
    ("data-folder", check_data_folder),
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
