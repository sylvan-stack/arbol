"""Narrow process identity for cooperative admission, never an ancestry oracle.

DRV-6.21 uses exact kernel microseconds. Historical Driver owner records and
vendor cleanup rules are not rewritten by this new shared representation.
The library and fixed sysctl command are called only during admitted execution.
"""

from __future__ import annotations

import ctypes
import errno
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from .driver_admission import LIMIT, Object, canonical_uuid, natural, refuse

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_SECONDS = 253402300799
_STARTED = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})\.([0-9]{6})Z\Z", re.ASCII)


class BsdInfo(ctypes.Structure):
    """Public sys/proc_info.h proc_bsdinfo, qualified 64-bit Darwin layout."""

    _fields_ = [
        ("flags", ctypes.c_uint32), ("status", ctypes.c_uint32), ("xstatus", ctypes.c_uint32),
        ("pid", ctypes.c_uint32), ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32), ("rgid", ctypes.c_uint32),
        ("svuid", ctypes.c_uint32), ("svgid", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
        ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32), ("jobc", ctypes.c_uint32),
        ("tdev", ctypes.c_uint32), ("tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32),
        ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64),
    ]


@lru_cache(maxsize=1)
def library() -> ctypes.CDLL:
    if (sys.platform != "darwin" or ctypes.sizeof(ctypes.c_void_p) != 8
            or ctypes.sizeof(BsdInfo) != 136 or ctypes.alignment(BsdInfo) != 8
            or BsdInfo.pid.offset != 12 or BsdInfo.status.offset != 4
            or BsdInfo.start_sec.offset != 120 or BsdInfo.start_usec.offset != 128):
        refuse()
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.restype = ctypes.c_int
    except (OSError, AttributeError):
        refuse()
    return lib


def start_string(seconds: int, microseconds: int) -> str:
    if (not natural(seconds, positive=True) or seconds > _MAX_SECONDS
            or not natural(microseconds) or microseconds >= 1000000):
        refuse()
    try:
        # Integer timedelta arithmetic preserves tvusec; no floating epoch roundtrip.
        value = _EPOCH + timedelta(seconds=seconds, microseconds=microseconds)
    except (OverflowError, ValueError):
        refuse()
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def valid_start(value: object) -> bool:
    if not isinstance(value, str) or (match := _STARTED.fullmatch(value)) is None:
        return False
    try:
        year, month, day, hour, minute, second, microsecond = map(int, match.groups())
        parsed = datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC)
        return parsed >= _EPOCH and parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") == value
    except ValueError:
        return False


def identity_record(value: object) -> Object:
    if (not isinstance(value, dict) or set(value) != {"pid", "startedAt"}
            or not natural(value["pid"], positive=True) or value["pid"] > 2**31 - 1
            or not valid_start(value["startedAt"])):
        refuse()
    return value


@dataclass(frozen=True)
class Process:
    owner: Object
    parent: int
    group: int


def inspect(pid: int) -> Process | None:
    if not natural(pid, positive=True) or pid > 2**31 - 1:
        refuse()
    value = BsdInfo()
    ctypes.set_errno(0)
    size = library().proc_pidinfo(pid, 3, 0, ctypes.byref(value), ctypes.sizeof(value))
    error = ctypes.get_errno()
    if not size and error == errno.ESRCH:
        return None
    if size != 136 or value.pid != pid:
        refuse()
    if value.status == 5:  # Public sys/proc.h SZOMB is not a live identity.
        return None
    if value.status not in (2, 3, 4) or value.uid != os.getuid() or not value.ppid:
        refuse()  # SIDL/unknown/inaccessible observations supply no authority.
    owner = {"pid": pid, "startedAt": start_string(value.start_sec, value.start_usec)}
    return Process(identity_record(owner), int(value.ppid), int(value.pgid))


def process_identity(pid: int) -> Object:
    value = inspect(pid)
    if value is None:
        refuse()
    return value.owner


def matches(owner: Object, *, parent: int | None = None) -> bool:
    identity_record(owner)
    current = inspect(owner["pid"])
    return (current is not None and current.owner == owner
            and (parent is None or current.parent == parent))


def boot_uuid() -> str:
    if sys.platform != "darwin":
        refuse()
    try:
        result = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"], check=False,
                                capture_output=True, timeout=5,
                                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        if result.returncode or not 0 < len(result.stdout) <= LIMIT:
            refuse()
        lines = result.stdout.decode("ascii", "strict").splitlines()
        if len(lines) != 1:
            refuse()
        value = lines[0].strip().lower()
        if not canonical_uuid(value):
            refuse()
        return value
    except (OSError, UnicodeError, subprocess.SubprocessError):
        refuse()
