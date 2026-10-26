"""The records of the registry, and the launcher of a component (BLD-0, "Running a Build").

arbol-builds writes the text of this module, followed by one call of launch(), into the file
named after each component: that file is the launcher (service.write_launcher). The launcher
arbol-trunk holds it too, before the text of roots.py and trunk_launcher.py. The module
therefore uses the standard library only and imports nothing of this package. The tool imports
the same functions, so the launcher and the tool judge a record in the same way.
"""

import json
import os
import re
import select
import signal
import sys  # noqa: F401  (the line arbol-builds appends calls sys.exit)
import time
from typing import Any

type Record = dict[str, Any]

COMPONENT_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
BUILD_PATTERN = re.compile(r"[1-9a-f][0-9a-f]*")
# A Trunk is the component arbol-trunk/<code name>; arbol-trunk alone is the folder of the Trunks (RCT-0).
TRUNKS = "arbol-trunk"
CODE_NAME = re.compile(r"[a-z][a-z0-9]{0,31}")
COMMAND_WORDS = ("run", "settle", "list")
# The components whose Builds are made for one Root, and the form of a Root identifier (ARC-1, RCT-0).
ROOT_COMPONENTS = ("arbol", "arbol-root")
ROOT_PATTERN = re.compile(r"[a-z0-9]+")
STATUSES = ("building", "failed", "working", "withdrawn")
SAFE_INTEGER = 2**53 - 1
# The ECMAScript date-time string format, which the records have always used (toISOString writes it).
# Digits are ASCII only, as in JavaScript.
DATE = re.compile(r"([+-]\d{6}|\d{4})(?:-(\d{2})(?:-(\d{2}))?)?"
                  r"(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:\d{2})?)?", re.ASCII)
# JavaScript's TimeClip: a time lies within 8.64e15 milliseconds of 1970.
TIME_LIMIT = 8_640_000_000_000_000
# Python reads at most this many digits as an integer; a longer JSON number is read as JavaScript reads it.
INTEGER_DIGITS = 4300
LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def inside(folder: str, path: str) -> bool:
    """Whether path lies strictly within folder."""
    relative = os.path.relpath(path, folder)
    return relative not in (".", "..") and not relative.startswith(".." + os.sep) and not os.path.isabs(relative)


def entry_path(folder: str, entry: object) -> str | None:
    if not isinstance(entry, str) or entry == "" or os.path.isabs(entry):
        return None
    path = os.path.normpath(os.path.join(folder, entry))
    return path if inside(folder, path) else None


def text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def days_from_civil(year: int, month: int, day: int) -> int:
    """Days from 1970-01-01 to a date of the proleptic Gregorian calendar (Howard Hinnant's algorithm)."""
    year -= month <= 2
    era = year // 400
    of_era = year - era * 400
    of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    return era * 146097 + of_era * 365 + of_era // 4 - of_era // 100 + of_year - 719468


def date(value: object) -> bool:
    """A time in the ECMAScript date-time string format that Date.parse accepts; other forms count as damaged
    (BLD-D15)."""
    return milliseconds(value) is not None


def milliseconds(value: object) -> int | None:
    """The time Date.parse gives a text in the ECMAScript date-time string format, in milliseconds since 1970, or
    None for a text in any other form."""
    match = DATE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    if year == "-000000" or (month and not 1 <= int(month) <= 12) or (day and not 1 <= int(day) <= 31):
        return None
    if hour is not None and (int(hour) > 24 or int(minute) > 59 or int(second or 0) > 59
                             or (int(hour) == 24 and (int(minute) or int(second or 0) or int(fraction or 0)))):
        return None
    if zone not in (None, "Z") and (int(zone[1:3]) > 23 or int(zone[4:6]) > 59):
        return None
    total = (days_from_civil(int(year), int(month or 1), int(day or 1)) * 86_400_000
             + ((int(hour or 0) * 60 + int(minute or 0)) * 60 + int(second or 0)) * 1000
             + int((fraction or "")[:3].ljust(3, "0")))
    if zone not in (None, "Z"):
        offset = (int(zone[1:3]) * 60 + int(zone[4:6])) * 60_000
        total += -offset if zone[0] == "+" else offset
    elif zone is None and hour is not None:
        total -= time.localtime().tm_gmtoff * 1000  # a date-time without an offset is local time
    return total if abs(total) <= TIME_LIMIT else None


def positive(value: object) -> bool:
    """A whole number from 1 to 2**53 - 1, as JSON gives it: 1 and 1.0 count, true does not."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 1 <= value <= SAFE_INTEGER
    return isinstance(value, float) and value.is_integer() and 1 <= value <= SAFE_INTEGER


def trunk(component: str) -> bool:
    """Whether the component is a Trunk, arbol-trunk/<code name>."""
    return component.startswith(TRUNKS + "/")


def code_name(code: str) -> bool:
    """A Trunk's code name: one lower-case word of 1 to 32 letters and digits that starts with a letter, and no
    command word of the Root Contract (RCT-0)."""
    return CODE_NAME.fullmatch(code) is not None and code not in COMMAND_WORDS


def root_identifier(value: object) -> bool:
    return isinstance(value, str) and ROOT_PATTERN.fullmatch(value) is not None


def root_contracts(value: object) -> bool:
    """The versions of the Root Contract a Trunk implements: a nonempty list of distinct positive whole numbers."""
    return (isinstance(value, list) and bool(value) and all(positive(item) for item in value)
            and len({int(item) for item in value}) == len(value))


def valid_record(value: object, component: str, build: str) -> bool:
    if (not isinstance(value, dict) or value.get("component") != component or value.get("build") != build
            or BUILD_PATTERN.fullmatch(build) is None or not text(value.get("packageVersion"))
            or not date(value.get("startedAt")) or value.get("status") not in STATUSES):
        return False
    source = value.get("source")
    if (not isinstance(source, dict) or not all(text(source.get(key)) for key in ("repository", "branch", "commit"))
            or not isinstance(source.get("uncommittedChanges"), bool)):
        return False
    checks = value.get("checks")
    if not isinstance(checks, list) or not all(
            isinstance(check, dict) and text(check.get("name")) and isinstance(check.get("passed"), bool)
            for check in checks):
        return False
    if any(key in value and not positive(value[key]) for key in ("contract", "dataFormat")):
        return False
    # A Build of arbol or arbol-root names its Root, and a Trunk's Build the Root Contract versions it implements.
    if ("root" in value or component in ROOT_COMPONENTS) and not root_identifier(value.get("root")):
        return False
    if ("rootContracts" in value or trunk(component)) and not root_contracts(value.get("rootContracts")):
        return False
    if any(key in value and not date(value[key]) for key in ("finishedAt", "prunedAt")):
        return False
    if "entry" in value and entry_path("/build", value["entry"]) is None:
        return False
    if value["status"] in ("working", "withdrawn") and (
            not date(value.get("finishedAt")) or not text(value.get("entry")) or not checks
            or any(check["passed"] is not True for check in checks)):
        return False
    if value["status"] == "withdrawn":
        withdrawn = value.get("withdrawn")
        if not isinstance(withdrawn, dict) or not date(withdrawn.get("at")) or not text(withdrawn.get("reason")):
            return False
    return True


def refuse_constant(name: str) -> object:
    raise ValueError(f"{name} is not JSON")


def js_integer(text: str) -> int | float:
    """A JSON integer; one longer than Python reads becomes a float, infinite when too large, as in JavaScript."""
    return int(text) if len(text) <= INTEGER_DIGITS else float(text)


def numbered_folders(folder: str) -> list[str]:
    try:
        with os.scandir(folder) as entries:
            return [item.name for item in entries
                    if item.is_dir(follow_symlinks=False) and BUILD_PATTERN.fullmatch(item.name)]
    except FileNotFoundError:
        return []


def read_records(registry: str, component: str) -> list[Record]:
    """The valid records of a component, newest first. A damaged or missing record hides only its own Build."""
    folder = os.path.join(registry, component)
    records: list[Record] = []
    for build in numbered_folders(folder):
        try:
            # Bytes that are not UTF-8 read as U+FFFD, as the Node.js tool read them.
            with open(os.path.join(folder, build, "build.json"), encoding="utf-8", errors="replace") as stream:
                record: object = json.loads(stream.read(), parse_constant=refuse_constant, parse_int=js_integer)
            if isinstance(record, dict) and valid_record(record, component, build):
                records.append(record)
        except Exception:
            continue
    return sorted(records, key=lambda record: int(record["build"], 16), reverse=True)


def executable_entry(folder: str, entry: object) -> str | None:
    path = entry_path(folder, entry)
    if path is None:
        return None
    try:
        if (not inside(os.path.realpath(folder), os.path.realpath(path)) or not os.path.isfile(path)
                or not os.access(path, os.X_OK)):
            return None
    except (OSError, ValueError):  # ValueError: a path with a zero byte or a lone surrogate
        return None
    return path


def runnable(registry: str, record: Record) -> bool:
    return (not record.get("prunedAt") and record["status"] in ("working", "withdrawn")
            and executable_entry(os.path.join(registry, record["component"], record["build"]),
                                 record.get("entry")) is not None)


def named_runnable(registry: str, record: Record) -> bool:
    """A Build named with -v: also a failed one whose program is there (BLD-D13). Never one still building."""
    return runnable(registry, record) or (
        not record.get("prunedAt") and record["status"] == "failed"
        and executable_entry(os.path.join(registry, record["component"], record["build"]),
                             record.get("entry")) is not None)


def default_record(registry: str, records: list[Record]) -> Record | None:
    return next((record for record in records if record["status"] == "working" and runnable(registry, record)), None)


def plain(value: object) -> object:
    """Numbers as JSON.stringify writes them: a whole number without ".0", and null for one that is not finite."""
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return int(value) if value.is_integer() and abs(value) < 1e21 else value
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


def json_line(value: object) -> bytes:
    """One JSON document on one line. Text that is not valid Unicode is escaped, as JSON.stringify does."""
    return (json.dumps(plain(value), ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8", "backslashreplace")


def readable(value: object) -> bytes:
    """Text for a person, as UTF-8: a lone surrogate shows as U+FFFD."""
    return LONE_SURROGATE.sub("\ufffd", str(value)).encode("utf-8", "replace")


def write_all(fd: int, data: bytes) -> None:
    """Write everything, also to a descriptor the caller left non-blocking."""
    while data:
        try:
            data = data[os.write(fd, data):]
        except BlockingIOError:
            select.select([], [fd], [])


def standard_descriptors() -> None:
    """A closed standard input, output or error becomes /dev/null, as Node.js does when it starts."""
    for fd in (0, 1, 2):
        try:
            os.fstat(fd)
        except OSError:
            # Inheritable, so that the Build and the commands receive it too.
            os.set_inheritable(os.open(os.devnull, os.O_RDWR), True)


def warning(component: str, record: Record) -> str | None:
    """The line on standard error that says a Build named with -v is withdrawn, with the reason, or failed, with the
    step that failed (BLD-D13); None for a working one."""
    if record["status"] == "withdrawn":
        return f"{component}@{record['build']} is withdrawn: {record['withdrawn']['reason']}\n"
    if record["status"] == "failed":
        failure = record.get("failure")
        step = (f"{failure.get('stage')} {failure.get('name')}: {failure.get('message')}"
                if isinstance(failure, dict) else "see build.log")
        return f"{component}@{record['build']} is failed: {step}\n"
    return None


def record_start(folder: str) -> None:
    """Best-effort last-start replacement, without a lock, retry or flush (BLD-0.24, BLD-D19).

    Run before restoring SIGXFSZ: Python ignores it, so a file-size limit becomes a caught write error.
    Only a complete timestamp replaces the old one, and only our own temporary file is removed.
    """
    stamp = time.time_ns()
    temporary = os.path.join(folder, f"last-start.{os.getpid()}.{stamp}.tmp")
    created = False
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(fd, "wb") as stream:
            value = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(stamp // 1_000_000_000))
            stream.write(f"{value}.{stamp // 1_000_000 % 1000:03d}Z\n".encode("ascii"))
        os.replace(temporary, os.path.join(folder, "last-start"))
    except OSError:
        pass  # start the Build even when its folder cannot record the start
    finally:
        if created:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def launch(registry: str, component: str, args: list[str]) -> int:
    """Choose the Build and replace this process with its program; return a status only when it cannot."""
    standard_descriptors()
    # A Ctrl-C while the Build is being chosen ends the launcher quietly, as it would end the Build;
    # a SIGINT the caller ignores stays ignored. (The launcher's first lines do the same, earlier.)
    if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        records = read_records(registry, component)
        available = [record["build"] for record in records if named_runnable(registry, record)]
        selected: Record | None = None
        if args[:1] == ["-v"]:
            number = args[1] if len(args) > 1 else ""
            if number and BUILD_PATTERN.fullmatch(number):
                selected = next((record for record in records
                                 if record["build"] == number and named_runnable(registry, record)), None)
            args = args[2:]
        else:
            selected = default_record(registry, records)
        if selected is None:
            message = (f"No runnable Build selected for {component}. "
                       f"Available Builds: {', '.join(available) or 'none'}.")
            write_all(1, json_line({"error": {"code": "build_unavailable", "message": message, "available": available}}))
            return 1
        line = warning(component, selected)
        if line is not None:
            try:
                write_all(2, readable(line))
            except OSError:
                pass  # the warning is a courtesy; the Build starts without it
        entry = executable_entry(os.path.join(registry, component, selected["build"]), selected.get("entry"))
        if entry is None:
            raise OSError(f"The program of {component}@{selected['build']} is no longer there.")
        record_start(os.path.join(registry, component, selected["build"]))
        # Python ignores these two signals when it starts; a direct start would leave them at their default.
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
        # execv passes the process's own environment exactly as the caller gave it.
        os.execv(entry, [entry, *args])
    except Exception as error:
        try:
            write_all(1, json_line({"error": {"code": "launch_failed", "message": str(error)}}))
        except OSError:
            pass
        return 1
