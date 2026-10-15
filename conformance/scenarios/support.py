"""What the scenarios share: JavaScript's array and date helpers, and Node's file functions with Node's errors."""

from __future__ import annotations

import asyncio
import math
import os
import re
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from stat import S_ISDIR
from typing import Any

from ..check import ScenarioError
from ..harness import FileError, fs_error, remove
from ..inspect import _escape, _utf16_cut
from ..js import (
    UNDEFINED,
    JSArray,
    JSObject,
    get,
    is_number,
    len16,
    parse,
    same_value,
    text_of,
    truthy,
    well_formed,
)

# --- JavaScript ------------------------------------------------------------------------------------------


async def delay(ms: float) -> None:
    await asyncio.sleep(ms / 1000)


def _no_method(items: Any, method: str) -> TypeError:
    """V8's TypeError for `items.<method>(...)` on a value that has no such method."""
    if items is None or items is UNDEFINED:
        return TypeError(f"Cannot read properties of {'null' if items is None else 'undefined'} (reading '{method}')")
    return TypeError(f"items.{method} is not a function")


def _array(items: Any, method: str) -> Any:
    """The receiver of an Array.prototype method: an array, or V8's TypeError for a JSON value that is not one."""
    if items is None or items is UNDEFINED or isinstance(items, dict | str | bool | int | float):
        raise _no_method(items, method)
    return items


def _units(text: str) -> list[str]:
    """The UTF-16 units of a string, each as a one-unit str (a surrogate of a pair stays alone)."""
    data = text.encode("utf-16-le", "surrogatepass")
    return [data[i:i + 2].decode("utf-16-le", "surrogatepass") for i in range(0, len(data), 2)]


def strictly_equal(a: Any, b: Any) -> bool:
    """`a === b`: numbers by value (NaN is never equal, -0 is 0), objects and arrays by identity."""
    if is_number(a) and is_number(b):
        return float(a) == float(b)
    if isinstance(a, dict | list) or isinstance(b, dict | list):
        return a is b
    return same_value(a, b)


def find(items: Iterable[Any], predicate: Callable[[Any], Any]) -> Any:
    """Array.prototype.find: the first match, or undefined."""
    for item in _array(items, "find"):
        if truthy(predicate(item)):
            return item
    return UNDEFINED


def index_of(items: list[Any] | str, value: Any) -> int:
    """Array.prototype.indexOf (strict equality) or String.prototype.indexOf (UTF-16 index); -1 when absent."""
    if isinstance(items, str):
        units = items.encode("utf-16-le", "surrogatepass")
        wanted = text_of(value).encode("utf-16-le", "surrogatepass")
        position = units.find(wanted)
        while position > 0 and position % 2:  # a match must start at a whole UTF-16 unit
            position = units.find(wanted, position + 1)
        return position // 2 if position >= 0 else -1
    for index, entry in enumerate(_array(items, "indexOf")):
        if strictly_equal(entry, value):
            return index
    return -1


def at(items: list[Any] | str, index: int) -> Any:
    """Array.prototype.at or String.prototype.at (a UTF-16 unit): a negative index counts from the end."""
    sequence = _units(items) if isinstance(items, str) else _array(items, "at")
    position = index + len(sequence) if index < 0 else index
    return sequence[position] if 0 <= position < len(sequence) else UNDEFINED


def item(items: Any, index: int) -> Any:
    """items[index] in JavaScript: undefined outside the array, also for -1; a TypeError on null and undefined."""
    if items is None or items is UNDEFINED:
        raise TypeError(f"Cannot read properties of {text_of(items)} (reading '{text_of(index)}')")
    return get(items, index)


def includes(items: Any, value: Any) -> bool:
    """Array.prototype.includes (SameValueZero) or String.prototype.includes."""
    if isinstance(items, str):
        return index_of(items, value) >= 0
    for entry in _array(items, "includes"):
        if is_number(entry) and is_number(value):
            if float(entry) == float(value) or (math.isnan(float(entry)) and math.isnan(float(value))):
                return True
        elif not isinstance(entry, dict | list) and same_value(entry, value):
            return True
        elif entry is value:
            return True
    return False


def is_integer(value: Any) -> bool:
    """Number.isInteger."""
    return is_number(value) and math.isfinite(float(value)) and float(value).is_integer()


def is_finite(value: Any) -> bool:
    """Number.isFinite."""
    return is_number(value) and math.isfinite(float(value))


ISO = re.compile(r"([+-]\d{6}|\d{4})(?:-(\d{2})(?:-(\d{2}))?)?"
                 r"(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:\d{2})?)?", re.ASCII)


def date_parse(value: Any) -> float:
    """Date.parse for the ECMAScript date-time format: milliseconds since 1970, or NaN."""
    if not isinstance(value, str):
        return math.nan
    match = ISO.fullmatch(value)
    if match is None:
        return math.nan
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    if year == "-000000" or (month and not 1 <= int(month) <= 12) or (day and not 1 <= int(day) <= 31):
        return math.nan
    if hour is not None and (int(hour) > 24 or int(minute) > 59 or int(second or 0) > 59
                             or (int(hour) == 24 and (int(minute) or int(second or 0) or int(fraction or 0)))):
        return math.nan
    if zone not in (None, "Z") and (int(zone[1:3]) > 23 or int(zone[4:6]) > 59):
        return math.nan
    y, m = int(year), int(month or 1)
    y -= m <= 2
    era = y // 400
    of_era = y - era * 400
    of_year = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + int(day or 1) - 1
    days = era * 146097 + of_era * 365 + of_era // 4 - of_era // 100 + of_year - 719468
    milliseconds: float = (days * 86_400_000 + ((int(hour or 0) * 60 + int(minute or 0)) * 60 + int(second or 0)) * 1000
                    + int((fraction or "")[:3].ljust(3, "0")))
    if zone not in (None, "Z"):
        offset = (int(zone[1:3]) * 60 + int(zone[4:6])) * 60_000
        milliseconds += -offset if zone[0] == "+" else offset
    elif zone is None and hour is not None:
        milliseconds -= _local_offset(milliseconds)
    return float(milliseconds) if abs(milliseconds) <= 8_640_000_000_000_000 else math.nan


def _offset_at(instant: float) -> int:
    """The local zone's offset from UTC in milliseconds at an instant (milliseconds since 1970)."""
    return time.localtime(math.floor(instant / 1000)).tm_gmtoff * 1000


def _local_offset(local: float) -> int:
    """The offset of a local date and time, as ECMAScript's UTC(t) picks it: for a time that a change of offset
    skips or repeats, the offset in force before the change."""
    day = 86_400_000
    try:
        before, after = _offset_at(local - day), _offset_at(local + day)
        instants = [local - offset for offset in dict.fromkeys((before, after)) if _offset_at(local - offset) == offset]
    except (OverflowError, OSError, ValueError):
        return 0
    return int(local - min(instants)) if instants else before


def now_iso() -> str:
    """new Date().toISOString()."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now_ms() -> float:
    """Date.now()."""
    return math.floor(datetime.now(UTC).timestamp() * 1000)


def test(pattern: str, value: Any, flags: int = 0) -> bool:
    """RegExp.prototype.test with JavaScript's ASCII \\d and \\w; the value is converted with String() first.

    Write JavaScript's `$` as `\\Z` (Python's `$` also matches before a final newline) and JavaScript's `\\s` as
    SPACE_CLASS."""
    return re.search(pattern, value if isinstance(value, str) else text_of(value), re.ASCII | flags) is not None


def js_map(items: list[Any], function: Callable[[Any], Any]) -> JSArray:
    return JSArray(function(entry) for entry in items)


# --- Node's file functions -------------------------------------------------------------------------------


def inspected(value: str) -> str:
    """util.inspect(value) for a string with Node's default options: a line of 128 columns, 10000 characters."""
    trailer = ""
    size = len16(value)
    if size > 10000:
        trailer = f"... {size - 10000} more character{'s' if size - 10000 > 1 else ''}"
        value, size = _utf16_cut(value, 10000), 10000
    if size > 16 and size > 128 - 4:
        return " +\n  ".join(_escape(piece) for piece in re.split(r"(?<=\n)", value) if piece) + trailer
    return _escape(value) + trailer


def null_check(path: str, name: str = "path") -> None:
    """Node's check of a path argument, before any system call: a NUL character is refused."""
    if "\0" in path:
        received = inspected(path)
        if len16(received) > 128:
            received = _utf16_cut(received, 128) + "..."
        raise ScenarioError(f"The argument '{name}' must be a string, Uint8Array, or URL without null bytes. "
                            f"Received {received}")


def read_file(path: str) -> str:
    """readFile(path, 'utf8'): bytes that are not UTF-8 read as U+FFFD; a byte-order mark stays."""
    null_check(path)
    try:
        with open(path, "rb") as stream:
            return stream.read().decode("utf-8", "replace")
    except IsADirectoryError as error:
        raise fs_error(error, "read") from None
    except OSError as error:
        raise fs_error(error, "open", path) from None


def read_json(path: str) -> Any:
    """JSON.parse(await readFile(path, 'utf8'))."""
    return parse(read_file(path))


def write_file(path: str, text: str | bytes, mode: int = 0o666) -> None:
    """writeFile(path, data): the mode applies only when the file is created; a lone surrogate is written as
    U+FFFD, as Node encodes a string."""
    null_check(path)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    except OSError as error:
        raise fs_error(error, "open", path) from None
    with os.fdopen(fd, "wb") as stream:
        stream.write(text if isinstance(text, bytes) else well_formed(text).encode("utf-8"))


def mkdir(path: str, recursive: bool = False, mode: int = 0o777) -> None:
    null_check(path)
    try:
        if recursive:
            os.makedirs(path, mode, exist_ok=True)
        else:
            os.mkdir(path, mode)
    except OSError as error:
        raise fs_error(error, "mkdir", path) from None


def readdir(path: str) -> JSArray:
    """readdir(path): names sorted by their bytes, as libuv returns them; bytes that are not UTF-8 as U+FFFD."""
    null_check(path)
    try:
        names = sorted(os.listdir(path), key=os.fsencode)
    except OSError as error:
        raise fs_error(error, "scandir", path) from None
    return JSArray(name.encode("utf-8", "surrogateescape").decode("utf-8", "replace") for name in names)


class Stats:
    def __init__(self, result: os.stat_result) -> None:
        self.mode = float(result.st_mode)
        self.size = float(result.st_size)
        self.mtime_ms = result.st_mtime_ns / 1_000_000
        self._result = result

    def is_file(self) -> bool:
        return (self._result.st_mode & 0o170000) == 0o100000

    def is_directory(self) -> bool:
        return (self._result.st_mode & 0o170000) == 0o040000

    def is_symbolic_link(self) -> bool:
        return (self._result.st_mode & 0o170000) == 0o120000


def stat(path: str) -> Stats:
    null_check(path)
    try:
        return Stats(os.stat(path))
    except OSError as error:
        raise fs_error(error, "stat", path) from None


def lstat(path: str) -> Stats:
    null_check(path)
    try:
        return Stats(os.lstat(path))
    except OSError as error:
        raise fs_error(error, "lstat", path) from None


def exists(path: str) -> bool:
    """stat(path) succeeds."""
    try:
        os.stat(path)
    except (OSError, ValueError):
        return False
    return True


def readlink(path: str) -> str:
    null_check(path, "oldPath")
    try:
        return os.readlink(path)
    except OSError as error:
        raise fs_error(error, "readlink", path) from None


def symlink(target: str, path: str) -> None:
    null_check(target, "target")
    null_check(path)
    try:
        os.symlink(target, path)
    except OSError as error:
        failure = fs_error(error, "symlink", target)
        raise FileError(f"{failure.message} -> '{path}'", failure.code) from None


def chmod(path: str, mode: int) -> None:
    null_check(path)
    try:
        os.chmod(path, mode)
    except OSError as error:
        raise fs_error(error, "chmod", path) from None


def rm(path: str, recursive: bool = False, force: bool = False) -> None:
    """fs.promises.rm: an lstat first (with `force` a missing path is fine), a folder only with `recursive`, then
    Node's rimraf, with Node's texts."""
    null_check(path)
    try:
        status = os.lstat(path)
    except OSError as error:
        if force and isinstance(error, FileNotFoundError):
            return
        raise fs_error(error, "lstat", path) from None
    if S_ISDIR(status.st_mode) and not recursive:
        raise FileError(f"Path is a directory: rm returned EISDIR (is a directory) {path}", "ERR_FS_EISDIR")
    remove(path)


def alive(pid: Any) -> bool:
    """process.kill(pid, 0) succeeds; Node refuses a pid that is not a 32-bit integer."""
    if not is_number(pid) or not math.isfinite(float(pid)) or float(pid) != int(float(pid)) \
            or not -2**31 <= int(float(pid)) < 2**31:
        return False
    try:
        os.kill(int(float(pid)), 0)
    except (OSError, ValueError, TypeError, OverflowError):
        return False
    return True


def record(**fields: Any) -> JSObject:
    """An object literal, in the order written."""
    return JSObject(fields)


def now_monotonic() -> float:
    """performance.now(): milliseconds on a clock that never goes back."""
    return asyncio.get_running_loop().time() * 1000


def find_by(items: Iterable[Any], field: str, value: Any) -> Any:
    """items.find(entry => entry[field] === value); an entry that is null or undefined throws, as in JavaScript."""
    for entry in _array(items, "find"):
        if entry is None or entry is UNDEFINED:
            raise TypeError(f"Cannot read properties of {'null' if entry is None else 'undefined'} (reading '{field}')")
        if strictly_equal(get(entry, field), value):
            return entry
    return UNDEFINED
