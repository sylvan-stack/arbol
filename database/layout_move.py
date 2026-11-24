"""Preparation and recoverable directory renames for the ARC-5 installation move."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import plistlib
import re
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from archive_volume import BACKUPS, Archive, ArchiveUnavailable, require_archive
from layout_archive import DIR, ENTRY, WORKING, identity, opened, stamp
from migrate_schema import Refusal, database_target
from recovery import verify_recovery
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
    read_state,
    unique_pairs,
)
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
MAX_RENAME_RECORD_BYTES = 65536
RENAME_EXCL = 0x00000004  # Darwin sys/stdio.h
WRITER_INVENTORY_FORMAT = 3


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


def read_rename_record(folder: int) -> dict[str, Any]:
    with opened(RENAME_RECORD, ENTRY, folder) as descriptor:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or info.st_size > MAX_RENAME_RECORD_BYTES):
            raise RecoveryError("The move rename record is not a private owner file of the expected size.")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            raw = stream.read(MAX_RENAME_RECORD_BYTES + 1)
        named = os.stat(RENAME_RECORD, dir_fd=folder, follow_symlinks=False)
        if len(raw) != info.st_size or stamp(info) != stamp(os.fstat(descriptor)) or stamp(info) != stamp(named):
            raise RecoveryError("The move rename record changed while it was read.")
    value = json.loads(raw, object_pairs_hook=unique_pairs)
    if not isinstance(value, dict) or canonical(value) != raw:
        raise RecoveryError("The move rename record is not a canonical JSON object.")
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
        temporary = f".{RENAME_RECORD}.{uuid4().hex}"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=new)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(canonical(record))
                stream.flush()
                os.fsync(stream.fileno())
            rename_exclusive(new, temporary, new, RENAME_RECORD)
            os.fsync(new)
        finally:
            try:
                os.unlink(temporary, dir_fd=new)
            except FileNotFoundError:
                pass


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


def tool_json(arguments: list[str], home: Path, *, timeout: int = 30) -> dict[str, Any]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("PG", "ARBOL_"))}
    env["HOME"] = str(home)
    result = subprocess.run(arguments, env=env, timeout=timeout, capture_output=True, check=False)
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
    paths: MovePaths, package: Path, build: str, request: dict[str, Any], operation: str, *, timeout: int = 30,
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
    return tool_json(arguments, paths.home, timeout=timeout)


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
) -> dict[str, Any]:
    """Invoke a prior fence transition after preflight, using a journaled session on resume."""
    if (prepared.get("status") != "release_pair_verified" or action not in ("drain", "freeze")
            or (action == "freeze" and attributed_session is None)
            or (attributed_session is not None
                and (not isinstance(attributed_session, str) or TOKEN.fullmatch(attributed_session) is None))):
        raise RecoveryError("The prior maintenance transition lacks verified preparation or its exact session.")
    package, backend = prior_backend(paths, prepared, prior_release_directory)
    request = {
        "action": action, "attributedSession": attributed_session,
        "source": checked_source(prepared["database"]), "schema": prepared["schema"],
        "runtimeIdentity": prepared["working"]["runtime"]["identity"],
    }
    operation = """
from arbol_backend.exchange_drain import begin_maintenance, freeze
from arbol_installation.admission import STATE

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
    return run_prior_backend(paths, package, backend["build"], request, operation, timeout=60)


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", nargs=2, metavar=("RELEASE_DIR", "SHA256"))
    parser.add_argument("--staged", nargs=2, metavar=("RELEASE_DIR", "SHA256"))
    parser.add_argument("--rename-status", action="store_true", help="Read the recorded locations of working directories.")
    args = parser.parse_args()
    if (args.prior is None) != (args.staged is None):
        parser.error("Supply both exact release records or neither.")
    if args.rename_status and args.prior is not None:
        parser.error("Read rename status separately from release verification.")
    paths = MovePaths(Path.home().resolve())
    try:
        if args.rename_status:
            result = inspect_renames(paths)
        elif args.prior is None:
            result = inspect(paths)
        else:
            result = verify_release_pair(paths, (Path(args.prior[0]), args.prior[1]), (Path(args.staged[0]), args.staged[1]))
        print(json.dumps(result))
        return 0
    except (AdmissionRefusal, ArchiveUnavailable, Refusal, RecoveryError, KeyError, OSError, ValueError,
            subprocess.SubprocessError, IndexError) as error:
        code = error.code if isinstance(error, ArchiveUnavailable) else "move_refused"
        print(json.dumps({"status": code, "message": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
