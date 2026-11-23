"""Read-only verification of the managed Exchange deployment.

The operator composes :func:`verified_deployment` with the exclusive reopen
procedure. It must separately verify the recovery and release selection.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from recovery_release import RecoveryError, digest, selected_entry, verify_release

from arbol_installation.exchange_release import pairs, payload_digest
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


def guarded_file(path: Path, stack: ExitStack, mode: int) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    stack.callback(os.close, fd)
    before = os.fstat(fd)
    named = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)):
        raise RecoveryError("A managed deployment lock is unsafe.")
    fcntl.flock(fd, mode | fcntl.LOCK_NB)


def read_json(path: Path) -> dict[str, Any]:
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
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if not isinstance(value, dict):
        raise RecoveryError("The deployment attachment is not an object.")
    return value


def executable_inventory(home: Path, root: Path) -> dict[str, str]:
    """Inventory every executable and symlink without following directory links."""
    result: dict[str, str] = {}
    for current, dirs, files in os.walk(root, followlinks=False):
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
    if digest(path) != expected:
        raise RecoveryError("A release input differs from its independently approved digest.")
    return read_json(path)


@contextmanager
def verified_deployment(release_dir: Path, release: str, manifest_sha256: str,
                        refusal_sha256: str) -> Iterator[VerifiedDeployment]:
    """Verify a pinned deployment under locks held until the caller exits.

    Only independently approved attachment hashes are accepted as inputs; a
    verified archive alone is not independent approval. The caller must also
    hold the admission locks when using this for the authoritative state write.
    """
    from archive_volume import require_archive

    archive = require_archive()
    record, actual = verify_release(release_dir, release, archive=archive)
    manifest = attachment(release_dir, record, "exchange-deployment.json", manifest_sha256)
    refusal = attachment(release_dir, record, "exchange-legacy-refusal.json", refusal_sha256)
    if (set(manifest) != {"format", "payloads", "executables", "routes", "toolSha256", "refusalSha256"}
            or type(manifest["format"]) is not int or manifest["format"] != 1
            or manifest["refusalSha256"] != refusal_sha256
            or not isinstance(manifest["payloads"], list) or not isinstance(manifest["executables"], dict)
            or not isinstance(manifest["routes"], dict) or not isinstance(manifest["toolSha256"], str)
            or SHA.fullmatch(manifest["toolSha256"]) is None):
        raise RecoveryError("The approved deployment manifest is invalid.")
    if (set(refusal) != {"format", "kind", "independent", "isolated", "result", "selected", "payloads", "executables"}
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
    tool = apps / ".arbol-builds"
    with ExitStack() as stack:
        for root in (home, registry, stable, apps, aliases, tool):
            physical(root)
        guarded_file(tool / ".install.lock", stack, fcntl.LOCK_SH)
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
        chosen = [row for row in payloads if (row["role"], row["build"]) in selected]
        if refusal["selected"] != chosen:
            raise RecoveryError("The refusal receipt is not bound to the exact selected successor.")
        legacy = [row for row in payloads if (row["role"], row["build"]) not in selected]
        legacy_entries = {path: value for path, value in executables.items()
                          if any(path.startswith((registry / role / number).relative_to(home).as_posix() + "/")
                                 for role in ROLES for number in {
                                     p.name for p in (registry / role).iterdir() if NUMBER.fullmatch(p.name)
                                 } if (role, number) not in selected)}
        if refusal["payloads"] != legacy or refusal["executables"] != legacy_entries:
            raise RecoveryError("The legacy direct-writer refusal evidence does not cover the retained payloads.")
        yield VerifiedDeployment(actual, manifest_sha256, manifest)
