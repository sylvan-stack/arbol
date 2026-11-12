"""Read the installed schema through the migration tool (ARC-4.1)."""

import json
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote, urlsplit

from .launcher import positive

SCHEMA_STATUS_SECONDS = 10
SCHEMA_ERRORS = {
    "unavailable": ("database_unavailable", "Cannot read the installed Arbol database."),
    "uninitialized": ("schema_uninitialized", "The installed Arbol database has no initialized schema."),
    "invalid": ("schema_invalid", "The installed Arbol migration history could not be verified."),
}


class SchemaPair(NamedTuple):
    revision: int
    compatibility_version: int


class SchemaState(NamedTuple):
    status: str
    pair: SchemaPair | None = None


def read_schema() -> SchemaState:
    """Use the release staged beside the launcher or registry tool, with the one configured database name."""
    home = Path.home()
    tool = Path(sys.argv[0]).resolve().parent / ".arbol-builds" / "schema" / "migrate_schema.py"
    try:
        settings = json.loads((home / ".arbol" / "database.json").read_text(encoding="utf-8"))
        if not isinstance(settings, dict) or set(settings) != {"address", "database"}:
            return SchemaState("unavailable")
        name, address = settings["database"], settings["address"]
        if not isinstance(name, str) or not isinstance(address, str) or not name:
            return SchemaState("unavailable")
        url = urlsplit(address)
        host = unquote(url.hostname or "", errors="strict")
        command = [sys.executable, "-EsB", str(tool), f"--database={name}"]
        if host.startswith("/"):
            if (url.scheme not in ("postgresql", "postgres") or url.password is not None
                    or url.path not in ("", "/") or url.query or url.fragment or not url.username or not url.port):
                return SchemaState("unavailable")
            command.extend(("--socket", host, "--port", str(url.port), "--user", unquote(url.username)))
        result = subprocess.run([*command, "status"],
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=SCHEMA_STATUS_SECONDS,
                                check=False)
    except (OSError, ValueError, subprocess.SubprocessError):
        return SchemaState("unavailable")
    try:
        payload = json.loads(result.stdout)
    except (UnicodeError, ValueError):
        return SchemaState("unavailable" if result.returncode else "invalid")
    if not isinstance(payload, dict):
        return SchemaState("invalid")
    status = payload.get("status")
    if result.returncode and status == "invalid_input":
        return SchemaState("unavailable")
    if result.returncode and isinstance(status, str) and status in SCHEMA_ERRORS:
        return SchemaState(status)
    revision, version = payload.get("revision"), payload.get("compatibilityVersion")
    if (result.returncode == 0 and status == "ready" and type(revision) is int and positive(revision)
            and type(version) is int and positive(version) and version <= revision):
        return SchemaState("ready", SchemaPair(revision, version))
    return SchemaState("invalid")
