"""Bounded local filesystem metadata, only for the connected database server's directory."""

from __future__ import annotations

import asyncio
import ipaddress
import math
import os
import signal
import stat
import subprocess
from pathlib import Path

from .bridge import Params


class LocalDisk:
    def __init__(self, *, program: str = "/usr/bin/du", seconds: float = 10) -> None:
        self.program, self.seconds = program, seconds

    @staticmethod
    def local(host: str, server: str | None) -> bool:
        def loopback(value: str) -> bool:
            try:
                return ipaddress.ip_interface(value).ip.is_loopback
            except ValueError:
                return False
        return (host.startswith("/") or host == "localhost" or loopback(host)) and (server is None or loopback(server))

    @staticmethod
    def location(raw: str) -> tuple[Path, int]:
        path = Path(raw)
        if not path.is_absolute():
            raise ValueError("Unconfirmed database directory.")
        path = path.resolve(strict=True)
        if not path.is_dir():
            raise ValueError("Unconfirmed database directory.")
        stat = os.statvfs(path)
        return path, stat.f_bavail*stat.f_frsize

    @staticmethod
    def confirm(candidate: Path, backend: int, started: float) -> Path:
        """Attest the conventional directory through this authenticated session's local process."""
        if type(backend) is not int or backend <= 0 or not math.isfinite(started):
            raise ValueError("Invalid authenticated process identity.")
        folder = candidate.lstat()
        if not stat.S_ISDIR(folder.st_mode) or folder.st_uid != os.getuid():
            raise ValueError("Unconfirmed local directory.")
        path = candidate / "postmaster.pid"
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid()
                    or before.st_mode & 0o077 or before.st_size > 4096):
                raise ValueError("Unconfirmed local server metadata.")
            raw = os.read(fd, 4097)
            lines = raw.decode("utf-8").splitlines()
            if (len(raw) > 4096 or len(lines) < 3 or not lines[0].isdigit() or not lines[2].isdigit()
                    or Path(lines[1]).resolve(strict=True) != candidate.resolve(strict=True)
                    or abs(int(lines[2]) - started) > 2):
                raise ValueError("Different local server identity.")
            postmaster = int(lines[0])
            if postmaster <= 0 or postmaster == backend:
                raise ValueError("Invalid local parent identity.")
            observation = subprocess.run(["/bin/ps", "-p", str(backend), "-o", "ppid=,uid="],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=2,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"})
            if observation.returncode or observation.stdout.split() != [str(postmaster).encode(), str(os.getuid()).encode()]:
                raise ValueError("The connection is not a child of this local server.")
            after = path.lstat()
            current = candidate.lstat()
            fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns")
            if (any(getattr(before, field) != getattr(after, field) for field in fields)
                    or (folder.st_dev, folder.st_ino) != (current.st_dev, current.st_ino)
                    or os.pread(fd, 4097, 0) != raw):
                raise ValueError("Local server metadata changed during observation.")
            return candidate.resolve(strict=True)
        finally:
            os.close(fd)

    async def size(self, path: Path) -> int:
        child = await asyncio.create_subprocess_exec(self.program, "-sk", str(path),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True, close_fds=True, env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"})
        try:
            async with asyncio.timeout(self.seconds):
                assert child.stdout
                buffer = bytearray()
                while len(buffer) <= 4096:
                    part = await child.stdout.read(4097-len(buffer))
                    if not part:
                        break
                    buffer.extend(part)
                if len(buffer) > 4096:
                    raise ValueError("The directory size reply is too large.")
                status = await child.wait()
            raw = bytes(buffer)
            number = raw.partition(b"\t")[0]
            if status != 0 or b"\t" not in raw or not raw.endswith(b"\n") or not number.isdigit():
                raise ValueError("The directory size is not available.")
            return int(number)*1024
        finally:
            if child.returncode is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await child.wait()

    async def get(self, raw: str, host: str, server: str | None) -> Params:
        if not self.local(host, server):
            return {"diskProblem": "This server's local data disk is not confirmed."}
        try:
            path, free = await asyncio.to_thread(self.location, raw)
        except (OSError, ValueError):
            return {"diskProblem": "The database data directory is not accessible."}
        result: Params = {"freeBytes": free}
        try:
            result["dataFolderBytes"] = await self.size(path)
        except (TimeoutError, OSError, ValueError):
            result["diskProblem"] = "The database data folder size is not available."
        return result
