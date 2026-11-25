"""Preparation and recoverable directory renames for the ARC-5 installation move."""

from __future__ import annotations

import argparse
import base64
import ctypes
import fcntl
import json
import os
import plistlib
import pwd
import re
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import psycopg
from archive_volume import BACKUPS, Archive, ArchiveUnavailable, require_archive
from database_server import BIN, LABEL, LAUNCHCTL, ROLE, Places, postmaster_pid, run
from exchange_format_transition import stage as stage_exchange_authorization
from install_database_server import Installation, launch_agent, scram_verifier
from layout_archive import DIR, ENTRY, WORKING, ensure_unused, identity, opened, stamp
from migrate_schema import Refusal, database_target
from psycopg import sql
from recovery import (
    capture,
    check_isolated,
    cluster_identity,
    observations,
    restore,
    source_identity,
    validate_snapshot,
    verify_recovery,
)
from recovery_release import (
    COMMIT,
    DIGEST,
    MUTABLE_BUILD_FILES,
    RecoveryError,
    canonical,
    document,
    relative,
    sha,
    tree,
    verify_release,
)

# migrate_schema loads the installation path module from its own release.
from arbol_installation.admission import (
    TOKEN,
    AdmissionRefusal,
    ExclusiveLayoutLease,
    State,
    checked_source,
    directory,
    exclusive_layout_lease,
    read_state,
    unique_pairs,
    write_state,
)
from arbol_installation.exchange_release import RECEIPT as EXCHANGE_AUTHORIZATION
from arbol_installation.paths import (
    INSTALLATION_LAYOUT,
    build_payload_directory,
    build_registry,
    database_settings,
    installation_root,
)

REQUIRED = frozenset(("database", "runtime", "app", "builds", "drivers", "native-resources"))
BACKEND = "arbol"
SCHEMA_FIELDS = ("revision", "compatibilityVersion")
MAX_SETTINGS_BYTES = 65536
RENAME_RECORD = "layout-move-renames.json"
SERVICE_RECORD = "layout-move-services.json"
STOPPED_RECORD = "layout-move-stopped.json"
MOVE_INTENT = "layout-move-intent.json"
DRAIN_RECORD = "layout-move-drain.json"
SNAPSHOT_RECORD = "layout-move-snapshot.json"
RETARGET_RECORD = "layout-move-retarget.json"
STARTED_RECORD = "layout-move-started.json"
REOPEN_RECORD = "layout-move-reopen.json"
BOUNDARY_RECORD = "layout-move-boundary.json"
PRIOR_REOPEN_RECORD = "layout-move-prior-reopen.json"
RECOVERY_BOUNDARY = "layout-move-recovery.json"
FALLBACK_RECORD = "layout-move-fallback.json"
MAX_RETARGET_BYTES = 32 * 1024 * 1024
MAX_RENAME_RECORD_BYTES = 65536
RENAME_EXCL = 0x00000004  # Darwin sys/stdio.h
WRITER_INVENTORY_FORMAT = 3
SEALED_DRIVERS = frozenset(f"arbol-{name}-driver" for name in ("claude", "codex", "mimo", "pi"))


@dataclass(frozen=True)
class MovePaths:
    home: Path

    @property
    def old(self) -> Path:
        return self.home / "Library/Application Support/Arbol"

    @property
    def new(self) -> Path:
        return installation_root(self.home)

    @property
    def historical_registry(self) -> Path:
        return self.old / "builds"

    @property
    def bin(self) -> Path:
        return self.home / ".local/bin"


class PriorPlaces(Places):
    @property
    def folder(self) -> Path:
        return MovePaths(self.home).old / "database"


def owner_directory(path: Path, *, private: bool = False) -> os.stat_result:
    info = path.lstat()
    if (path.resolve(strict=True) != path or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or (private and stat.S_IMODE(info.st_mode) != 0o700)):
        raise RecoveryError(f"An installation directory does not have its expected ownership or mode: {path}.")
    return info


def resolve_registry(paths: MovePaths) -> Path:
    managed = build_registry(paths.home)
    historical = paths.historical_registry
    if os.path.lexists(managed):
        if os.path.lexists(historical):
            raise RecoveryError("Both managed and historical Build registries exist. Resolve the active registry first.")
        registry = managed
    else:
        registry = historical
    if owner_directory(registry).st_mode & 0o022:
        raise RecoveryError("The Build registry must be writable only by its owner.")
    return registry


def check_disk(data: Path) -> None:
    listing = subprocess.check_output(["/bin/df", "-Pk", str(data)], timeout=10).decode().splitlines()
    device = listing[1].split(None, 1)[0]
    disk = plistlib.loads(subprocess.check_output(["/usr/sbin/diskutil", "info", "-plist", device], timeout=10))
    if not device.startswith("/dev/disk") or disk.get("Internal") is not True or disk.get("RemovableMedia") is not False:
        raise RecoveryError("The PostgreSQL data directory must be on an internal, non-removable disk.")


def destination_name(name: str) -> str:
    return "postgres" if name == "database" else name


def working_paths(paths: MovePaths, registry: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    old = owner_directory(paths.old, private=True)
    new = owner_directory(paths.new, private=True)
    if old.st_dev != new.st_dev:
        raise RecoveryError("The old installation and the new folder are on different filesystem volumes.")
    working = {}
    absent = {}
    for name in sorted(WORKING):
        if name == "builds" and registry != paths.historical_registry:
            continue
        source = paths.old / name
        destination = paths.new / destination_name(name)
        if os.path.lexists(destination):
            raise RecoveryError(f"Cannot rename the working directory without overwriting: {name}.")
        if not os.path.lexists(source) and name not in REQUIRED:
            absent[name] = {"source": str(source), "destination": str(destination)}
            continue
        info = owner_directory(source)
        if info.st_dev != new.st_dev:
            raise RecoveryError(f"Cannot rename the working directory across a volume: {name}.")
        working[name] = {"source": str(source), "destination": str(destination), "identity": [info.st_dev, info.st_ino]}
    data = paths.old / "database/data"
    if owner_directory(data, private=True).st_dev != new.st_dev:
        raise RecoveryError("The PostgreSQL data directory crosses a volume boundary.")
    check_disk(data)
    return working, absent


@contextmanager
def rename_roots(paths: MovePaths) -> Iterator[tuple[int, int]]:
    with opened(paths.old, DIR) as old, opened(paths.new, DIR) as new:
        for path, descriptor in ((paths.old, old), (paths.new, new)):
            if not os.path.samestat(owner_directory(path, private=True), os.fstat(descriptor)):
                raise RecoveryError("A move parent directory changed while it was opened.")
        if os.fstat(old).st_dev != os.fstat(new).st_dev:
            raise RecoveryError("The move parent directories are on different filesystem volumes.")
        yield old, new


def rename_exclusive(source: int, name: str, destination: int, target: str) -> None:
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameatx_np
    except AttributeError:
        raise RecoveryError("This system does not support exclusive directory renames.") from None
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(source, os.fsencode(name), destination, os.fsencode(target), RENAME_EXCL):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), name, None, target)


def rename_identity(folder: int, name: str) -> list[int] | None:
    try:
        info = os.stat(name, dir_fd=folder, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RecoveryError(f"A move path is not an owner-controlled directory: {name}.")
    return list(identity(info))


def read_move_document(folder: int, name: str, *, limit: int = MAX_RENAME_RECORD_BYTES) -> dict[str, Any]:
    with opened(name, ENTRY, folder) as descriptor:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or info.st_size > limit):
            raise RecoveryError("The move record is not a private owner file of the expected size.")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            raw = stream.read(limit + 1)
        named = os.stat(name, dir_fd=folder, follow_symlinks=False)
        if len(raw) != info.st_size or stamp(info) != stamp(os.fstat(descriptor)) or stamp(info) != stamp(named):
            raise RecoveryError("The move record changed while it was read.")
    value = json.loads(raw, object_pairs_hook=unique_pairs)
    if not isinstance(value, dict) or canonical(value) != raw:
        raise RecoveryError("The move record is not a canonical JSON object.")
    return value


def write_move_document(folder: int, name: str, record: dict[str, Any]) -> None:
    temporary = f".{name}.{uuid4().hex}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical(record))
            stream.flush()
            os.fsync(stream.fileno())
        rename_exclusive(folder, temporary, folder, name)
        os.fsync(folder)
    finally:
        try:
            os.unlink(temporary, dir_fd=folder)
        except FileNotFoundError:
            pass


def optional_move_document(folder: int, name: str, *, limit: int = MAX_RENAME_RECORD_BYTES) -> dict[str, Any] | None:
    try:
        return read_move_document(folder, name, limit=limit)
    except FileNotFoundError:
        return None


def read_rename_record(folder: int) -> dict[str, Any]:
    value = read_move_document(folder, RENAME_RECORD)
    if value.get("format") in (2, WRITER_INVENTORY_FORMAT):
        rename_snapshot_pins(value)
    if value.get("format") == WRITER_INVENTORY_FORMAT:
        rename_inventory_proof(value)
    return value


def rename_inventory_proof(record: dict[str, Any]) -> dict[str, str]:
    proof = record.get("writerInventory")
    if (not isinstance(proof, dict) or proof.keys() != {"backend", "sourceCommit", "generation"}
            or any(not isinstance(value, str) for value in proof.values())
            or re.fullmatch(r"[1-9a-f][0-9a-f]*", proof["backend"]) is None
            or COMMIT.fullmatch(proof["sourceCommit"]) is None
            or TOKEN.fullmatch(proof["generation"]) is None):
        raise RecoveryError("The move rename record lacks a bound prior Backend writer inventory.")
    return proof


def rename_snapshot_pins(record: dict[str, Any]) -> dict[str, str]:
    pins = record.get("snapshotProof")
    paths = ("snapshotDirectory", "restoreReceipt")
    digests = ("snapshotSha256", "receiptSha256")
    if (not isinstance(pins, dict) or pins.keys() != set(paths + digests)
            or any(not isinstance(value, str) for value in pins.values())
            or any(not Path(pins[key]).is_relative_to(BACKUPS) or ".." in Path(pins[key]).parts for key in paths)
            or any(DIGEST.fullmatch(pins[key]) is None for key in digests)):
        raise RecoveryError("The move rename record does not pin the verified snapshot and restore receipt.")
    return pins


def verify_rename_snapshot(record: dict[str, Any], snapshot_directory: Path, restore_receipt: Path) -> dict[str, str]:
    schema = record.get("schema")
    if (not isinstance(schema, dict) or schema.keys() != set(SCHEMA_FIELDS)
            or any(type(value) is not int or value <= 0 for value in schema.values())):
        raise RecoveryError("The move rename record does not bind the verified starting schema.")
    snapshot_directory = snapshot_directory.absolute()
    restore_receipt = restore_receipt.absolute()
    proof = verify_recovery(
        snapshot_directory, restore_receipt, source=checked_source(record["database"]), schema=schema,
        release_sha256=record["priorRelease"], maintenance_session=record["session"],
    )
    return {
        "snapshotDirectory": str(snapshot_directory), "restoreReceipt": str(restore_receipt),
        "snapshotSha256": proof["snapshotSha256"], "receiptSha256": proof["receiptSha256"],
    }


def rename_positions(paths: MovePaths, roots: tuple[int, int], record: dict[str, Any]) -> dict[str, str]:
    old, new = roots
    parents = [list(identity(os.fstat(descriptor))) for descriptor in roots]
    if (type(record.get("format")) is not int or record["format"] not in (1, 2, WRITER_INVENTORY_FORMAT)
            or record.get("parents") != parents
            or not isinstance(record.get("session"), str) or TOKEN.fullmatch(record["session"]) is None
            or any(not isinstance(record.get(field), str) or DIGEST.fullmatch(record[field]) is None
                   for field in ("priorRelease", "stagedRelease"))):
        raise RecoveryError("The move rename record does not bind the expected roots, session and releases.")
    checked_source(record.get("database"))
    for path, descriptor in ((paths.old, old), (paths.new, new)):
        if not os.path.samestat(owner_directory(path, private=True), os.fstat(descriptor)):
            raise RecoveryError("A recorded move parent no longer names its held directory.")
    working, absent = record["working"], record["absentWorking"]
    registry = record.get("registry")
    expected = WORKING
    required = REQUIRED
    if registry == str(build_registry(paths.home)):
        expected = expected - {"builds"}
        required = required - {"builds"}
    elif registry != str(paths.historical_registry):
        raise RecoveryError("The move rename record has an unknown Build registry.")
    if (not isinstance(working, dict) or not isinstance(absent, dict)
            or working.keys() & absent.keys() or (working.keys() | absent.keys()) != expected
            or not required <= working.keys()):
        raise RecoveryError("The move rename record has an incomplete or conflicting directory inventory.")

    positions = {}
    seen = set()
    source_remaining = False
    for name in sorted(expected):
        target = destination_name(name)
        before = {"source": str(paths.old / name), "destination": str(paths.new / target)}
        at_source = rename_identity(old, name)
        at_destination = rename_identity(new, target)
        if name in absent:
            if absent[name] != before or at_source is not None or at_destination is not None:
                raise RecoveryError(f"An absent move path changed: {name}.")
            positions[name] = "absent"
            continue
        item = working[name]
        recorded = item.get("identity") if isinstance(item, dict) else None
        if (not isinstance(recorded, list) or len(recorded) != 2
                or any(type(part) is not int or part <= 0 for part in recorded)
                or recorded[0] != parents[0][0] or tuple(recorded) in seen
                or item != {**before, "identity": recorded}):
            raise RecoveryError(f"The move rename record has an invalid before-image: {name}.")
        seen.add(tuple(recorded))
        if at_source == recorded and at_destination is None:
            positions[name] = "source"
            source_remaining = True
        elif at_source is None and at_destination == recorded and not source_remaining:
            positions[name] = "destination"
        else:
            raise RecoveryError(f"Cannot determine the recorded directory's move position: {name}.")
    database_parent, database_name = (old, "database") if positions["database"] == "source" else (new, "postgres")
    with opened(database_name, DIR, database_parent) as database:
        with opened("data", DIR, database) as data:
            info = os.fstat(data)
            if (list(identity(info)) != record.get("dataIdentity")
                    or info.st_dev != parents[0][0] or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o700):
                raise RecoveryError("The PostgreSQL data directory no longer matches its move before-image.")
    return positions


def require_rename_fence(
    paths: MovePaths, record: dict[str, Any], positions: dict[str, str], lease: ExclusiveLayoutLease,
) -> State:
    runtime = (paths.new if positions["runtime"] == "destination" else paths.old) / "runtime"
    folder = lease.require(runtime)
    try:
        marker = read_state(folder, layout=1)
    except ValueError:
        marker = read_state(folder, layout=INSTALLATION_LAYOUT)
    if marker.phase != "exclusive" or marker.session != record["session"] or marker.source != record["database"]:
        raise RecoveryError("The held exclusive admission marker does not bind the move's database and session.")
    if "writerInventory" in record and marker.generation != rename_inventory_proof(record)["generation"]:
        raise RecoveryError("The held exclusive admission marker differs from the recorded writer inventory generation.")
    return marker


def record_renames(
    paths: MovePaths, prepared: dict[str, Any], session: str, lease: ExclusiveLayoutLease, *,
    prior_release_directory: Path, snapshot_directory: Path, restore_receipt: Path,
) -> None:
    """Persist the complete before-images before the caller requests a rename."""
    if prepared.get("status") != "release_pair_verified":
        raise RecoveryError("Directory renames require a verified release pair.")
    with rename_roots(paths) as roots:
        _, new = roots
        data = paths.old / "database/data"
        data_info = owner_directory(data, private=True)
        record = {key: prepared[key] for key in ("database", "schema", "priorRelease", "stagedRelease",
                                                 "registry", "working", "absentWorking")}
        record.update(format=WRITER_INVENTORY_FORMAT, session=session, parents=[list(identity(os.fstat(fd))) for fd in roots],
                      dataIdentity=list(identity(data_info)))
        positions = rename_positions(paths, roots, record)
        if "destination" in positions.values():
            raise RecoveryError("A working directory moved before its before-image was written.")
        marker = require_rename_fence(paths, record, positions, lease)
        record["snapshotProof"] = verify_rename_snapshot(record, snapshot_directory, restore_receipt)
        record["writerInventory"] = verify_prior_writer_inventories(paths, record, prior_release_directory, marker, lease)
        if rename_positions(paths, roots, record) != positions:
            raise RecoveryError("A recorded directory changed during snapshot and writer inventory verification.")
        if require_rename_fence(paths, record, positions, lease) != marker:
            raise RecoveryError("The exclusive marker changed during snapshot and writer inventory verification.")
        write_move_document(new, RENAME_RECORD, record)


def relocate_renames(paths: MovePaths, session: str, lease: ExclusiveLayoutLease, *, reverse: bool = False) -> None:
    """Advance or reverse the recorded renames under the same exclusive fence."""
    with rename_roots(paths) as roots:
        old, new = roots
        record = read_rename_record(new)
        if record["session"] != session:
            raise RecoveryError("A different session owns the move rename record.")
        positions = rename_positions(paths, roots, record)
        require_rename_fence(paths, record, positions, lease)
        if not reverse:
            if record["format"] != WRITER_INVENTORY_FORMAT:
                raise RecoveryError("Forward relocation requires a rename record with snapshot and writer inventory proof.")
            pins = rename_snapshot_pins(record)
            observed = verify_rename_snapshot(record, Path(pins["snapshotDirectory"]), Path(pins["restoreReceipt"]))
            if observed != pins or read_rename_record(new) != record or rename_positions(paths, roots, record) != positions:
                raise RecoveryError("The move record, its directory positions or its snapshot proof changed.")
            require_rename_fence(paths, record, positions, lease)
            require_stopped_installation(paths, new, record, positions)
        # A retry may observe a rename whose first directory sync failed.
        os.fsync(new)
        os.fsync(old)
        previous, desired = ("destination", "source") if reverse else ("source", "destination")
        for name in sorted(record["working"], reverse=reverse):
            if read_rename_record(new) != record:
                raise RecoveryError("The move rename record changed during relocation.")
            positions = rename_positions(paths, roots, record)
            require_rename_fence(paths, record, positions, lease)
            if positions[name] != previous:
                continue
            target = destination_name(name)
            if reverse:
                rename_exclusive(new, target, old, name)
            else:
                rename_exclusive(old, name, new, target)
            positions = rename_positions(paths, roots, record)
            if positions[name] != desired:
                raise RecoveryError(f"The completed rename did not preserve its recorded identity: {name}.")
            require_rename_fence(paths, record, positions, lease)
            os.fsync(new)
            os.fsync(old)


def inspect_renames(paths: MovePaths) -> dict[str, Any]:
    with rename_roots(paths) as roots:
        record = read_rename_record(roots[1])
        positions = rename_positions(paths, roots, record)
    return {"status": "rename_positions", "session": record["session"], "positions": positions}


def read_settings(file: Path) -> tuple[bytes, tuple[int, ...]]:
    with opened(file, ENTRY) as fd:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                or info.st_nlink != 1 or info.st_size > MAX_SETTINGS_BYTES):
            raise RecoveryError("The database settings must be a private owner file of the expected size.")
        before = stamp(info)
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(MAX_SETTINGS_BYTES + 1)
        if len(raw) != info.st_size or stamp(os.fstat(fd)) != before or stamp(file.lstat()) != before:
            raise RecoveryError("The database settings changed while they were read.")
    return raw, before


def installation_database(paths: MovePaths) -> tuple[dict[str, Any], dict[str, str | int], tuple[int, ...]]:
    raw, version = read_settings(database_settings(paths.home))
    settings = json.loads(raw.decode("utf-8"))
    if not isinstance(settings, dict):
        raise RecoveryError("The database settings must be a JSON object.")
    name = settings.get("database")
    if not isinstance(name, str):
        raise RecoveryError("The configured database name is unavailable.")
    target = database_target(name, home=paths.home, settings=raw)
    with target.connect() as connection:
        with connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            binding = target.identity(connection)
    return settings, binding, version


def tool_json(arguments: list[str], home: Path, *, timeout: int = 30, pass_fds: tuple[int, ...] = ()) -> dict[str, Any]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("PG", "ARBOL_"))}
    env["HOME"] = str(home)
    result = subprocess.run(arguments, env=env, timeout=timeout, capture_output=True, check=False, pass_fds=pass_fds)
    try:
        value = json.loads(result.stdout)
    except ValueError as error:
        raise RecoveryError("A selected Build did not return its expected JSON.") from error
    if not isinstance(value, dict) or result.returncode:
        raise RecoveryError("A selected Build could not verify its effective configuration.")
    return value


def read_schema(
    package: Path, paths: MovePaths, binding: dict[str, str | int], settings_version: tuple[int, ...],
) -> dict[str, int]:
    reader = package / "database/migrate_schema.py"
    # Use the release's own catalog and bind its ledger result to the database
    # identity obtained in the same read-only transaction.
    bootstrap = """
import json
import sys
from pathlib import Path

reader = Path(sys.argv[1])
root = reader.parents[1]
sys.path[:0] = [str(reader.parent), str(root / "runtime/site-packages"), str(root / "src")]
from migrate_schema import database_target, load_manifest, read_prefix

manifest = load_manifest(reader.with_name("migrations.toml"))
target = database_target(sys.argv[2])
with target.connect() as connection, connection.transaction():
    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    identity = target.identity(connection)
    rows = read_prefix(connection, manifest)
if rows:
    print(json.dumps({"status": "ready", "database": identity,
                      "revision": rows[-1][0], "compatibilityVersion": rows[-1][3]}))
else:
    print(json.dumps({"status": "uninitialized"}))
"""
    runtime = package / "runtime/python/bin/python3.14"
    settings = database_settings(paths.home)
    if stamp(settings.lstat()) != settings_version:
        raise RecoveryError("The database settings changed before the packaged schema read.")
    result = tool_json([str(runtime), "-I", "-B", "-c", bootstrap, str(reader), str(binding["database"])], paths.home)
    if stamp(settings.lstat()) != settings_version or result.get("database") != binding:
        raise RecoveryError("A recorded Backend read a different database or the database settings changed.")
    if result.get("status") != "ready" or any(type(result.get(key)) is not int for key in SCHEMA_FIELDS):
        raise RecoveryError("A recorded Backend could not read the current schema by its own catalog.")
    return {key: result[key] for key in SCHEMA_FIELDS}


def selected_build(paths: MovePaths, registry: Path, component: str) -> dict[str, Any]:
    return tool_json([str(paths.bin / "arbol-builds"), "show", component, "--registry-dir", str(registry)], paths.home)


def verify_payload(paths: MovePaths, registry: Path, item: dict[str, Any], layout: int) -> tuple[Path, dict[str, Any]]:
    if item["installationLayout"] != layout:
        raise RecoveryError(f"The release lists a Build from the wrong layout: {item['component']}.")
    component = str(relative(item["component"]))
    build = str(relative(item["build"]))
    record_file = registry / component / build / "build.json"
    if not os.path.lexists(record_file):
        raise RecoveryError(f"The layout-{layout} release Build is not staged in the registry: {item['component']}.")
    owner_directory(record_file.parent)
    info = record_file.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise RecoveryError(f"The Build registry record is not an owner-controlled file: {component}.")
    record = document(record_file)
    if (record.get("installationLayout", 1) != layout or record.get("status") != "working"
            or record.get("prunedAt") is not None
            or record.get("source", {}).get("commit") != item["sourceCommit"]
            or any(record.get(key) != item[key] for key in ("component", "build", "entry", "packageVersion"))):
        raise RecoveryError(f"Registry identity differs from the layout-{layout} release record: {item['component']}.")
    package = build_payload_directory(registry, component, build, home=paths.home)
    owner_directory(package)
    evidence = item["evidence"]
    if component == "arbol-app":
        app = package / relative(item["entry"]).parts[0]
        owner_directory(app)
        result = subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(app)],
                                timeout=45, capture_output=True)
        if result.returncode or sha(canonical(tree(app))) != evidence["signedApp"]["filesSha256"]:
            raise RecoveryError("The signed App differs from the release record.")
    elif sha(canonical(tree(package, exclude=frozenset(MUTABLE_BUILD_FILES)))) != evidence.get("installedFilesSha256"):
        raise RecoveryError(f"The installed payload differs from the release record: {item['component']}.")
    return package, record


def prior_backend(
    paths: MovePaths, prepared: dict[str, Any], prior_release_directory: Path,
) -> tuple[Path, dict[str, Any]]:
    archive = require_archive()
    release, _ = verify_release(prior_release_directory, prepared["priorRelease"], archive=archive)
    backends = [item for item in release["builds"] if item["component"] == BACKEND]
    if release.get("kind") != "current" or len(backends) != 1:
        raise RecoveryError("The prior release does not identify one installed Backend.")
    backend = backends[0]
    registry = resolve_registry(paths)
    if str(registry) != prepared["registry"]:
        raise RecoveryError("The active Build registry differs from the verified prior release preparation.")
    package, _ = verify_payload(paths, registry, backend, 1)
    return package, backend


def run_prior_backend(
    paths: MovePaths, package: Path, build: str, request: dict[str, Any], operation: str, *,
    timeout: int = 30, pass_fds: tuple[int, ...] = (),
) -> dict[str, Any]:
    values = {**request, "runtime": str(paths.old / "runtime"), "home": str(paths.home), "build": build}
    bootstrap = """
import asyncio
import json
import os
import sys
from pathlib import Path

package = Path(sys.argv[1])
request = json.loads(sys.argv[2])
sys.path[:0] = [str(package / "src"), str(package / "runtime/site-packages")]
from arbol_backend.exchange_context import context
from arbol_backend.exchange_drain import inspect_database
from arbol_installation.admission import directory, read_state

ctx = context(package, {})
if (str(ctx.identity.folder) != request["runtime"] or str(ctx.identity.home) != request["home"]
        or ctx.identity.build != request["build"] or ctx.identity.fixture):
    raise ValueError("The prior Backend opened a different installation context.")
"""
    python = package / "runtime/python/bin/python3.14"
    arguments = [str(python), "-I", "-B", "-c", bootstrap + operation, str(package), canonical(values).decode()]
    return tool_json(arguments, paths.home, timeout=timeout, pass_fds=pass_fds)


def move_provider_module(name: str) -> Any:
    """Load the operator's own packaged Build provider, outside the old state."""
    source = Path(__file__).resolve().parents[1] / "driver-payload/src"
    sys.path.insert(0, str(source))
    try:
        module = import_module("arbol_builds." + name)
    finally:
        sys.path.pop(0)
    if module.__file__ is None or not Path(module.__file__).resolve().is_relative_to(source):
        raise RecoveryError("The move operator requires its own packaged Build provider.")
    return module


def observed_process(observer: Any, pid: int) -> dict[str, Any] | None:
    before = observer.inspect(pid)
    if before is None:
        return None
    thread = observer.library().proc_pidpath
    thread.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
    thread.restype = ctypes.c_int
    image = ctypes.create_string_buffer(4096)
    length = thread(pid, image, len(image))
    current = observer.inspect(pid)
    if current is None or current.owner != before.owner:
        return None
    if not 0 < length < len(image) or not image.value.startswith(b"/"):
        raise RecoveryError("Cannot identify the executable of an installation process.")
    return {**before.owner, "executable": str(Path(os.fsdecode(image.value)).resolve(strict=True))}


def app_executables(paths: MovePaths, release: dict[str, Any], registry: Path) -> set[str]:
    apps = [item for item in release["builds"] if item["component"] == "arbol-app"]
    if len(apps) != 1:
        raise RecoveryError("The prior release does not identify one signed App.")
    item = apps[0]
    package, _ = verify_payload(paths, registry, item, 1)
    recorded = package / relative(item["entry"]).parts[0]
    installed = paths.home / "Applications/Arbol App/Arbol App.app"
    bundles = [recorded]
    if os.path.lexists(installed) and installed != recorded:
        owner_directory(installed)
        result = subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(installed)],
                                timeout=45, capture_output=True)
        if result.returncode or sha(canonical(tree(installed))) != item["evidence"]["signedApp"]["filesSha256"]:
            raise RecoveryError("The installed App differs from the prior signed release.")
        bundles.append(installed)
    executables = set()
    for bundle in bundles:
        with (bundle / "Contents/Info.plist").open("rb") as stream:
            metadata = plistlib.load(stream)
        executable = metadata["CFBundleExecutable"]
        if not isinstance(executable, str) or len(relative(executable).parts) != 1:
            raise RecoveryError("The prior App has an invalid executable name.")
        image = (bundle / "Contents/MacOS" / executable).resolve(strict=True)
        if not image.is_relative_to(bundle):
            raise RecoveryError("The signed App executable leaves its bundle.")
        executables.add(str(image))
    return executables


def running_apps(observer: Any, images: set[str]) -> list[dict[str, Any]]:
    scan = subprocess.run(["/usr/sbin/lsof", "-nP", "-F0pfn", "-d", "txt", "-a", "-u", str(os.getuid())],
                          check=False, capture_output=True, timeout=45)
    if scan.returncode not in (0, 1) or scan.stderr:
        raise RecoveryError("Cannot verify the owner process executable inventory.")
    pid = None
    matches = {}
    for field in scan.stdout.split(b"\0"):
        field = field.lstrip(b"\n")
        if field.startswith(b"p"):
            pid = int(field[1:])
        elif pid is not None and field.startswith(b"n/") and os.fsdecode(field[1:]) in images:
            process = observed_process(observer, pid)
            if process is not None and process["executable"] in images:
                matches[pid] = process
    return [matches[number] for number in sorted(matches)]


def running_backend(paths: MovePaths, observer: Any, image: Path) -> dict[str, Any] | None:
    try:
        with opened(paths.old / "runtime/backend.lock", ENTRY) as descriptor:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
                raise RecoveryError("The prior Backend lifetime lock is unsafe.")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                owner = json.loads(os.read(descriptor, 4097))
            else:
                return None
    except FileNotFoundError:
        return None
    if not isinstance(owner, dict) or type(owner.get("pid")) is not int or owner["pid"] <= 0:
        raise RecoveryError("The prior Backend lifetime lock has an invalid process identity.")
    process = observed_process(observer, owner["pid"])
    if process is None or process["executable"] != str(image):
        raise RecoveryError("The prior Backend lifetime lock names a different executable.")
    return process


def database_service(paths: MovePaths) -> dict[str, str] | None:
    domain = f"gui/{os.getuid()}"
    service = run([LAUNCHCTL, "print", f"{domain}/{LABEL}"], paths.home, timeout=15)
    if service.returncode:
        listing = run([LAUNCHCTL, "print", domain], paths.home, timeout=15)
        if (listing.returncode or "Could not find service" not in service.stderr or LABEL not in service.stderr):
            raise RecoveryError("Cannot establish the Arbol database launch agent's status.")
        return None
    return dict(line[1:].split(" = ", 1) for line in service.stdout.splitlines()
                if line.startswith("\t") and not line.startswith("\t\t") and " = " in line)


def stop_recorded_process(observer: Any, expected: dict[str, Any], number: int | None) -> None:
    pid = expected["pid"]
    if observed_process(observer, pid) != expected:
        return
    if number is not None:
        try:
            os.kill(pid, number)
        except ProcessLookupError:
            return
    deadline = time.monotonic() + 45
    while observed_process(observer, pid) == expected:
        if time.monotonic() >= deadline:
            raise RecoveryError("A recorded installation process did not stop.")
        time.sleep(0.25)


def stop_installation_services(
    paths: MovePaths, session: str, lease: ExclusiveLayoutLease, prior_release_directory: Path,
) -> dict[str, Any]:
    """Save exact before-images and stop only the bound App, Backend and launch agent."""
    if any(Path(name).resolve().is_relative_to(paths.old) for name in (__file__, sys.executable)):
        raise RecoveryError("Run the move operator from a verified package outside the old installation.")
    archive = require_archive()
    observer = move_provider_module("driver_process")
    with rename_roots(paths) as roots:
        _, new = roots
        record = read_rename_record(new)
        positions = rename_positions(paths, roots, record)
        if (record["session"] != session or record["format"] != WRITER_INVENTORY_FORMAT
                or "destination" in positions.values()):
            raise RecoveryError("Service shutdown requires the verified, unmoved exclusive session.")
        marker = require_rename_fence(paths, record, positions, lease)
        pins = rename_snapshot_pins(record)
        if verify_rename_snapshot(record, Path(pins["snapshotDirectory"]), Path(pins["restoreReceipt"])) != pins:
            raise RecoveryError("The move snapshot or restore receipt changed before shutdown.")
        release, _ = verify_release(prior_release_directory, record["priorRelease"], archive=archive)
        registry = resolve_registry(paths)
        if str(registry) != record["registry"]:
            raise RecoveryError("The prior Build registry changed before shutdown.")
        app_images = app_executables(paths, release, registry)
        package, _ = prior_backend(paths, record, prior_release_directory)
        backend_image = (package / "runtime/python/bin/python3.14").resolve(strict=True)
        places = Places(paths.home)
        data = paths.old / "database/data"
        with opened(places.plist, ENTRY) as fd, os.fdopen(os.dup(fd), "rb") as plist_file:
            prior_plist = plist_file.read(65537)
        if (len(prior_plist) > 65536 or plistlib.loads(prior_plist).get("ProgramArguments")
                != [str(BIN / "postgres"), "-D", str(data)]):
            raise RecoveryError("The prior launch agent does not name the exact database data directory.")
        service = database_service(paths)
        try:
            before = read_move_document(new, SERVICE_RECORD)
        except FileNotFoundError:
            pg_pid = postmaster_pid(data)
            pg = observed_process(observer, pg_pid) if pg_pid is not None else None
            if (service is None or service.get("state") != "running" or service.get("path") != str(places.plist)
                    or service.get("pid") != str(pg_pid) or pg is None
                    or pg["executable"] != str((BIN / "postgres").resolve(strict=True))):
                raise RecoveryError("The prior launch agent and postmaster identities do not agree.") from None
            before = {"format": 1, "session": session, "generation": marker.generation, "postgres": pg,
                      "plistSha256": sha(prior_plist), "apps": running_apps(observer, app_images),
                      "appImages": sorted(app_images), "backendImage": str(backend_image),
                      "backend": running_backend(paths, observer, backend_image)}
            write_move_document(new, SERVICE_RECORD, before)
        if (before.get("format") != 1 or before.get("session") != session
                or before.get("generation") != marker.generation or before.get("plistSha256") != sha(prior_plist)
                or before.get("appImages") != sorted(app_images) or before.get("backendImage") != str(backend_image)
                or require_rename_fence(paths, record, positions, lease) != marker):
            raise RecoveryError("The saved service inventory does not bind this exclusive session.")
        os.fsync(new)
        for app in before["apps"]:
            if app["executable"] not in app_images:
                raise RecoveryError("The recorded App is outside the verified prior release.")
            stop_recorded_process(observer, app, signal.SIGTERM)
        backend = before["backend"]
        if backend is not None:
            live = running_backend(paths, observer, backend_image)
            if live is not None and live != backend:
                raise RecoveryError("The Backend lifetime lock changed before shutdown.")
            if live is not None:
                stop_recorded_process(observer, backend, signal.SIGTERM)
        pg = before["postgres"]
        if service is not None:
            if (service.get("path") != str(places.plist) or service.get("pid") != str(pg["pid"])
                    or postmaster_pid(data) != pg["pid"] or observed_process(observer, pg["pid"]) != pg):
                raise RecoveryError("The database launch agent changed before shutdown.")
            result = run([LAUNCHCTL, "bootout", f"gui/{os.getuid()}/{LABEL}"], paths.home, timeout=90)
            if result.returncode:
                raise RecoveryError("launchd did not unload the exact database service.")
        stop_recorded_process(observer, pg, None)
        if (database_service(paths) is not None or postmaster_pid(data) is not None
                or running_apps(observer, app_images) or running_backend(paths, observer, backend_image) is not None):
            raise RecoveryError("An installation service is still running after shutdown.")
        ensure_unused({"prior installation": paths.old})
        require_rename_fence(paths, record, positions, lease)
        stopped = {"format": 1, "session": session, "servicesSha256": sha(canonical(before))}
        try:
            previous = read_move_document(new, STOPPED_RECORD)
        except FileNotFoundError:
            write_move_document(new, STOPPED_RECORD, stopped)
        else:
            if previous != stopped:
                raise RecoveryError("The recorded shutdown differs from the verified service inventory.")
        return before


def require_stopped_installation(
    paths: MovePaths, folder: int, record: dict[str, Any], positions: dict[str, str],
) -> None:
    before = read_move_document(folder, SERVICE_RECORD)
    stopped = read_move_document(folder, STOPPED_RECORD)
    if (before.get("session") != record["session"]
            or before.get("generation") != rename_inventory_proof(record)["generation"]
            or stopped != {"format": 1, "session": record["session"], "servicesSha256": sha(canonical(before))}):
        raise RecoveryError("The move does not have a verified shutdown of its recorded services.")
    data = paths.old / "database/data" if positions["database"] == "source" else paths.new / "postgres/data"
    if database_service(paths) is not None or postmaster_pid(data) is not None:
        raise RecoveryError("The database is still running before relocation.")
    observer = move_provider_module("driver_process")
    if (running_apps(observer, set(before["appImages"])) or
            (positions["runtime"] == "source" and running_backend(paths, observer, Path(before["backendImage"])) is not None)):
        raise RecoveryError("The App or Backend restarted after the recorded shutdown.")
    ensure_unused({"prior installation": paths.old})


def verify_prior_writer_inventories(
    paths: MovePaths, rename_record: dict[str, Any], prior_release_directory: Path,
    marker: State, lease: ExclusiveLayoutLease,
) -> dict[str, str]:
    package, backend = prior_backend(paths, rename_record, prior_release_directory)
    folder = lease.require(paths.old / "runtime")
    if read_state(folder, layout=1) != marker:
        raise RecoveryError("Writer inventory verification requires the unchanged layout-1 exclusive marker.")
    request = {
        "admissionDirectory": list(identity(os.fstat(folder))),
        "source": marker.source, "session": marker.session, "generation": marker.generation,
    }
    # The historical readers leave the parent's locks held. The SQL reader
    # uses the same separate PostgreSQL writer latch as ordinary freeze.
    operation = """
from arbol_backend.exchange_listing import drained_inventory

with directory(ctx.identity.folder) as folder:
    info = os.fstat(folder)
    marker = read_state(folder)
    if ([info.st_dev, info.st_ino] != request["admissionDirectory"] or marker.phase != "exclusive"
            or marker.source != request["source"] or marker.session != request["session"]
            or marker.generation != request["generation"]):
        raise ValueError("The prior Backend did not read the held admission marker.")
    drained_inventory(ctx)
    schema = asyncio.run(inspect_database(ctx, marker.source, idle=True))
    if read_state(folder) != marker:
        raise ValueError("The prior admission marker changed during writer inventory verification.")
print(json.dumps({"backend": ctx.identity.build, "generation": marker.generation, "schema": schema}))
"""
    result = run_prior_backend(paths, package, backend["build"], request, operation)
    if result != {"backend": backend["build"], "generation": marker.generation, "schema": rename_record["schema"]}:
        raise RecoveryError("The prior Backend did not prove the expected writer inventories and schema.")
    return {"backend": backend["build"], "sourceCommit": backend["sourceCommit"], "generation": marker.generation}


def prior_maintenance_transition(
    paths: MovePaths, prepared: dict[str, Any], prior_release_directory: Path, *,
    action: Literal["drain", "freeze"], attributed_session: str | None = None,
    attribution: tuple[int, str] | None = None,
) -> dict[str, Any]:
    """Invoke a prior fence transition after preflight, using a journaled session on resume."""
    if (prepared.get("status") != "release_pair_verified" or action not in ("drain", "freeze")
            or (attributed_session is None and (action != "drain" or attribution is None))
            or (attributed_session is not None
                and (not isinstance(attributed_session, str) or TOKEN.fullmatch(attributed_session) is None))):
        raise RecoveryError("The prior maintenance transition lacks verified preparation or its exact session.")
    package, backend = prior_backend(paths, prepared, prior_release_directory)
    request = {
        "action": action, "attributedSession": attributed_session,
        "source": checked_source(prepared["database"]), "schema": prepared["schema"],
        "runtimeIdentity": prepared["working"]["runtime"]["identity"],
        "attribution": attribution,
    }
    operation = r"""
from arbol_backend.exchange_drain import begin_maintenance, freeze
from arbol_installation.admission import STATE, TOKEN
from uuid import uuid4

runtime = ctx.identity.folder
runtime_info = runtime.lstat()
if [runtime_info.st_dev, runtime_info.st_ino] != request["runtimeIdentity"]:
    raise ValueError("The prior runtime no longer matches its preparation.")
with directory(runtime) as folder:
    directory_info = os.fstat(folder)
    before = read_state(folder)
    source = request["source"]
    attributed = request["attributedSession"]
    fresh = attributed is None
    if (before.source != source or (fresh and before.phase != "normal")
            or (not fresh and (before.phase not in ("draining", "exclusive") or before.session != attributed))):
        raise ValueError("The prior marker does not belong to the requested move transition.")
    schema = asyncio.run(inspect_database(ctx, source, idle=False))
    if schema != request["schema"] or read_state(folder) != before:
        raise ValueError("The prior schema or maintenance marker changed.")

    marker_writes_observed = []

    def verify_marker_write(event, args):
        if event != "os.rename" or args[1] != STATE:
            return
        target = args[3]
        if target < 0 or not os.path.samestat(os.fstat(target), directory_info) or read_state(target) != before:
            raise ValueError("The prior maintenance marker or its directory changed under admission.")
        if fresh:
            journal, intent = request["attribution"]
            with os.fdopen(os.open(args[0], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=args[2]), "rb") as stream:
                next_state = json.load(stream)
            session = next_state.get("session")
            if (not isinstance(session, str) or TOKEN.fullmatch(session) is None
                    or next_state.get("state") != "draining" or next_state.get("generation") != before.generation
                    or next_state.get("source") != source or next_state.get("release") != before.release):
                raise ValueError("The prior Backend did not stage the expected draining marker.")
            receipt = {"format": 1, "intentSha256": intent, "session": session, "generation": before.generation}
            name = "layout-move-drain.json"
            try:
                opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=journal)
            except FileNotFoundError:
                pass
            else:
                with os.fdopen(opened, "rb") as stream:
                    previous = json.loads(stream.read(16385))
                if previous.get("intentSha256") != intent or previous.get("generation") != before.generation:
                    raise ValueError("An earlier move already owns the drain attribution.")
            temporary = f".{name}.{uuid4().hex}"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=journal)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(receipt, stream, sort_keys=True, separators=(",", ":"))
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, name, src_dir_fd=journal, dst_dir_fd=journal)
                os.fsync(journal)
            finally:
                try:
                    os.unlink(temporary, dir_fd=journal)
                except FileNotFoundError:
                    pass
        marker_writes_observed.append(True)

    # os.replace emits os.rename before the write, while the historical
    # transition holds its admission locks. Require our own write on drain.
    sys.addaudithook(verify_marker_write)
    if request["action"] == "drain":
        session = begin_maintenance(source, runtime=runtime)
        phase = "draining" if fresh else before.phase
        changes_phase = fresh
    else:
        session = freeze(ctx, source, attributed)
        phase = "exclusive"
        changes_phase = before.phase == "draining"
    after = read_state(folder)
    current_runtime = runtime.lstat()
    with directory(runtime) as named:
        if (not os.path.samestat(directory_info, os.fstat(named))
                or not os.path.samestat(runtime_info, current_runtime)):
            raise ValueError("The prior runtime changed during the maintenance transition.")
    if (len(marker_writes_observed) != int(changes_phase) or after.phase != phase
            or after.session != session or after.source != before.source or after.release != before.release
            or getattr(after, "exchange_authorization", None) != getattr(before, "exchange_authorization", None)
            or (not fresh and session != attributed)
            or (not changes_phase and after != before)
            or (changes_phase and (after.generation == before.generation) != (phase == "draining"))):
        raise ValueError("The prior Backend did not make the expected maintenance transition.")
print(json.dumps({"status": after.phase, "session": session, "generation": after.generation,
                  "database": after.source, "schema": schema}))
"""
    descriptors = () if attribution is None else (attribution[0],)
    return run_prior_backend(paths, package, backend["build"], request, operation, timeout=60, pass_fds=descriptors)


def check_release(
    paths: MovePaths, registry: Path, archive: Archive,
    proof: tuple[Path, str], layout: int, settings: dict[str, Any],
) -> dict[str, tuple[Path, dict[str, Any]]]:
    directory, expected = proof
    release, _ = verify_release(directory, expected, archive=archive)
    if (release.get("kind") != "current"
            or document(directory / "configuration/installation") != settings):
        raise RecoveryError("A recorded release does not bind the configured database.")
    components = set()
    result = {}
    for item in release["builds"]:
        component = item["component"]
        payload, record = verify_payload(paths, registry, item, layout)
        if component in components:
            raise RecoveryError(f"Choose one exact default Build of {component} for the move.")
        if layout == 1 and selected_build(paths, registry, component).get("build") != record["build"]:
            raise RecoveryError(f"The live default differs from the layout-1 release: {component}.")
        components.add(component)
        result[component] = (payload, record)
    if not {BACKEND, "arbol-app", "arbol-trunk/trivial"} <= components:
        raise RecoveryError("Both release records must include Arbol, the App and Trivial.")
    return result


def has_schema(record: dict[str, Any], schema: dict[str, int]) -> bool:
    return any(item["compatibilityVersion"] == schema["compatibilityVersion"] and
               item["minRevision"] <= schema["revision"]
               for item in record.get("schemaCompatibility", ()))


def inspect(paths: MovePaths) -> dict[str, Any]:
    archive = require_archive()
    registry = resolve_registry(paths)
    working, absent = working_paths(paths, registry)
    _, binding, settings_version = installation_database(paths)
    selected = selected_build(paths, registry, BACKEND)
    build = str(relative(selected["build"]))
    backend = build_payload_directory(registry, BACKEND, build, home=paths.home)
    owner_directory(backend)
    schema = read_schema(backend, paths, binding, settings_version)
    return {"status": "inspected", "mercuryDevice": archive.device, "working": working, "absentWorking": absent,
            "registry": str(registry), "backend": build, "schema": schema, "database": binding}


def verify_release_pair(
    paths: MovePaths, prior: tuple[Path, str], staged: tuple[Path, str],
) -> dict[str, Any]:
    archive = require_archive()
    registry = resolve_registry(paths)
    working, absent = working_paths(paths, registry)
    settings, binding, settings_version = installation_database(paths)
    baseline = check_release(paths, registry, archive, prior, 1, settings)
    candidate = check_release(paths, registry, archive, staged, 2, settings)
    missing = baseline.keys() - candidate.keys()
    if missing:
        raise RecoveryError(f"The staged layout-2 release omits installed defaults: {', '.join(sorted(missing))}.")
    packages = (baseline[BACKEND], candidate[BACKEND])
    schema = read_schema(packages[0][0], paths, binding, settings_version)
    if (read_schema(packages[1][0], paths, binding, settings_version) != schema
            or any(not has_schema(record, schema) for _, record in packages)):
        raise RecoveryError("The installed and staged Backends do not admit the same schema. Qualify the upgrade separately.")
    return {"status": "release_pair_verified", "working": working, "absentWorking": absent, "registry": str(registry),
            "schema": schema, "database": binding, "priorRelease": prior[1], "stagedRelease": staged[1]}


def pinned_move_input(archive: Archive, path: Path, checksum: str, *, limit: int = 2**20) -> bytes:
    if not isinstance(checksum, str) or DIGEST.fullmatch(checksum) is None:
        raise RecoveryError("A prepared move input lacks its exact SHA-256.")
    path = archive.backup_path(path)
    with opened(path, ENTRY) as fd, os.fdopen(os.dup(fd), "rb") as stream:
        info = os.fstat(fd)
        raw = stream.read(limit + 1)
        if (not stat.S_ISREG(info.st_mode) or len(raw) != info.st_size or len(raw) > limit
                or stamp(info) != stamp(os.fstat(fd)) or stamp(info) != stamp(path.lstat()) or sha(raw) != checksum):
            raise RecoveryError("A prepared move input is missing, changed or differs from its approved digest.")
    return raw


def move_object(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw, object_pairs_hook=unique_pairs)
    if not isinstance(value, dict) or canonical(value) != raw:
        raise RecoveryError("A prepared move input must be one canonical JSON object.")
    return value


def stage_input(archive: Archive, release: Path, record: dict[str, Any], pin: Any) -> bytes:
    if (not isinstance(pin, dict) or pin.keys() != {"name", "sha256"}
            or not isinstance(pin["name"], str) or len(relative(pin["name"]).parts) != 1
            or pin["name"] not in record.get("inputs", ())):
        raise RecoveryError("A move input is missing from the verified staged release attachments.")
    return pinned_move_input(archive, release / "inputs" / pin["name"], pin["sha256"])


def move_route(paths: MovePaths, value: Any) -> Path:
    if not isinstance(value, str):
        raise RecoveryError("The handoff does not name a safe launcher route.")
    path = Path(value)
    if (str(path) != value or path.parent not in (paths.bin, paths.home / "Applications/Arbol/bin")
            or re.fullmatch(r"arbol(?:-[a-z0-9]+)*", path.name) is None):
        raise RecoveryError("The handoff does not name a supported installation launcher route.")
    return path


def verify_staged_move(
    paths: MovePaths, prior: tuple[Path, str], staged: tuple[Path, str], handoff: tuple[Path, str],
    *, recorded: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify the approved AFL-16 input bundle before granting maintenance entry."""
    archive = require_archive()
    manifest = move_object(pinned_move_input(archive, *handoff))
    expected_keys = {"format", "kind", "priorRelease", "stagedRelease", "database", "schema", "sourceRoot",
                     "destinationRoot", "registry", "launchers", "databasePlist", "continuity", "sealedDrivers"}
    if (manifest.keys() != expected_keys or type(manifest["format"]) is not int or manifest["format"] != 1
            or manifest["kind"] != "arbol-layout-move-preparation" or manifest["priorRelease"] != prior[1]
            or manifest["stagedRelease"] != staged[1] or manifest["sourceRoot"] != str(paths.old)
            or manifest["destinationRoot"] != str(paths.new)):
        raise RecoveryError("The handoff is not for this exact pair of releases and installation paths.")
    prepared = verify_release_pair(paths, prior, staged) if recorded is None else recorded
    if prepared["priorRelease"] != prior[1] or prepared["stagedRelease"] != staged[1]:
        raise RecoveryError("The saved move does not bind these release records.")
    if checked_source(manifest["database"]) != prepared["database"] or manifest["schema"] != prepared["schema"]:
        raise RecoveryError("The handoff does not identify the current database and common schema.")
    prior_record, _ = verify_release(*prior, archive=archive)
    release, _ = verify_release(*staged, archive=archive)
    before = {item["component"]: item["build"] for item in prior_record["builds"]}
    selected = {item["component"]: item for item in release["builds"]}
    after = {component: item["build"] for component, item in selected.items()}
    registry = paths.new / "builds" if prepared["registry"] == str(paths.historical_registry) else Path(prepared["registry"])
    if manifest["registry"] != {"source": prepared["registry"], "destination": str(registry),
                                 "priorDefaults": before, "stagedDefaults": after}:
        raise RecoveryError("The ordinary Build selection handoff differs from the recorded releases or registry paths.")

    def attachment(pin: Any) -> bytes:
        return stage_input(archive, staged[0], release, pin)

    plan = manifest["launchers"]
    if not isinstance(plan, list) or not 1 <= len(plan) <= 32:
        raise RecoveryError("The handoff does not name the staged ordinary launchers.")
    launchers = {}
    for row in plan:
        if not isinstance(row, dict) or row.keys() != {"route", "input"}:
            raise RecoveryError("A staged launcher lacks its exact route and attachment.")
        route = move_route(paths, row["route"])
        raw = attachment(row["input"])
        if (route.name in SEALED_DRIVERS or str(route) in launchers or not raw.startswith(b"#!")
                or os.fsencode(paths.old) in raw):
            raise RecoveryError("A staged ordinary launcher overlaps a sealed or relocating path.")
        launchers[str(route)] = raw
    if not {"arbol", "arbol-trunk"} <= {Path(route).name for route in launchers}:
        raise RecoveryError("The staged ordinary Backend and Trunk launchers are required.")

    owner = pwd.getpwuid(os.getuid())
    plist = attachment(manifest["databasePlist"])
    expected_plist = launch_agent(Installation(Places(paths.home), owner.pw_name, BIN))
    if plistlib.loads(plist) != plistlib.loads(expected_plist.encode()):
        raise RecoveryError("The staged database plist differs from the ordinary layout-2 launch agent.")

    continuity = move_object(attachment(manifest["continuity"]))
    if (continuity.keys() != {"format", "kind", "result", "destinationRoot", "promptsSent", "claudeVersion", "codexVersion"}
            or type(continuity["format"]) is not int or continuity["format"] != 1
            or continuity["kind"] != "arbol-layout-continuity" or continuity["result"] != "passed"
            or continuity["destinationRoot"] != str(paths.new) or type(continuity["promptsSent"]) is not int
            or continuity["promptsSent"] != 0
            or any(not isinstance(continuity[key], str) or not continuity[key].strip()
                   for key in ("claudeVersion", "codexVersion"))):
        raise RecoveryError("The verified no-prompt continuity observations are missing for the destination paths.")

    driver = manifest["sealedDrivers"]
    if (not isinstance(driver, dict) or driver.keys() != {"gate", "acceptances"}
            or not isinstance(driver["acceptances"], dict) or driver["acceptances"].keys() != SEALED_DRIVERS
            or not SEALED_DRIVERS <= selected.keys()):
        raise RecoveryError("The destination-bound sealed Driver handoff is incomplete.")
    gate_raw = attachment(driver["gate"])
    gate = move_object(gate_raw)
    provider = selected[BACKEND]["evidence"]["sealedPayload"]["descriptorSha256"]
    if (gate.keys() != {"version", "kind", "providerPayloadSha256", "components"}
            or type(gate["version"]) is not int or gate["version"] != 1 or gate["kind"] != "driver-gate"
            or gate["providerPayloadSha256"] != provider or not isinstance(gate["components"], list)
            or len(gate["components"]) != len(SEALED_DRIVERS)):
        raise RecoveryError("The staged Driver gate does not bind the verified provider and all four launchers.")
    platform = os.uname()
    for component, row in zip(sorted(SEALED_DRIVERS), gate["components"], strict=True):
        if (not isinstance(row, dict) or row.keys() != {"component", "launcher", "launcherSha256"}
                or row["component"] != component or not isinstance(row["launcherSha256"], str)
                or DIGEST.fullmatch(row["launcherSha256"]) is None
                or move_route(paths, row["launcher"]).name != component):
            raise RecoveryError("The staged Driver gate has an invalid destination launcher.")
        acceptance = move_object(attachment(driver["acceptances"][component]))
        producer = selected[component]["evidence"]["sealedPayload"]["descriptorSha256"]
        required = {
            "version": 1, "kind": "driver-qualification", "scope": str(registry),
            "contract": "DRV-browser-identity-1", "providerPayloadSha256": provider,
            "producerPayloadSha256": producer, "gateSha256": sha(gate_raw),
            "platform": {"system": platform.sysname, "release": platform.release, "machine": platform.machine},
        }
        if (acceptance.keys() != required.keys() | {"status", "evidenceSha256"}
                or any(acceptance.get(key) != value for key, value in required.items())
                or acceptance["status"] not in ("candidate", "qualified")
                or (paths.home == Path(owner.pw_dir).resolve() and acceptance["status"] != "qualified")
                or not isinstance(acceptance["evidenceSha256"], str)
                or DIGEST.fullmatch(acceptance["evidenceSha256"]) is None):
            raise RecoveryError("A sealed Driver acceptance does not match the destination and selected payload.")

    return {**prepared, "handoffSha256": handoff[1], "targetRegistry": str(registry), "stage": manifest,
            "stagedLaunchers": launchers, "stagedPlist": plist}


def verify_writer_refusal(archive: Archive, prepared: dict[str, Any], pin: tuple[Path, str]) -> None:
    evidence = move_object(pinned_move_input(archive, *pin))
    prior = prepared["stage"]["registry"]["priorDefaults"]
    writers = {name for name in prior if name == BACKEND or name.startswith("arbol-trunk/")}
    expected = {name: {"build": prior[name], "default": "refused", "explicit": "refused", "missingMarker": "refused"}
                for name in writers}
    expected["arbol-exchanges"] = expected[BACKEND]
    if evidence != {"format": 1, "kind": "arbol-layout-writer-refusal", "priorRelease": prepared["priorRelease"],
                    "handoffSha256": prepared["handoffSha256"], "isolated": True, "writers": expected}:
        raise RecoveryError("The isolated prior writer refusal evidence does not cover the exact release and routes.")


def drain_attribution(folder: int, intent: dict[str, Any], marker: State) -> str | None:
    try:
        receipt = read_move_document(folder, DRAIN_RECORD)
    except FileNotFoundError:
        if marker.phase != "normal":
            raise RecoveryError("An existing closed session has no durable attribution to this move.") from None
        return None
    session = receipt.get("session")
    generation = receipt.get("generation")
    if (receipt.keys() != {"format", "intentSha256", "session", "generation"} or receipt["format"] != 1
            or receipt["intentSha256"] != sha(canonical(intent))
            or not isinstance(session, str) or TOKEN.fullmatch(session) is None
            or not isinstance(generation, str) or TOKEN.fullmatch(generation) is None):
        raise RecoveryError("The saved drain attribution does not match this move.")
    if marker.phase == "normal":
        if marker.generation != generation:
            raise RecoveryError("The prior release reopened after the recorded drain intent.")
        return None  # The child journaled the proposal but its marker write did not take effect.
    if marker.session != session or (marker.phase == "draining" and marker.generation != generation):
        raise RecoveryError("A different exclusive session owns the layout-1 runtime.")
    return session


def prepare_move_maintenance(
    paths: MovePaths, prior: tuple[Path, str], staged: tuple[Path, str], handoff: tuple[Path, str], *,
    refusal: tuple[Path, str], snapshot_directory: Path, restore_directory: Path,
    restore_socket: Path, restore_port: int, restore_role: str, drain_only: bool,
) -> dict[str, Any]:
    archive = require_archive()
    prepared = verify_staged_move(paths, prior, staged, handoff)
    verify_writer_refusal(archive, prepared, refusal)
    snapshot_directory = archive.backup_path(snapshot_directory, allow_missing=True)
    restore_directory = archive.backup_path(restore_directory, allow_missing=True)
    if (snapshot_directory == BACKUPS or restore_directory == BACKUPS
            or snapshot_directory.is_relative_to(restore_directory) or restore_directory.is_relative_to(snapshot_directory)):
        raise RecoveryError("Use separate private archive destinations for the snapshot and isolated restore.")
    isolated = database_target(str(prepared["database"]["database"]), socket=restore_socket, port=restore_port,
                               user=restore_role, home=paths.home)
    if any(Path(isolated.host).is_relative_to(root) for root in (paths.old, paths.new)):
        raise RecoveryError("The restore socket must be outside both installation layouts.")
    intent = {
        "format": 1, "handoffSha256": handoff[1], "priorRelease": prior[1], "stagedRelease": staged[1],
        "priorDirectory": str(prior[0]), "stagedDirectory": str(staged[0]), "database": prepared["database"],
        "schema": prepared["schema"], "refusalSha256": refusal[1], "snapshotDirectory": str(snapshot_directory),
        "restoreDirectory": str(restore_directory),
        "isolated": {"host": isolated.host, "port": isolated.port, "user": isolated.user},
    }
    runtime = paths.old / "runtime"
    with rename_roots(paths) as (_, folder):
        with directory(runtime) as admission:
            marker = read_state(admission, layout=1)
        if marker.source != prepared["database"]:
            raise RecoveryError("The current layout-1 marker names a different source database.")
        try:
            previous = read_move_document(folder, MOVE_INTENT)
        except FileNotFoundError:
            if not drain_only or marker.phase != "normal":
                raise RecoveryError("Start the exact move drain before freezing or capturing.") from None
            write_move_document(folder, MOVE_INTENT, intent)
        else:
            if previous != intent:
                attempt = {"restoreDirectory", "isolated"}
                accepted = optional_move_document(folder, SNAPSHOT_RECORD)
                if (drain_only or {key: value for key, value in previous.items() if key not in attempt}
                        != {key: value for key, value in intent.items() if key not in attempt}):
                    raise RecoveryError("A different verified move already owns this installation.")
                if accepted is not None and (accepted.get("restoreReceipt") != str(restore_directory / "restore.json")
                                             or accepted.get("isolated") != intent["isolated"]):
                    raise RecoveryError("The move already has a different verified isolated restore.")
                # A failed isolated restore stays on Mercury. Retry only its
                # disposable target, keeping the original drain attribution.
                intent = previous
        session = drain_attribution(folder, intent, marker)
        if drain_only:
            return prior_maintenance_transition(paths, prepared, prior[0], action="drain", attributed_session=session,
                                                attribution=(folder, sha(canonical(intent))) if session is None else None)
        if session is None:
            raise RecoveryError("The exact move has yet to publish its draining marker.")
        exclusive = prior_maintenance_transition(paths, prepared, prior[0], action="freeze", attributed_session=session)
        with exclusive_layout_lease(runtime) as lease:
            starting = read_state(lease.require(runtime), layout=1)
            if (starting.phase != "exclusive" or starting.session != session or starting.source != prepared["database"]
                    or starting.generation != exclusive["generation"]):
                raise RecoveryError("The exclusive marker changed before snapshot capture.")

            def bound_snapshot(source: dict[str, Any], owner: str) -> Any:
                if source != starting.source or owner != session or read_state(lease.require(runtime), layout=1) != starting:
                    raise RecoveryError("The snapshot no longer owns the exact exclusive move session.")
                return nullcontext(session)

            settings, _ = read_settings(database_settings(paths.home))
            target = database_target(str(starting.source["database"]), home=paths.home, settings=settings)
            if not os.path.lexists(snapshot_directory):
                capture(target, prior[0], snapshot_directory, maintenance_session=session, exclusive=bound_snapshot,
                        installed_data=paths.old / "database/data")
            snapshot, _, _ = validate_snapshot(snapshot_directory, storage=archive)
            expected = {"source": starting.source, "schema": prepared["schema"], "releaseSha256": prior[1],
                        "maintenanceSession": session}
            if any(snapshot.get(key) != value for key, value in expected.items()):
                raise RecoveryError("The saved snapshot belongs to a different schema, release or move session.")
            receipt = restore_directory / "restore.json"
            if not os.path.lexists(restore_directory):
                receipt = restore(isolated, snapshot_directory, restore_directory)
            proof = verify_recovery(snapshot_directory, receipt, source=starting.source, schema=prepared["schema"],
                                    release_sha256=prior[1], maintenance_session=session)
            if (proof["target"]["host"], proof["target"]["port"]) != (isolated.host, isolated.port):
                raise RecoveryError("The isolated restore receipt belongs to a different socket target.")
            bound_snapshot(starting.source, session)
            result = {"format": 1, "session": session, "generation": starting.generation, "handoffSha256": handoff[1],
                      "snapshotDirectory": str(snapshot_directory), "restoreReceipt": str(receipt),
                      "snapshotSha256": proof["snapshotSha256"], "receiptSha256": proof["receiptSha256"],
                      "isolated": {"host": isolated.host, "port": isolated.port, "user": isolated.user}}
            try:
                recorded = read_move_document(folder, SNAPSHOT_RECORD)
            except FileNotFoundError:
                write_move_document(folder, SNAPSHOT_RECORD, result)
            else:
                if recorded != result and recorded != {key: value for key, value in result.items() if key != "isolated"}:
                    raise RecoveryError("The existing move snapshot record changed.")
        return {**result, "status": "move_snapshot_verified"}


def file_image(path: Path) -> dict[str, Any] | None:
    owner_directory(path.parent)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if info.st_uid != os.getuid():
        raise RecoveryError(f"A move configuration entry has a different owner: {path.name}.")
    value: dict[str, Any]
    if stat.S_ISLNK(info.st_mode):
        value = {"link": os.readlink(path)}
    elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not info.st_mode & 0o022:
        with opened(path, ENTRY) as fd, os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read((2**20) + 1)
            if (len(raw) != info.st_size or len(raw) > 2**20 or stamp(info) != stamp(os.fstat(fd))):
                raise RecoveryError(f"A move configuration file changed or is too large: {path.name}.")
        value = {"mode": stat.S_IMODE(info.st_mode), "bytes": base64.b64encode(raw).decode("ascii")}
    else:
        raise RecoveryError(f"A move configuration entry is unsafe: {path.name}.")
    if stamp(info) != stamp(path.lstat()):
        raise RecoveryError(f"A move configuration entry changed: {path.name}.")
    return value


def installed_file(raw: bytes, mode: int) -> dict[str, Any]:
    return {"mode": mode, "bytes": base64.b64encode(raw).decode("ascii")}


def replace_move_file(path: Path, before: Any, after: Any) -> None:
    current = file_image(path)
    if current == after:
        return
    if current != before:
        raise RecoveryError(f"A move configuration entry no longer matches either saved image: {path.name}.")
    with opened(path.parent, DIR) as folder:
        if not os.path.samestat(os.fstat(folder), owner_directory(path.parent)):
            raise RecoveryError(f"A move configuration directory changed: {path.parent}.")
        if after is None:
            if file_image(path) != before:
                raise RecoveryError(f"A move configuration entry changed before removal: {path.name}.")
            os.unlink(path.name, dir_fd=folder)
        else:
            temporary = f".{path.name}.arbol-move-{uuid4().hex}"
            try:
                if "link" in after:
                    os.symlink(after["link"], temporary, dir_fd=folder)
                else:
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(base64.b64decode(after["bytes"], validate=True))
                        stream.flush()
                        os.fchmod(stream.fileno(), after["mode"])
                        os.fsync(stream.fileno())
                if file_image(path) != before:
                    raise RecoveryError(f"A move configuration entry changed during replacement: {path.name}.")
                if before is None:
                    rename_exclusive(folder, temporary, folder, path.name)
                else:
                    os.replace(temporary, path.name, src_dir_fd=folder, dst_dir_fd=folder)
            finally:
                try:
                    os.unlink(temporary, dir_fd=folder)
                except FileNotFoundError:
                    pass
        os.fsync(folder)
    if file_image(path) != after:
        raise RecoveryError(f"The installed move configuration did not match its saved image: {path.name}.")


def backup_excluded(paths: MovePaths, data: Path) -> bool:
    result = run(["/usr/bin/tmutil", "isexcluded", str(data)], paths.home, timeout=15)
    report = result.stdout.strip()
    if result.returncode or report not in (f"[Excluded] {data}", f"[Included] {data}"):
        raise RecoveryError("Time Machine could not establish the exact data folder exclusion.")
    return report.startswith("[Excluded]")


def verify_driver_destination(prepared: dict[str, Any], *, ready: bool = False) -> None:
    """Read the existing closed Driver deployment and exact selected authority at its destination."""
    admission = move_provider_module("driver_admission")
    payloads = move_provider_module("driver_payload")
    process = move_provider_module("driver_process")
    registry = Path(prepared["targetRegistry"])
    owner_directory(registry)
    staged = prepared["stage"]
    gate = payloads.verify_gate(registry)
    if gate.digest != staged["sealedDrivers"]["gate"]["sha256"]:
        raise RecoveryError("The destination Driver gate differs from the approved relocation handoff.")
    selected = staged["registry"]["stagedDefaults"]
    if gate.provider.build != selected[BACKEND]:
        raise RecoveryError("The destination Driver gate selects a different Backend provider.")
    authorities = {component: admission.Authority(registry, component) for component in sorted(SEALED_DRIVERS)}
    first = next(iter(authorities.values()))
    deployment = admission.decode(admission.read_bytes(first.shared / "deployment.json"))
    admission.validate("deployment", deployment)
    closed = deployment["phase"] == "maintaining"
    if (deployment["phase"] not in ("maintaining", "complete") or (ready and closed)
            or (closed and deployment["newBoot"] != process.boot_uuid())
            or deployment["gateSha256"] != gate.digest
            or deployment["registrySha256"] != admission.sha256(admission.canonical(first.identity))):
        raise RecoveryError("The destination lacks the exact closed Driver deployment and boot readback.")
    deployed = {item["component"]: item for item in deployment["components"]}
    selected_payloads = []
    for row in gate.document["components"]:
        component = row["component"]
        authority = authorities[component]
        route = Path(row["launcher"])
        image = file_image(route)
        if image is None or "bytes" not in image or not image["mode"] & 0o111:
            raise RecoveryError("A destination Driver launcher is missing or is not executable.")
        if sha(base64.b64decode(image["bytes"], validate=True)) != row["launcherSha256"]:
            raise RecoveryError("A destination Driver launcher differs from its gate.")
        payload = payloads.registered(registry, component, selected[component])
        payloads.verify_acceptance(authority, payload, digest=staged["sealedDrivers"]["acceptances"][component]["sha256"])
        selected_payloads.append(payload)
        control = authority.read("control")
        if (deployed[component]["launcherSha256"] != row["launcherSha256"]
                or (closed and control["epoch"] != deployed[component]["epoch"])
                or control["phase"] != ("exclusive" if closed else "normal")
                or control["session"] != (deployment["session"] if closed else None)):
            raise RecoveryError("A Driver does not belong to the verified destination cohort.")
    if not closed:
        state = move_provider_module("driver_state")
        with ExitStack() as locks:
            for authority in authorities.values():
                locks.enter_context(authority.mutex())
            observed = admission.decode(admission.read_bytes(first.shared / "deployment.json"))
            if observed != deployment:
                raise RecoveryError("The destination Driver deployment changed during readback.")
            state._verified_complete(registry, list(authorities.values()), selected_payloads, gate, deployment)


def record_retarget(paths: MovePaths, prepared: dict[str, Any], session: str, lease: ExclusiveLayoutLease) -> None:
    with rename_roots(paths) as roots:
        record = read_rename_record(roots[1])
        positions = rename_positions(paths, roots, record)
        marker = require_rename_fence(paths, record, positions, lease)
        if record["session"] != session or "destination" in positions.values():
            raise RecoveryError("Record the retarget before-images before the working directories move.")
        data = paths.old / "database/data"
        config = file_image(data / "postgresql.conf")
        if config is None or config.keys() != {"mode", "bytes"}:
            raise RecoveryError("The prior PostgreSQL configuration is missing.")
        raw = base64.b64decode(config["bytes"], validate=True)
        old_socket = os.fsencode(paths.old / "database/socket")
        new_socket = os.fsencode(Places(paths.home).socket)
        line = re.compile(rb"(?m)^([ \t]*unix_socket_directories[ \t]*=[ \t]*)'([^']+)'([^\r\n]*)$")
        matches = list(line.finditer(raw))
        if len(matches) != 1 or matches[0][2] != old_socket or b"'" in new_socket or b"\n" in new_socket:
            raise RecoveryError("The database configuration does not name exactly the prior private socket.")
        start, end = matches[0].span(2)
        changed = raw[:start] + new_socket + raw[end:]
        plist = Places(paths.home).plist
        before_plist = file_image(plist)
        if before_plist is None or "bytes" not in before_plist:
            raise RecoveryError("The prior database launch agent is missing.")
        routes: dict[str, dict[str, dict[str, Any] | None]] = {
            str(plist): {"before": before_plist, "after": installed_file(prepared["stagedPlist"], 0o644)},
        }
        for route, contents in prepared["stagedLaunchers"].items():
            path = move_route(paths, route)
            routes[route] = {"before": file_image(path), "after": installed_file(contents, 0o755)}
        journal = {"format": 1, "session": session, "generation": marker.generation,
                   "handoffSha256": prepared["handoffSha256"],
                   "config": {"before": config, "after": installed_file(changed, config["mode"])},
                   "routes": routes, "excluded": backup_excluded(paths, data),
                   "exchangeAuthorization": file_image(paths.old / "runtime/writer-admission" / EXCHANGE_AUTHORIZATION)}
        if len(canonical(journal)) > MAX_RETARGET_BYTES:
            raise RecoveryError("The staged launcher and configuration inventory exceeds the move record limit.")
        try:
            previous = read_move_document(roots[1], RETARGET_RECORD, limit=MAX_RETARGET_BYTES)
        except FileNotFoundError:
            write_move_document(roots[1], RETARGET_RECORD, journal)
        else:
            if previous != journal:
                raise RecoveryError("The previous installation configuration changed before relocation.")


def retarget_move(
    paths: MovePaths, prepared: dict[str, Any], session: str, lease: ExclusiveLayoutLease, *, reverse: bool = False,
) -> None:
    with rename_roots(paths) as roots:
        record = read_rename_record(roots[1])
        positions = rename_positions(paths, roots, record)
        marker = require_rename_fence(paths, record, positions, lease)
        journal = read_move_document(roots[1], RETARGET_RECORD, limit=MAX_RETARGET_BYTES)
        if (record["session"] != session or journal["session"] != session or journal["generation"] != marker.generation
                or journal["handoffSha256"] != prepared["handoffSha256"] or database_service(paths) is not None
                or ("source" in positions.values() and not reverse)):
            raise RecoveryError("Retargeting requires the matching fenced move and stopped database.")
        if not reverse:
            verify_driver_destination(prepared)
        data = paths.old / "database/data" if positions["database"] == "source" else paths.new / "postgres/data"
        if postmaster_pid(data) is not None:
            raise RecoveryError("A database process still uses the configuration being retargeted.")
        previous, desired = ("after", "before") if reverse else ("before", "after")
        pg = journal["config"]
        replace_move_file(data / "postgresql.conf", pg[previous], pg[desired])
        plist = Places(paths.home).plist
        expected = {str(plist), *prepared["stagedLaunchers"].keys()}
        if journal["routes"].keys() != expected:
            raise RecoveryError("The saved launcher inventory differs from the verified handoff.")
        for route, pair in journal["routes"].items():
            path = plist if route == str(plist) else move_route(paths, route)
            replace_move_file(path, pair[previous], pair[desired])
        excluded = journal["excluded"] if reverse else True
        if backup_excluded(paths, data) != excluded:
            operation = "addexclusion" if excluded else "removeexclusion"
            result = run(["/usr/bin/tmutil", operation, str(data)], paths.home, timeout=15)
            if result.returncode or backup_excluded(paths, data) != excluded:
                raise RecoveryError("Time Machine did not apply the recorded data folder exclusion.")
        require_rename_fence(paths, record, positions, lease)


def move_database_ready(paths: MovePaths, data: Path, socket: Path, port: int) -> dict[str, str]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        service = database_service(paths)
        pid = postmaster_pid(data)
        if (service is not None and service.get("path") == str(Places(paths.home).plist)
                and service.get("state") == "running" and pid is not None and service.get("pid") == str(pid)):
            ready = run([str(BIN / "pg_isready"), "-h", str(socket), "-p", str(port), "-t", "2"], paths.home, timeout=10)
            if ready.returncode == 0:
                return service
        time.sleep(0.5)
    raise RecoveryError("The exact move database service did not become ready on its private socket.")


def start_move_database(paths: MovePaths, session: str, record: dict[str, Any], folder: int) -> None:
    places = Places(paths.home)
    data = owner_directory(places.data, private=True)
    plist = file_image(places.plist)
    retarget = read_move_document(folder, RETARGET_RECORD, limit=MAX_RETARGET_BYTES)
    if (plist != retarget["routes"][str(places.plist)]["after"]
            or list(identity(data)) != record["dataIdentity"] or not backup_excluded(paths, places.data)):
        raise RecoveryError("The database startup paths or configuration differ from the retargeted move.")
    intent = {"format": 1, "session": session, "dataIdentity": record["dataIdentity"],
              "plistSha256": sha(canonical(plist))}
    active = database_service(paths)
    try:
        prior = read_move_document(folder, STARTED_RECORD)
    except FileNotFoundError:
        if active is not None or postmaster_pid(places.data) is not None:
            raise RecoveryError("An unrecorded database process already occupies the moved installation.") from None
        write_move_document(folder, STARTED_RECORD, intent)
    else:
        if prior != intent:
            raise RecoveryError("The saved startup intent belongs to a different move.")
    if active is None:
        result = run([LAUNCHCTL, "bootstrap", f"gui/{os.getuid()}", str(places.plist)], paths.home, timeout=30)
        if result.returncode:
            raise RecoveryError("launchd did not start the staged database service.")
    move_database_ready(paths, places.data, places.socket, int(record["database"]["port"]))


def unload_retired_launch_job(paths: MovePaths, folder: int) -> None:
    """Resume after a Driver boot boundary that reloaded the unchanged old plist."""
    service = database_service(paths)
    if service is None or optional_move_document(folder, STARTED_RECORD) is not None:
        return
    places = Places(paths.home)
    journal = read_move_document(folder, RETARGET_RECORD, limit=MAX_RETARGET_BYTES)
    if (service.get("path") != str(places.plist) or "pid" in service or service.get("state") == "running"
            or postmaster_pid(places.data) is not None
            or file_image(places.plist) != journal["routes"][str(places.plist)]["before"]):
        raise RecoveryError("An unrecorded database service occupies the closed move.")
    result = run([LAUNCHCTL, "bootout", f"gui/{os.getuid()}/{LABEL}"], paths.home, timeout=90)
    if result.returncode or database_service(paths) is not None:
        raise RecoveryError("The unloaded prior database job was reloaded across the closed move.")


def verify_move_database(
    paths: MovePaths, record: dict[str, Any], snapshot: dict[str, Any], *, compare_data: bool, prior: bool = False,
) -> dict[str, Any]:
    from probe_database_server import (
        Context,
        Failed,
        check_data_folder,
        check_launch_agent,
        check_listening,
        check_settings,
    )

    places = PriorPlaces(paths.home) if prior else Places(paths.home)
    probe = Context(places, restart=False)
    try:
        for inspect_database in (check_settings, check_data_folder, check_listening, check_launch_agent):
            inspect_database(probe)
    except Failed as problem:
        raise RecoveryError("The moved database failed its read-only installed probe.") from problem
    raw, version = read_settings(places.settings)
    target = database_target(str(record["database"]["database"]), home=paths.home, settings=raw)
    with target.connect() as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        source = source_identity(connection, target.host, target.port)
        cluster = cluster_identity(connection, target, places.data)
        socket = connection.execute("SHOW unix_socket_directories").fetchone()
        data = connection.execute("SHOW data_directory").fetchone()
        observed = observations(connection, None)
        if (source != record["database"] or cluster != snapshot["sourceCluster"] or socket != (str(places.socket),)
                or data != (str(places.data),) or observed["schema"] != record["schema"]
                or (compare_data and observed != snapshot["observation"])):
            raise RecoveryError("The moved database does not match its retained cluster, socket, data and schema.")
    if stamp(places.settings.lstat()) != version:
        raise RecoveryError("The database settings changed during post-move verification.")
    return {"source": source, "cluster": cluster, "schema": observed["schema"]}


def verify_reopen_witness(
    archive: Archive, prepared: dict[str, Any], record: dict[str, Any], pin: tuple[Path, str],
) -> None:
    witness = move_object(pinned_move_input(archive, *pin))
    accounts = {component: {"accounts": "read", "signIn": "unchanged", "keychain": "unchanged", "nativeHomes": "unchanged"}
                for component in SEALED_DRIVERS}
    prior = prepared["stage"]["registry"]["priorDefaults"]
    writers = {name: build for name, build in prior.items() if name == BACKEND or name.startswith("arbol-trunk/")}
    writers["arbol-exchanges"] = prior[BACKEND]
    refused = {name: {"build": build, "default": "refused", "explicit": "refused", "admission": "refused"}
               for name, build in writers.items()}
    if witness != {"format": 1, "kind": "arbol-layout-move-verification", "session": record["session"],
                   "handoffSha256": prepared["handoffSha256"], "release": record["stagedRelease"],
                   "snapshotSha256": rename_snapshot_pins(record)["snapshotSha256"],
                   "noPrompts": True, "accounts": accounts, "layout1": refused}:
        raise RecoveryError("The accepted Driver continuity and layout-1 refusal observations do not match this move.")


def finish_move(
    paths: MovePaths, prepared: dict[str, Any], staged: tuple[Path, str], verification: tuple[Path, str],
    session: str, lease: ExclusiveLayoutLease,
) -> dict[str, Any]:
    from arbol_backend.exchange_context import context
    from arbol_backend.exchange_drain import GuardedSelection, reopen
    from arbol_installation.exchange_release import authorization_from_release, verify_authorization

    archive = require_archive()
    places = Places(paths.home)
    with rename_roots(paths) as roots:
        _, folder = roots
        record = read_rename_record(folder)
        positions = rename_positions(paths, roots, record)
        runtime = paths.new / "runtime"
        admission = lease.require(runtime)
        state = read_state(admission)
        if (record["session"] != session or record["stagedRelease"] != staged[1]
                or "source" in positions.values() or state.source != record["database"]):
            raise RecoveryError("Reopening requires the same exact completed relocation.")
        retarget = read_move_document(folder, RETARGET_RECORD, limit=MAX_RETARGET_BYTES)
        started = read_move_document(folder, STARTED_RECORD)
        if (started.get("session") != session or started.get("dataIdentity") != record["dataIdentity"]
                or retarget["session"] != session or retarget["handoffSha256"] != prepared["handoffSha256"]
                or file_image(places.data / "postgresql.conf") != retarget["config"]["after"]
                or any(file_image(Path(path)) != image["after"] for path, image in retarget["routes"].items())
                or not backup_excluded(paths, places.data)):
            raise RecoveryError("The retargeted configuration or Time Machine exclusion changed before reopen.")
        verify_reopen_witness(archive, prepared, record, verification)
        verify_driver_destination(prepared, ready=True)
        pins = rename_snapshot_pins(record)
        snapshot, snapshot_sha256, _ = validate_snapshot(Path(pins["snapshotDirectory"]), storage=archive)
        if snapshot_sha256 != pins["snapshotSha256"]:
            raise RecoveryError("The verified move snapshot changed before reopen.")
        checked = verify_move_database(paths, record, snapshot, compare_data=state.phase != "normal")
        settings, _ = read_settings(places.settings)
        registry = Path(prepared["targetRegistry"])
        builds = check_release(paths, registry, archive, staged, 2, json.loads(settings))
        if any(selected_build(paths, registry, component).get("build") != about["build"]
               for component, (_, about) in builds.items()):
            raise RecoveryError("An ordinary selector differs from the staged release.")
        package, _ = builds[BACKEND]
        backend_context = context(package, {})
        if backend_context.identity.folder != runtime or backend_context.identity.package != package:
            raise RecoveryError("The staged Backend did not resolve the relocated runtime.")
        release, _ = verify_release(*staged, archive=archive)
        authorization = authorization_from_release(release, staged[1])
        expected = {"format": 1, "session": session, "handoffSha256": prepared["handoffSha256"],
                    "snapshotSha256": snapshot_sha256, "verificationSha256": verification[1], "release": staged[1],
                    "database": checked, "authorizationSha256": sha(authorization)}
        try:
            attempt = read_move_document(folder, REOPEN_RECORD)
        except FileNotFoundError:
            if state.phase != "exclusive":
                raise RecoveryError("There is no durable move reopen attempt for this normal admission marker.") from None
            require_rename_fence(paths, record, positions, lease)
            attempt = {**expected, "normalGeneration": uuid4().hex}
            write_move_document(folder, REOPEN_RECORD, attempt)
        else:
            generation = attempt.get("normalGeneration")
            if not isinstance(generation, str) or TOKEN.fullmatch(generation) is None or attempt != {**expected, "normalGeneration": generation}:
                raise RecoveryError("The durable reopen attempt differs from the verified relocation.")
        if state.phase == "exclusive":
            require_rename_fence(paths, record, positions, lease)

            @contextmanager
            def selected(admission_folder: int, current: State) -> Iterator[GuardedSelection]:
                if current != state:
                    raise RecoveryError("The exclusive marker changed before staging Exchange authorization.")
                commitment = stage_exchange_authorization(admission_folder, authorization, staged[1])
                yield GuardedSelection("successor", record["database"], session, state.generation, state.release,
                                       staged[1], commitment)

            reopen(backend_context, record["database"], session, release=staged[1], schema=record["schema"],
                   verify_selection=selected, lease=lease, generation=attempt["normalGeneration"])
        normal = read_state(lease.require(runtime))
        if (normal.phase != "normal" or normal.generation != attempt["normalGeneration"] or normal.release != staged[1]
                or normal.source != record["database"] or normal.exchange_authorization != sha(authorization)):
            raise RecoveryError("The installed normal marker does not prove the recorded reopen boundary.")
        verify_authorization(admission, normal.exchange_authorization, staged[1])
        boundary = {**attempt, "status": "move_reopened"}
        try:
            existing = read_move_document(folder, BOUNDARY_RECORD)
        except FileNotFoundError:
            write_move_document(folder, BOUNDARY_RECORD, boundary)
        else:
            if existing != boundary:
                raise RecoveryError("An existing reopen boundary differs from the observed normal marker.")
        return boundary


def recover_interrupted_drain(
    paths: MovePaths, prepared: dict[str, Any], prior: tuple[Path, str], session: str,
) -> dict[str, Any]:
    raw, _ = read_settings(database_settings(paths.home))
    archive = require_archive()
    check_release(paths, resolve_registry(paths), archive, prior, 1, json.loads(raw))
    package, backend = prior_backend(paths, prepared, prior[0])
    operation = """
from arbol_backend.exchange_drain import reopen

with directory(ctx.identity.folder) as folder:
    before = read_state(folder)
    if (before.phase not in ("draining", "exclusive") or before.session != request["session"]
            or before.source != request["source"] or before.release != request["release"]):
        raise ValueError("Only the unchanged prior release can recover this drain.")
    schema = asyncio.run(inspect_database(ctx, before.source, idle=False))
    if schema != request["schema"] or read_state(folder) != before:
        raise ValueError("The prior schema or admission changed during drain recovery.")
    reopen(ctx, before.source, before.session, release=before.release, schema=schema,
           verify_release=lambda: request["release"])
    after = read_state(folder)
    if after.phase != "normal" or after.source != before.source or after.release != before.release:
        raise ValueError("The unchanged prior release did not reopen.")
print(json.dumps({"status": "drain_recovered", "release": after.release, "generation": after.generation}))
"""
    request = {"source": checked_source(prepared["database"]), "schema": prepared["schema"],
               "release": prior[1], "session": session}
    return run_prior_backend(paths, package, backend["build"], request, operation, timeout=60)


def stop_move_database(paths: MovePaths, folder: int, record: dict[str, Any]) -> None:
    places = Places(paths.home)
    running = database_service(paths)
    pid = postmaster_pid(places.data) if places.data.exists() else None
    if running is None and pid is None:
        return
    started = read_move_document(folder, STARTED_RECORD)
    data_identity = list(identity(owner_directory(places.data, private=True)))
    if (started.get("session") != record["session"] or started.get("dataIdentity") != data_identity
            or started.get("plistSha256") != sha(canonical(file_image(places.plist)))
            or not pid or running is None or running.get("pid") != str(pid) or running.get("path") != str(places.plist)):
        raise RecoveryError("The running database is outside the recorded move startup.")
    observer = move_provider_module("driver_process")
    process = observed_process(observer, pid)
    if process is None or process["executable"] != str((BIN / "postgres").resolve(strict=True)):
        raise RecoveryError("The recorded move database executable changed.")
    result = run([LAUNCHCTL, "bootout", f"gui/{os.getuid()}/{LABEL}"], paths.home, timeout=90)
    if result.returncode:
        raise RecoveryError("launchd did not unload the move's recorded database startup.")
    stop_recorded_process(observer, process, None)
    if database_service(paths) is not None or postmaster_pid(places.data) is not None:
        raise RecoveryError("The move database did not stop before recovery.")


def recover_move_files(paths: MovePaths, session: str, lease: ExclusiveLayoutLease) -> dict[str, Any]:
    """Restore the local before-images while the same closed admission lease is held."""
    with rename_roots(paths) as roots:
        _, folder = roots
        if optional_move_document(folder, BOUNDARY_RECORD) is not None:
            raise RecoveryError("A published layout-2 reopen boundary excludes pre-reopen recovery.")
        record = read_rename_record(folder)
        positions = rename_positions(paths, roots, record)
        marker = require_rename_fence(paths, record, positions, lease)
        if marker.session != session:
            raise RecoveryError("The move recovery session does not match.")
        moved = "destination" in positions.values()
        journal = optional_move_document(folder, RETARGET_RECORD, limit=MAX_RETARGET_BYTES)
        if moved:
            stop_move_database(paths, folder, record)
            if journal is None:
                raise RecoveryError("The moved installation has no original retarget configuration.")
        if journal is not None and (moved or database_service(paths) is None):
            prepared = {"handoffSha256": journal["handoffSha256"],
                        "stagedLaunchers": {path: None for path in journal["routes"]
                                            if path != str(Places(paths.home).plist)}}
            retarget_move(paths, prepared, session, lease, reverse=True)
        if moved:
            relocate_renames(paths, session, lease, reverse=True)
        runtime = paths.old / "runtime"
        lease.convert_marker(runtime, session=session, before=INSTALLATION_LAYOUT, after=1)
        if journal is not None:
            saved = journal["exchangeAuthorization"]
            authorization = runtime / "writer-admission" / EXCHANGE_AUTHORIZATION
            active = file_image(authorization)
            if active != saved:
                attempt = optional_move_document(folder, REOPEN_RECORD)
                if (attempt is None or active is None or "bytes" not in active
                        or sha(base64.b64decode(active["bytes"], validate=True)) != attempt.get("authorizationSha256")):
                    raise RecoveryError("The installed Exchange authorization is outside the recorded move.")
                replace_move_file(authorization, active, saved)
            if (file_image(PriorPlaces(paths.home).data / "postgresql.conf") != journal["config"]["before"]
                    or any(file_image(Path(path)) != images["before"] for path, images in journal["routes"].items())
                    or backup_excluded(paths, PriorPlaces(paths.home).data) != journal["excluded"]):
                raise RecoveryError("The original configuration and backup exclusion did not return to their recorded state.")
        return {**record, "status": "move_files_recovered"}


def start_prior_database(paths: MovePaths, record: dict[str, Any], folder: int) -> None:
    places = PriorPlaces(paths.home)
    active = database_service(paths)
    if active is None:
        previous = read_move_document(folder, SERVICE_RECORD)
        plist = file_image(places.plist)
        if (previous["session"] != record["session"] or plist is None or "bytes" not in plist
                or sha(base64.b64decode(plist["bytes"], validate=True)) != previous["plistSha256"]
                or postmaster_pid(places.data) is not None):
            raise RecoveryError("The verified prior launch agent is unavailable for recovery.")
        result = run([LAUNCHCTL, "bootstrap", f"gui/{os.getuid()}", str(places.plist)], paths.home, timeout=30)
        if result.returncode:
            raise RecoveryError("launchd did not start the verified prior database.")
    move_database_ready(paths, places.data, places.socket, int(record["database"]["port"]))


def reopen_prior_release(
    paths: MovePaths, folder: int, record: dict[str, Any], prior: tuple[Path, str],
    snapshot: dict[str, Any], lease: ExclusiveLayoutLease, *, fallback: bool = False,
) -> dict[str, Any]:
    from arbol_backend.exchange_context import Context
    from arbol_backend.exchange_drain import GuardedSelection, reopen
    from arbol_backend.model import Identity, schema_compatibility

    if record["priorRelease"] != prior[1]:
        raise RecoveryError("Recovery requires the exact prior release.")
    runtime = paths.old / "runtime"
    admission = lease.require(runtime)
    marker = read_state(admission, layout=1)
    if marker.source != record["database"] or (marker.phase != "normal" and marker.session != record["session"]):
        raise RecoveryError("The prior admission marker is outside this recovery session.")
    start_prior_database(paths, record, folder)
    checked = verify_move_database(paths, record, snapshot, compare_data=marker.phase != "normal", prior=True)
    raw, _ = read_settings(database_settings(paths.home))
    archive = require_archive()
    registry = resolve_registry(paths)
    builds = check_release(paths, registry, archive, prior, 1, json.loads(raw))
    package, backend = builds[BACKEND]
    context = Context(Identity(backend["build"], runtime, paths.bin, paths.new, None, paths.home,
                               package, schema_compatibility(backend["schemaCompatibility"])))
    expected = {"format": 1, "session": record["session"], "release": prior[1], "database": checked,
                "snapshotFallback": fallback}
    attempt = optional_move_document(folder, PRIOR_REOPEN_RECORD)
    if attempt is None:
        if marker.phase != "exclusive":
            raise RecoveryError("There is no recorded prior reopen attempt for the normal marker.")
        attempt = {**expected, "normalGeneration": uuid4().hex}
        write_move_document(folder, PRIOR_REOPEN_RECORD, attempt)
    else:
        generation = attempt.get("normalGeneration")
        if not isinstance(generation, str) or TOKEN.fullmatch(generation) is None or attempt != {**expected, "normalGeneration": generation}:
            raise RecoveryError("A different prior reopen attempt is already recorded.")
    if marker.phase == "exclusive":
        common = {"release": prior[1], "schema": record["schema"], "layout": 1, "lease": lease,
                  "generation": attempt["normalGeneration"]}
        if marker.release == prior[1]:
            reopen(context, record["database"], record["session"], verify_release=lambda: prior[1], **common)
        else:
            @contextmanager
            def selected(_: int, state: State) -> Iterator[GuardedSelection]:
                if state != marker:
                    raise RecoveryError("The verified prior marker changed before reopen.")
                yield GuardedSelection("prior", state.source, record["session"], state.generation, state.release,
                                       prior[1], None)

            reopen(context, record["database"], record["session"], verify_selection=selected, **common)
    current = read_state(lease.require(runtime), layout=1)
    if (current.phase != "normal" or current.release != prior[1] or current.generation != attempt["normalGeneration"]
            or current.source != record["database"]):
        raise RecoveryError("The prior release did not reach its recorded normal boundary.")
    result = {**attempt, "status": "prior_reopened"}
    previous = optional_move_document(folder, RECOVERY_BOUNDARY)
    if previous is None:
        write_move_document(folder, RECOVERY_BOUNDARY, result)
    elif previous != result:
        raise RecoveryError("The recorded prior recovery boundary differs from the normal marker.")
    return result


def stop_prior_for_fallback(
    paths: MovePaths, folder: int, record: dict[str, Any], snapshot: dict[str, Any],
) -> None:
    places = PriorPlaces(paths.home)
    service = database_service(paths)
    pid = postmaster_pid(places.data)
    if service is None and pid is None:
        return
    previous = read_move_document(folder, SERVICE_RECORD)
    image = file_image(places.plist)
    if (previous.get("session") != record["session"] or service is None or pid is None
            or service.get("pid") != str(pid) or service.get("path") != str(places.plist) or image is None
            or sha(base64.b64decode(image["bytes"], validate=True)) != previous.get("plistSha256")):
        raise RecoveryError("The surviving prior database process is outside the recorded installation.")
    try:
        verify_move_database(paths, record, snapshot, compare_data=True, prior=True)
    except (RecoveryError, Refusal, psycopg.Error):
        pass
    else:
        raise RecoveryError("The original cluster verifies. Use the same-cluster recovery route.")
    observer = move_provider_module("driver_process")
    current = observed_process(observer, pid)
    if current is None or current["executable"] != str((BIN / "postgres").resolve(strict=True)):
        raise RecoveryError("The surviving prior database process changed before retirement.")
    result = run([LAUNCHCTL, "bootout", f"gui/{os.getuid()}/{LABEL}"], paths.home, timeout=90)
    if result.returncode:
        raise RecoveryError("The original database service did not retire.")
    stop_recorded_process(observer, current, None)
    if database_service(paths) is not None or postmaster_pid(places.data) is not None:
        raise RecoveryError("The original PostgreSQL service is still running.")


def record_fallback(
    paths: MovePaths, folder: int, record: dict[str, Any], snapshot: dict[str, Any],
    proof: dict[str, Any], isolated: dict[str, Any],
) -> dict[str, Any]:
    places = PriorPlaces(paths.home)
    if (proof["target"]["host"], proof["target"]["port"]) != (isolated["host"], isolated["port"]):
        raise RecoveryError("The verified restore belongs to a different isolated socket.")
    target = database_target(str(record["database"]["database"]), socket=Path(isolated["host"]), port=isolated["port"],
                             user=isolated["user"], home=paths.home)
    with target.connect() as connection:
        if (check_isolated(connection, target, snapshot) != proof["targetCluster"]
                or source_identity(connection, target.host, target.port) != proof["target"]):
            raise RecoveryError("The isolated cluster differs from its verified restore.")
        with connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            restored = observations(connection, None)
            data = connection.execute("SHOW data_directory").fetchone()
            if restored != snapshot["observation"] or data is None:
                raise RecoveryError("The isolated data or ledger differs from the verified snapshot.")
        restored_data = Path(data[0])
        info = owner_directory(restored_data, private=True)
        if (any(restored_data.is_relative_to(root) or root.is_relative_to(restored_data)
                for root in (paths.old, paths.new))
                or info.st_dev != owner_directory(places.folder, private=True).st_dev):
            raise RecoveryError("The restored cluster must be separate and on the installation's internal volume.")
        check_disk(restored_data)
        raw, _ = read_settings(places.settings)
        installed = database_target(target.database, home=paths.home, settings=raw)
        if installed.user != ROLE or (installed.host, installed.port) != (record["database"]["host"], record["database"]["port"]):
            raise RecoveryError("The saved installation does not name the verified PostgreSQL role and endpoint.")
        connection.execute(
            sql.SQL("ALTER ROLE {} LOGIN CREATEDB NOSUPERUSER NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}")
            .format(sql.Identifier(installed.user), sql.Literal(scram_verifier(installed.password)))
        )
    settings = {}
    for name in ("postgresql.conf", "postgresql.auto.conf", "pg_hba.conf", "pg_ident.conf"):
        old = file_image(places.data / name)
        if old is None or "bytes" not in old:
            raise RecoveryError("The exact prior PostgreSQL configuration is incomplete.")
        settings[name] = {"isolated": file_image(restored_data / name), "prior": old}
    result = {"format": 1, "session": record["session"], "generation": rename_inventory_proof(record)["generation"],
              "snapshotSha256": proof["snapshotSha256"], "restoreSha256": proof["receiptSha256"],
              "original": record["dataIdentity"], "priorCluster": snapshot["sourceCluster"],
              "replacement": list(identity(info)), "replacementCluster": proof["targetCluster"],
              "isolatedData": str(restored_data), "settings": settings,
              "source": record["database"],
              "replacementSource": {**record["database"], "databaseOid": proof["target"]["databaseOid"]}}
    write_move_document(folder, FALLBACK_RECORD, result)
    return result


def seat_fallback_data(paths: MovePaths, fallback: dict[str, Any]) -> None:
    places = PriorPlaces(paths.home)
    replacement = Path(fallback["isolatedData"])
    retired_name = f".arbol-move-original-{fallback['session']}"
    with opened(places.folder, DIR) as home, opened(replacement.parent, DIR) as staging:
        original = fallback["original"]
        recovered = fallback["replacement"]
        active = rename_identity(home, places.data.name)
        retired = rename_identity(home, retired_name)
        staged = rename_identity(staging, replacement.name)
        if (active, retired, staged) == (recovered, original, None):
            os.fsync(home)
            os.fsync(staging)
            return
        if ((active, retired, staged) not in ((original, None, recovered), (None, original, recovered))
                or database_service(paths) is not None):
            raise RecoveryError("Cannot determine which fallback cluster is seated or retired.")
        if postmaster_pid(replacement) is not None:
            response = run([str(BIN / "pg_ctl"), "-D", str(replacement), "-m", "fast", "-w", "-t", "60", "stop"],
                           paths.home, timeout=90)
            if response.returncode or postmaster_pid(replacement) is not None:
                raise RecoveryError("The verified isolated cluster did not stop before seating.")
        ensure_unused({"original": places.data if active is not None else places.folder / retired_name,
                       "isolated": replacement})
        for name, pair in fallback["settings"].items():
            if name not in ("postgresql.conf", "postgresql.auto.conf", "pg_hba.conf", "pg_ident.conf"):
                raise RecoveryError("The saved fallback configuration contains an unknown entry.")
            replace_move_file(replacement / name, pair["isolated"], pair["prior"])
        if active is not None:
            rename_exclusive(home, places.data.name, home, retired_name)
            os.fsync(home)
        if (rename_identity(home, retired_name) != original or rename_identity(staging, replacement.name) != recovered):
            raise RecoveryError("The original or restored data directory changed before seating.")
        rename_exclusive(staging, replacement.name, home, places.data.name)
        os.fsync(home)
        os.fsync(staging)
        if rename_identity(home, places.data.name) != recovered:
            raise RecoveryError("The seated cluster is outside the verified restore.")


def recover_snapshot_fallback(
    paths: MovePaths, folder: int, record: dict[str, Any], prior: tuple[Path, str],
    lease: ExclusiveLayoutLease,
) -> dict[str, Any]:
    archive = require_archive()
    pins = rename_snapshot_pins(record)
    snapshot_directory, restore_receipt = Path(pins["snapshotDirectory"]), Path(pins["restoreReceipt"])
    snapshot, _, _ = validate_snapshot(snapshot_directory, storage=archive)
    proof = verify_recovery(snapshot_directory, restore_receipt, source=record["database"], schema=record["schema"],
                            release_sha256=prior[1], maintenance_session=record["session"])
    if proof["receiptSha256"] != pins["receiptSha256"] or proof["snapshotSha256"] != pins["snapshotSha256"]:
        raise RecoveryError("The fallback restore differs from its pinned move evidence.")
    runtime = paths.old / "runtime"
    admission = lease.require(runtime)
    marker = read_state(admission, layout=1)
    fallback = optional_move_document(folder, FALLBACK_RECORD, limit=MAX_RETARGET_BYTES)
    if (optional_move_document(folder, BOUNDARY_RECORD) is not None
            or (marker.phase != "exclusive" and (fallback is None or marker.phase != "normal"))):
        raise RecoveryError("Snapshot fallback requires the recorded prior exclusive fence.")
    if fallback is None:
        if marker.session != record["session"] or marker.source != record["database"]:
            raise RecoveryError("A different database or session owns the prior marker.")
        stop_prior_for_fallback(paths, folder, record, snapshot)
        captured = read_move_document(folder, SNAPSHOT_RECORD)
        isolated = captured.get("isolated") or read_move_document(folder, MOVE_INTENT)["isolated"]
        fallback = record_fallback(paths, folder, record, snapshot, proof, isolated)
    if (fallback["session"] != record["session"] or fallback["snapshotSha256"] != proof["snapshotSha256"]
            or fallback["restoreSha256"] != proof["receiptSha256"]
            or marker.source not in (fallback["source"], fallback["replacementSource"])
            or (marker.phase == "exclusive" and (marker.session != fallback["session"] or marker.generation != fallback["generation"]))):
        raise RecoveryError("The saved replacement handoff does not match the live recovery boundary.")
    seat_fallback_data(paths, fallback)
    replacement = {**record, "database": checked_source(fallback["replacementSource"])}
    replacement_snapshot = {**snapshot, "sourceCluster": fallback["replacementCluster"]}
    start_prior_database(paths, replacement, folder)
    verify_move_database(paths, replacement, replacement_snapshot, compare_data=marker.phase != "normal", prior=True)
    current = read_state(lease.require(runtime), layout=1)
    if current != marker:
        raise RecoveryError("The prior exclusive marker changed while seating its recovery cluster.")
    if current.source != replacement["database"]:
        if current.phase != "exclusive":
            raise RecoveryError("Snapshot fallback cannot rebind an open admission marker.")
        write_state(admission, State("exclusive", current.generation, replacement["database"], current.session,
                                     current.release, current.exchange_authorization), layout=1)
    return reopen_prior_release(paths, folder, replacement, prior, replacement_snapshot, lease, fallback=True)


def intent_matches(
    intent: dict[str, Any], prior: tuple[Path, str], staged: tuple[Path, str], handoff: tuple[Path, str],
) -> None:
    expected = {"priorDirectory": str(prior[0]), "priorRelease": prior[1],
                "stagedDirectory": str(staged[0]), "stagedRelease": staged[1], "handoffSha256": handoff[1]}
    if any(intent.get(key) != value for key, value in expected.items()):
        raise RecoveryError("The command does not name the release pair and handoff that own the recorded move.")


def wait_for_move_witness(archive: Archive, verification: tuple[Path, str], seconds: int) -> None:
    path = archive.backup_path(verification[0], allow_missing=True)
    deadline = time.monotonic() + seconds
    while not os.path.lexists(path):
        if time.monotonic() >= deadline:
            raise RecoveryError("The independent verification receipt is still absent. The move remains fenced.")
        time.sleep(0.5)
    pinned_move_input(archive, path, verification[1])


def execute_move(
    paths: MovePaths, prior: tuple[Path, str], staged: tuple[Path, str], handoff: tuple[Path, str],
    verification: tuple[Path, str], *, witness_wait: int,
) -> dict[str, Any]:
    archive = require_archive()
    with rename_roots(paths) as roots:
        _, folder = roots
        intent = read_move_document(folder, MOVE_INTENT)
        capture = read_move_document(folder, SNAPSHOT_RECORD)
        intent_matches(intent, prior, staged, handoff)
        if capture.get("handoffSha256") != handoff[1] or optional_move_document(folder, PRIOR_REOPEN_RECORD) is not None:
            raise RecoveryError("The snapshot is outside this move or prior recovery already owns the boundary.")
        record = optional_move_document(folder, RENAME_RECORD)
        prepared = verify_staged_move(paths, prior, staged, handoff, recorded=record)
        session = capture["session"]
        runtime = paths.old / "runtime"
        if record is not None and rename_positions(paths, roots, record)["runtime"] == "destination":
            runtime = paths.new / "runtime"
        with exclusive_layout_lease(runtime) as lease:
            if record is None:
                record_renames(paths, prepared, session, lease, prior_release_directory=prior[0],
                               snapshot_directory=Path(capture["snapshotDirectory"]), restore_receipt=Path(capture["restoreReceipt"]))
                record = read_rename_record(folder)
            pins = rename_snapshot_pins(record)
            if (record["session"] != session or any(pins.get(key) != capture.get(key) for key in pins)
                    or rename_inventory_proof(record)["generation"] != capture.get("generation")):
                raise RecoveryError("The recorded rename does not bind the verified capture and exact exclusive session.")
            positions = rename_positions(paths, roots, record)
            if "source" in positions.values():
                if "destination" not in positions.values():
                    record_retarget(paths, prepared, session, lease)
                    stop_installation_services(paths, session, lease, prior[0])
                relocate_renames(paths, session, lease)
            runtime = paths.new / "runtime"
            admission = lease.require(runtime)
            try:
                marker = read_state(admission)
            except ValueError:
                marker = read_state(admission, layout=1)
            if marker.phase == "exclusive":
                lease.convert_marker(runtime, session=session, before=1, after=INSTALLATION_LAYOUT)
                unload_retired_launch_job(paths, folder)
                if database_service(paths) is None:
                    retarget_move(paths, prepared, session, lease)
                start_move_database(paths, session, record, folder)
                wait_for_move_witness(archive, verification, witness_wait)
            return finish_move(paths, prepared, staged, verification, session, lease)


def execute_recovery(
    paths: MovePaths, mode: Literal["files", "prior", "fallback"], prior: tuple[Path, str] | None = None,
) -> dict[str, Any]:
    with rename_roots(paths) as roots:
        _, folder = roots
        if optional_move_document(folder, BOUNDARY_RECORD) is not None:
            raise RecoveryError("The layout-2 boundary is already open. The move is past pre-reopen recovery.")
        intent = read_move_document(folder, MOVE_INTENT)
        record = optional_move_document(folder, RENAME_RECORD)
        if mode != "files":
            if prior is None or (str(prior[0]), prior[1]) != (intent["priorDirectory"], intent["priorRelease"]):
                raise RecoveryError("Recovery requires the exact prior release of the recorded move.")
            archive = require_archive()
        if record is None:
            if mode != "prior" or prior is None or optional_move_document(folder, SERVICE_RECORD) is not None:
                raise RecoveryError("There is no recorded relocation to recover.")
            with directory(paths.old / "runtime") as admission:
                marker = read_state(admission, layout=1)
            session = drain_attribution(folder, intent, marker)
            if session is None:
                raise RecoveryError("There is no attributed prior session to recover.")
            prepared = {**intent, "registry": str(resolve_registry(paths))}
            return recover_interrupted_drain(paths, prepared, prior, session)
        session = record["session"]
        fallback = optional_move_document(folder, FALLBACK_RECORD, limit=MAX_RETARGET_BYTES)
        if fallback is not None and mode != "fallback":
            raise RecoveryError("The recorded snapshot fallback already owns recovery.")
        runtime = paths.old / "runtime"
        if fallback is None and rename_positions(paths, roots, record)["runtime"] == "destination":
            runtime = paths.new / "runtime"
        with exclusive_layout_lease(runtime) as lease:
            if mode == "files":
                recover_move_files(paths, session, lease)
                return {"status": "move_files_recovered", "session": session}
            assert prior is not None
            if fallback is None and optional_move_document(folder, PRIOR_REOPEN_RECORD) is None:
                recover_move_files(paths, session, lease)
            if mode == "fallback":
                return recover_snapshot_fallback(paths, folder, record, prior, lease)
            pins = rename_snapshot_pins(record)
            snapshot, checksum, _ = validate_snapshot(Path(pins["snapshotDirectory"]), storage=archive)
            if checksum != pins["snapshotSha256"] or snapshot["source"] != record["database"]:
                raise RecoveryError("The prior snapshot no longer matches the recovery record.")
            return reopen_prior_release(paths, folder, record, prior, snapshot, lease)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", nargs=2, metavar=("RELEASE_DIR", "SHA256"))
    parser.add_argument("--staged", nargs=2, metavar=("RELEASE_DIR", "SHA256"))
    parser.add_argument("--handoff", nargs=2, metavar=("MANIFEST", "SHA256"))
    operation = parser.add_mutually_exclusive_group()
    for flag, description in (
        ("drain", "Begin or read back this exact move's drain."),
        ("capture", "Freeze and verify the move snapshot by isolated restore."),
        ("move", "Relocate and reopen the verified move."),
        ("rename-status", "Read the recorded locations of working directories."),
        ("recover-files", "Restore the local before-images and leave the closed fence in place."),
        ("recover", "Recover and reopen the verified prior layout with its original cluster."),
        ("fallback", "Recover and reopen the prior layout with its verified isolated restore."),
    ):
        operation.add_argument(f"--{flag}", dest="mode", action="store_const", const=flag, help=description)
    parser.add_argument("--writer-refusal", nargs=2, metavar=("RECEIPT", "SHA256"))
    parser.add_argument("--snapshot-directory", type=Path)
    parser.add_argument("--restore-directory", type=Path)
    parser.add_argument("--restore-target", nargs=3, metavar=("SOCKET_DIR", "PORT", "ROLE"))
    parser.add_argument("--verification", nargs=2, metavar=("RECEIPT", "SHA256"))
    parser.add_argument("--verification-wait", type=int, default=0, metavar="SECONDS")
    args = parser.parse_args()
    mode = args.mode
    if mode in ("recover", "fallback"):
        if args.prior is None or args.staged is not None or args.handoff is not None:
            parser.error("Prior recovery takes only the exact --prior release.")
    elif (args.prior is None) != (args.staged is None):
        parser.error("Supply both exact release records or neither.")
    if mode in ("rename-status", "recover-files") and (args.prior is not None or args.handoff is not None):
        parser.error("Use local rename status and file recovery separately from release verification.")
    if args.handoff is not None and args.prior is None:
        parser.error("A handoff requires the exact prior and staged release records.")
    capture_inputs = (args.writer_refusal, args.snapshot_directory, args.restore_directory, args.restore_target)
    if mode in ("drain", "capture"):
        if args.handoff is None or not all(capture_inputs):
            parser.error("Drain and capture require the verified handoff, writer proof and exact snapshot and restore inputs.")
    elif any(capture_inputs):
        parser.error("Snapshot and restore inputs require drain or capture.")
    if mode == "move":
        if args.handoff is None or args.verification is None or not 0 <= args.verification_wait <= 3600:
            parser.error("Move requires the handoff, pinned verification receipt and a wait of at most 3600 seconds.")
    elif args.verification is not None or args.verification_wait:
        parser.error("Verification inputs require --move.")
    paths = MovePaths(Path.home().resolve())
    try:
        if mode == "rename-status":
            result = inspect_renames(paths)
        elif mode == "recover-files":
            result = execute_recovery(paths, "files")
        elif mode in ("recover", "fallback"):
            prior = Path(args.prior[0]), args.prior[1]
            result = execute_recovery(paths, "prior" if mode == "recover" else "fallback", prior)
        elif args.prior is None:
            result = inspect(paths)
        else:
            prior = Path(args.prior[0]), args.prior[1]
            staged = Path(args.staged[0]), args.staged[1]
            if args.handoff is None:
                result = verify_release_pair(paths, prior, staged)
            else:
                handoff = Path(args.handoff[0]), args.handoff[1]
                if mode in ("drain", "capture"):
                    socket, port, role = args.restore_target
                    result = prepare_move_maintenance(
                        paths, prior, staged, handoff, refusal=(Path(args.writer_refusal[0]), args.writer_refusal[1]),
                        snapshot_directory=args.snapshot_directory, restore_directory=args.restore_directory,
                        restore_socket=Path(socket), restore_port=int(port), restore_role=role, drain_only=mode == "drain",
                    )
                elif mode == "move":
                    assert args.verification is not None
                    witness = Path(args.verification[0]), args.verification[1]
                    result = execute_move(paths, prior, staged, handoff, witness, witness_wait=args.verification_wait)
                else:
                    prepared = verify_staged_move(paths, prior, staged, handoff)
                    result = {key: value for key, value in prepared.items()
                              if key not in ("stage", "stagedLaunchers", "stagedPlist")}
                    result["status"] = "move_prepared"
        print(json.dumps(result))
        return 0
    except psycopg.Error:
        print(json.dumps({"status": "move_refused", "message": "PostgreSQL could not complete the move operation."}))
        return 1
    except (AdmissionRefusal, ArchiveUnavailable, Refusal, RecoveryError, KeyError, OSError, ValueError,
            subprocess.SubprocessError, IndexError, TypeError, RecursionError) as error:
        code = error.code if isinstance(error, ArchiveUnavailable) else "move_refused"
        print(json.dumps({"status": code, "message": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
