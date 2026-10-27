"""Private lifetime lock/socket, owned cleanup and connection tasks."""

from __future__ import annotations

import fcntl
import json
import os
import socket
import stat
from pathlib import Path

from .model import Refused


class Lifetime:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.path = folder / "backend.sock"
        self.lock = -1
        self.socket: socket.socket | None = None
        self.socket_identity: tuple[int, int] | None = None

    def acquire(self) -> socket.socket:
        try:
            self.lock = os.open(self.folder / "backend.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            info = os.fstat(self.lock)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise Refused("invalid_input", "The backend lock must be an owned regular file.")
            os.set_inheritable(self.lock, False)
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                data = os.pread(self.lock, 256, 0)
                try:
                    pid = json.loads(data).get("pid")
                    text = str(pid) if type(pid) is int and pid > 0 else "unknown"
                except (ValueError, AttributeError):
                    text = "unknown"
                raise Refused("already_running", "Backend already running, PID " + text + ".") from error
            os.fchmod(self.lock, 0o600)
            os.ftruncate(self.lock, 0)
            os.write(self.lock, json.dumps({"pid": os.getpid()}).encode() + b"\n")
            if os.path.lexists(self.path):
                if not stat.S_ISSOCK(self.path.lstat().st_mode):
                    raise Refused("invalid_input", "Only a stale socket may be removed at backend.sock.")
                self.path.unlink()
            previous = os.umask(0o077)
            try:
                self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.socket.set_inheritable(False)
                self.socket.bind(str(self.path))
                info = self.path.lstat()
                self.socket_identity = (info.st_dev, info.st_ino)
                self.path.chmod(0o600)
                self.socket.listen(128)
                self.socket.setblocking(False)
            finally:
                os.umask(previous)
            return self.socket
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        if self.socket_identity is not None:
            try:
                info = self.path.lstat()
                if (info.st_dev, info.st_ino) == self.socket_identity and stat.S_ISSOCK(info.st_mode):
                    self.path.unlink()
            except FileNotFoundError:
                pass
            self.socket_identity = None
        if self.lock >= 0:
            os.close(self.lock)
            self.lock = -1
