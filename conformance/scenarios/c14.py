# Test implementations moved to tests/mid/archived/conformance/scenarios/c14.py.
"""C14: resume or rebuild the caller conversation (DRV-2, DRV-6)."""

from __future__ import annotations

import ctypes
import math
import os
import stat as stat_module
import struct
from typing import Any

from ..check import ScenarioError
from ..harness import Scenario, ScenarioHome, fs_error
from ..js import UNDEFINED, JSArray, JSObject, join, parse, text_of
from .support import null_check


def to_string(value: Any) -> str:
    """String(value), also the ToString of `+` and of JSON.parse: an object with its own `toString` field, also
    one inside an array, has no primitive value (V8's TypeError)."""
    try:
        return text_of(value)
    except TypeError as error:
        raise ScenarioError(str(error)) from None


def saved_files(folder: str) -> list[str]:
    """Every file under a folder, depth first in readdir order; a missing folder has none."""
    null_check(folder)
    try:
        with os.scandir(folder) as scan:
            entries = sorted(((entry.name, entry.is_dir(follow_symlinks=False), entry.is_file(follow_symlinks=False))
                              for entry in scan), key=lambda entry: os.fsencode(entry[0]))
    except FileNotFoundError:
        return []
    except OSError as error:
        raise fs_error(error, "scandir", folder) from None
    paths: list[str] = []
    for name, directory, regular in entries:
        path = join(folder, name)
        if directory:
            paths.extend(saved_files(path))
        elif regular:
            paths.append(path)
    return paths


def remove_file(path: str, force: bool = False) -> None:
    """rm(path, { force }) without `recursive`: lstat first, as Node does, with Node's texts."""
    null_check(path)
    try:
        result = os.lstat(path)
    except OSError as error:
        if force and isinstance(error, FileNotFoundError):
            return
        raise fs_error(error, "lstat", path) from None
    if stat_module.S_ISDIR(result.st_mode):
        raise ScenarioError(f"Path is a directory: rm returned EISDIR (is a directory) {path}")
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError as error:
        raise fs_error(error, "unlink", path) from None


def creation_ns(path: str) -> int | None:
    """stat's st_birthtimespec in nanoseconds, which Node reads and os.stat gives only as a float: macOS's
    getattrlist(ATTR_CMN_CRTIME), following links as stat does; None where it is not available."""
    try:
        function = ctypes.CDLL(None, use_errno=True).getattrlist
    except (OSError, AttributeError):
        return None
    function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint]
    function.restype = ctypes.c_int
    request = struct.pack("=HHIIIII", 5, 0, 0x200, 0, 0, 0, 0)  # ATTR_BIT_MAP_COUNT, ATTR_CMN_CRTIME
    answer = ctypes.create_string_buffer(64)
    if function(os.fsencode(path), request, answer, len(answer), 0) != 0:
        return None
    _, seconds, nanoseconds = struct.unpack_from("=Iqq", answer.raw)
    return int(seconds) * 1_000_000_000 + int(nanoseconds)


def node_stats(path: str) -> JSObject:
    """The fields of Node's Stats object for a path (stat follows links)."""
    try:
        result = os.stat(path)
    except OSError as error:
        raise fs_error(error, "stat", path) from None

    def milliseconds(nanoseconds: int) -> float:
        return nanoseconds // 1_000_000_000 * 1e3 + nanoseconds % 1_000_000_000 / 1e6

    birth = creation_ns(path)
    if birth is None:
        seconds = math.floor(result.st_birthtime)
        birth = seconds * 1_000_000_000 + round((result.st_birthtime - seconds) * 1e9)
    return JSObject(dev=float(result.st_dev), mode=float(result.st_mode), nlink=float(result.st_nlink),
                    uid=float(result.st_uid), gid=float(result.st_gid), rdev=float(result.st_rdev),
                    blksize=float(result.st_blksize), ino=float(result.st_ino), size=float(result.st_size),
                    blocks=float(result.st_blocks), atimeMs=milliseconds(result.st_atime_ns),
                    mtimeMs=milliseconds(result.st_mtime_ns), ctimeMs=milliseconds(result.st_ctime_ns),
                    birthtimeMs=milliseconds(birth))


def slice_text(value: Any, start: int, end: int | None = None) -> Any:
    """`item.text.slice(start, end)`: UTF-16 units of a string, items of an array, else V8's TypeError."""
    if value is UNDEFINED or value is None:
        raise ScenarioError(f"Cannot read properties of {text_of(value)} (reading 'slice')")
    if isinstance(value, str):
        units = value.encode("utf-16-le", "surrogatepass")
        return units[2 * start: None if end is None else 2 * end].decode("utf-16-le", "surrogatepass")
    if isinstance(value, list):
        return JSArray(value[start:end])
    raise ScenarioError("item.text.slice is not a function")


def json_parse(value: Any) -> Any:
    """JSON.parse(value): a value that is not a string is first made one."""
    return parse(value if isinstance(value, str) else to_string(value))


def inputs(records: list[JSObject]) -> list[JSObject]:
    return [record for record in records if record["stage"] == "input"]


async def run(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


c14 = Scenario("C14", "Resume or rebuild the caller conversation",
               "continuity, reasons, history, map privacy, competing and failed runs",
               ["DRV-2.11", "DRV-2.12", "DRV-2.13", "DRV-2.34", "DRV-2.35", "DRV-6.11", "DRV-6.12", "DRV-6.14",
                "DRV-6.15"], run)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
