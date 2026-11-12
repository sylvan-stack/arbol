"""Installation identity, private paths and optional route defaults (BKD-0)."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT_ID = re.compile(r"[a-z0-9]+\Z", re.ASCII)
BUILD_ID = re.compile(r"[1-9a-f][0-9a-f]*\Z", re.ASCII)
ISOLATION = {"--runtime-dir", "--bin-dir", "--settings-dir", "--database"}
OPTIONS = ISOLATION
FLAGS = {"--text"}  # the options of `arbol vigor` without a value (SGM-D28)
OPTIONAL = {"--refresh"}  # the options of `arbol vigor` whose value may be absent
VERBS = ("backend", "vigor")
ACTIONS = {"learn": 0, "profiles": 0, "approve": 1}  # the words after `vigor` and the values each takes (SGM-1.11)
USAGE = (
    "Usage: arbol backend [acquire] [isolation options] | vigor [--refresh [<driver>/<subscription>]] [--text]"
    " | vigor learn|profiles|approve <version> [--text]."
)


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def object_file(path: Path) -> dict[str, Any]:
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > 1024 * 1024:
        raise ValueError("Expected a regular bounded JSON object.")
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value


def parse(args: list[str]) -> dict[str, str]:
    words: list[str] = []
    options: dict[str, str] = {}
    i = 0
    while i < len(args):
        word = args[i]
        if word in OPTIONS:
            if word in options or i + 1 == len(args) or not args[i + 1] or args[i + 1].startswith("--"):
                raise Refused("invalid_input", "An option is repeated or lacks its value.")
            options[word] = args[i + 1]
            i += 2
        elif word in FLAGS or word in OPTIONAL:
            if word in options:
                raise Refused("invalid_input", "An option is repeated or lacks its value.")
            value = ""
            if word in OPTIONAL and i + 1 < len(args) and args[i + 1] and not args[i + 1].startswith("-"):
                value = args[i + 1]
            options[word] = value
            i += 2 if value else 1
        elif word.startswith("-"):
            raise Refused("invalid_input", "Unknown option.")
        else:
            words.append(word)
            i += 1
    if not words or words[0] not in VERBS:
        raise Refused("invalid_input", USAGE)
    if len(words) > 1 and not (words == ["backend", "acquire"] or (
            words[0] == "vigor" and words[1] in ACTIONS and len(words) == 2 + ACTIONS[words[1]])):
        raise Refused("invalid_input", USAGE)
    if len(words) > 1 and "--refresh" in options:
        raise Refused("invalid_input", "--refresh belongs to the read arbol vigor.")
    if words[0] == "backend" and options.keys() & (FLAGS | OPTIONAL):
        raise Refused("invalid_input", "--refresh and --text belong to arbol vigor.")
    if options.keys() & ISOLATION and not {"--runtime-dir", "--bin-dir"} <= options.keys():
        raise Refused("invalid_input", "Isolation requires --runtime-dir and --bin-dir with a private database socket.")
    options["verb"] = words[0]
    if len(words) > 1:
        options["action"] = words[1]
        if len(words) > 2:
            options["version"] = words[2]
    return options


@dataclass(frozen=True)
class Identity:
    build: str
    folder: Path
    bin_dir: Path
    settings: Path
    database: str | None
    home: Path
    package: Path
    compatibility: tuple[tuple[int, int], ...]
    fixture: bool = False


def schema_compatibility(value: object) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("Missing schema compatibility.")
    versions: dict[int, int] = {}
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"compatibilityVersion", "minRevision"}:
            raise ValueError("Invalid schema compatibility entry.")
        version, revision = entry["compatibilityVersion"], entry["minRevision"]
        if type(version) is not int or type(revision) is not int or version < 1 or revision < 1 or version in versions:
            raise ValueError("Invalid schema compatibility pair.")
        versions[version] = revision
    return tuple(versions.items())


def private_directory(folder: Path) -> None:
    try:
        info = folder.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Expected an owner-only directory.")
    except (OSError, ValueError) as error:
        raise Refused("invalid_input", "The installation runtime directory is not private.") from error


def identity(package: Path, options: dict[str, str], *, home: Path | None = None) -> Identity:
    home = home or Path.home()
    number = "0"
    try:
        if os.path.lexists(package / "build.json"):
            record = object_file(package / "build.json")
            manifest = object_file(package / "package.json")
            version = manifest.get("version")
            compatibility = schema_compatibility(record.get("schemaCompatibility"))
            if (
                record.get("component") != "arbol"
                or record.get("entry") != "bin/arbol"
                or "root" in record
                or not isinstance(record.get("build"), str)
                or not BUILD_ID.fullmatch(record["build"])
                or not isinstance(version, str)
                or record.get("packageVersion") != version
                or dict(schema_compatibility(manifest.get("schemaCompatibility"))) != dict(compatibility)
            ):
                raise ValueError("Invalid Build identity.")
            number = record["build"]
        else:
            description = object_file(package / "arbol-build.json")
            compatibility = schema_compatibility(description.get("schemaCompatibility"))
    except (OSError, ValueError, UnicodeError) as error:
        raise Refused("invalid_input", "Cannot read the backend Build and its schema compatibility.") from error

    def path(key: str, default: Path) -> Path:
        return Path(os.path.abspath(os.path.expanduser(options.get(key, str(default)))))

    installed = home / "Library/Application Support/Arbol/runtime"
    folder = path("--runtime-dir", installed)
    if "--runtime-dir" in options:
        if folder.resolve() == installed.resolve():
            raise Refused("invalid_input", "An isolated backend cannot use the installed runtime directory.")
    if len(os.fsencode(folder / "backend.sock")) > 103:
        raise Refused("invalid_input", "The backend socket path exceeds 103 bytes.")
    return Identity(
        number, folder, path("--bin-dir", home / ".local/bin"),
        path("--settings-dir", home / ".arbol" if folder == installed else folder / "settings"),
        options.get("--database"), home, package,
        compatibility, bool(options.keys() & ISOLATION),
    )


def route(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("A route must be an object.")
    result: dict[str, str] = {}
    for key in ("driver", "subscription", "model", "effort"):
        if key in value:
            if not isinstance(value[key], str) or not value[key].strip() or "\0" in value[key]:
                raise ValueError("Known route fields must be nonblank strings.")
            result[key] = value[key]
    return result


@dataclass(frozen=True)
class Settings:
    route: dict[str, str]
    repositories: dict[str, dict[str, str]]
    small_call_route: dict[str, str] | None

    def for_repository(self, repository: str) -> dict[str, str]:
        return dict(self.repositories.get(repository, self.route))


def settings(folder: Path) -> Settings:
    try:
        path = folder / "arbol.json"
        value = object_file(path) if path.exists() else {}
        repositories = value.get("repositories", {})
        if not isinstance(repositories, dict):
            raise ValueError("repositories must be an object.")
        rows: dict[str, dict[str, str]] = {}
        for key, item in repositories.items():
            if not isinstance(item, dict):
                raise ValueError("Repository settings must be an object.")
            if "route" in item:
                rows[key] = route(item["route"])
        return Settings(
            route(value.get("route", {})), rows, route(value["smallCallRoute"]) if "smallCallRoute" in value else None
        )
    except (OSError, ValueError, UnicodeError) as error:
        raise Refused("invalid_input", "Cannot read valid arbol.json defaults.") from error
