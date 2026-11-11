"""The records of the Roots, as the launchers read them (ARC-1, "A Root on disk"; BLD-0, "Running a Build", BLD-D17).

arbol-builds writes the text of this module after the text of launcher.py into a launcher that chooses by Root
(service.launcher_source). It therefore uses the standard library only; there, the import from .launcher below is
left out, and the names it imports are those of the text before it.
"""

import json
import os
import stat

from .launcher import ROOT_PATTERN, Record, date, js_integer, milliseconds, positive, refuse_constant, root_identifier

ROOT_STATES = ("preparing", "working", "failed")
CURRENT_ROOT_FILE = ".current-root.json"


def roots_folder() -> str:
    """The folder of the Roots' folders, reached from the home folder at every call, so a test gives a home of its
    own (RCT-0, "How a Trunk finds its Root's folder and database")."""
    return os.path.join(os.path.expanduser("~"), "Library/Application Support/Arbol/roots")


def valid_root(value: object, root: str) -> bool:
    """A Root's record names its own folder, a state, the time it was created and its Root Contract version; the
    launchers read no other field (BLD-D17)."""
    return (isinstance(value, dict) and value.get("root") == root and root_identifier(root)
            and value.get("status") in ROOT_STATES and date(value.get("createdAt"))
            and positive(value.get("rootContract")))


def read_root(folder: str, root: str) -> Record | None:
    """The record of one Root, or None when it is missing or damaged, or the identifier is not one."""
    if not root_identifier(root):
        return None
    try:
        # Bytes that are not UTF-8 read as U+FFFD, as in the Build records.
        with open(os.path.join(folder, root, "root.json"), encoding="utf-8", errors="replace") as stream:
            record: object = json.loads(stream.read(), parse_constant=refuse_constant, parse_int=js_integer)
    except Exception:
        return None
    return record if isinstance(record, dict) and valid_root(record, root) else None


def read_roots(folder: str) -> list[Record]:
    """The valid records of every Root. A damaged or missing record takes only its own Root out of use."""
    try:
        with os.scandir(folder) as entries:
            names = sorted(entry.name for entry in entries if ROOT_PATTERN.fullmatch(entry.name))
    except OSError:
        return []
    return [record for name in names if (record := read_root(folder, name)) is not None]


def current_root_preference(folder: str) -> tuple[str, str] | None:
    """Read the saved identity without following a link or waiting on a nonregular file."""
    try:
        fd = os.open(os.path.join(folder, CURRENT_ROOT_FILE), os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None
            payload = os.read(fd, 4097)
        finally:
            os.close(fd)
        if len(payload) > 4096:
            return None
        value = json.loads(payload)
    except (OSError, ValueError, RecursionError):
        return None
    if isinstance(value, dict):
        root, created_at = value.get("root"), value.get("createdAt")
        if isinstance(root, str) and root_identifier(root) and isinstance(created_at, str) and date(created_at):
            return root, created_at
    return None

def current_root(records: list[Record], *, folder: str | None = None) -> Record | None:
    """Choose the saved working Root, or the newest working record in automatic mode (ARC-1.7)."""
    working = [record for record in records if record["status"] == "working"]
    if folder is not None:
        preference = current_root_preference(folder)
        for record in working:
            if (record["root"], record["createdAt"]) == preference:
                return record
    return max(working,
               key=lambda record: (milliseconds(record["createdAt"]), record["root"]), default=None)
