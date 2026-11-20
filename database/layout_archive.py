"""Publish and retire the legacy files covered by ARC-5."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from archive_volume import ARCHIVE_ROOT, BACKUPS, MERCURY, VOLUME_UUID, Archive, ArchiveUnavailable, require_archive
from recovery_release import RecoveryError, canonical, document, write_private

WORKING = frozenset(("database", "runtime", "app", "builds", "drivers", "native-resources",
                     "browser", "agents", "imports"))
LEGACY = frozenset((
    ".DS_Store", "cache", "config", "db", "deployments", "detached-views.json", "detached-views.lock", "development",
    "entity-search-cache.json", "entity-search-hotkey.lock", "ip", "knowledge-synchronization.json", "last-active-ui",
    "latest-chat-sessions-hotkey.lock", "logs", "organizations.json", "provider-retirement", "quick-input-hotkey.lock",
    "rebuild-and-restart.zsh", "rebuild-complete-notification.pending", "rebuilds", "recovery", "run", "selective-build",
    "trunks", "tray.lock", "ui-elma.lock", "ui-oaken.lock", "ui-seqoya.lock", "ui-switcher-hotkeys.lock", "ui-willo.lock",
))
RETIRED = "Arbol-retired-migration-20260923T110411"
DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
ENTRY = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
MANIFEST = "manifest.json"


@contextmanager
def opened(path: str | Path, flags: int, parent: int | None = None) -> Iterator[int]:
    fd = os.open(path, flags, mode=0o600, dir_fd=parent)
    try:
        yield fd
    finally:
        os.close(fd)


def identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def stamp(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (*identity(info), info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def selection(home: Path, kind: str) -> tuple[Path, dict[str, Path]]:
    support = home / "Library/Application Support"
    old = support / "Arbol"
    if kind == "backups":
        return BACKUPS / "pre-layout-arbol", {
            "application-support/Arbol/backups": old / "backups",
            "installation/backups": home / ".arbol/backups",
        }
    if os.path.lexists(old):
        with opened(old, DIR) as folder:
            unknown = set(os.listdir(folder)) - LEGACY - WORKING - {"backups"}
        if unknown:
            raise RecoveryError(f"Unclassified old installation entries: {', '.join(sorted(unknown))}.")
    sources = {f"Arbol/{name}": old / name for name in sorted(LEGACY)}
    sources[RETIRED] = support / RETIRED
    return ARCHIVE_ROOT / "legacy/arbol-1", sources


def describe(parent: int, name: str, destination: Path | None = None) -> dict[str, Any]:
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    entry: dict[str, Any] = {"mode": stat.S_IMODE(info.st_mode), "identity": list(identity(info))}
    if stat.S_ISDIR(info.st_mode):
        entry["type"] = "directory"
    elif stat.S_ISLNK(info.st_mode):
        target = os.readlink(name, dir_fd=parent)
        entry.update(type="link", target=target, size=info.st_size)
        if destination is not None:
            destination.symlink_to(target)
            os.lchmod(destination, entry["mode"])
    elif stat.S_ISREG(info.st_mode):
        with opened(name, ENTRY, parent) as fd, os.fdopen(os.dup(fd), "rb") as stream:
            if stamp(os.fstat(fd)) != stamp(info):
                raise RecoveryError("An archive source changed before it was read.")
            if destination is not None:
                with destination.open("xb") as output:
                    shutil.copyfileobj(stream, output)
                    output.flush()
                    os.fchmod(output.fileno(), entry["mode"])
                    os.fsync(output.fileno())
                stream.seek(0)
            entry.update(type="file", size=info.st_size, sha256=hashlib.file_digest(stream, "sha256").hexdigest())
    else:
        raise RecoveryError("An archive source contains a special file.")
    if stamp(os.stat(name, dir_fd=parent, follow_symlinks=False)) != stamp(info):
        raise RecoveryError("An archive source changed while it was read.")
    return entry


def walk(parent: int, name: str, key: str, device: int, result: dict[str, Any],
         destination: Path | None = None) -> None:
    entry = describe(parent, name, destination)
    if entry["identity"][0] != device:
        raise RecoveryError("An archive source crosses a volume boundary.")
    result[key] = entry
    if entry["type"] != "directory":
        return
    if destination is not None:
        destination.mkdir(mode=0o700)
    with opened(name, DIR, parent) as folder:
        before = stamp(os.fstat(folder))
        if list(before[:2]) != entry["identity"]:
            raise RecoveryError("An archive source directory was replaced.")
        for child in sorted(os.listdir(folder)):
            walk(folder, child, f"{key}/{child}", device, result, None if destination is None else destination / child)
        if stamp(os.fstat(folder)) != before:
            raise RecoveryError("An archive source directory changed during traversal.")
    if destination is not None:
        with opened(destination, DIR) as output:
            os.fchmod(output, entry["mode"])
            os.fsync(output)


def inventory(sources: dict[str, Path], output: Path | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, path in sources.items():
        if not os.path.lexists(path):
            continue
        destination = None if output is None else output / key
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with opened(path.parent, DIR) as parent:
            walk(parent, path.name, key, os.fstat(parent).st_dev, result, destination)
    return result


def content(entries: dict[str, Any]) -> dict[str, Any]:
    return {name: {field: value for field, value in entry.items() if field != "identity"}
            for name, entry in entries.items()}


def archive_sources(output: Path, sources: dict[str, Path]) -> dict[str, Path]:
    return {key: output / "files" / key for key in sources}


def ensure_unused(sources: dict[str, Path]) -> None:
    run = subprocess.run(["/usr/sbin/lsof", "-nP", "-Fn", "-u", str(os.getuid())], capture_output=True, timeout=45)
    if run.returncode not in (0, 1) or run.stderr:
        raise RecoveryError("Could not verify the owner process file inventory.")
    this_process = f"p{os.getpid()}".encode()
    own = False
    for raw in run.stdout.splitlines():
        if raw.startswith(b"p"):
            own = raw == this_process
        elif raw.startswith(b"n/") and not own:
            path = Path(os.fsdecode(raw[1:]).removesuffix(" (deleted)"))
            if any(path.is_relative_to(source) for source in sources.values()):
                raise RecoveryError("A running process still uses an archive source.")


def publish(archive: Archive, destination: Path, kind: str, sources: dict[str, Path]) -> dict[str, Any]:
    archive.path(destination, allow_missing=True)
    if os.path.lexists(destination):
        raise RecoveryError("An archive already occupies the publication path.")
    ensure_unused(sources)
    original = inventory(sources)
    if not original:
        raise RecoveryError("No old files were found for this archive.")
    with tempfile.TemporaryDirectory(prefix=".layout-archive-", dir=destination.parent) as scratch:
        payload = Path(scratch) / "output"
        payload.mkdir(mode=0o700)
        copied = inventory(sources, payload / "files")
        if copied != original or content(inventory(archive_sources(payload, sources))) != content(original):
            raise RecoveryError("The independent archive readback differs from its original listing.")
        value = {"format": 1, "kind": kind, "entries": original}
        write_private(payload / MANIFEST, value)
        archive.path(payload)
        archive.path(destination, allow_missing=True)
        if os.path.lexists(destination):
            raise RecoveryError("An archive already occupies the publication path.")
        payload.rename(destination)
        with opened(destination.parent, DIR) as parent:
            os.fsync(parent)
    return value


def check_archive(archive: Archive, destination: Path, kind: str, sources: dict[str, Path]) -> dict[str, Any]:
    value = document(archive.path(destination / MANIFEST))
    if value.get("format") != 1 or value.get("kind") != kind or not isinstance(value.get("entries"), dict):
        raise RecoveryError("The published archive manifest is invalid.")
    if content(inventory(archive_sources(destination, sources))) != content(value["entries"]):
        raise RecoveryError("The published archive no longer matches its manifest.")
    return value


def keep_manifest(private: Path, kind: str, value: dict[str, Any]) -> None:
    keep = private / f"{kind}-manifest.json"
    if os.path.lexists(keep):
        if keep.is_symlink() or keep.read_bytes() != canonical(value):
            raise RecoveryError("The internal manifest differs from the published record.")
    else:
        write_private(keep, value)
        with opened(private, DIR) as parent:
            os.fsync(parent)


def remove_entry(parent: int, name: str, key: str, expected: dict[str, Any]) -> None:
    saved = expected.get(key)
    if saved is None or describe(parent, name) != saved:
        raise RecoveryError("An unrecorded or changed original appeared during retirement.")
    if saved["type"] != "directory":
        os.unlink(name, dir_fd=parent)
        return
    with opened(name, DIR, parent) as folder:
        if list(identity(os.fstat(folder))) != saved["identity"]:
            raise RecoveryError("An original directory was replaced.")
        for child in sorted(os.listdir(folder)):
            remove_entry(folder, child, f"{key}/{child}", expected)
        os.fsync(folder)
    if describe(parent, name) != saved:
        raise RecoveryError("An original directory was replaced.")
    os.rmdir(name, dir_fd=parent)


def retire(archive: Archive, destination: Path, kind: str, sources: dict[str, Path], private: Path) -> int:
    value = check_archive(archive, destination, kind, sources)
    keep_manifest(private, kind, value)
    ensure_unused(sources)
    expected = value["entries"]
    remaining = inventory(sources)
    # Interrupted removals leave a subset with its original file identities.
    if any(expected.get(key) != entry for key, entry in remaining.items()):
        raise RecoveryError("An original entry differs from the verified archive.")
    for key, path in sources.items():
        if key in remaining:
            manifest = archive.path(destination / MANIFEST)
            if manifest.read_bytes() != canonical(value):
                raise RecoveryError("The published archive manifest changed during retirement.")
            with opened(path.parent, DIR) as parent:
                remove_entry(parent, path.name, key, expected)
                os.fsync(parent)
    return len(remaining)


def remove_empty_old_root(home: Path) -> bool:
    old = home / "Library/Application Support/Arbol"
    if not os.path.lexists(old):
        return True
    with opened(old.parent, DIR) as parent, opened(old.name, DIR, parent) as folder:
        if os.listdir(folder):
            return False
        ensure_unused({"old installation": old})
        current = os.stat(old.name, dir_fd=parent, follow_symlinks=False)
        if identity(current) != identity(os.fstat(folder)):
            raise RecoveryError("The old installation directory was replaced.")
        os.rmdir(old.name, dir_fd=parent)
        os.fsync(parent)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("legacy", "backups"))
    parser.add_argument("action", choices=("publish", "verify", "remove"))
    args = parser.parse_args()
    try:
        archive = require_archive()
        home = Path.home()
        destination, sources = selection(home, args.kind)
        private = home / ".arbol/layout-retirement"
        volume = plistlib.loads(subprocess.check_output(
            ["/usr/sbin/diskutil", "info", "-plist", str(MERCURY)], timeout=10,
        ))
        if volume.get("VolumeUUID") != VOLUME_UUID or volume.get("FileVault") is not True:
            raise ArchiveUnavailable("Mercury must have FileVault enabled for legacy credentials.")
        if args.kind == "legacy" and not os.path.lexists(destination.parent) and args.action == "publish":
            archive.path(destination.parent, allow_missing=True).mkdir(mode=0o700)
        archive.path(destination.parent)
        private.mkdir(mode=0o700, exist_ok=True)
        with opened(private, DIR) as folder:
            info = os.fstat(folder)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise RecoveryError("Retirement evidence needs a private internal directory.")
            with opened("archive.lock", os.O_CREAT | os.O_NOFOLLOW | os.O_RDWR, folder) as fd:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result: dict[str, Any] = {"status": "ready", "action": args.action, "archive": str(destination)}
                if args.action == "remove":
                    result["entries"] = retire(archive, destination, args.kind, sources, private)
                    result["oldRootAbsent"] = remove_empty_old_root(home)
                else:
                    value = (publish(archive, destination, args.kind, sources) if args.action == "publish"
                             else check_archive(archive, destination, args.kind, sources))
                    keep_manifest(private, args.kind, value)
                    result["entries"] = len(value["entries"])
        print(json.dumps(result))
        return 0
    except (ArchiveUnavailable, RecoveryError, OSError, ValueError, subprocess.SubprocessError) as error:
        code = error.code if isinstance(error, ArchiveUnavailable) else "archive_refused"
        print(json.dumps({"status": code, "message": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
