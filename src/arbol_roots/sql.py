"""Apply only the explicit Root's qualified copied SQL (RTM-D25/D26)."""

import hashlib
import json
import os
import shutil
import signal
import stat
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import FrameType
from typing import Any

from arbol_builds.launcher import default_record, open_use_guard, read_records

from .database import Database, DatabaseError
from .model import Places, Refused, catalogue, database_name, selected
from .operations import catalogue_lock


def regular(path: Path) -> bytes:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Expected a regular copied Build file: {path}")
    return path.read_bytes()


def connect_name(value: object) -> str:
    name = database_name(value)
    if "=" in name or name.startswith(("postgres://", "postgresql://")) or name == "-":
        raise Refused("invalid_input", "The database name must not have psql's connection-string or reuse form.")
    return name


def databases(paths: Places, record: dict[str, Any], *, migration: bool = True) -> tuple[str, str | None]:
    target = connect_name(record.get("database"))
    if any(other["root"] != record["root"] and other.get("database") == target for other in catalogue(paths)):
        raise Refused("invalid_input", "Another retained Root names the target database; SQL application is refused.")
    older = selected(paths, record["grewFrom"]) if migration and "grewFrom" in record else None
    source = connect_name(older.get("database")) if older else None
    if source == target:
        raise Refused("invalid_input", "The older and new Root must name different databases.")
    return target, source


@dataclass(frozen=True)
class SqlBuild:
    number: str
    files: dict[str, Path]
    modes: tuple[str, ...] = ()


@contextmanager
def selected_sql(paths: Places, record: dict[str, Any], *, migration: bool) -> Iterator[SqlBuild]:
    """The caller holds the catalogue lock; this guard prevents legitimate pruning."""
    registry = str(paths.registry)
    candidates = [build for build in read_records(registry, "arbol-root")
                  if build.get("root") == record["root"]
                  and (paths.registry / "arbol-root" / build["build"] / "layout").is_dir()
                  and not (paths.registry / "arbol-root" / build["build"] / "layout").is_symlink()]
    build = default_record(registry, candidates)
    if build is None:
        raise Refused("build_unavailable", f"Root {record['root']} has no runnable working arbol-root Build with SQL.")
    fd: int | None = None
    try:
        fd = open_use_guard(registry, "arbol-root", build["build"])
        # Pruning may have won the race between the initial selection and our shared guard.
        current = default_record(registry, [entry for entry in read_records(registry, "arbol-root")
                                           if entry["build"] == build["build"]
                                           and entry.get("root") == record["root"]])
        if current is None:
            raise ValueError("The selected Root Build is no longer working and available.")
        folder = paths.registry / "arbol-root" / build["build"]
        manifest = json.loads(regular(folder / "package-manifest.json"))
        expected: dict[str, Any] = {"root":record["root"], "rootContract":record["rootContract"],
                                   "grewFrom":record.get("grewFrom")}
        modes: tuple[str, ...] = ()
        if isinstance(manifest, dict) and isinstance(manifest.get("layout"), dict) and "migrationModes" in manifest["layout"]:
            capability = manifest["layout"]["migrationModes"]
            path = folder / "layout/migration-modes.json"
            data = regular(path)
            if not isinstance(manifest.get("files"), dict):
                raise ValueError("The copied Build must have a file hash map.")
            if (not isinstance(capability, dict) or type(capability.get("version")) is not int
                    or capability != {"version":1,"modes":["check","chat"]} or "grewFrom" not in record
                    or json.loads(data) != capability
                    or hashlib.sha256(data).hexdigest() != manifest.get("files",{}).get("layout/migration-modes.json")):
                raise ValueError("The advertised migration modes must match their verified copied descriptor and lineage.")
            # JSON booleans compare equal to integers in Python; check the copied type independently.
            if type(json.loads(data).get("version")) is not int:
                raise ValueError("The copied migration capability version must be integer 1.")
            expected["migrationModes"] = capability
            modes = ("check", "chat")
        if (not isinstance(manifest, dict) or manifest.get("component") != "arbol-root"
                or manifest.get("root") != record["root"] or manifest.get("build") != build["build"]
                or not isinstance(manifest.get("layout"), dict)
                or type(manifest["layout"].get("rootContract")) is not int
                or manifest["layout"] != expected or not isinstance(manifest.get("files"), dict)):
            raise ValueError("The copied SQL manifest must match the Root, Build, contract and lineage.")
        names = ["chat-tables.sql", "root-tables.sql"]
        if migration and "grewFrom" in record:
            names.append("migrate.sql")
        files = {name:folder / "layout" / name for name in names}
        for name, path in files.items():
            if hashlib.sha256(regular(path)).hexdigest() != manifest["files"].get("layout/" + name):
                raise ValueError(f"Copied SQL does not match its qualified manifest: {path}")
        yield SqlBuild(build["build"], files, modes)
    except BlockingIOError as error:
        raise Refused("busy", "The selected Root Build is being pruned; try again.") from error
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Refused("build_unavailable", f"Cannot use the selected Root Build's copied SQL: {error}") from error
    finally:
        if fd is not None:
            os.close(fd)


def database_client(paths: Places) -> Database:
    program = paths.psql
    if "/" in program and not os.path.isabs(program):
        program = str(paths.home / program)
    found = shutil.which(program)
    if found is None:
        raise DatabaseError("psql must be an available executable before applying Root SQL.")
    return Database(replace(paths, psql=os.path.abspath(found)))


def layout(paths: Places, root: str) -> dict[str, Any]:
    with catalogue_lock(paths):
        record = selected(paths, root)
        if record["status"] == "preparing":
            raise Refused("invalid_input", "A preparing Root needs migrate; layout applies to a Root in use.")
        target, _source = databases(paths, record, migration=False)
        with selected_sql(paths, record, migration=False) as build:
            database = database_client(paths)
            for file in build.files.values():
                database.file(target, file)
            return {"root":root, "rootBuild":build.number, "files":list(build.files)}


@contextmanager
def migration_directory() -> Iterator[Path]:
    """The CLI entry point's raw signal defaults must not bypass copy cleanup."""
    previous = {number:signal.getsignal(number) for number in [signal.SIGINT, signal.SIGTERM]}
    temporary: tempfile.TemporaryDirectory[str] | None = None

    def interrupted(number: int, _frame: FrameType | None) -> None:
        raise Refused("operation_failed", f"Migration interrupted by {signal.Signals(number).name}; "
                                         "the Root record was not changed.")

    try:
        for number in previous:
            signal.signal(number, interrupted)
        temporary = tempfile.TemporaryDirectory(prefix="arbol-root-migration-")
        folder = Path(temporary.name)
        if stat.S_IMODE(folder.stat().st_mode) != 0o700:
            raise Refused("operation_failed", "The migration's temporary directory must be private (0700).")
        yield folder
    finally:
        try:
            # A second catchable signal cannot interrupt removal of the private copies.
            for number in previous:
                signal.signal(number, signal.SIG_IGN)
            if temporary is not None:
                temporary.cleanup()
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)


def chat_uuid(value: str) -> str:
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError) as error:
        raise Refused("invalid_input", "The chat must be a canonical lower-case UUID.") from error
    return value


def mode_result(raw: str, mode: str, older: str, chat: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw)
        if not isinstance(value,dict) or value.get("mode") != mode or value.get("fromRoot") != older:
            raise ValueError("Wrong mode or source Root.")
        if mode == "check":
            if (set(value) != {"mode","fromRoot","checked","stale"} or type(value["checked"]) is not int
                    or value["checked"] < 0 or not isinstance(value["stale"],list)
                    or any(not isinstance(item,str) or chat_uuid(item) != item for item in value["stale"])
                    or len(set(value["stale"])) != len(value["stale"]) or len(value["stale"]) > value["checked"]):
                raise ValueError("Invalid comparison counts or chat identifiers.")
        else:
            if (set(value) != {"mode","fromRoot","chat","fromChat","resultChat","action","endedThrough","snapshotAt"}
                    or value["chat"] != chat or value["action"] not in ("replaced","copied")
                    or type(value["endedThrough"]) is not int or value["endedThrough"] < 0
                    or not isinstance(value["snapshotAt"],str)
                    or datetime.fromisoformat(value["snapshotAt"]).tzinfo is None):
                raise ValueError("Invalid single-chat result.")
            for key in ["chat","fromChat","resultChat"]:
                chat_uuid(value[key])
            if (value["action"] == "replaced") != (value["resultChat"] == chat):
                raise ValueError("The result chat does not match the migration action.")
        return value
    except (ValueError, TypeError, KeyError, Refused) as error:
        raise Refused("operation_failed", "The migration returned an invalid result; inspect the copy before trying again.") from error


def migrate(paths: Places, root: str, *, check: bool = False, chat: str | None = None) -> dict[str, Any]:
    if check and chat is not None:
        raise Refused("invalid_input", "--check and --chat are mutually exclusive.")
    if chat is not None:
        chat_uuid(chat)
    mode = "check" if check else "chat" if chat is not None else None
    with catalogue_lock(paths):
        record = selected(paths, root)
        if mode is not None and (record["status"] not in ("working","failed") or "grewFrom" not in record):
            raise Refused("invalid_input", "Comparison or one-chat migration needs a working/failed Root with lineage.")
        if mode is None and record["status"] != "preparing":
            raise Refused("invalid_input", "Only a preparing Root can be migrated; nothing was changed.")
        target, source = databases(paths, record)
        with selected_sql(paths, record, migration=True) as build:
            if mode is not None and mode not in build.modes:
                raise Refused("build_unavailable", "The selected Root Build does not advertise this migration mode.")
            database = database_client(paths)
            with migration_directory() as folder:
                if mode is not None:
                    assert source is not None
                    variables = {"from_database":source,"from_root":record["grewFrom"],
                                 "arbol_migrate_check" if check else "arbol_migrate_chat":"1" if check else str(chat)}
                    try:
                        raw = database.file(target,build.files["migrate.sql"],single=False,variables=variables,cwd=folder)
                    except DatabaseError as error:
                        if error.sqlstate == "P0002":
                            raise Refused("unknown_chat", f"Selected chat {chat} or its original is no longer available.") from error
                        if error.sqlstate in ("55P03","40P01"):
                            raise Refused("busy", "The selected chat or provenance is busy; nothing was replaced.") from error
                        raise
                    return {"root":root,"rootBuild":build.number,**mode_result(raw,mode,record["grewFrom"],chat)}
                database.drop(target)
                database.create(target)
                for name in ["chat-tables.sql", "root-tables.sql"]:
                    database.file(target, build.files[name])
                if source is not None:
                    database.file(target, build.files["migrate.sql"], single=False,
                                  variables={"from_database":source, "from_root":record["grewFrom"]}, cwd=folder)
            return {"root":root, "rootBuild":build.number, "files":list(build.files)}
