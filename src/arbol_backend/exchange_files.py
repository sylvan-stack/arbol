"""Own-Root private Exchange descriptors, validated records and bounded UTC process reads."""

from __future__ import annotations

import asyncio
import os
import signal
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .bridge import Error, Params, uuid_id
from .chat_data import metadata
from .metadata import iso
from .migration import message
from .model import BUILD_ID, Identity, Refused
from .validation import integer, text

MAX_RECORD = 1024 * 1024
PS_SECONDS = 5.0
MONTHS = {name: n for n, name in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def timestamp(value: object) -> datetime:
    raw = text(value)
    if len(raw) > 128:
        raise Error("no_answer")
    try:
        result = datetime.fromisoformat(raw)
        if result.tzinfo is None:
            raise ValueError("Naive time.")
        return result.astimezone(UTC)
    except ValueError as error:
        raise Error("no_answer") from error


def private(info: os.stat_result, *, directory: bool = False) -> bool:
    return (info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
            and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1))


@dataclass(frozen=True)
class Record:
    exchange: str
    chat: str
    pid: int
    started: datetime
    accepted: datetime | None
    heartbeat: int
    waiting: str
    since: datetime
    end: Params | None
    immutable: tuple[Any, ...]

    def status(self, alive: bool, *, stopping: bool = False) -> Params | None:
        if self.accepted is None:
            state = "accepting" if alive else "unaccepted"
        elif self.end is not None:
            state = "ending" if alive else "unsaved"
        else:
            state = "running" if alive else "gone"
        if state == "unaccepted":
            return None
        if stopping and self.end is None:
            state = "stopping"
        value: Params = {"exchange": self.exchange, "state": state}
        if state == "running":
            value.update(waitingFor=self.waiting, since=iso(self.since))
        if self.end is not None:
            value["end"] = self.end
        return value


def record(value: Params, identity: Identity, exchange: str, *, secrets: tuple[str, ...] = ()) -> Record:
    try:
        if type(value.get("rootContract")) is not int or value["rootContract"] != 1 or value.get("root") != identity.root:
            raise Error("no_answer")
        if uuid_id(value.get("exchange")) != exchange:
            raise Error("no_answer")
        chat = uuid_id(value.get("chat"))
        trunk, build = text(value.get("trunk")), text(value.get("build"))
        if not trunk.isascii() or not trunk[0].isalpha() or not trunk.isalnum() or not trunk.islower() or len(trunk) > 32:
            raise Error("no_answer")
        if (build != "0" and not BUILD_ID.fullmatch(build)) or not isinstance(value.get("route"), dict):
            raise Error("no_answer")
        folder = text(value.get("workingFolder"))
        if not os.path.isabs(folder):
            raise Error("no_answer")
        process, life = value.get("process"), value.get("signsOfLife")
        if not isinstance(process, dict) or not isinstance(life, dict):
            raise Error("no_answer")
        pid = integer(process.get("pid"), 1, 2147483647)
        started = timestamp(process.get("startedAt"))
        heartbeat = integer(life.get("heartbeat"), 0, 9223372036854775807)
        waiting, since = text(life.get("waitingFor")), timestamp(life.get("since"))
        if len(waiting.encode("utf-8")) > 1024:
            raise Error("no_answer")
        accepted = timestamp(value["acceptedAt"]) if "acceptedAt" in value else None
        ended: Params | None = None
        if "end" in value:
            raw = value["end"]
            if not isinstance(raw, dict):
                raise Error("no_answer")
            ended = {"state": text(raw.get("state")), "at": iso(timestamp(raw.get("at")))}
            if "error" in raw:
                if not isinstance(raw["error"], dict):
                    raise Error("no_answer")
                ended["error"] = metadata(raw["error"])
                if "message" in ended["error"]:
                    ended["error"]["message"] = message(ended["error"]["message"], secrets=secrets,
                        fallback="The Exchange failed; its diagnostic is not safe to display.")
        # Structural equality of these private metadata values is enough to detect a rewritten identity.
        immutable = (chat, trunk, build, pid, started, value["route"], value.get("smallCallRoute"), folder)
        return Record(exchange, chat, pid, started, accepted, heartbeat, waiting, since, ended, immutable)
    except (Refused, ValueError, UnicodeError, KeyError, TypeError) as error:
        raise Error("no_answer") from error


@dataclass
class Folder:
    descriptor: int
    exchange: str

    def open(self, name: str, *, append: bool = False) -> int:
        if name not in {"record.json", "events.jsonl", "control"} or append and name != "control":
            raise Error("invalid_input")
        flags = (os.O_WRONLY | os.O_APPEND) if append else os.O_RDONLY
        fd = os.open(name, flags | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.descriptor)
        try:
            if not private(os.fstat(fd)):
                raise Error("no_answer")
            return fd
        except BaseException:
            os.close(fd)
            raise

    def close(self) -> None:
        os.close(self.descriptor)


class Folders:
    def __init__(self, identity: Identity) -> None:
        self.identity = identity
        self.identities: dict[str, tuple[Any, ...]] = {}

    def directory(self) -> int:
        root = os.open(self.identity.folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            folder = os.open("exchanges", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
            if not private(os.fstat(folder), directory=True):
                os.close(folder)
                raise Error("no_answer")
            return folder
        finally:
            os.close(root)

    def open(self, exchange: str, *, temporary: bool = False) -> Folder:
        uuid_id(exchange)
        parent = self.directory()
        try:
            name = "." + exchange + ".new" if temporary else exchange
            descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            if not private(os.fstat(descriptor), directory=True):
                os.close(descriptor)
                raise Error("no_answer")
            return Folder(descriptor, exchange)
        finally:
            os.close(parent)

    def names(self) -> list[str]:
        try:
            parent = self.directory()
        except FileNotFoundError:
            return []
        try:
            result = []
            for name in os.listdir(parent):
                if name.startswith("."):
                    continue
                try:
                    uuid_id(name)
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if private(info, directory=True):
                        result.append(name)
                except (FileNotFoundError, Refused):
                    continue
            return sorted(result)
        finally:
            os.close(parent)

    def read(self, exchange: str, *, secrets: tuple[str, ...] = ()) -> Record:
        import json

        from .bridge import pairs
        folder = self.open(exchange)
        try:
            fd = folder.open("record.json")
            try:
                if os.fstat(fd).st_size > MAX_RECORD:
                    raise Error("no_answer")
                raw = os.read(fd, MAX_RECORD + 1)
            finally:
                os.close(fd)
            if len(raw) > MAX_RECORD:
                raise Error("no_answer")
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
            if not isinstance(value, dict):
                raise Error("no_answer")
            result = record(value, self.identity, exchange, secrets=secrets)
            previous = self.identities.get(exchange)
            if previous is not None and previous != result.immutable:
                raise Error("no_answer")
            self.identities[exchange] = result.immutable
            return result
        except (ValueError, UnicodeError, RecursionError) as error:
            raise Error("no_answer") from error
        finally:
            folder.close()

    def forget(self, names: set[str]) -> None:
        for exchange in set(self.identities) - names:
            self.identities.pop(exchange)


async def processes(pids: set[int], *, seconds: float = PS_SECONDS) -> dict[int, datetime | None]:
    if not pids:
        return {}
    for pid in pids:
        integer(pid, 1, 2147483647)
    child = None
    try:
        child = await asyncio.create_subprocess_exec(
            "/bin/ps", "-p", ",".join(str(pid) for pid in sorted(pids)), "-o", "pid=,lstart=",
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True, close_fds=True)
        async with asyncio.timeout(seconds):
            assert child.stdout is not None
            raw = await child.stdout.read(MAX_RECORD + 1)
            status = await child.wait()
        if status not in (0, 1) or len(raw) > MAX_RECORD:
            raise Error("no_answer")
        result: dict[int, datetime | None] = {pid: None for pid in pids}
        for line in raw.decode("ascii").splitlines():
            parts = line.split()
            if (len(parts) != 6 or not parts[0].isdigit() or parts[1] not in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
                    or parts[2] not in MONTHS):
                raise Error("no_answer")
            pid = int(parts[0])
            if pid not in pids or result[pid] is not None:
                raise Error("no_answer")
            result[pid] = datetime.fromisoformat(f"{parts[5]}-{MONTHS[parts[2]]:02d}-{int(parts[3]):02d}T{parts[4]}+00:00")
        return result
    except (OSError, ValueError, UnicodeError, TimeoutError) as error:
        raise Error("no_answer") from error
    finally:
        if child is not None and child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(child.wait(), 0.2)
            except TimeoutError:
                pass


def living(value: Record, observed: dict[int, datetime | None]) -> bool:
    start = observed.get(value.pid)
    return start is not None and abs((start - value.started).total_seconds()) <= 2
