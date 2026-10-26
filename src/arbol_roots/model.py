"""Catalogue paths, shared Root headers and atomic record writes (ARC-D65–67)."""

import os
from dataclasses import dataclass
from pathlib import Path

from arbol_builds.config import JS_SPACE
from arbol_builds.launcher import BUILD_PATTERN, Record, date, milliseconds, root_identifier
from arbol_builds.pruning import retained_roots
from arbol_builds.roots import current_root, valid_root
from arbol_builds.service import atomic_write, json_text


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Places:
    home: Path
    roots: Path
    settings: Path
    registry: Path
    database_config: Path
    psql: str
    security: str


def places(options: dict[str, str]) -> Places:
    home = Path.home()

    def path(key: str, default: Path) -> Path:
        return Path(os.path.abspath(os.path.expanduser(options.get(key, str(default)))))

    return Places(home, path("--roots-dir", home / "Library/Application Support/Arbol/roots"),
                  path("--settings-dir", home / ".arbol/roots"),
                  path("--registry-dir", home / "Library/Application Support/Arbol/builds"),
                  path("--database-config", home / ".arbol/database.json"),
                  options.get("--psql", "psql"), options.get("--security", "/usr/bin/security"))


def identifier(value: str) -> str:
    if not root_identifier(value):
        raise Refused("invalid_input", "A Root identifier is one lower-case word of letters and digits.")
    return value


def nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip(JS_SPACE):
        raise Refused("invalid_input", field + " must be nonblank text.")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise Refused("invalid_input", field + " must be valid Unicode.") from error
    if "\0" in value:
        raise Refused("invalid_input", field + " must contain no NUL.")
    return value


def database_name(value: object) -> str:
    name = nonblank(value, "Database name")
    if len(name.encode("utf-8")) > 63 or name.lower() in ("postgres", "template0", "template1"):
        raise Refused("invalid_input", "A Root database must fit 63 UTF-8 bytes and be no maintenance/template database.")
    return name


def validate_record(record: Record, *, complete: bool = False) -> None:
    root = record.get("root")
    if not isinstance(root, str) or not valid_root(record, root):
        raise Refused("invalid_input", "The Root record has an invalid identity, state, creation time or contract.")
    for name in ("name", "database", "app"):
        if complete and name not in record:
            raise Refused("invalid_input", "The new Root record needs " + name + ".")
    if "name" in record:
        nonblank(record["name"], "Display name")
    if "database" in record:
        database_name(record["database"])
    if "app" in record and (not isinstance(record["app"], str)
                            or (record["app"] != "0" and BUILD_PATTERN.fullmatch(record["app"]) is None)):
        raise Refused("invalid_input", "The App minimum is a canonical Build number, or the bootstrap sentinel 0.")
    if "grewFrom" in record and (not root_identifier(record["grewFrom"]) or record["grewFrom"] == root):
        raise Refused("invalid_input", "The Root it grew from must name another Root.")
    if record["status"] == "failed":
        failed = record.get("failed")
        if not isinstance(failed, dict) or not date(failed.get("at")):
            raise Refused("invalid_input", "A failed Root needs its failure time and reason.")
        nonblank(failed.get("reason"), "Failure reason")


def catalogue(paths: Places) -> list[Record]:
    """Use the shared header validator/current choice; unreadable records affect only their own Root."""
    try:
        return [record for record in retained_roots(str(paths.roots)).values() if record is not None]
    except ValueError as error:
        raise Refused("operation_failed", str(error)) from error


def list_roots(paths: Places) -> list[Record]:
    records = catalogue(paths)
    current = current_root(records)
    return [{**record, "current": current is not None and record["root"] == current["root"]}
            for record in sorted(records, key=lambda item: (milliseconds(item["createdAt"]), item["root"]), reverse=True)]


def selected(paths: Places, name: str | None) -> Record:
    records = catalogue(paths)
    if name is None:
        found = current_root(records)
    else:
        identifier(name)
        found = next((record for record in records if record["root"] == name), None)
    if found is None:
        message = "No Root is working." if name is None else f"Root {name} has no readable valid root.json."
        raise Refused("unknown_root", message)
    return found


def save_record(paths: Places, record: Record, *, complete: bool = False) -> None:
    validate_record(record, complete=complete)
    atomic_write(str(paths.roots / record["root"] / "root.json"), json_text(record, 2) + b"\n")
