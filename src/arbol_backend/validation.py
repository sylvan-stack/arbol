"""Validate all request identifiers before effects; never retain public account objects."""

from __future__ import annotations

import asyncio
import os
import re
import stat
from pathlib import Path
from uuid import uuid4

from .bridge import Error, Params, driver_id, subscription_id, uuid_id
from .model import Identity, Refused
from .process import DRIVERS, Programs


def text(value: object, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()) or "\0" in value:
        raise Error("invalid_input")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise Error("invalid_input") from error
    return value


def integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise Error("invalid_input")
    return value


async def chat(params: Params) -> Params:
    return {"chat": uuid_id(params.get("chat"))}


class Catalogues:
    def __init__(self, identity: Identity, programs: Programs) -> None:
        self.identity, self.programs = identity, programs
        self.launchers = {name for name in DRIVERS if (identity.bin_dir / ("arbol-" + name + "-driver")).is_file()}
        self.subscriptions: dict[str, set[str]] = {}
        self.task: asyncio.Task[None] | None = None

    async def load_driver(self, driver: str) -> None:
        try:
            value = await self.programs.call("arbol-" + driver + "-driver", ["subscriptions", "list"],
                                             kind="account", key="catalogue-" + driver)
            if not isinstance(value, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str)
                                                   for row in value):
                return
            self.subscriptions[driver] = {row["id"] for row in value}
        except Refused:
            pass

    async def load(self) -> None:
        await asyncio.gather(*(self.load_driver(driver) for driver in self.launchers))

    def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self.load())

    async def route(self, value: object) -> Params:
        if not isinstance(value, dict):
            raise Error("invalid_input")
        result = {key: text(value.get(key)) for key in ("driver", "subscription", "model")}
        if "effort" in value:
            result["effort"] = text(value["effort"])
        driver_id(result["driver"], self.launchers)
        if result["subscription"].startswith("-") or not re.fullmatch(r"[^\x00-\x20\x7f]+", result["subscription"]):
            raise Error("invalid_input")
        if self.task:
            await asyncio.shield(self.task)
        if result["driver"] not in self.subscriptions:
            raise Error("no_answer", source="driver")
        subscription_id(result["subscription"], self.subscriptions[result["driver"]])
        return result

    async def settings(self, params: Params) -> Params:
        result = await chat(params)
        # Syntax for all fields is checked before membership/I/O for any of them.
        folder: str | None = None
        if "workingFolder" in params:
            folder = text(params["workingFolder"])
            if not Path(folder).is_absolute():
                raise Error("invalid_input")
        if "route" in params:
            result["route"] = await self.route(params["route"])
        if folder is not None:
            if not Path(folder).is_dir():
                raise Error("invalid_input")
            result["workingFolder"] = folder
        if len(result) == 1:
            raise Error("invalid_input")
        return result

    async def close(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


def save_paste(identity: Identity, value: str) -> str:
    root_fd: int | None = None
    folder_fd: int | None = None
    name = str(uuid4()) + ".txt"
    created = False
    try:
        root_fd = os.open(identity.folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.mkdir("pastes", mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        folder_fd = os.open("pastes", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd)
        info = os.fstat(folder_fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise Error("invalid_input")
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=folder_fd)
        created = True
        try:
            os.fchmod(fd, 0o600)
            data = memoryview(value.encode("utf-8"))
            while data:
                written = os.write(fd, data)
                if written == 0:
                    raise OSError("The private file stopped accepting bytes.")
                data = data[written:]
        finally:
            os.close(fd)
        return str(identity.folder / "pastes" / name)
    except (OSError, UnicodeError, Refused) as error:
        if created and folder_fd is not None:
            os.unlink(name, dir_fd=folder_fd)
        raise Error("invalid_input") from error
    finally:
        if folder_fd is not None:
            os.close(folder_fd)
        if root_fd is not None:
            os.close(root_fd)
