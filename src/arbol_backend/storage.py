"""Bounded local filesystem metadata, only for the connected database server's directory."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import signal
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
