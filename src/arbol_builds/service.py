"""Building, listing, withdrawing and pruning Builds, and writing the launchers (BLD-0)."""

import ast
import fcntl
import json
import os
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any

from arbol_installation.admission import Admission, AdmissionRefusal, runtime_folder
from arbol_installation.build_output import unseal_directories
from arbol_installation.paths import build_payload_directory, build_registry, prepare_installation

from .config import Locations, default_repository, description, load_json
from .launcher import (
    BUILD_PATTERN,
    DRIVER_LAUNCHER_MARK,
    LONE_SURROGATE,
    TRUNKS,
    Record,
    backend_fits,
    code_name,
    default_record,
    executable_entry,
    installation_layout,
    numbered_folders,
    open_use_guard,
    plain,
    read_records,
    runnable,
    schema_compatibility,
    trunk,
)
from .mutation import make_dirs, with_mutation_lock
from .schema_state import SCHEMA_ERRORS, SchemaState, read_schema
from .trunk_launcher import chosen

if TYPE_CHECKING:
    from .driver_payload import Payload

PACKAGE = os.path.dirname(os.path.abspath(__file__))
# The shared Trunk launcher embeds the registry reader, the schema reader and the selector.
TRUNK_MODULES = ("launcher.py", "schema_state.py", "trunk_launcher.py")
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
    def change() -> None:
        # The builder owns the lifecycle fields. Lock/unlock owns this mark, including its absence (BLD-D20).
        try:
            current = load_json(os.path.join(folder, "build.json"))
        except FileNotFoundError:
            current = {}
        if isinstance(current, dict) and "lockedAt" in current:
            record["lockedAt"] = current["lockedAt"]
        else:
            record.pop("lockedAt", None)
        save_unlocked(folder, record)

    with_mutation_lock(os.path.dirname(folder), change)


def reserve(registry: str, component: str) -> tuple[str, str]:
    """The folder and the number of a new Build: one more than the highest numbered folder."""
    if Path(registry).resolve() == build_registry().resolve():
        prepare_installation()
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


def module_text(name: str, folder: Path = Path(PACKAGE)) -> str:
    """Inline a module, omitting imports supplied by the preceding launcher source."""
    source = (folder / name).read_text(encoding="utf-8")
    lines = source.split("\n")
    for node in reversed(ast.parse(source).body):
        if isinstance(node, ast.ImportFrom) and (node.level > 0 or node.module == "arbol_installation.paths"):
            del lines[node.lineno - 1:node.end_lineno]
    return "\n".join(lines)


def launcher_source(registry: str, component: str, python: str) -> bytes:
    """A launcher: the text of launcher.py, then the call that serves this component and registry. The launcher
    arbol-trunk also carries its schema reader and its selection code."""
    if component in ("arbol-root", "arbol-roots"):
        raise ValueError("The legacy Root entry point has been retired.")
    first = shebang(python)
    if component == TRUNKS:
        body = "\n".join(module_text(name) for name in TRUNK_MODULES)
        call = f"sys.exit(launch_trunk({os.path.abspath(registry)!r}, sys.argv[1:]))"
    elif component == "arbol":
        body = "\n".join(module_text(name) for name in ("launcher.py", "schema_state.py"))
        body += "\ninstalled_schema = read_schema()"
        call = (f"sys.exit(launch({os.path.abspath(registry)!r}, {component!r}, sys.argv[1:], "
                "schema=installed_schema.pair, schema_error=SCHEMA_ERRORS.get(installed_schema.status)))")

    else:
        body = module_text("launcher.py")
        call = f"sys.exit(launch({os.path.abspath(registry)!r}, {component!r}, sys.argv[1:]))"
    paths = module_text("paths.py", Path(PACKAGE).parent / "arbol_installation")
    return f"{first}\n{LAUNCHER_MARK}\n{SIGINT_LINE}\n{paths}\n{body}\n{call}\n".encode("utf-8", "surrogateescape")


def early_driver_signals(source: bytes) -> bytes:
    """Keep the existing built-in-only SIGINT prelude before sealed verification."""
    future = b"from __future__ import annotations\n"
    if not source.startswith(future):
        raise ValueError("The sealed provider prefix must begin with its annotations declaration.")
    return future + SIGINT_LINE.encode("ascii") + b"\n" + source[len(future):]


def driver_launcher_source(registry: str, component: str, route: str, provider: Payload) -> bytes:
    """Stage exact gate bytes; this function never installs or issues acceptance."""
    from .driver_admission import COMPONENTS, physical
    from .driver_payload import SUBTREE, load

    registry_path = physical(registry)
    if component not in COMPONENTS or provider.component != "arbol":
        raise ValueError("A Driver gate requires its exact immutable Arbol provider.")
    expected = registry_path / "arbol" / provider.build / SUBTREE
    verified = load(expected, "arbol", provider.build)
    if provider.root != expected or provider.digest != verified.digest:
        raise ValueError("The fixed provider payload does not match the registered gate.")
    target = Path(route)
    if (not target.is_absolute() or target.name != component
            or os.path.realpath(target.parent) != str(target.parent)):
        raise ValueError("A Driver gate route must name its canonical registered launcher.")
    interpreter, _, entry = verified.prefix
    # This route always executes the exact M-inventoried sealed provider entry.
    # It never renders trusted bootstrap bytes from mutable source/installed
    # library modules. This is the same fixed literal wrapper used for spaces.
    words = [interpreter, "-ISB", entry, "--driver-launch", str(registry_path), component, str(target)]
    command = "exec " + " ".join(shlex.quote(word) for word in words) + ' "$@"\n'
    return ("#!/bin/sh\n" + DRIVER_LAUNCHER_MARK + "\n" + command).encode("utf-8")


def _keep_driver_gate(bin_folder: str, registry: str, component: str) -> bool:
    """Ordinary build/install refresh is never a Driver gate downgrade path."""
    from .driver_admission import COMPONENTS, Refusal, physical
    from .driver_payload import verify_gate

    if component not in COMPONENTS:
        return False
    path = Path(bin_folder) / component
    marked = False
    if os.path.lexists(path):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise Refusal("Cannot replace an unsafe registered Driver launcher.")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            marked = DRIVER_LAUNCHER_MARK.encode("ascii") in os.read(descriptor, 1024).splitlines()[:3]
        finally:
            os.close(descriptor)
    gate = Path(registry) / ".driver-qualification" / "gate.json"
    control = Path(registry) / component / ".driver-admission"
    if not (marked or os.path.lexists(gate) or os.path.lexists(control)):
        return False
    verified = verify_gate(physical(registry))
    row = next(row for row in verified.document["components"] if row["component"] == component)
    if not marked or str(physical(path, directory=False)) != row["launcher"]:
        raise Refusal("Driver gate refresh requires an explicit closed verified deployment.")
    _driver_gate_authority(physical(registry), component)
    if verify_gate(physical(registry)).digest != verified.digest:
        raise Refusal("Driver gate changed during preservation preflight.")
    return True


def _driver_gate_authority(registry: Path, component: str) -> None:
    """Read-only preserve preflight, never initial deployment or acceptance issuance."""
    from .driver_admission import Authority, Refusal, decode, private_directory, read_bytes, sha256, valid_hash
    from .driver_payload import BUILD, DESCRIPTOR, SUBTREE, registered, verify_acceptance

    authority = Authority(registry, component)
    with authority.mutex(seconds=0):
        authority.read("control")
        for name in ("control.lock", "admission.lock"):
            descriptor = authority.open_lock(name)  # create=False; no lease/unlock/publication.
            os.close(descriptor)
        qualification = authority.read("qualification")
        if qualification["component"] != component:
            raise Refusal("Driver gate qualification component changed.")
        digest = qualification["acceptanceSha256"]
        raw = read_bytes(authority.shared / "acceptances" / (digest + ".json"))
        value = decode(raw)
        if sha256(raw) != digest or not valid_hash(value.get("producerPayloadSha256")):
            raise Refusal("Driver gate acceptance digest changed.")
        matches = []
        count = 0
        for folder in (registry / component).iterdir():
            count += 1
            if count > 100000:
                raise Refusal("Driver gate registry exceeds its bounded inventory.")
            if BUILD.fullmatch(folder.name) is None:
                continue
            private_directory(folder)
            root = folder / SUBTREE
            # A genuine legacy Build has no payload root. Existing unsafe roots
            # remain errors; do not broadly swallow Refusal or manufacture D.
            if not os.path.lexists(root):
                continue
            try:
                descriptor_raw = read_bytes(root / DESCRIPTOR)
            except FileNotFoundError:
                continue
            if sha256(descriptor_raw) == value["producerPayloadSha256"]:
                matches.append(registered(registry, component, folder.name))
        if len(matches) != 1:
            raise Refusal("The exact qualified gate payload is unavailable.")
        verify_acceptance(authority, matches[0], digest=digest)
        taint = authority.folder / "taint.json"
        if os.path.lexists(taint) and authority.read("taint")["component"] != component:
            raise Refusal("Driver gate taint component changed.")


def driver_gate_identity(path: Path) -> tuple[str, str] | None:
    """Recognize old inline and exact-entry gates without executing their bytes.

    A marked but damaged gate refuses. Unmarked legacy/non-Driver files retain
    the installer's existing classification behavior.
    """
    from .driver_admission import COMPONENTS, Refusal, physical

    if path.name not in COMPONENTS:
        return None
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        prefix = os.read(descriptor, 1024)
    finally:
        os.close(descriptor)
    if DRIVER_LAUNCHER_MARK.encode("ascii") not in prefix.splitlines()[:3]:
        return None
    found = driver_route_bytes(path)
    if found is None:
        raise Refusal("Registered Driver gate disappeared.")
    try:
        text = found[0].decode("utf-8", "strict")
        lines = text.rstrip("\n").split("\n")
        if len(lines) < 3 or lines[1] != DRIVER_LAUNCHER_MARK:
            raise ValueError
        if lines[0] == "#!/bin/sh":
            words = shlex.split("\n".join(lines[2:]), posix=True)
            if (len(words) != 9 or words[0] != "exec" or words[2] != "-ISB"
                    or words[4] != "--driver-launch" or words[8] != "$@"):
                raise ValueError
            registry, component, route = words[5:8]
        else:
            outer = ast.parse(lines[-1], mode="eval").body
            if not isinstance(outer, ast.Call) or len(outer.args) != 1:
                raise ValueError
            inner = outer.args[0]
            if (not isinstance(inner, ast.Call) or not isinstance(inner.func, ast.Name)
                    or inner.func.id != "launch_gated" or len(inner.args) != 4):
                raise ValueError
            registry, component, route = (ast.literal_eval(node) for node in inner.args[:3])
        if (not isinstance(registry, str) or not os.path.isabs(registry) or component != path.name
                or not isinstance(route, str) or str(physical(path, directory=False)) != route):
            raise ValueError
        if not _keep_driver_gate(str(path.parent), registry, component):
            raise ValueError
        return registry, component
    except (OSError, UnicodeError, SyntaxError, TypeError, ValueError):
        raise Refusal("Registered Driver gate is malformed or its authority is missing/changed.") from None


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
    if _keep_driver_gate(bin_folder, registry, component):
        return
    source = launcher_source(registry, component, python or sys.executable)
    os.makedirs(bin_folder, exist_ok=True)
    atomic_write(os.path.join(bin_folder, component), source, 0o755)


class Stop:
    """Set by SIGINT or SIGTERM during a build: the running command's process group is stopped."""

    def __init__(self, *, check_group_exit: bool = False) -> None:
        self.requested = False
        self.group: int | None = None
        self.at = 0.0
        self.check_group_exit = check_group_exit
        self.groups_ended = True

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
    if stop.check_group_exit:
        try:
            os.killpg(child.pid, 0)
        except ProcessLookupError:
            pass  # The command was reaped and no process group remains.
        except OSError:
            stop.groups_ended = False
        else:
            stop.groups_ended = False
    ended = str(code) if code >= 0 else signal.Signals(-code).name
    os.write(log, f"Exit: {ended}{' (stopped by caller)' if stop.requested else ''}\n".encode())
    return code == 0 and not stop.requested


def build_component(component: str, paths: Locations, stop: Stop) -> Record:
    if component in ("arbol-root", "arbol-roots"):
        raise ValueError("The legacy Root runtime cannot be built by this release.")
    repo = os.path.abspath(paths.repo or default_repository(component))
    config, version, source = description(repo, component)
    if component == "arbol" and not schema_compatibility(config.get("schemaCompatibility")):
        raise ValueError("Arbol must declare schemaCompatibility in arbol-build.json.")
    folder, build = reserve(paths.registry, component)
    record: Record = {"component": component, "build": build, "packageVersion": version, "status": "building",
                      "startedAt": now(), "source": source, "entry": config["entry"], "checks": []}
    # Whole numbers, also when written 1.0, in the order of BuildRecord.
    if "contract" in config:
        record["contract"] = int(config["contract"])
    if "installationLayout" in config:
        record["installationLayout"] = installation_layout(config)
    if "schemaCompatibility" in config:
        record["schemaCompatibility"] = config["schemaCompatibility"]
    if "dataFormat" in config:
        record["dataFormat"] = int(config["dataFormat"])
    save_record(folder, record)
    log = os.open(os.path.join(folder, "build.log"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    stage, name = "launcher", "launcher"
    try:
        # The Trunks share the one launcher arbol-trunk, which the build of any Trunk writes (RCT-0).
        write_launcher(paths.bin, paths.registry, TRUNKS if trunk(component) else component)
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


def folders(path: str) -> list[str]:
    try:
        with os.scandir(path) as entries:
            return [item.name for item in entries if item.is_dir(follow_symlinks=False)]
    except FileNotFoundError:
        return []


def components_in(registry: str) -> list[str]:
    """The components of the registry: its folders, and in builds/arbol-trunk/ the folder of each Trunk."""
    names: list[str] = []
    for name in folders(registry):
        if name != TRUNKS:
            names.append(name)
            continue
        names.extend(f"{TRUNKS}/{code}" for code in folders(os.path.join(registry, TRUNKS)) if code_name(code))
    # In the order of JavaScript's sort: by UTF-16 code units.
    return sorted(names, key=lambda name: name.encode("utf-16-be", "surrogatepass"))


def list_builds(registry: str, component: str | None = None) -> list[Record]:
    components = [component] if component else components_in(registry)
    listed: list[Record] = []
    schema = read_schema() if any(name == "arbol" or trunk(name) for name in components) else None
    for name in components:
        records = read_records(registry, name)
        if name == "arbol":
            selected = default_record(registry, [record for record in records
                                                 if backend_fits(record, schema.pair if schema else None)])
        elif name == "arbol-root":
            selected = None
        elif trunk(name):
            selected = chosen(registry, records, schema.pair if schema is not None else None)
        else:
            selected = default_record(registry, records)
        listed.extend({**build_details(registry, record),
                       "default": selected is not None and record["build"] == selected["build"]}
                      for record in records)
    return listed


def last_start(folder: str) -> str | None:
    """Read a regular last-start file, falling back to its modification time (BLD-0.24, BLD-D19)."""
    path = os.path.join(folder, "last-start")
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    try:
        # A replacement with a pipe or symlink must neither block inventory nor read another file.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                return None
            raw = stream.read(26)
        value = raw.decode("ascii")
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ\n")
        canonical = parsed.isoformat(timespec="milliseconds") + "Z"
        if raw == (canonical + "\n").encode("ascii"):
            return canonical
    except (OSError, ValueError):
        pass
    try:
        return datetime.fromtimestamp(info.st_mtime, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def build_details(registry: str, record: Record) -> Record:
    """Derived inventory fields never become part of build.json."""
    started = last_start(os.path.join(registry, record["component"], record["build"]))
    return {**record, "installationLayout": installation_layout(record), "lastStart": started,
            "unusedSince": started or record.get("finishedAt") or record["startedAt"]}


def show_build(registry: str, component: str, number: str | None = None) -> Record:
    if number is not None and BUILD_PATTERN.fullmatch(number) is None:
        raise ValueError("A build number is lower-case hexadecimal, without leading zero.")
    records = read_records(registry, component)
    if number is not None:
        found = next((record for record in records if record["build"] == number), None)
    elif component == "arbol" or trunk(component):
        schema = read_schema()
        if schema.pair is None:
            raise ValueError(SCHEMA_ERRORS[schema.status][1])
        found = (default_record(registry, [record for record in records if backend_fits(record, schema.pair)])
                 if component == "arbol" else chosen(registry, records, schema.pair))
    else:
        found = None if component == "arbol-root" else default_record(registry, records)
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


def lock_build(registry: str, component: str, number: str, locked: bool) -> Record:
    """Idempotent lock/unlock of any known unpruned Build, serialized with every other record change."""
    def change() -> Record:
        record = show_build(registry, component, number)
        if record.get("prunedAt"):
            raise ValueError("A pruned Build cannot be locked or unlocked.")
        if locked and "lockedAt" not in record:
            record["lockedAt"] = now()
            save_unlocked(os.path.join(registry, component, number), record)
        elif not locked and "lockedAt" in record:
            del record["lockedAt"]
            save_unlocked(os.path.join(registry, component, number), record)
        return record

    return with_mutation_lock(os.path.join(registry, component), change)


def missing_only(function: Any, path: str, error: BaseException) -> None:
    if not isinstance(error, FileNotFoundError):
        raise error


def prune_protections(registry: str, component: str, working: list[Record],
                      *,
                      schema: SchemaState | None = None) -> set[str]:
    """Defaults and persistent Driver pins, in addition to newest-n and Locks."""
    from .driver_payload import protected_payloads

    pinned = protected_payloads(registry, component, [record["build"] for record in working])
    if component == "arbol" or trunk(component):
        schema = schema if schema is not None else read_schema()
        if schema.pair is None:
            raise ValueError(f"Cannot prune {component}. {SCHEMA_ERRORS[schema.status][1]}")
        selected = (default_record(registry, [record for record in working if backend_fits(record, schema.pair)])
                    if component == "arbol" else chosen(registry, working, schema.pair))
        return pinned | ({selected["build"]} if selected is not None else set())
    if component in ("arbol-root", "arbol-roots"):
        return {record["build"] for record in working}
    selected = default_record(registry, working)
    return pinned | ({selected["build"]} if selected is not None else set())



def remove_build_payload(registry: str, record: Record, eligible: Callable[[], bool] | None = None) -> str:
    """Called under the component reservation; active/unverifiable usage keeps every file and record."""
    from .driver_payload import retention_status

    try:
        descriptor = open_use_guard(registry, record["component"], record["build"], exclusive=True)
    except BlockingIOError:
        return "inUse"
    except OSError:
        return "unverifiable"
    runtime_descriptor = None
    try:
        if eligible is not None and not eligible():
            return "recent"
        # This snapshot releases its short control mutexes before deletion.
        # A new reference publisher must first acquire SH on our held EX inode.
        retained = retention_status(registry, record["component"], record["build"])
        if retained is not None:
            return retained
        folder = os.path.join(registry, record["component"], record["build"])
        payload = build_payload_directory(registry, record["component"], record["build"])
        external = payload != Path(folder)
        if external and os.path.lexists(payload) and payload.resolve() != payload:
            return "unverifiable"
        if external and payload.is_dir():
            try:
                runtime_descriptor = os.open(payload / "use.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                info = os.fstat(runtime_descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                    return "unverifiable"
                fcntl.flock(runtime_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return "inUse"
            except OSError:
                return "unverifiable"
        record["prunedAt"] = now()
        save_unlocked(folder, record)
        if external and os.path.lexists(payload):
            unseal_directories(payload, payload.lstat(), Event())
            shutil.rmtree(payload, onexc=missing_only)
        for item in os.listdir(folder):
            if item in ("build.json", "build.log", "last-start"):
                continue
            path = os.path.join(folder, item)
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, onexc=missing_only)
            else:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
        return "pruned"
    finally:
        if runtime_descriptor is not None:
            os.close(runtime_descriptor)
        os.close(descriptor)


def prune_builds(registry: str, component: str, keep: int, *, bin_dir: str | None = None) -> dict[str, Any]:
    try:
        with Admission(runtime_folder()).permit("normal"):
            return prune_admitted(registry, component, keep, bin_dir=bin_dir)
    except AdmissionRefusal:
        return {"component": component, "pruned": [], "maintenance": True}


def prune_admitted(registry: str, component: str, keep: int, *, bin_dir: str | None = None) -> dict[str, Any]:
    from .unused import shared_runtime, usage_snapshot

    dynamic = trunk(component) or shared_runtime(component)
    schema = read_schema() if dynamic or component == "arbol" else None
    paths = Locations(registry, bin_dir or str(Path.home() / ".local/bin"))

    def change() -> dict[str, Any]:
        working = [record for record in read_records(registry, component)
                   if record["status"] == "working" and not record.get("prunedAt")]
        protected = prune_protections(registry, component, working, schema=schema)
        usage = usage_snapshot(paths, schema) if dynamic and schema is not None else None
        if usage is not None and usage.unavailable:
            return {"component": component, "pruned": [], "runtimeUnavailable": True}
        pruned: list[str] = []
        retained: dict[str, list[str]] = {}
        for record in working[keep:]:
            if record.get("lockedAt") or record["build"] in protected:
                continue
            number = record["build"]
            if usage is not None and usage.retains(component, number):
                retained.setdefault("inUse", []).append(number)
                continue

            def still_unused(number: str = number) -> bool:
                return schema is None or not dynamic or not usage_snapshot(paths, schema).retains(component, number)

            outcome = remove_build_payload(registry, record, still_unused)
            if outcome == "pruned":
                pruned.append(record["build"])
            elif outcome in ("inUse", "unverifiable", "recent"):
                retained.setdefault("inUse" if outcome == "recent" else outcome, []).append(number)
        return {"component": component, "pruned": pruned, **retained}

    return with_mutation_lock(os.path.join(registry, component), change)


DRIVER_LAUNCHER_LIMIT = 1024 * 1024


def driver_route_bytes(path: Path) -> tuple[bytes, int] | None:
    """Read one exact publisher route without following links or blocking."""
    from .driver_admission import Refusal, physical

    parent = physical(path.parent)
    info = parent.lstat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise Refusal("Unsafe registered launcher directory.")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) & 0o022 or not before.st_mode & 0o111
                or before.st_size > DRIVER_LAUNCHER_LIMIT):
            raise Refusal("Unsafe registered Driver launcher.")
        raw = bytearray()
        while len(raw) <= DRIVER_LAUNCHER_LIMIT:
            block = os.read(descriptor, min(65536, DRIVER_LAUNCHER_LIMIT + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        after, named = os.fstat(descriptor), path.lstat()
        if (len(raw) != before.st_size or len(raw) > DRIVER_LAUNCHER_LIMIT
                or (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) !=
                (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size)
                or (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)):
            raise Refusal("Driver launcher changed while reading.")
        return bytes(raw), stat.S_IMODE(before.st_mode)
    finally:
        os.close(descriptor)


def publish_driver_route(path: Path, expected: tuple[bytes, int] | None,
                         desired: tuple[bytes, int] | None) -> None:
    """Compare exact before bytes; fsync atomic executable publication/removal."""
    from .driver_admission import Refusal, sync_directory, token

    if driver_route_bytes(path) != expected:
        raise Refusal("Registered Driver launcher changed during deployment.")
    if desired is None:
        if expected is not None:
            path.unlink()
            sync_directory(path.parent)
        return
    raw, mode = desired
    if (len(raw) > DRIVER_LAUNCHER_LIMIT or mode & 0o022 or not mode & 0o111
            or mode & ~0o777):
        raise Refusal("Invalid staged Driver launcher.")
    temporary = path.parent / ("." + path.name + "." + token())
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        if driver_route_bytes(path) != expected:
            raise Refusal("Registered Driver launcher changed before publication.")
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
