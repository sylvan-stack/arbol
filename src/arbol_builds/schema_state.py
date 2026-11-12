"""Read the installed schema through the migration tool (ARC-4.1)."""

import json
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

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
        name = settings.get("database") if isinstance(settings, dict) else None
        if not isinstance(name, str) or not name or name.startswith("-") or "\0" in name:
            return SchemaState("unavailable")
        result = subprocess.run([sys.executable, "-EsB", str(tool), "--database", name, "status"],
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
    if result.returncode and isinstance(status, str) and status in SCHEMA_ERRORS:
        return SchemaState(status)
    revision, version = payload.get("revision"), payload.get("compatibilityVersion")
    if (result.returncode == 0 and status == "ready" and type(revision) is int and positive(revision)
            and type(version) is int and positive(version) and version <= revision):
        return SchemaState("ready", SchemaPair(revision, version))
    return SchemaState("invalid")
