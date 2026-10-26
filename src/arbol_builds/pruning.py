"""The retained Root catalogue for pruning (BLD-0.20, BLD-D22).

These reads preserve damaged records rather than hiding them as launchers do.
This module is never embedded into a launcher.
"""

import json
import os
import stat

from .launcher import Record, js_integer, refuse_constant, root_identifier
from .roots import valid_root


def retained_record(path: str, name: str) -> Record | None:
    """Read a regular record without waiting on a pipe; reuse the launchers' validation."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, encoding="utf-8", errors="replace") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return None
            value: object = json.loads(stream.read(), parse_constant=refuse_constant, parse_int=js_integer)
    except Exception:
        return None
    return value if isinstance(value, dict) and valid_root(value, name) else None


def retained_roots(folder: str) -> dict[str, Record | None]:
    """An existing root.json entry retains its folder identity even when its record is unreadable."""
    try:
        with os.scandir(folder) as entries:
            names = sorted(entry.name for entry in entries if root_identifier(entry.name))
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise ValueError(f"Cannot list the retained Roots in {folder}: {error}") from error
    found: dict[str, Record | None] = {}
    for name in names:
        path = os.path.join(folder, name, "root.json")
        try:
            os.lstat(path)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            found[name] = None
            continue
        found[name] = retained_record(path, name)
    return found
