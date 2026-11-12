"""Recover a UUID receipt or start its selected Trunk in a private process group."""

from __future__ import annotations

import asyncio
import fcntl
import os
import re
import stat
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

from .database import Unavailable
from .exchange_admission import GENERATION_ENV, Admission
from .exchange_command import UUID, Command
from .exchange_context import Context, Refusal
from .exchange_launcher import MAX_REPLY, Reply, object_line, select_build
from .model import BUILD_ID, Refused, private_directory

ACCEPT_SECONDS = 20.0
UNRESOLVED = {"no_answer", "in_progress"}


async def receipt(context: Context, exchange: str, timeout: float, *, wait_for_commit: bool = False) -> Reply | None:
    database = context.database()
    try:
        async with asyncio.timeout(timeout):
            async with database.session() as session:
                if wait_for_commit:
                    await session.execute("BEGIN")
                    await session.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [exchange])
                rows = await session.execute(
                    "SELECT chat_id::text, number, trunk, build FROM public.exchanges WHERE id = %s", [exchange])
    except (TimeoutError, Unavailable):
        raise Refusal("database_unavailable", "The installation database could not confirm the Exchange UUID.") from None
    except Refused as error:
        if error.code == "schema_incompatible" and database.schema.pair() is None:
            raise Refusal("schema_invalid", "The installed migration history could not be verified.") from None
        raise
    finally:
        await database.close()
    if not rows:
        return None
    chat, number, trunk, build = rows[0]
    value = {"accepted": True, "duplicate": True, "exchange": exchange, "chat": chat, "number": number,
             "trunk": trunk, "build": build}
    if not accepted(value, exchange):
        raise Refusal("no_answer", "The database returned an unreadable Exchange receipt.")
    return Reply(value)


@contextmanager
def launch_lock(context: Context, exchange: str) -> Iterator[tuple[int, Path]]:
    place = context.identity.folder / "exchange-starts"
    path = place / exchange
    try:
        context.identity.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_directory(context.identity.folder)
        place.mkdir(mode=0o700, exist_ok=True)
        private_directory(place)
    except OSError:
        raise Refusal("runtime_unavailable", "The private Exchange runtime could not be opened.") from None
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError:
        raise Refusal("runtime_unavailable", "The Exchange start could not be coordinated.") from None
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise Refusal("runtime_unavailable", "The Exchange start lock is not private.")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            named = path.lstat()
            if (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
                raise BlockingIOError
        except (BlockingIOError, FileNotFoundError):
            raise Refusal("in_progress", "A start for this Exchange UUID is still being resolved.") from None
        yield descriptor, path
    finally:
        # The Trunk inherits this open file description and keeps the lock after a lost reply.
        os.close(descriptor)


def accepted(value: dict[str, Any], exchange: str) -> bool:
    chat, trunk, build, number = (value.get(key) for key in ("chat", "trunk", "build", "number"))
    return (value.get("accepted") is True and type(value.get("duplicate")) is bool
            and value.get("exchange") == exchange and isinstance(chat, str) and UUID.fullmatch(chat) is not None
            and type(number) is int and number > 0
            and isinstance(trunk, str) and re.fullmatch(r"[a-z][a-z0-9]{0,31}", trunk) is not None
            and isinstance(build, str) and (build == "0" or BUILD_ID.fullmatch(build) is not None))


def wait_reply(child: subprocess.Popen[bytes], output: BinaryIO, deadline: float) -> dict[str, Any] | None:
    pending = bytearray()
    while time.monotonic() < deadline:
        chunk = os.pread(output.fileno(), min(65536, MAX_REPLY + 1 - len(pending)), len(pending))
        pending.extend(chunk)
        if b"\n" in pending:
            return object_line(bytes(pending).partition(b"\n")[0])
        if len(pending) > MAX_REPLY:
            return None
        if not chunk:
            if child.poll() is not None:
                return object_line(bytes(pending))
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))
    return None


def forget(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def start(context: Context, command: Command, *, timeout: float = ACCEPT_SECONDS) -> Reply:
    deadline = time.monotonic() + timeout
    exchange = command.options["--exchange"]
    request = Path(command.options["--request"])
    folders = tuple(context.exchanges / name for name in (exchange, f".{exchange}.new", f".{exchange}.old"))
    lock_file = context.identity.folder / "exchange-starts" / exchange
    admission = Admission(context.identity.folder)
    expected = os.environ.get(GENERATION_ENV)
    try:
        # An already accepted UUID may be recovered during draining. This read
        # neither consumes the request nor grants permission to start a Trunk.
        with admission.lease("controlled", generation=expected) as read:
            generation = read.state.generation
            prior = asyncio.run(receipt(context, exchange, max(0, deadline - time.monotonic())))
    except Refused as refusal:
        if refusal.code == "maintenance":
            raise
        if any(os.path.lexists(path) for path in (*folders, lock_file)):
            raise Refusal("in_progress", "The database could not resolve this earlier Exchange start.") from None
        raise
    if prior is not None:
        return prior
    with admission.lease("normal", generation=generation), launch_lock(context, exchange) as (lock, lock_path):
        try:
            prior = asyncio.run(receipt(context, exchange, max(0, deadline - time.monotonic()), wait_for_commit=True))
        except Refused:
            raise Refusal("in_progress", "The Exchange acceptance could not be confirmed under its UUID lock.") from None
        if prior is not None:
            forget(lock_path)
            return prior
        if any(os.path.lexists(path) for path in folders):
            raise Refusal("in_progress", "The Exchange already has a pending folder. Resolve it before retrying.")
        try:
            selected = select_build(context, command, timeout=max(0, deadline - time.monotonic()))
        except Refusal:
            forget(lock_path)
            raise
        if isinstance(selected, Reply):
            forget(lock_path)
            return selected
        if time.monotonic() >= deadline:
            forget(lock_path)
            raise Refusal("no_answer", "The start time limit expired during Build selection.")
        assert command.code is not None
        try:
            request_info = request.lstat()
        except OSError:
            request_info = None
        arguments = [str(context.bin_dir / "arbol-trunk"), command.code, "-v", selected, "run", "--detach",
                     "--exchange", exchange, "--request", str(request), *command.forward]
        # An anonymous output file keeps a late acceptance independent of the caller.
        with tempfile.TemporaryFile() as output:
            try:
                env = {**context.environment(), GENERATION_ENV: generation}
                child = subprocess.Popen(arguments, env=env, start_new_session=True,
                                         stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                                         pass_fds=(lock,))
            except (OSError, ValueError):
                forget(lock_path)
                raise Refusal("trunk_unavailable", "Cannot start the selected Trunk launcher.") from None
            value = wait_reply(child, output, deadline)
        if value is not None and accepted(value, exchange):
            if not value["duplicate"] and (value["trunk"] != command.code or value["build"] != selected):
                raise Refusal("no_answer", "The receipt did not match the selected Trunk Build.")
            status = 0
        elif value is not None and isinstance(error := value.get("error"), dict) and isinstance(error.get("code"), str):
            if error["code"] in UNRESOLVED:
                return Reply(value, 1)
            status = 1
        else:
            raise Refusal("no_answer", "The start could not be confirmed. Recover it using the same Exchange UUID.")
        forget(lock_path)
        if request_info is not None and stat.S_ISREG(request_info.st_mode):
            try:
                current = request.lstat()
                if (current.st_dev, current.st_ino) == (request_info.st_dev, request_info.st_ino):
                    forget(request)
            except OSError:
                pass
        return Reply(value, status)
