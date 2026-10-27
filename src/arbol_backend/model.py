"""Command identity, Root metadata and optional route defaults (BKD-0)."""

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
OPTIONS = {"--root", "--root-dir", "--bin-dir", "--settings-dir", "--database"}
FLAGS = {"--text"}  # the options of `arbol vigor` without a value (SGM-D28)
OPTIONAL = {"--refresh"}  # the options of `arbol vigor` whose value may be absent
VERBS = ("backend", "vigor")
ACTIONS = {"learn": 0, "profiles": 0, "approve": 1}  # the words after `vigor` and the values each takes (SGM-1.11)
USAGE = (
    "Usage: arbol [--root <root>] backend [isolation options] | vigor [--refresh [<driver>/<subscription>]] [--text]"
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
    if len(words) > 1 and (words[0] != "vigor" or words[1] not in ACTIONS or len(words) != 2 + ACTIONS[words[1]]):
        raise Refused("invalid_input", USAGE)
    if len(words) > 1 and "--refresh" in options:
        raise Refused("invalid_input", "--refresh belongs to the read arbol vigor.")
    if words == ["backend"] and options.keys() & (FLAGS | OPTIONAL):
        raise Refused("invalid_input", "--refresh and --text belong to arbol vigor.")
    if "--root-dir" in options and not {"--bin-dir", "--database"} <= options.keys():
        raise Refused("invalid_input", "--root-dir requires --bin-dir and --database.")
    options["verb"] = words[0]
    if len(words) > 1:  # `vigor learn`, `vigor profiles` or `vigor approve <version>`
        options["action"] = words[1]
        if len(words) > 2:
            options["version"] = words[2]
    return options


@dataclass(frozen=True)
class Identity:
    root: str
    build: str
    folder: Path
    bin_dir: Path
    settings: Path
    database: str | None
    home: Path


def root_record(folder: Path, selected: str) -> dict[str, Any]:
    try:
        record = object_file(folder / "root.json")
        if (
            record.get("root") != selected
            or record.get("status") not in ("preparing", "working", "failed")
            or not isinstance(record.get("database"), str)
            or not record["database"]
            or not isinstance(record.get("name"), str)
            or not record["name"]
        ):
            raise ValueError("Invalid Root header.")
        return record
    except (OSError, ValueError, UnicodeError) as error:
        raise Refused("unknown_root", "The selected Root has no readable valid root.json.") from error


def identity(package: Path, options: dict[str, str], *, home: Path | None = None) -> Identity:
    home = home or Path.home()
    selected = options.get("--root")
    if selected is not None and not ROOT_ID.fullmatch(selected):
        raise Refused("invalid_input", "A Root identifier contains only lower-case letters and digits.")
    number = "0"
    try:
        if os.path.lexists(package / "build.json"):
            record = object_file(package / "build.json")
            version = object_file(package / "package.json").get("version")
            root = record.get("root")
            if (
                record.get("component") != "arbol"
                or record.get("entry") != "bin/arbol"
                or not isinstance(root, str)
                or not ROOT_ID.fullmatch(root)
                or not isinstance(record.get("build"), str)
                or not BUILD_ID.fullmatch(record["build"])
                or not isinstance(version, str)
                or record.get("packageVersion") != version
            ):
                raise ValueError("Invalid Build identity.")
            if selected is not None and selected != root:
                raise ValueError("Explicit Root differs from the Build.")
            selected, number = root, record["build"]
        elif selected is None:
            raise ValueError("--root is required outside a Build.")
    except (OSError, ValueError, UnicodeError) as error:
        raise Refused("invalid_input", "Cannot read a matching program/Root Build identity.") from error
    assert selected is not None

    def path(key: str, default: Path) -> Path:
        return Path(os.path.abspath(os.path.expanduser(options.get(key, str(default)))))

    folder = path("--root-dir", home / "Library/Application Support/Arbol/roots" / selected)
    root_record(folder, selected)
    if len(os.fsencode(folder / "backend.sock")) > 103:
        raise Refused("invalid_input", "The backend socket path exceeds 103 bytes.")
    return Identity(
        selected,
        number,
        folder,
        path("--bin-dir", home / ".local/bin"),
        path("--settings-dir", home / ".arbol/roots" / selected),
        options.get("--database"),
        home,
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
