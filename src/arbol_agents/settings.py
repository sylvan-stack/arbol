"""Settings snapshots and whole-file changes for the hook installer."""

from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path


class SettingsError(ValueError):
    """The user's settings could not be read or safely updated."""


def write_complete(path: Path, contents: bytes, mode: int, *, first_only: bool = False) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        if first_only:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise SettingsError(f"Backup is not a regular file: {path}") from None
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class SettingsFile:
    path: Path
    contents: bytes | None
    mode: int = 0o600

    @classmethod
    def read(cls, path: Path) -> SettingsFile:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                mode = os.fstat(stream.fileno()).st_mode
                if not stat.S_ISREG(mode):
                    raise SettingsError(f"Settings are not a regular file: {path}")
                return cls(path, stream.read(), stat.S_IMODE(mode))
        except FileNotFoundError:
            return cls(path, None)
        except OSError:
            raise SettingsError(f"Could not read settings: {path}") from None

    def verify_current(self) -> None:
        if self != self.read(self.path):
            raise SettingsError(f"Settings changed while editing: {self.path}")

    def backup(self) -> None:
        self.verify_current()
        if self.contents is not None:
            backup = self.path.with_name(f"{self.path.name}.before-arbol-agents")
            write_complete(backup, self.contents, 0o600, first_only=True)

    def save(self, contents: bytes) -> None:
        if contents != self.contents:
            self.backup()
            self.verify_current()
            write_complete(self.path, contents, self.mode)

    def restore(self, contents_written: bytes) -> None:
        if self.read(self.path).contents != contents_written:
            raise SettingsError(f"Settings changed before rollback: {self.path}")
        if self.contents is None:
            self.path.unlink()
        else:
            write_complete(self.path, self.contents, self.mode)
