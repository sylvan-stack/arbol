"""The installation of Arbol's database server (ARC-0.25, ARC-D64, SYL-156).

It makes the server's data folder with PostgreSQL 17's `initdb` and writes its settings: 127.0.0.1 at port 5433,
the socket in a private folder beside the data folder, and a password for every connection over the network. Then
it writes the launch agent that runs the server at login and starts it again whenever it ends, loads it, and waits
until the server answers. Last it makes the role `arbol`, which may log in and create databases and nothing more,
with a password it makes up and stores in the Keychain item `com.sylvan-stack.arbol.database` without ever
printing it; the server receives only the password's SCRAM verifier. It writes the server's address, and nothing
else, to `~/.arbol/database.json` (ARC-1).

It can be run again: a second run keeps the data folder and the password, and writes only what differs, keeping a
copy of every file it replaces. It refuses a data folder that it did not make, and a port that another program
holds.

    uv run --no-sync python database/install_database_server.py

It prints a JSON report and ends with the exit status 0, or 1 with `{"error": {"code", "message"}}` when it refused.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import plistlib
import pwd
import secrets
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database_server import (
    BIN,
    HOST,
    LABEL,
    LAUNCHCTL,
    LSOF,
    MAJOR,
    PORT,
    ROLE,
    SECURITY,
    SERVICE,
    SETTINGS_MARK,
    SOCKET_PATH_LIMIT,
    Places,
    address,
    major_version,
    postmaster_pid,
    run,
)

Report = dict[str, Any]


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Installation:
    places: Places
    owner: str
    bin: Path

    def program(self, name: str) -> str:
        return str(self.bin / name)


def settings_block(places: Places) -> str:
    """The settings this script adds at the end of the data folder's `postgresql.conf`."""
    return (f"{SETTINGS_MARK}\n"
            f"listen_addresses = '{HOST}'\n"
            f"port = {PORT}\n"
            f"unix_socket_directories = '{places.socket}'\n"
            "unix_socket_permissions = 0700\n"
            "password_encryption = 'scram-sha-256'\n"
            "logging_collector = on\n"
            "log_directory = 'log'\n"
            "log_filename = 'postgresql-%a.log'\n"
            "log_rotation_age = '1d'\n"
            "log_rotation_size = 0\n"
            "log_truncate_on_rotation = on\n")


def host_rules(owner: str) -> str:
    """The whole `pg_hba.conf`: the owner's account on the private socket, and a password over 127.0.0.1."""
    return (f"{SETTINGS_MARK}\n"
            "# TYPE  DATABASE  USER  ADDRESS  METHOD\n"
            f"local   all  {owner}  peer\n"
            f"host    all  all  {HOST}/32  scram-sha-256\n")


def keep_copy(installation: Installation, path: Path) -> str | None:
    """Copies a file this script is about to replace into the backups folder, and returns where."""
    if not path.exists():
        return None
    backups = installation.places.backups
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    copy = backups / f"{path.name}.{time.strftime('%Y%m%dT%H%M%S')}"
    shutil.copy2(path, copy)
    return str(copy)


def write_if_different(installation: Installation, path: Path, text: str, mode: int) -> str | None:
    """Writes a file whose text differs, keeping a copy of the old one. Returns the copy's path, or "" if new."""
    try:
        if path.read_text(encoding="utf-8") == text:
            return None
    except FileNotFoundError:
        pass
    copy = keep_copy(installation, path)
    temporary = path.with_name(f".{path.name}.new")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    return copy or ""


def check_programs(installation: Installation) -> Report:
    found: Report = {}
    for name in ("initdb", "pg_ctl", "postgres", "psql", "pg_isready"):
        path = installation.program(name)
        if not os.access(path, os.X_OK):
            raise Refused("postgresql_missing", f"{path} is missing; install PostgreSQL {MAJOR} with Homebrew")
        major, version = major_version(path, installation.places.home)
        if major != MAJOR:
            raise Refused("postgresql_version", f"{path} is version {version}, not {MAJOR}")
        found[name] = version
    return {"bin": str(installation.bin), "version": found["postgres"]}


def check_port(installation: Installation) -> Report:
    """Refuses when a program other than this server listens on the port."""
    ours = postmaster_pid(installation.places.data)
    result = run([LSOF, "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN", "-Fpc"], installation.places.home)
    holders: dict[int, str] = {}
    pid = 0
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
            holders[pid] = ""
        elif line.startswith("c") and pid:
            holders[pid] = line[1:]
    others = {number: name for number, name in holders.items() if number != ours}
    if others:
        named = ", ".join(f"{name} ({number})" for number, name in sorted(others.items()))
        raise Refused("port_taken", f"Port {PORT} is held by another program: {named}")
    return {"port": PORT, "free": not holders}


def make_data_folder(installation: Installation) -> Report:
    """Makes the data folder with `initdb`, or keeps the one this script made, and writes its settings."""
    places = installation.places
    data = places.data
    socket = places.socket / f".s.PGSQL.{PORT}"
    if "'" in str(places.socket):
        raise Refused("bad_folder", f"The socket folder {places.socket} has a quote in its name")
    if len(os.fsencode(socket)) > SOCKET_PATH_LIMIT:
        raise Refused("bad_folder", f"The socket path {socket} is longer than {SOCKET_PATH_LIMIT} bytes")
    if data.exists():
        version_file = data / "PG_VERSION"
        settings_file = data / "postgresql.conf"
        if not version_file.is_file() or not settings_file.is_file():
            raise Refused("foreign_data_folder", f"{data} exists and is not a PostgreSQL data folder")
        if SETTINGS_MARK not in settings_file.read_text(encoding="utf-8"):
            raise Refused("foreign_data_folder", f"{data} was not made by this script")
        version = version_file.read_text(encoding="utf-8").strip()
        if version != str(MAJOR):
            raise Refused("foreign_data_folder", f"{data} is a data folder of PostgreSQL {version}, not {MAJOR}")
        state = "kept"
    else:
        places.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(places.folder, 0o700)
        result = run([installation.program("initdb"), "--pgdata", str(data), "--username", installation.owner,
                      "--encoding", "UTF8", "--no-locale", "--locale-provider", "builtin", "--builtin-locale",
                      "C.UTF-8", "--auth-local", "peer", "--auth-host", "scram-sha-256", "--data-checksums",
                      "--no-instructions"], places.home, timeout=300)
        if result.returncode != 0:
            shutil.rmtree(data, ignore_errors=True)
            raise Refused("initdb_failed", f"initdb ended with {result.returncode}: {result.stderr.strip()}")
        state = "made"
    places.socket.mkdir(mode=0o700, exist_ok=True)
    os.chmod(places.socket, 0o700)
    settings_file = data / "postgresql.conf"
    current = settings_file.read_text(encoding="utf-8")
    base = current.split(SETTINGS_MARK, 1)[0].rstrip("\n")
    settings_copy = write_if_different(installation, settings_file, f"{base}\n\n{settings_block(places)}", 0o600)
    rules_copy = write_if_different(installation, data / "pg_hba.conf", host_rules(installation.owner), 0o600)
    return {"path": str(data), "state": state,
            "settingsChanged": settings_copy is not None, "hostRulesChanged": rules_copy is not None,
            "copies": [copy for copy in (settings_copy, rules_copy) if copy]}


def launch_agent(installation: Installation) -> str:
    """The launch agent: `postgres` on the data folder, started at login and again whenever it ends."""
    places = installation.places
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [installation.program("postgres"), "-D", str(places.data)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "WorkingDirectory": str(places.folder),
        "EnvironmentVariables": {"LANG": "C"},
        "StandardOutPath": str(places.launchd_log),
        "StandardErrorPath": str(places.launchd_log),
    }).decode("utf-8")


def answers(installation: Installation) -> bool:
    places = installation.places
    result = run([installation.program("pg_isready"), "--host", str(places.socket), "--port", str(PORT),
                  "--timeout", "2"], places.home, timeout=10)
    return result.returncode == 0


def start_with_launchd(installation: Installation, settings_changed: bool) -> Report:
    """Writes and loads the launch agent, or restarts the server when its settings changed, and waits for it."""
    places = installation.places
    service = f"gui/{os.getuid()}/{LABEL}"
    places.plist.parent.mkdir(parents=True, exist_ok=True)
    plist_copy = write_if_different(installation, places.plist, launch_agent(installation), 0o644)
    loaded = run([LAUNCHCTL, "print", service], places.home).returncode == 0
    action = "kept"
    if loaded and plist_copy is not None:
        run([LAUNCHCTL, "bootout", service], places.home, timeout=90)
        loaded = False
    if not loaded:
        if postmaster_pid(places.data) is not None:
            # A server that runs on the data folder outside the launch agent is stopped first.
            run([installation.program("pg_ctl"), "--pgdata", str(places.data), "--mode", "fast", "--wait",
                 "--timeout", "60", "stop"], places.home, timeout=90)
        run([LAUNCHCTL, "enable", service], places.home)
        result = run([LAUNCHCTL, "bootstrap", f"gui/{os.getuid()}", str(places.plist)], places.home)
        if result.returncode != 0:
            raise Refused("launchd_failed", f"launchctl bootstrap ended with {result.returncode}: "
                                            f"{(result.stderr or result.stdout).strip()}")
        action = "loaded"
    elif settings_changed:
        run([LAUNCHCTL, "kickstart", "-k", service], places.home, timeout=90)
        action = "restarted"
    deadline = time.monotonic() + 60
    while not answers(installation):
        if time.monotonic() > deadline:
            raise Refused("server_not_answering", f"The server did not answer within 60 seconds; see "
                                                  f"{places.launchd_log} and {places.data / 'log'}")
        time.sleep(0.5)
    return {"plist": str(places.plist), "label": LABEL, "action": action, "pid": postmaster_pid(places.data),
            "copies": [plist_copy] if plist_copy else []}


def keychain_password(installation: Installation) -> str | None:
    """The password of the Keychain item, or None when there is no such item. Never printed."""
    result = run([SECURITY, "find-generic-password", "-s", SERVICE, "-a", ROLE, "-w"], installation.places.home,
                 timeout=10)
    if result.returncode == 44:
        return None
    if result.returncode != 0:
        raise Refused("keychain_failed", f"Reading the Keychain item {SERVICE} ended with {result.returncode}")
    return result.stdout.rstrip("\n")


def store_new_password(installation: Installation) -> str:
    """Makes up a password and stores it in the Keychain item, through standard input so no process list shows it."""
    password = secrets.token_hex(32)
    result = run([SECURITY, "-i"], installation.places.home, timeout=10,
                 input_text=f"add-generic-password -s {SERVICE} -a {ROLE} -w {password}\n")
    # The output of `security -i` may repeat the command, and with it the password: it is never shown.
    if result.returncode != 0 or keychain_password(installation) != password:
        raise Refused("keychain_failed", f"Storing the Keychain item {SERVICE} failed (exit status {result.returncode})")
    return password


def scram_verifier(password: str, iterations: int = 4096) -> str:
    """The SCRAM-SHA-256 verifier PostgreSQL stores for a password (RFC 7677), made here so the server never sees it."""
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    stored_key = hashlib.sha256(hmac.new(salted, b"Client Key", "sha256").digest()).digest()
    server_key = hmac.new(salted, b"Server Key", "sha256").digest()

    def encode(value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    return f"SCRAM-SHA-256${iterations}:{encode(salt)}${encode(stored_key)}:{encode(server_key)}"


def make_role(installation: Installation) -> Report:
    """Makes the role, or brings it back to what it may do, with the password of the Keychain item."""
    places = installation.places
    password = keychain_password(installation)
    state = "kept"
    if password is None:
        password = store_new_password(installation)
        state = "made"
    sql = (f"DO $$BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN CREATE ROLE {ROLE}; "
           "END IF; END$$;\n"
           f"ALTER ROLE {ROLE} WITH LOGIN CREATEDB NOSUPERUSER NOCREATEROLE NOREPLICATION NOBYPASSRLS "
           f"CONNECTION LIMIT -1 PASSWORD '{scram_verifier(password)}';\n")
    result = run([installation.program("psql"), "--no-psqlrc", "--quiet", "--host", str(places.socket), "--port",
                  str(PORT), "--username", installation.owner, "--dbname", "postgres", "--set", "ON_ERROR_STOP=1",
                  "--file", "-"], places.home, input_text=sql, timeout=30)
    if result.returncode != 0:
        first = (result.stderr.strip().splitlines() or [""])[0]
        raise Refused("role_failed", f"Making the role {ROLE} ended with {result.returncode}: {first}")
    check = run([installation.program("psql"), "--no-psqlrc", "--tuples-only", "--no-align", "--command",
                 "select current_user", f"{address()}/postgres"], places.home, timeout=30,
                extra={"PGPASSWORD": password, "PGCONNECT_TIMEOUT": "10"})
    if check.returncode != 0 or check.stdout.strip() != ROLE:
        raise Refused("role_failed", f"The role {ROLE} cannot log in with the password of the Keychain item")
    return {"role": ROLE, "keychainItem": SERVICE, "password": state, "logsIn": True}


def write_settings(installation: Installation) -> Report:
    """Writes `~/.arbol/database.json` with the address and nothing else (ARC-1, ARC-D51)."""
    places = installation.places
    places.settings.parent.mkdir(parents=True, exist_ok=True)
    copy = write_if_different(installation, places.settings, json.dumps({"address": address()}, indent=2) + "\n",
                              0o644)
    return {"path": str(places.settings), "address": address(), "changed": copy is not None,
            "copies": [copy] if copy else []}


def install(installation: Installation) -> Report:
    report: Report = {"programs": check_programs(installation)}
    report["port"] = check_port(installation)
    folder = make_data_folder(installation)
    report["dataFolder"] = folder
    report["launchAgent"] = start_with_launchd(installation, folder["settingsChanged"] or folder["hostRulesChanged"])
    report["role"] = make_role(installation)
    report["settings"] = write_settings(installation)
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bin-dir", type=Path, default=BIN, help=f"PostgreSQL {MAJOR}'s programs (default {BIN})")
    options = parser.parse_args(argv)
    installation = Installation(places=Places(Path.home()), owner=pwd.getpwuid(os.getuid()).pw_name,
                                bin=options.bin_dir)
    try:
        report = install(installation)
    except Refused as refusal:
        print(json.dumps({"error": {"code": refusal.code, "message": str(refusal)}}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
