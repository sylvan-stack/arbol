"""Atomic private write-ahead notes with verified crash recovery and conditional removal."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from uuid import uuid4

from .bridge import Error, Params, constant, finite, pairs, uuid_id
from .exchange_files import timestamp
from .metadata import iso
from .model import Identity

MAX_NOTE = 4096


def fingerprint(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def regular(info: os.stat_result, *, links: tuple[int, ...] = (1,)) -> bool:
    return (stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == os.getuid() and info.st_nlink in links)


@dataclass(frozen=True)
class Note:
    value: Params
    file: tuple[int, int, int, int]
    directory: tuple[int, int]

    @property
    def wire(self) -> Params:
        return {key: self.value[key] for key in ("exchange", "kind", "at")}


class NoteFiles:
    def __init__(self, identity: Identity) -> None:
        self.identity = identity

    def directory(self, *, create: bool = False) -> int:
        root = os.open(self.identity.folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if create:
                try:
                    os.mkdir("notes", mode=0o700, dir_fd=root)
                    os.fsync(root)
                except FileExistsError:
                    pass
            fd = os.open("notes", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                os.close(fd)
                raise Error("no_answer")
            return fd
        finally:
            os.close(root)

    def validate(self, value: object, exchange: str) -> Params:
        if (not isinstance(value, dict) or value.get("root") != self.identity.root
                or uuid_id(value.get("exchange")) != exchange or value.get("kind") != "ended_stuck"):
            raise Error("no_answer")
        return {"root": self.identity.root, "exchange": exchange, "chat": uuid_id(value.get("chat")),
                "kind": "ended_stuck", "at": iso(timestamp(value.get("at")))}

    def heal(self, parent: int, exchange: str, expected: os.stat_result) -> None:
        pattern = re.compile(r"\."+re.escape(exchange)+r"\.[0-9a-f]{32}\.new\Z")
        matches = []
        for name in os.listdir(parent):
            if not pattern.fullmatch(name):
                continue
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if regular(info, links=(2,)) and fingerprint(info) == fingerprint(expected):
                matches.append(name)
        if len(matches) != 1:
            raise Error("no_answer")
        # Both private names and complete canonical contents were verified before removing our temporary link.
        os.unlink(matches[0], dir_fd=parent)
        os.fsync(parent)

    def read(self, exchange: str) -> Note:
        uuid_id(exchange)
        parent = self.directory()
        fd: int | None = None
        try:
            fd = os.open(exchange+".json", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            before = os.fstat(fd)
            if not regular(before, links=(1, 2)) or before.st_size > MAX_NOTE:
                raise Error("no_answer")
            raw = os.read(fd, MAX_NOTE+1)
            if len(raw) > MAX_NOTE or fingerprint(before) != fingerprint(os.fstat(fd)):
                raise Error("no_answer")
            value = self.validate(json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite), exchange)
            if before.st_nlink == 2:
                self.heal(parent, exchange, before)
            info = os.fstat(fd)
            named = os.stat(exchange+".json", dir_fd=parent, follow_symlinks=False)
            if (not regular(info) or not regular(named) or fingerprint(info) != fingerprint(named)
                    or fingerprint(info) != fingerprint(before)):
                raise Error("no_answer")
            folder = os.fstat(parent)
            return Note(value, fingerprint(info), (folder.st_dev, folder.st_ino))
        except (ValueError, UnicodeError, RecursionError) as error:
            raise Error("no_answer") from error
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent)

    def put(self, value: Params) -> Note:
        value = self.validate(value, uuid_id(value.get("exchange")))
        exchange = value["exchange"]
        try:
            previous = self.read(exchange)
        except FileNotFoundError:
            pass
        else:
            if any(previous.value[key] != value[key] for key in ("root", "exchange", "chat", "kind")):
                raise Error("no_answer")
            return previous  # The first timestamp of this same immutable Exchange wins.
        raw = (json.dumps(value, ensure_ascii=False, separators=(",", ":"))+"\n").encode()
        if len(raw) > MAX_NOTE:
            raise Error("no_answer")
        parent = self.directory(create=True)
        name = "."+exchange+"."+uuid4().hex+".new"
        fd: int | None = None
        own: tuple[int, int, int, int] | None = None
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
            if os.write(fd, raw) != len(raw):
                raise Error("no_answer")
            os.fsync(fd)
            own = fingerprint(os.fstat(fd))
            try:
                os.link(name, exchange+".json", src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            except FileExistsError:
                pass  # Read and validate the winner after removing only our temporary name.
        finally:
            try:
                if fd is not None:
                    if own is None:
                        own = fingerprint(os.fstat(fd))
                    os.close(fd)
                    try:
                        if fingerprint(os.stat(name, dir_fd=parent, follow_symlinks=False)) == own:
                            os.unlink(name, dir_fd=parent)
                            os.fsync(parent)
                    except FileNotFoundError:
                        pass
            finally:
                os.close(parent)
        result = self.read(exchange)
        if any(result.value[key] != value[key] for key in ("root", "exchange", "chat", "kind")):
            raise Error("no_answer")
        return result

    def names(self) -> list[str]:
        try:
            parent = self.directory()
        except FileNotFoundError:
            return []
        try:
            found = []
            for name in os.listdir(parent):
                if not name.endswith(".json"):
                    continue
                try:
                    found.append(uuid_id(name[:-5]))
                except Error:
                    pass
            return sorted(found)
        finally:
            os.close(parent)

    def remove(self, note: Note) -> None:
        parent = self.directory()
        try:
            folder = os.fstat(parent)
            if (folder.st_dev, folder.st_ino) != note.directory:
                raise Error("no_answer")
            name = note.value["exchange"]+".json"
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not regular(info) or fingerprint(info) != note.file:
                raise Error("no_answer")
            os.unlink(name, dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(parent)
