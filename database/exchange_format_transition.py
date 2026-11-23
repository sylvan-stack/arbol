"""Read-only verification of the managed Exchange deployment.

The operator composes :func:`verified_deployment` with the exclusive reopen
procedure. It must separately verify the recovery and release selection.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from recovery_release import RecoveryError, digest, selected_entry, verify_release

from arbol_installation.exchange_release import (
    RECEIPT,
    authorization_from_release,
    pairs,
    payload_digest,
    verify_authorization,
)
from arbol_installation.paths import build_registry

ROLES = ("arbol", "arbol-trunk/steady", "arbol-trunk/trivial")
NUMBER = re.compile(r"[1-9a-f][0-9a-f]*\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class VerifiedDeployment:
    release: str
    manifest: str
    inventory: dict[str, Any]


def physical(path: Path) -> None:
    info = path.lstat()
    if (path.resolve(strict=True) != path or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid() or info.st_mode & 0o022):
        raise RecoveryError("A managed deployment directory is not physical and owner controlled.")


def guarded_file(path: Path, stack: ExitStack, mode: int, *, install: bool = False) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    stack.callback(os.close, fd)
    before = os.fstat(fd)
    named = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) not in ((0o600, 0o644) if install else (0o600,))
            or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)):
        raise RecoveryError("A managed deployment lock is unsafe.")
    fcntl.flock(fd, mode | fcntl.LOCK_NB)
    named = path.lstat()
    if (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino):
        raise RecoveryError("A managed deployment lock was replaced.")


def read_json(path: Path, expected: str) -> dict[str, Any]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 1024 * 1024):
            raise RecoveryError("The deployment attachment is not a bounded private file.")
        raw = os.read(fd, 1024 * 1024 + 1)
        end, named = os.fstat(fd), path.lstat()
        if (len(raw) != info.st_size or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                != (end.st_dev, end.st_ino, end.st_size, end.st_mtime_ns)
                or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
            raise RecoveryError("The deployment attachment changed while reading.")
    finally:
        os.close(fd)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RecoveryError("A release input differs from its independently approved digest.")
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if not isinstance(value, dict):
        raise RecoveryError("The deployment attachment is not an object.")
    return value


def executable_inventory(home: Path, root: Path) -> dict[str, str]:
    """Inventory every executable and symlink without following directory links."""
    result: dict[str, str] = {}
    def fail(error: OSError) -> None:
        raise RecoveryError("A managed executable tree could not be completely read.") from error

    for current, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        base = Path(current)
        physical(base)
        for name in sorted(dirs + files):
            path = base / name
            info = path.lstat()
            relative = path.relative_to(home).as_posix()
            if stat.S_ISLNK(info.st_mode):
                result[relative] = "link:" + os.readlink(path)
                if name in dirs:
                    dirs.remove(name)
            elif stat.S_ISREG(info.st_mode):
                if info.st_uid != os.getuid() or info.st_nlink != 1:
                    raise RecoveryError("A managed executable tree contains an unsafe file.")
                if info.st_mode & 0o111:
                    result[relative] = digest(path)
            elif not stat.S_ISDIR(info.st_mode):
                raise RecoveryError("A managed executable tree contains a special file.")
    return result


def attachment(release_dir: Path, record: dict[str, Any], name: str, expected: str) -> dict[str, Any]:
    if (SHA.fullmatch(expected) is None or name not in record.get("inputs", [])
            or "/" in name or name in (".", "..")):
        raise RecoveryError("A pinned release input is missing.")
    path = release_dir / "inputs" / name
    return read_json(path, expected)


@contextmanager
def verified_deployment(release_dir: Path, release: str, manifest_sha256: str,
                        refusal_sha256: str | None = None) -> Iterator[VerifiedDeployment]:
    """Verify a pinned deployment under locks held until the caller exits.

    Only independently approved attachment hashes are accepted as inputs; a
    verified archive alone is not independent approval. The caller must also
    hold the admission locks when using this for the authoritative state write.
    """
    from archive_volume import require_archive

    archive = require_archive()
    record, actual = verify_release(release_dir, release, archive=archive)
    manifest = attachment(release_dir, record, "exchange-deployment.json", manifest_sha256)
    role = record.get("exchangeTransition", {}).get("role")
    if role not in ("prior", "successor"):
        raise RecoveryError("The archived release has no valid Exchange transition role.")
    if role == "successor":
        if not isinstance(refusal_sha256, str):
            raise RecoveryError("The successor requires independently approved refusal evidence.")
        refusal = attachment(release_dir, record, "exchange-legacy-refusal.json", refusal_sha256)
    else:
        if refusal_sha256 is not None:
            raise RecoveryError("The prior deployment must not claim successor refusal evidence.")
        refusal = None
    if (set(manifest) != {"format", "payloads", "executables", "routes", "toolSha256", "refusalSha256"}
            or type(manifest["format"]) is not int or manifest["format"] != 1
            or manifest["refusalSha256"] != refusal_sha256
            or not isinstance(manifest["payloads"], list) or not isinstance(manifest["executables"], dict)
            or not isinstance(manifest["routes"], dict) or not isinstance(manifest["toolSha256"], str)
            or SHA.fullmatch(manifest["toolSha256"]) is None):
        raise RecoveryError("The approved deployment manifest is invalid.")
    if refusal is not None and (set(refusal) != {"format", "kind", "independent", "isolated", "result", "selected", "payloads", "executables"}
            or type(refusal["format"]) is not int or refusal["format"] != 1
            or refusal["kind"] != "exchange-legacy-direct-refusal"
            or refusal["independent"] is not True or refusal["isolated"] is not True or refusal["result"] != "passed"
            or not isinstance(refusal["payloads"], list) or not isinstance(refusal["executables"], dict)):
        raise RecoveryError("The independent legacy refusal receipt is invalid.")
    home = Path.home()
    registry = build_registry(home)
    stable = home / ".local/lib/sylvan-stack/arbol/stable"
    apps = home / "Applications/Arbol/bin"
    aliases = home / ".local/bin"
    tool = home / ".local/lib/sylvan-stack/arbol/bin/.arbol-builds"
    with ExitStack() as stack:
        for root in (home, registry, stable, apps, aliases, tool):
            physical(root)
        guarded_file(tool / ".install.lock", stack, fcntl.LOCK_SH, install=True)
        for role in ROLES:
            physical(registry / role)
            physical(stable / role)
            guarded_file(registry / role / ".stable-promotion.lock", stack, fcntl.LOCK_SH)
        payloads: list[dict[str, str]] = []
        executables: dict[str, str] = {}
        for role in ROLES:
            for base, installed in ((stable / role, True), (registry / role, False)):
                for path in sorted(base.iterdir()):
                    if not NUMBER.fullmatch(path.name):
                        if path.name in (".uses", ".writers") and not installed:
                            continue
                        if path.is_dir() and not path.is_symlink():
                            if executable_inventory(home, path):
                                raise RecoveryError("An unknown managed path contains executable entries.")
                        elif path.is_symlink() or (path.is_file() and path.stat().st_mode & 0o111):
                            raise RecoveryError("An unknown managed executable path is present.")
                        continue
                    physical(path)
                    if installed:
                        guarded_file(path / "use.lock", stack, fcntl.LOCK_SH)
                        payloads.append({"role": role, "build": path.name,
                                         "path": path.relative_to(home).as_posix(),
                                         "sha256": payload_digest(path)})
                    else:
                        found = executable_inventory(home, path)
                        if found:
                            guarded_file(base / ".uses" / path.name, stack, fcntl.LOCK_SH)
                            executables.update(found)
        routes: dict[str, str] = {}
        for folder in (apps, aliases):
            for path in sorted(folder.iterdir()):
                if not (path.name in ("arbol", "arbol-exchanges", "arbol-trunk", "arbol-builds")
                        or path.name.startswith("arbol-trunk-")):
                    continue
                key = path.relative_to(home).as_posix()
                if path.is_symlink():
                    routes[key] = "link:" + os.readlink(path)
                else:
                    raw, mode = selected_entry(path)
                    routes[key] = f"{hashlib.sha256(raw).hexdigest()}:{mode:o}"
        if (payloads != manifest["payloads"] or executables != manifest["executables"]
                or routes != manifest["routes"] or payload_digest(tool) != manifest["toolSha256"]):
            raise RecoveryError("The managed deployment differs from the approved complete inventory.")
        selected = {(row["component"], row["build"]) for row in record["builds"]}
        for build in record["builds"]:
            matches = [row for row in payloads if (row["role"], row["build"]) == (build["component"], build["build"])]
            if len(matches) != 1 or matches[0]["sha256"] != build["evidence"]["installedFilesSha256"]:
                raise RecoveryError("An archived selected payload does not match the installed bytes.")
        for item in record["exchangeTransition"]["selected"]:
            for entry in item["entries"]:
                key = (apps / entry["name"]).relative_to(home).as_posix()
                if routes.get(key) != f"{entry['sha256']}:{entry['mode']:o}":
                    raise RecoveryError("An archived stable entry differs from the installed wrapper.")
                if digest(Path(entry["interpreter"]).resolve(strict=True)) != entry["interpreterSha256"]:
                    raise RecoveryError("The installed wrapper interpreter differs from the archived identity.")
        if refusal is not None:
            chosen = [row for row in payloads if (row["role"], row["build"]) in selected]
            if refusal["selected"] != chosen:
                raise RecoveryError("The refusal receipt is not bound to the exact selected successor.")
            legacy = [row for row in payloads if (row["role"], row["build"]) not in selected]
            if refusal["payloads"] != legacy or refusal["executables"] != executables:
                raise RecoveryError("The legacy direct-writer refusal evidence does not cover the retained payloads.")
        yield VerifiedDeployment(actual, manifest_sha256, manifest)


# Qualification labels are literal and are bound to each archived candidate.
TRUNK_JOURNEYS = {"format2-lifecycle", "legacy-drain", "pruning"}
BACKEND_JOURNEYS = {"note-replay", "interruption-rollback"}


def request(path: Path) -> dict[str, Any]:
    """Read a bounded owner-only request, rejecting duplicate or extra fields."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 65536):
            raise RecoveryError("The operation request is not a bounded private file.")
        raw = os.read(fd, 65537)
        after, named = os.fstat(fd), path.lstat()
        if (len(raw) != info.st_size or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
            raise RecoveryError("The operation request changed while reading.")
    finally:
        os.close(fd)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    keys = {"format", "source", "schema", "session", "historical", "prior", "successor",
            "snapshot", "restore", "qualificationSha256"}
    if (not isinstance(value, dict) or set(value) != keys or type(value["format"]) is not int
            or value["format"] != 1 or not isinstance(value["source"], dict)
            or not isinstance(value["schema"], dict)
            or set(value["schema"]) != {"revision", "compatibilityVersion"}
            or any(type(x) is not int or x < 1 for x in value["schema"].values())
            or not isinstance(value["session"], str) or re.fullmatch(r"[0-9a-f]{32}", value["session"]) is None
            or not isinstance(value["qualificationSha256"], str)
            or SHA.fullmatch(value["qualificationSha256"]) is None):
        raise RecoveryError("The operation request is invalid.")
    for key in ("historical", "prior", "successor"):
        item = value[key]
        expected = {"directory", "sha256"} if key == "historical" else {"directory", "sha256", "manifestSha256"}
        if key == "successor":
            expected.add("refusalSha256")
        if (not isinstance(item, dict) or set(item) != expected
                or not isinstance(item["directory"], str) or not Path(item["directory"]).is_absolute()
                or any(not isinstance(item[k], str) or SHA.fullmatch(item[k]) is None for k in expected - {"directory"})):
            raise RecoveryError("The operation request has invalid release pins.")
    if any(not isinstance(value[k], str) or not Path(value[k]).is_absolute() for k in ("snapshot", "restore")):
        raise RecoveryError("The operation request has invalid recovery paths.")
    from arbol_installation.admission import checked_source
    value["source"] = checked_source(value["source"])
    return cast(dict[str, Any], value)


def verify_inputs(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify archive membership, independent journeys and same-session recovery."""
    from archive_volume import require_archive
    from recovery import verify_recovery

    archive = require_archive()
    records: dict[str, dict[str, Any]] = {}
    for name in ("historical", "prior", "successor"):
        item = spec[name]
        records[name], _ = verify_release(Path(item["directory"]), item["sha256"], archive=archive)
    for name in ("prior", "successor"):
        transition = records[name].get("exchangeTransition", {})
        if (transition.get("role") != name or transition.get("admissionRelease") != spec["historical"]["sha256"]
                or transition.get("admissionReleaseDirectory") != spec["historical"]["directory"]):
            raise RecoveryError("The release roles or historical admission evidence differ.")
    qualification = records["successor"]["exchangeTransition"]["qualification"]
    if qualification["sha256"] != spec["qualificationSha256"]:
        raise RecoveryError("The successor qualification is not independently approved.")
    qualified = read_json(Path(spec["successor"]["directory"]) / qualification["path"], spec["qualificationSha256"])
    builds = {row["component"]: row["build"] for row in records["successor"]["builds"]}
    journeys = qualified.get("journeys")
    if not isinstance(journeys, list):
        raise RecoveryError("The successor qualification lacks required journeys.")
    passed = {(row["component"], row["build"], row["name"]) for row in journeys
              if isinstance(row, dict) and row.get("passed") is True
              and all(isinstance(row.get(k), str) for k in ("component", "build", "name"))}
    required = {(role, builds[role], name) for role in ("arbol-trunk/steady", "arbol-trunk/trivial")
                for name in TRUNK_JOURNEYS}
    required |= {("arbol", builds["arbol"], name) for name in BACKEND_JOURNEYS}
    if not required <= passed:
        raise RecoveryError("The approved qualification lacks required passing journeys.")
    verify_recovery(Path(spec["snapshot"]), Path(spec["restore"]), source=spec["source"], schema=spec["schema"],
                    release_sha256=spec["prior"]["sha256"], maintenance_session=spec["session"])
    return records["prior"], records["successor"]


def stage(folder: int, data: bytes, release: str) -> str:
    """Atomically replace only the compact owner-only authorization."""
    checksum = hashlib.sha256(data).hexdigest()
    name = ".exchange-authorization-" + uuid4().hex
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, RECEIPT, src_dir_fd=folder, dst_dir_fd=folder)
        os.fsync(folder)
    finally:
        try:
            os.unlink(name, dir_fd=folder)
        except FileNotFoundError:
            pass
    verify_authorization(folder, checksum, release)
    return checksum


def operate(spec: dict[str, Any], command: Literal["prepare", "status", "apply", "rollback"]) -> dict[str, str]:
    from migrate_schema import database_target

    from arbol_backend.exchange_context import context
    from arbol_backend.exchange_drain import GuardedSelection, reopen
    from arbol_installation.admission import GATE, directory, lock, read_state, runtime_folder

    role = "prior" if command == "rollback" else "successor"
    item = spec[role]
    with directory(runtime_folder()) as folder, lock(folder, GATE, fcntl.LOCK_SH):
        state = read_state(folder)
        if state.source != spec["source"]:
            raise RecoveryError("Admission belongs to a different database target.")
        if state.phase == "normal":
            if state.release != item["sha256"]:
                raise RecoveryError("A different release is already active.")
            if state.exchange_authorization is not None:
                verify_authorization(folder, state.exchange_authorization, state.release)
            elif role == "successor":
                raise RecoveryError("The active successor lacks authorization.")
            return {"status": "active", "release": item["sha256"]}
        if state.session != spec["session"] or (state.phase != "exclusive" and command not in ("prepare", "status")):
            raise RecoveryError("The operation requires the same maintenance session and exclusive apply.")
        if command == "status":
            return {"status": state.phase, "release": state.release or ""}
    prior, successor = verify_inputs(spec)
    selected_record = prior if role == "prior" else successor
    package = (Path.home() / ".local/lib/sylvan-stack/arbol/stable/arbol"
               / next(row["build"] for row in selected_record["builds"] if row["component"] == "arbol"))
    ctx = context(package, {})
    target = database_target(str(spec["source"]["database"]))
    with target.connect() as connection:
        if target.identity(connection) != spec["source"]:
            raise RecoveryError("The live database identity differs from the request.")
    if command == "prepare":
        with verified_deployment(Path(item["directory"]), item["sha256"], item["manifestSha256"],
                                 item["refusalSha256"]):
            return {"status": "prepared", "release": item["sha256"]}

    @contextmanager
    def selection(folder: int, current: Any) -> Iterator[GuardedSelection]:
        if current.session != spec["session"] or current.source != spec["source"]:
            raise RecoveryError("The exclusive session changed.")
        if current.exchange_authorization is None:
            if current.release != spec["historical"]["sha256"]:
                raise RecoveryError("The historical admission release changed.")
        elif role == "prior":
            raise RecoveryError("Prior rollback is unavailable after successor activation.")
        else:
            verify_authorization(folder, current.exchange_authorization, current.release)
            if current.release != item["sha256"]:
                raise RecoveryError("Forward recovery requires the same approved successor.")
        checked_prior, checked_successor = verify_inputs(spec)
        if checked_prior != prior or checked_successor != successor:
            raise RecoveryError("The archived release evidence changed.")
        with verified_deployment(Path(item["directory"]), item["sha256"], item["manifestSha256"],
                                 item.get("refusalSha256")):
            authorization = None
            if role == "successor":
                data = authorization_from_release(checked_successor, item["sha256"])
                authorization = stage(folder, data, item["sha256"])
            yield GuardedSelection(cast(Literal["prior", "successor"], role), spec["source"], spec["session"],
                                   current.generation, current.release, item["sha256"], authorization)

    reopen(ctx, spec["source"], spec["session"], release=item["sha256"], schema=spec["schema"],
           verify_selection=selection)
    return {"status": "reopened", "release": item["sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "status", "apply", "rollback"))
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = operate(request(args.request), args.command)
    except Exception:
        print("Exchange transition refused: required evidence or the maintenance session could not be verified.",
              file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
