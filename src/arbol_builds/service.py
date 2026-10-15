"""Building, listing, withdrawing and pruning Builds, and writing the launchers (BLD-0)."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from .config import Locations, description
from .launcher import (
    BUILD_PATTERN,
    LONE_SURROGATE,
    Record,
    default_record,
    executable_entry,
    numbered_folders,
    plain,
    read_records,
    runnable,
)
from .mutation import make_dirs, with_mutation_lock

LAUNCHER_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launcher.py")
LAUNCHER_MARK = "# arbol-builds launcher (BLD-0): written by arbol-builds, rewritten when it is installed again."
# The first statement of the launcher and of the tool: from here on a Ctrl-C ends the program quietly, as it would
# end the Build, and one that Python's start-up caught and printed is delivered again, so that it is not lost. A
# SIGINT the caller ignores stays ignored. _signal and sys are built in, so nothing is imported for them. A Ctrl-C
# while Python itself starts can still print "KeyboardInterrupt" (BLD-0, "Running a Build").
SIGINT_LINE = ("import _signal, sys; _signal.getsignal(_signal.SIGINT) is _signal.default_int_handler "
               "and _signal.signal(_signal.SIGINT, _signal.SIG_DFL); "
               "isinstance(getattr(sys, 'last_exc', None), KeyboardInterrupt) and _signal.raise_signal(_signal.SIGINT)")
# The kernel ends the interpreter path of a first line at a space or a "#".
SHEBANG_STOPS = " \t\n#"
SHEBANG_LIMIT = 500
STOP_SECONDS = 2.0


def now() -> str:
    """The time as JavaScript's toISOString gives it, which the records have always used."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def json_text(value: object, indent: int | None = None) -> bytes:
    """JSON as UTF-8. Text that is not valid Unicode is escaped, as JSON.stringify does."""
    if indent is None:
        dumped = json.dumps(plain(value), ensure_ascii=False, separators=(",", ":"))
    else:
        dumped = json.dumps(plain(value), ensure_ascii=False, indent=indent)
    return dumped.encode("utf-8", "backslashreplace")


def atomic_write(path: str, contents: bytes, mode: int = 0o600) -> None:
    temporary = f"{path}.{os.getpid()}.{uuid.uuid4()}.tmp"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def save_unlocked(folder: str, record: Record) -> None:
    atomic_write(os.path.join(folder, "build.json"), json_text(record, indent=2) + b"\n")


def save_record(folder: str, record: Record) -> None:
    with_mutation_lock(os.path.dirname(folder), lambda: save_unlocked(folder, record))


def reserve(registry: str, component: str) -> tuple[str, str]:
    """The folder and the number of a new Build: one more than the highest numbered folder."""
    root = os.path.join(registry, component)
    make_dirs(root, 0o700)
    number = max((int(name, 16) for name in numbered_folders(root)), default=0) + 1
    while True:
        build = format(number, "x")
        folder = os.path.join(root, build)
        try:
            os.mkdir(folder, 0o700)
            return folder, build
        except FileExistsError:
            number += 1


def launcher_source(registry: str, component: str, python: str) -> bytes:
    """A launcher: the text of launcher.py, then the call that serves this component and registry."""
    first = shebang(python)
    with open(LAUNCHER_SOURCE, encoding="utf-8") as stream:
        body = stream.read()
    call = f"sys.exit(launch({os.path.abspath(registry)!r}, {component!r}, sys.argv[1:]))"
    return f"{first}\n{LAUNCHER_MARK}\n{SIGINT_LINE}\n{body}\n{call}\n".encode("utf-8", "surrogateescape")


def shebang(python: str) -> str:
    """The first line that starts a program with this Python, or a refusal when the line cannot name it."""
    first = f"#!{python} -ISB"
    if (any(character.isspace() or character in SHEBANG_STOPS for character in python) or not os.path.isabs(python)
            or len(first.encode("utf-8", "surrogateescape")) > SHEBANG_LIMIT):
        raise ValueError(f"A program names its Python in its first line, which cannot hold {python}: "
                         "the path must be absolute and short, without a space or a '#'.")
    return first


def write_launcher(bin_folder: str, registry: str, component: str, python: str | None = None) -> None:
    """Write the launcher, started by the Python that runs this tool unless another is named."""
    source = launcher_source(registry, component, python or sys.executable)
    os.makedirs(bin_folder, exist_ok=True)
    atomic_write(os.path.join(bin_folder, component), source, 0o755)


class Stop:
    """Set by SIGINT or SIGTERM during a build: the running command's process group is stopped."""

    def __init__(self) -> None:
        self.requested = False
        self.group: int | None = None
        self.at = 0.0

    def request(self) -> None:
        if self.requested:
            return
        self.requested = True
        self.at = time.monotonic()
        if self.group is not None:
            signal_group(self.group, signal.SIGTERM)


def signal_group(group: int, number: signal.Signals) -> None:
    try:
        os.killpg(group, number)
    except (ProcessLookupError, PermissionError):
        pass  # the group is gone; macOS says EPERM while its last member waits to be reaped


def default_signals() -> None:
    """In the child: every signal at its default, as the earlier Node.js tool gave its commands."""
    for number in signal.valid_signals():
        if number in (signal.SIGKILL, signal.SIGSTOP):
            continue
        try:
            signal.signal(number, signal.SIG_DFL)
        except (OSError, ValueError):
            pass
    signal.pthread_sigmask(signal.SIG_SETMASK, set())


def command(text: str, repo: str, folder: str, number: str, log: int, stop: Stop) -> bool:
    """Run one build or check command in its own session, its output into the log."""
    # Text that is not valid Unicode reaches the shell and the log as U+FFFD, as with the Node.js tool.
    text = LONE_SURROGATE.sub("\ufffd", text)
    os.write(log, f"\n$ {text}\n".encode())
    if stop.requested:
        # Stopped before the command could start: logged as the Node.js tool logged it.
        os.write(log, b"Exit: SIGTERM (stopped by caller)\n")
        return False
    env = {**os.environ, "ARBOL_BUILD_DIR": folder, "ARBOL_BUILD_NUMBER": number}
    try:
        child = subprocess.Popen(["/bin/sh", "-c", text], cwd=repo, env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, start_new_session=True, preexec_fn=default_signals)
    except (OSError, ValueError) as error:
        os.write(log, f"Command could not start: {error}\n".encode("utf-8", "replace"))
        return False
    stop.group = child.pid
    if stop.requested:
        signal_group(child.pid, signal.SIGTERM)
    killed = False
    while True:
        try:
            code = child.wait(timeout=0.05)
            break
        except subprocess.TimeoutExpired:
            if stop.requested and not killed and time.monotonic() - stop.at > STOP_SECONDS:
                signal_group(child.pid, signal.SIGKILL)
                killed = True
    stop.group = None
    if stop.requested:
        signal_group(child.pid, signal.SIGKILL)
    ended = str(code) if code >= 0 else signal.Signals(-code).name
    os.write(log, f"Exit: {ended}{' (stopped by caller)' if stop.requested else ''}\n".encode())
    return code == 0 and not stop.requested


def build_component(component: str, paths: Locations, stop: Stop) -> Record:
    repo = os.path.abspath(paths.repo or os.path.join(os.path.expanduser("~"), "repos/sylvan-stack", component))
    config, version, source = description(repo, component)
    folder, build = reserve(paths.registry, component)
    record: Record = {"component": component, "build": build, "packageVersion": version, "status": "building",
                      "startedAt": now(), "source": source, "entry": config["entry"], "checks": []}
    for key in ("contract", "dataFormat"):
        if key in config:
            record[key] = int(config[key])  # a whole number, also when written 1.0
    save_record(folder, record)
    log = os.open(os.path.join(folder, "build.log"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    stage, name = "launcher", "launcher"
    try:
        write_launcher(paths.bin, paths.registry, component)
        stage = "build"
        for index, text in enumerate(config["build"], 1):
            name = f"build-{index}"
            if not command(text, repo, folder, build, log, stop):
                raise RuntimeError("Build stopped by the caller." if stop.requested
                                   else "Build command failed; see build.log.")
        stage, name = "entry", config["entry"]
        if executable_entry(folder, config["entry"]) is None:
            raise RuntimeError("The entry must be an executable file within the Build folder.")
        stage = "check"
        for check in config["checks"]:
            name = check["name"]
            passed = command(check["command"], repo, folder, build, log, stop)
            record["checks"].append({"name": name, "passed": passed})
            save_record(folder, record)
            if not passed:
                raise RuntimeError("Check stopped by the caller." if stop.requested else "Check failed; see build.log.")
        stage, name = "entry", config["entry"]
        if executable_entry(folder, config["entry"]) is None:
            raise RuntimeError("A check removed the Build entry.")
        record["status"] = "working"
    except Exception as error:
        record["status"] = "failed"
        record["failure"] = {"stage": stage, "name": name, "message": str(error)}
        os.write(log, LONE_SURROGATE.sub("\ufffd", f"\nFAILED {stage} {name}: {error}\n").encode())
    finally:
        os.close(log)
        record["finishedAt"] = now()
        save_record(folder, record)
    return record


def list_builds(registry: str, component: str | None = None) -> list[Record]:
    if component:
        components = [component]
    else:
        try:
            with os.scandir(registry) as entries:
                # In the order of JavaScript's sort: by UTF-16 code units.
                components = sorted((item.name for item in entries if item.is_dir(follow_symlinks=False)),
                                    key=lambda name: name.encode("utf-16-be", "surrogatepass"))
        except FileNotFoundError:
            components = []
    listed: list[Record] = []
    for name in components:
        records = read_records(registry, name)
        selected = default_record(registry, records)
        listed.extend({**record, "default": selected is not None and record["build"] == selected["build"]}
                      for record in records)
    return listed


def show_build(registry: str, component: str, number: str | None = None) -> Record:
    if number is not None and BUILD_PATTERN.fullmatch(number) is None:
        raise ValueError("A build number is lower-case hexadecimal, without leading zero.")
    records = read_records(registry, component)
    found = (default_record(registry, records) if number is None
             else next((record for record in records if record["build"] == number), None))
    if found is None:
        raise ValueError(f"No {'default' if number is None else number} Build of {component}.")
    return found


def withdraw_build(registry: str, component: str, number: str, reason: str) -> Record:
    def change() -> Record:
        record = show_build(registry, component, number)
        if record["status"] != "working" or not runnable(registry, record):
            raise ValueError("Only a working, unpruned Build can be withdrawn.")
        record["status"] = "withdrawn"
        record["withdrawn"] = {"at": now(), "reason": reason}
        save_unlocked(os.path.join(registry, component, number), record)
        return record

    return with_mutation_lock(os.path.join(registry, component), change)


def missing_only(function: Any, path: str, error: BaseException) -> None:
    if not isinstance(error, FileNotFoundError):
        raise error


def prune_builds(registry: str, component: str, keep: int) -> dict[str, Any]:
    def change() -> dict[str, Any]:
        working = [record for record in read_records(registry, component)
                   if record["status"] == "working" and not record.get("prunedAt")]
        selected = default_record(registry, working)
        pruned: list[str] = []
        for record in working[keep:]:
            if selected is not None and record["build"] == selected["build"]:
                continue
            folder = os.path.join(registry, component, record["build"])
            # Mark unavailable before removing files: a partly pruned Build cannot be started.
            record["prunedAt"] = now()
            save_unlocked(folder, record)
            for item in os.listdir(folder):
                if item in ("build.json", "build.log"):
                    continue
                path = os.path.join(folder, item)
                # Only a file that is already gone is ignored, as with Node.js rm --force; any other failure stops.
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path, onexc=missing_only)
                else:
                    try:
                        os.unlink(path)
                    except FileNotFoundError:
                        pass
            pruned.append(record["build"])
        return {"component": component, "pruned": pruned}

    return with_mutation_lock(os.path.join(registry, component), change)
