"""Private, atomic request files, with cleanup limited to the inode acquired here."""

from __future__ import annotations

import json
import os
import re
import stat
import time
from dataclasses import dataclass
from uuid import uuid4

from .bridge import MAX_LINE, Error, Params, uuid_id
from .model import Identity

NAME = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
OWN_NAME = re.compile(rf"(?:{NAME}\.json|\.{NAME}\.{NAME}\.tmp)")


def private(info: os.stat_result) -> bool:
    return (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)


@dataclass
class Request:
    folder: int
    name: str
    inode: tuple[int, int]
    path: str

    def remove(self) -> None:
        try:
            info = os.stat(self.name, dir_fd=self.folder, follow_symlinks=False)
            if (info.st_dev, info.st_ino) == self.inode and private(info):
                os.unlink(self.name, dir_fd=self.folder)
        except FileNotFoundError:
            pass
        finally:
            os.close(self.folder)


class Requests:
    def __init__(self, identity: Identity) -> None:
        self.identity = identity

    def directory(self, *, create: bool = True) -> int:
        root = os.open(self.identity.folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if create:
                try:
                    os.mkdir("requests", 0o700, dir_fd=root)
                except FileExistsError:
                    pass
            folder = os.open("requests", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
            info = os.fstat(folder)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                os.close(folder)
                raise Error("invalid_input")
            return folder
        finally:
            os.close(root)

    def write(self, exchange: str, request: Params) -> Request:
        uuid_id(exchange)
        folder: int | None = None
        temporary = "." + exchange + "." + str(uuid4()) + ".tmp"
        made = False
        try:
            data = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                              allow_nan=False).encode("utf-8") + b"\n"
            if len(data) > MAX_LINE:
                raise Error("invalid_input")
            folder = self.directory()
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=folder)
            made = True
            try:
                os.fchmod(descriptor, 0o600)
                pending = memoryview(data)
                while pending:
                    written = os.write(descriptor, pending)
                    if written == 0:
                        raise OSError("Request write stopped.")
                    pending = pending[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            name = exchange + ".json"
            try:
                os.link(temporary, name, src_dir_fd=folder, dst_dir_fd=folder, follow_symlinks=False)
            except FileExistsError:
                pass
            os.unlink(temporary, dir_fd=folder)
            made = False
            descriptor = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=folder)
            try:
                info = os.fstat(descriptor)
                if not private(info) or info.st_size != len(data) or os.read(descriptor, len(data) + 1) != data:
                    raise Error("invalid_input")
                named = os.stat(name, dir_fd=folder, follow_symlinks=False)
                if (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
                    raise Error("invalid_input")
            finally:
                os.close(descriptor)
            result = Request(folder, name, (info.st_dev, info.st_ino), str(self.identity.folder / "requests" / name))
            folder = None
            return result
        except (OSError, UnicodeError, ValueError) as error:
            raise Error("invalid_input") from error
        finally:
            if folder is not None:
                if made:
                    try:
                        os.unlink(temporary, dir_fd=folder)
                    except OSError:
                        pass
                os.close(folder)

    def clean(self, *, now: float | None = None) -> None:
        try:
            folder = self.directory(create=False)
        except FileNotFoundError:
            return
        try:
            cutoff = (time.time() if now is None else now) - 3600
            for name in os.listdir(folder):
                if not OWN_NAME.fullmatch(name):
                    continue
                try:
                    first = os.stat(name, dir_fd=folder, follow_symlinks=False)
                    if not private(first) or first.st_mtime >= cutoff:
                        continue
                    second = os.stat(name, dir_fd=folder, follow_symlinks=False)
                    if (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino) and private(second):
                        os.unlink(name, dir_fd=folder)
                except FileNotFoundError:
                    pass
        finally:
            os.close(folder)
