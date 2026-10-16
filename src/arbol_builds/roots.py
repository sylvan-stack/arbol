"""The records of the Roots, as the launchers read them (ARC-1, "A Root on disk"; BLD-0, "Running a Build", BLD-D17).

arbol-builds writes the text of this module after the text of launcher.py into a launcher that chooses by Root
(service.launcher_source). It therefore uses the standard library only; there, the import from .launcher below is
left out, and the names it imports are those of the text before it.
"""

import json
import os

from .launcher import ROOT_PATTERN, Record, date, js_integer, milliseconds, positive, refuse_constant, root_identifier

ROOT_STATES = ("preparing", "working", "failed")


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


def current_root(records: list[Record]) -> Record | None:
    """The Root created last among those in the state working (ARC-1, "The states of a Root and the current Root"),
    worked out from the records at every call; of two created at the same millisecond, the one whose identifier sorts
    last (BLD-D17). A Root that is preparing or failed is never current."""
    return max((record for record in records if record["status"] == "working"),
               key=lambda record: (milliseconds(record["createdAt"]), record["root"]), default=None)
