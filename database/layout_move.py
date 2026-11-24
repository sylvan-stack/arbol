"""Read-only preparation for the ARC-5 installation move."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from archive_volume import Archive, ArchiveUnavailable, require_archive
from layout_archive import ENTRY, WORKING, opened, stamp
from migrate_schema import Refusal, database_target
from recovery_release import (
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
from arbol_installation.paths import build_payload_directory, build_registry, database_settings, installation_root

REQUIRED = frozenset(("database", "runtime", "app", "builds", "drivers", "native-resources"))
BACKEND = "arbol"
SCHEMA_FIELDS = ("revision", "compatibilityVersion")
MAX_SETTINGS_BYTES = 65536


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
        destination = paths.new / ("postgres" if name == "database" else name)
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


def tool_json(arguments: list[str], home: Path) -> dict[str, Any]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("PG", "ARBOL_"))}
    env["HOME"] = str(home)
    result = subprocess.run(arguments, env=env, timeout=30, capture_output=True, check=False)
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
    args = parser.parse_args()
    if (args.prior is None) != (args.staged is None):
        parser.error("Supply both exact release records or neither.")
    paths = MovePaths(Path.home().resolve())
    try:
        if args.prior is None:
            result = inspect(paths)
        else:
            result = verify_release_pair(paths, (Path(args.prior[0]), args.prior[1]), (Path(args.staged[0]), args.staged[1]))
        print(json.dumps(result))
        return 0
    except (ArchiveUnavailable, Refusal, RecoveryError, KeyError, OSError, ValueError,
            subprocess.SubprocessError, IndexError) as error:
        code = error.code if isinstance(error, ArchiveUnavailable) else "move_refused"
        print(json.dumps({"status": code, "message": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
