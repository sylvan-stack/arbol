"""Apply only the explicit Root's qualified copied SQL (RTM-D25/D26)."""

import hashlib
import json
import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
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
        if (not isinstance(manifest, dict) or manifest.get("component") != "arbol-root"
                or manifest.get("root") != record["root"] or manifest.get("build") != build["build"]
                or not isinstance(manifest.get("layout"), dict)
                or type(manifest["layout"].get("rootContract")) is not int
                or manifest.get("layout") != {"root":record["root"], "rootContract":record["rootContract"],
                                              "grewFrom":record.get("grewFrom")}
                or not isinstance(manifest.get("files"), dict)):
            raise ValueError("The copied SQL manifest must match the Root, Build, contract and lineage.")
        names = ["chat-tables.sql", "root-tables.sql"]
        if migration and "grewFrom" in record:
            names.append("migrate.sql")
        files = {name:folder / "layout" / name for name in names}
        for name, path in files.items():
            if hashlib.sha256(regular(path)).hexdigest() != manifest["files"].get("layout/" + name):
                raise ValueError(f"Copied SQL does not match its qualified manifest: {path}")
        yield SqlBuild(build["build"], files)
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
