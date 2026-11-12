"""Remove abandoned staging only when the installed database proves it safe."""

from __future__ import annotations

import fcntl
import os
import shutil
import stat
import subprocess
import time
from collections.abc import Callable

from .exchange_command import UUID
from .exchange_context import Context
from .exchange_listing import open_catalogue, project, read_record
from .model import Refused

START_SECONDS = 15


def cleanup(context: Context, state: Callable[[str], str]) -> None:
    catalogue = open_catalogue(context)
    if catalogue is None:
        return
    try:
        try:
            fcntl.flock(catalogue, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        for name in os.listdir(catalogue):
            exchange = name[1:-4]
            if not name.startswith(".") or not name.endswith((".old", ".new")) or not UUID.fullmatch(exchange):
                continue
            try:
                original = os.stat(name, dir_fd=catalogue, follow_symlinks=False)
                if not stat.S_ISDIR(original.st_mode) or original.st_uid != os.getuid() or original.st_mode & 0o077:
                    continue
                staged = name.endswith(".new")
                if staged and time.time() - original.st_mtime <= START_SECONDS:
                    continue
                try:
                    record = read_record(catalogue, name)
                except FileNotFoundError:
                    record = None
                if staged and record is not None and project(record, exchange)["process"]["alive"]:
                    continue
                confirmed = state(exchange)
                if confirmed == "open" or (staged and confirmed != "none"):
                    continue
                if confirmed == "none" and record is not None and ("acceptedAt" in record or "end" in record):
                    continue
                current = os.stat(name, dir_fd=catalogue, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino):
                    if shutil.rmtree.avoids_symlink_attacks:
                        shutil.rmtree(name, dir_fd=catalogue)
            except Refused as error:
                if error.code in ("database_unavailable", "schema_uninitialized", "schema_incompatible"):
                    break
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
                # Retained staging is reported as unreadable by the subsequent listing.
                continue
    finally:
        os.close(catalogue)
