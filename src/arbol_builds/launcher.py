"""The records of the registry, and the launcher of a component (BLD-0, "Running a Build").

arbol-builds writes the text of this module, followed by one call of launch(), into the file
named after each component: that file is the launcher (service.write_launcher). The module
therefore uses the standard library only and imports nothing of this package. The tool imports
the same functions, so the launcher and the tool judge a record in the same way.
"""

import json
import os
import re
import signal
import sys  # noqa: F401  (the line arbol-builds appends calls sys.exit)
from datetime import datetime
from typing import Any

type Record = dict[str, Any]

COMPONENT_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
BUILD_PATTERN = re.compile(r"[1-9a-f][0-9a-f]*")
STATUSES = ("building", "failed", "working", "withdrawn")
SAFE_INTEGER = 2**53 - 1


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


def date(value: object) -> bool:
    if not text(value):
        return False
    try:
        datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return True


def positive(value: object) -> bool:
    """A whole number from 1 to 2**53 - 1, as JSON gives it: 1 and 1.0 count, true does not."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return float(value).is_integer() and 1 <= value <= SAFE_INTEGER


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
            with open(os.path.join(folder, build, "build.json"), encoding="utf-8") as stream:
                record: object = json.loads(stream.read(), parse_constant=refuse_constant)
        except (OSError, ValueError, RecursionError):
            continue
        if isinstance(record, dict) and valid_record(record, component, build):
            records.append(record)
    return sorted(records, key=lambda record: int(record["build"], 16), reverse=True)


def executable_entry(folder: str, entry: object) -> str | None:
    path = entry_path(folder, entry)
    if path is None:
        return None
    try:
        if not inside(os.path.realpath(folder), os.path.realpath(path)) or not os.path.isfile(path):
            return None
    except OSError:
        return None
    return path if os.access(path, os.X_OK) else None


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


def json_line(value: object) -> bytes:
    """One JSON document on one line. Text that is not valid Unicode is escaped, as JSON.stringify does."""
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8", "backslashreplace")


def write_all(fd: int, data: bytes) -> None:
    while data:
        data = data[os.write(fd, data):]


def launch(registry: str, component: str, args: list[str]) -> int:
    """Choose the Build and replace this process with its program; return a status only when it cannot."""
    # A Ctrl-C while the Build is being chosen ends the launcher quietly, as it would end the Build.
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
        if selected["status"] == "withdrawn":
            write_all(2, f"{component}@{selected['build']} is withdrawn: {selected['withdrawn']['reason']}\n"
                      .encode("utf-8", "backslashreplace"))
        if selected["status"] == "failed":
            failure = selected.get("failure")
            step = (f"{failure.get('stage')} {failure.get('name')}: {failure.get('message')}"
                    if isinstance(failure, dict) else "see build.log")
            write_all(2, f"{component}@{selected['build']} is failed: {step}\n".encode("utf-8", "backslashreplace"))
        entry = executable_entry(os.path.join(registry, component, selected["build"]), selected.get("entry"))
        if entry is None:
            raise OSError(f"The program of {component}@{selected['build']} is no longer there.")
        # Python ignores these two signals when it starts; a direct start would leave them at their default.
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
        os.execve(entry, [entry, *args], os.environ)
    except Exception as error:
        write_all(1, json_line({"error": {"code": "launch_failed", "message": str(error)}}))
        return 1
