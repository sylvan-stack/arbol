"""Changes to a component's records, one at a time (BLD-0, Interface: "Short-lived process reservations").

Lamport's bakery lock, with one file per invocation in the component's `.writers/` folder, so
that reclaiming a dead writer can never remove a new writer's reservation, and no resident
process is needed. The file names, their JSON and the comparisons are those of the earlier
Node.js tool, so the two tools exclude each other while both are installed.
"""

import json
import os
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

WAIT_SECONDS = 30.0
POLL_SECONDS = 0.01
WRITER_NAME = re.compile(r"\d+-[0-9a-f-]+\.json")
TICKET = re.compile(r"\d+")


class Busy(Exception):
    pass


def make_dirs(path: str, mode: int) -> None:
    """Create path and every missing parent with the same mode, as Node.js mkdir does."""
    missing: list[str] = []
    current = os.path.abspath(path)
    while not os.path.isdir(current):
        missing.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    for folder in reversed(missing):
        try:
            os.mkdir(folder, mode)
        except FileExistsError:
            if not os.path.isdir(folder):
                raise


def with_mutation_lock[T](component_folder: str, action: Callable[[], T]) -> T:
    folder = os.path.join(component_folder, ".writers")
    make_dirs(folder, 0o700)
    name = f"{os.getpid()}-{uuid.uuid4()}.json"
    path = os.path.join(folder, name)
    writer: dict[str, Any] = {"pid": os.getpid(), "choosing": True, "ticket": "0"}
    started = time.monotonic()

    def pause() -> None:
        if time.monotonic() - started > WAIT_SECONDS:
            raise Busy("Another invocation is still changing this component; try again when it finishes.")
        time.sleep(POLL_SECONDS)

    def publish() -> None:
        temporary = f"{path}.tmp"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(writer, separators=(",", ":")))
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def others() -> list[tuple[str, dict[str, Any]]]:
        found: list[tuple[str, dict[str, Any]]] = []
        for item in os.listdir(folder):
            if not WRITER_NAME.fullmatch(item) or item == name:
                continue
            other_path = os.path.join(folder, item)
            try:
                with open(other_path, encoding="utf-8") as stream:
                    other: object = json.load(stream)
            except FileNotFoundError:
                continue
            if (not isinstance(other, dict) or isinstance(other.get("pid"), bool) or not isinstance(other.get("pid"), int)
                    or not 1 <= other["pid"] <= 2**53 - 1 or not isinstance(other.get("choosing"), bool)
                    or not isinstance(other.get("ticket"), str) or not TICKET.fullmatch(other["ticket"])):
                raise ValueError(f"Damaged writer reservation: {other_path}")
            try:
                os.kill(other["pid"], 0)
            except ProcessLookupError:
                try:
                    os.unlink(other_path)
                except FileNotFoundError:
                    pass
                continue
            except PermissionError:
                pass  # alive, owned by someone else
            found.append((item, other))
        return found

    def waiting() -> bool:
        mine = int(writer["ticket"])
        for other_name, other in others():
            ticket = int(other["ticket"])
            if other["choosing"] or (ticket > 0 and (ticket < mine or (ticket == mine and other_name < name))):
                return True
        return False

    try:
        publish()
        writer["ticket"] = str(max((int(other["ticket"]) for _, other in others()), default=0) + 1)
        writer["choosing"] = False
        publish()
        while waiting():
            pause()
        return action()
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
