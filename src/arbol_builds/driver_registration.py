"""Register immutable installed Driver packages without granting launch authority."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from arbol_installation.paths import build_payload_directory, build_registry

from .driver_admission import (
    COMPONENTS,
    Object,
    canonical,
    canonical_uuid,
    decode,
    physical,
    private_directory,
    publish_bytes,
    read_bytes,
    sha256,
    sync_directory,
)
from .driver_payload import SUBTREE, Payload, _file_hash, _private_registration, contained, load, pin_payloads
from .launcher import json_line, layout_fits, valid_record, write_all
from .mutation import with_mutation_lock
from .service import browser_production_high_water

REGISTRATION_COMPONENTS = ("arbol", *COMPONENTS)
REGISTRATION_RECORD = "driver-registration.json"
REGISTRATION_LIMIT = 64 * 1024

type CandidateCheck = Callable[[Path], tuple[Object, Object, Path]]
type DeploymentBlock = Callable[[str, Object], bool]


@dataclass(frozen=True)
class _Candidate:
    folder: Path
    component: str
    build: str
    record: Object
    row: Object

    def registry_record(self, registration: str) -> bytes:
        return canonical({"version": 1, "kind": "driver-registered-build",
                          "registrationSha256": registration, "record": self.record})


def _read_record(path: Path) -> Object:
    return decode(read_bytes(path, limit=REGISTRATION_LIMIT), limit=REGISTRATION_LIMIT, exact=False)


def _entry(root: Path, name: str) -> tuple[int, str]:
    path = physical(contained(root, name, regular=True).resolve(strict=True), directory=False)
    before = path.lstat()
    mode = stat.S_IMODE(before.st_mode)
    if before.st_nlink != 1 or mode & 0o7022 or not mode & stat.S_IXUSR:
        raise ValueError("Driver registration requires a private, regular executable entry.")
    _, digest = _file_hash(path)
    after = path.lstat()
    if ((before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns) !=
            (after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns)):
        raise ValueError("The Driver candidate entry changed while it was being verified.")
    return mode, digest


def _candidate(folder: Path, check_candidate: CandidateCheck) -> _Candidate:
    private_directory(folder)
    checked, recipe, repo = check_candidate(folder)
    record = _read_record(folder / "build.json")
    component, build = folder.parent.name, folder.name
    artifact_checks = [{"name": check["name"], "passed": True} for check in recipe["checks"] if "kind" not in check]
    if (checked != record or not valid_record(record, component, build) or not layout_fits(record)
            or record.get("packageOnly") is not True or record.get("stableCandidate") is not True
            or record.get("status") != "working" or record["checks"] != artifact_checks
            or set(record).intersection(("prunedAt", "withdrawn", "promotedAt"))
            or os.path.lexists(folder / "use.lock")
            or (component in COMPONENTS and (record.get("dataFormat") != 2 or recipe.get("dataFormat") != 2))):
        raise ValueError(f"{component}@{build} is not a verified layout-2 package-only stable candidate.")
    payload = load(folder / SUBTREE, component, build)
    source = record["source"]
    commit = source["commit"]
    if source["uncommittedChanges"] is not False or payload.descriptor["source"]["commit"] != commit:
        raise ValueError(f"{component}@{build} does not match its clean source commit.")
    tree = subprocess.check_output(
        ["/usr/bin/git", "--no-optional-locks", "-C", str(physical(repo)), "rev-parse", "--verify", commit + "^{tree}"],
        encoding="ascii",
    ).strip()
    if payload.descriptor["source"]["tree"] != tree:
        raise ValueError(f"{component}@{build} does not match its source tree.")
    mode, digest = _entry(folder, record["entry"])
    row: Object = {"component": component, "build": build, "source": {"commit": commit, "tree": tree},
                   "manifestSha256": payload.descriptor["payloadManifestSha256"],
                   "descriptorSha256": payload.digest, "recordSha256": sha256(canonical(record)),
                   "entry": record["entry"], "entrySha256": digest, "entryMode": mode, "candidate": str(folder)}
    return _Candidate(folder, component, build, record, row)


def _stable_parent(folder: Path) -> None:
    private_directory(folder.parent)
    try:
        folder.mkdir(mode=0o700)
    except FileExistsError:
        pass
    else:
        sync_directory(folder.parent)
    physical(folder)
    info = folder.lstat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("The installed Driver payload directory must be owner controlled.")


def _check_image(folder: Path, candidate: _Candidate) -> Payload:
    private_directory(folder)
    payload = load(folder / SUBTREE, candidate.component, candidate.build)
    mode, digest = _entry(folder, candidate.row["entry"])
    if (payload.digest != candidate.row["descriptorSha256"]
            or payload.descriptor["payloadManifestSha256"] != candidate.row["manifestSha256"]
            or payload.descriptor["source"] != candidate.row["source"]
            or mode != candidate.row["entryMode"] or digest != candidate.row["entrySha256"]
            or _read_record(folder / "build.json") != candidate.record
            or read_bytes(folder / "use.lock", limit=1) != b""):
        raise ValueError("The installed Driver image differs from the recorded candidate.")
    return payload


def _sync_image(folder: Path) -> None:
    def raise_error(error: OSError) -> None:
        raise error

    for directory, _, files in folder.walk(top_down=False, on_error=raise_error):
        for name in files:
            path = directory / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("The staged Driver image contains a special file.")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                if not os.path.samestat(info, os.fstat(fd)):
                    raise ValueError("The staged Driver image changed before it could be made durable.")
                os.fsync(fd)
            finally:
                os.close(fd)
        sync_directory(directory)


def _matches(path: Path, expected: bytes) -> bool:
    if not os.path.lexists(path):
        return False
    if read_bytes(path, limit=REGISTRATION_LIMIT) != expected:
        raise ValueError("The Driver registration conflicts with different recorded bytes.")
    return True


def _publish_directory(staged: Path, destination: Path) -> None:
    if os.path.lexists(destination):
        raise ValueError("A numbered Driver registration destination is already occupied.")
    staged.rename(destination)
    sync_directory(destination.parent)


def _register(folders: list[Path], registry: Path, check_candidate: CandidateCheck,
              blocked: DeploymentBlock, installed: dict[str, Payload] | None) -> dict[str, Payload]:
    candidates = [_candidate(folder, check_candidate) for folder in folders]
    rows = {candidate.component: candidate.row for candidate in candidates}
    if installed is not None:
        for candidate in candidates:
            if int(candidate.build, 16) <= int(installed[candidate.component].build, 16):
                raise ValueError(f"{candidate.component}@{candidate.build} is not newer than the installed Build.")
        for component in REGISTRATION_COMPONENTS:
            if component not in rows:
                build = installed[component].build
                _, rows[component] = _private_registration(registry, component, build, registry / component / build)
    receipt = canonical({"version": 1, "kind": "driver-build-registration", "scope": str(registry),
                         "builds": [rows[component] for component in REGISTRATION_COMPONENTS]})
    registration = sha256(receipt)
    shared = private_directory(registry / ".driver-qualification", create=True)
    receipts = private_directory(shared / "registrations", create=True)
    complete = receipts / (registration + ".json")
    pending = receipts / ("." + registration + ".pending.json")
    is_complete = _matches(complete, receipt)
    resuming = _matches(pending, receipt)
    payloads: dict[str, Payload] = {}
    missing_images: list[tuple[_Candidate, Path]] = []
    missing_records: list[tuple[bytes, Path]] = []

    for candidate in candidates:
        component, build = candidate.component, candidate.build
        parent = registry / component
        target = parent / build
        image = build_payload_directory(registry, component, build)
        high_water = browser_production_high_water(str(parent / ".stable-high-water"))
        number = int(build, 16)
        if number > high_water or (number != high_water and not (resuming or is_complete)):
            raise ValueError(f"{component}@{build} is not the current reserved stable Build.")
        if blocked(component, candidate.record):
            raise ValueError(f"{component}@{build} is blocked by the stable deployment ledger.")
        _stable_parent(image.parent)
        private_record = candidate.registry_record(registration)
        if os.path.lexists(target):
            private_directory(target)
            if (not (resuming or is_complete) or os.path.lexists(target / "build.json")
                    or not _matches(target / REGISTRATION_RECORD, private_record)):
                raise ValueError("A numbered Driver registration record is already occupied.")
        else:
            missing_records.append((private_record, target))
        if os.path.lexists(image):
            if not (resuming or is_complete):
                raise ValueError("A numbered Driver registration payload is already occupied.")
            payloads[component] = _check_image(image, candidate)
        else:
            missing_images.append((candidate, image))

    if is_complete:
        if missing_records or missing_images:
            raise ValueError("The committed Driver registration is missing an exact recorded artifact.")
        return payloads
    if not resuming:
        publish_bytes(pending, receipt, limit=REGISTRATION_LIMIT)

    with ExitStack() as staging:
        directories: list[tuple[Path, Path]] = []
        for candidate, image in missing_images:
            container = Path(staging.enter_context(tempfile.TemporaryDirectory(prefix=".driver-image-", dir=image.parent)))
            staged = container / "image"
            subprocess.run(["/usr/bin/ditto", str(candidate.folder), str(staged)], check=True)
            publish_bytes(staged / "use.lock", b"", limit=1)
            payload = _check_image(staged, candidate)
            _sync_image(staged)
            directories.append((staged, image))
            payloads[candidate.component] = Payload(image / SUBTREE, payload.descriptor, payload.digest)
        for raw, target in missing_records:
            container = Path(staging.enter_context(
                tempfile.TemporaryDirectory(prefix=".driver-record-", dir=target.parent)))
            staged = private_directory(container / "record", create=True)
            publish_bytes(staged / REGISTRATION_RECORD, raw, limit=REGISTRATION_LIMIT)
            directories.append((staged, target))
        for candidate in candidates:
            checked, _, _ = check_candidate(candidate.folder)
            if checked != candidate.record:
                raise ValueError("A Driver candidate record changed before registration publication.")
        for staged, target in directories:
            _publish_directory(staged, target)
        publish_bytes(complete, receipt, limit=REGISTRATION_LIMIT)
        pending.unlink()
        sync_directory(receipts)
    return payloads


def _with_writers(action: Callable[[], dict[str, Payload]], registry: Path,
                  components: tuple[str, ...]) -> dict[str, Payload]:
    if not components:
        return action()
    parent = registry / components[0]
    return with_mutation_lock(str(parent), lambda: _with_writers(action, registry, components[1:]))


def register_candidates(folders: list[Path], registry: Path, *,
                        installed: dict[str, Payload] | None = None) -> dict[str, Payload]:
    """Register the five fresh packages or a subset of the already installed Drivers."""
    home = Path.home()
    if registry != build_registry(home):
        raise ValueError("Driver stable registration requires the installed Build registry.")
    private_directory(registry)
    ordered = sorted(folders, key=lambda folder: folder.parent.name)
    components = tuple(folder.parent.name for folder in ordered)
    if installed is None:
        if components != REGISTRATION_COMPONENTS:
            raise ValueError("Register exactly one stable candidate for Arbol and for each of the four Drivers.")
    elif (not components or len(components) != len(set(components)) or not set(components).issubset(COMPONENTS)
          or set(installed) != set(REGISTRATION_COMPONENTS)):
        raise ValueError("Register one newer stable candidate for each selected installed Driver.")
    # The installed Build tool owns numbered candidate allocation and its locks.
    # The sealed provider and source CLI can read registration without those adapters.
    try:
        candidates = import_module(".candidates", __package__)
        promotion = import_module(".promotion", __package__)
        launcher = import_module(".launcher", __package__)
    except ImportError as error:
        raise ValueError("Use the installed Build tool to register Driver packages.") from error

    def blocked(component: str, record: Object) -> bool:
        failures = launcher.deployment_failures(str(registry), component)
        return launcher.deployment_failure(failures, record) is not None

    with ExitStack() as locks:
        for component, folder in zip(components, ordered, strict=True):
            run = candidates.promotion_run(physical(folder), home)
            locks.enter_context(candidates.candidate_lease(run, component, home))
        for component in components:
            private_directory(registry / component)
            locks.enter_context(promotion.stable_lock(home, component))
        return _with_writers(lambda: _register(ordered, registry, promotion.check_candidate, blocked, installed),
                             registry, components)


def install_command(arguments: list[str], registry: Path) -> int:
    if len(arguments) >= 2 and arguments[0] == "replace" and canonical_uuid(arguments[1]):
        from .driver_replacement import replace_installed

        result = replace_installed(registry, arguments[1], [Path(argument) for argument in arguments[2:]])
        write_all(1, json_line(result))
        return 0
    if len(arguments) != 7 or arguments[0] != "fresh" or not canonical_uuid(arguments[1]):
        raise ValueError("Use arbol-builds driver-install fresh <UUID> <five stable candidate folders> or "
                         "driver-install replace <UUID> [newer stable candidate folders ...].")
    payloads = register_candidates([Path(argument) for argument in arguments[2:]], registry)
    provider = payloads["arbol"]
    builds = [payloads[component].build for component in COMPONENTS]
    with pin_payloads(registry, list(payloads.values())):
        return subprocess.run([*provider.prefix, "--driver-install-fresh", str(registry), arguments[1], *builds],
                              check=False).returncode
