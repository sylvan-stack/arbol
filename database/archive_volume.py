"""Check the installed Arbol recovery archive before entering maintenance (ARC-5)."""

from __future__ import annotations

import argparse
import json
import plistlib
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

MERCURY = Path("/Volumes/Mercury")
VOLUME_UUID = "AE1E97B8-CE93-4019-B6DC-21482165C3F2"
ARCHIVE_ROOT = MERCURY / "Arbol"
BACKUPS = ARCHIVE_ROOT / "backups"


class ArchiveUnavailable(ValueError):
    code = "archive_unavailable"


@dataclass(frozen=True)
class Archive:
    device: int

    def path(self, path: Path, *, allow_missing: bool = False) -> Path:
        """Verify each component on Mercury. Only the final component may be missing."""
        path = path.absolute()
        if not path.is_relative_to(ARCHIVE_ROOT) or ".." in path.parts:
            raise ArchiveUnavailable("The archive path must be below /Volumes/Mercury/Arbol.")
        parts = path.relative_to(ARCHIVE_ROOT).parts
        current = MERCURY
        try:
            mount = current.lstat()
            if not stat.S_ISDIR(mount.st_mode) or mount.st_dev != self.device or not current.is_mount():
                raise ArchiveUnavailable("The verified Mercury mount is no longer available.")
            components = (ARCHIVE_ROOT.name, *parts)
            for index, part in enumerate(components):
                current /= part
                leaf = index == len(components) - 1
                try:
                    info = current.lstat()
                except FileNotFoundError:
                    if allow_missing and leaf and parts:
                        return current
                    raise
                directory = stat.S_ISDIR(info.st_mode)
                if info.st_dev != self.device or not (directory or (leaf and parts and stat.S_ISREG(info.st_mode))):
                    raise ArchiveUnavailable("The archive path crosses a volume or contains an unsafe entry.")
        except OSError as error:
            raise ArchiveUnavailable("The required directory or file on Mercury is unavailable.") from error
        return current

    def backup_path(self, path: Path, *, allow_missing: bool = False) -> Path:
        absolute = path.absolute()
        if not absolute.is_relative_to(BACKUPS):
            raise ArchiveUnavailable("Recovery files must be below /Volumes/Mercury/Arbol/backups.")
        return self.path(absolute, allow_missing=allow_missing)


def require_archive() -> Archive:
    try:
        result = subprocess.run(
            ["/usr/sbin/diskutil", "info", "-plist", str(MERCURY)],
            stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=10,
        )
        info = plistlib.loads(result.stdout)
        if (not isinstance(info, dict) or info.get("MountPoint") != str(MERCURY)
                or info.get("VolumeUUID") != VOLUME_UUID):
            raise ArchiveUnavailable("Mount the expected Mercury volume at /Volumes/Mercury.")
        archive = Archive(MERCURY.lstat().st_dev)
        archive.path(ARCHIVE_ROOT)
        return archive
    except ArchiveUnavailable:
        raise
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise ArchiveUnavailable("Mount Mercury and make its Arbol archive root available.") from error


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        require_archive()
    except ArchiveUnavailable as error:
        print(json.dumps({"status": error.code, "message": str(error)}))
        return 1
    print(json.dumps({"status": "ready", "archive": str(ARCHIVE_ROOT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
