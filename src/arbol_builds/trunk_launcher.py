"""Select a Trunk Build for the installed database (ARC-4.3).

The generated arbol-trunk launcher embeds this module after the registry and schema readers.
"""

import json
import os
import signal
from pathlib import Path

from arbol_installation.paths import INSTALLATION_LAYOUT, build_payload_directory, build_registry
from arbol_installation.admission import Admission, AdmissionRefusal, GENERATION_ENV, runtime_folder
from arbol_installation.exchange_release import writer_version

from .launcher import (
    BUILD_PATTERN,
    COMMAND_WORDS,
    TRUNKS,
    Record,
    close_build_use,
    code_name,
    default_record,
    hold_build_use,
    installation_layout,
    json_line,
    layout_fits,
    named_runnable,
    read_records,
    readable,
    record_start,
    registered_entry,
    schema_compatibility,
    standard_descriptors,
    warning,
    write_all,
)
from .schema_state import SCHEMA_ERRORS, SchemaPair, SchemaState, read_schema

DEFAULT_TRUNK = "trivial"
LIST = "list"
VERIFY_START = "verify-start"


def admission_runtime(registry: str | None = None) -> Path:
    managed = runtime_folder().resolve()
    if registry is None or Path(registry).resolve() == build_registry().resolve():
        return managed
    value = os.environ.get("ARBOL_EXCHANGE_RUNTIME_DIR")
    if value is None:
        raise ValueError("An isolated registry requires an isolated Exchange runtime.")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("The Exchange runtime path must be absolute.")
    path = path.resolve()
    if path == managed or path.is_relative_to(managed) or managed.is_relative_to(path):
        raise ValueError("An isolated registry cannot address the managed Exchange runtime.")
    return path


class Refused(Exception):
    """A call the launcher refuses, with the available alternatives for no_fit."""

    def __init__(self, code: str, message: str, available: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.available = available or []


class Call:
    def __init__(self, trunk: str | None, build: str | None, command: list[str]) -> None:
        self.trunk = trunk
        self.build = build
        self.command = command


def read_call(args: list[str]) -> Call:
    """[<code name>] [-v <build>] <command> …, with run, settle or list."""
    index = 0
    trunk: str | None = None
    build: str | None = None
    if args and args[0] not in (*COMMAND_WORDS, VERIFY_START) and not args[0].startswith("-"):
        trunk = args[0]
        if not code_name(trunk):
            raise Refused("invalid_input", f"Invalid Trunk code name {shown(trunk)!r}.")
        index = 1
    if args[index:index + 1] == ["-v"]:
        build = args[index + 1] if index + 1 < len(args) else ""
        if BUILD_PATTERN.fullmatch(build) is None:
            raise Refused("invalid_input", "Build numbers are lower-case hexadecimal without a leading zero.")
        index += 2
    command = args[index:]
    if not command or command[0] not in (*COMMAND_WORDS, VERIFY_START):
        raise Refused("invalid_input", "Use arbol-trunk [<code name>] [-v <build>] <run|settle|list> …")
    if command[0] == LIST and (build is not None or len(command) > 1):
        raise Refused("invalid_input", "list takes no -v or trailing arguments.")
    if command[0] == VERIFY_START and (build is None or len(command) != 1):
        raise Refused("invalid_input", "verify-start requires one explicit Build and no trailing arguments.")
    return Call(trunk, build, command)


def shown(value: str) -> str:
    """Show command line bytes outside UTF-8 as U+FFFD."""
    return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def known_trunk(registry: str, code: str) -> bool:
    folder = os.path.join(registry, TRUNKS, code)
    return code_name(code) and os.path.isdir(folder) and not os.path.islink(folder)


def fits(record: Record, pair: SchemaPair | None) -> bool:
    """Check installation layout and then the independent installed schema pair."""
    return layout_fits(record) and pair is not None and any(
        item["compatibilityVersion"] == pair.compatibility_version and item["minRevision"] <= pair.revision
        for item in record.get("schemaCompatibility", [])
    )


def chosen(registry: str, records: list[Record], pair: SchemaPair | None) -> Record | None:
    """The newest working, runnable Build compatible with a verified installed schema."""
    return default_record(registry, [record for record in records if fits(record, pair)])


def pick_build(registry: str, component: str, number: str | None, pair: SchemaPair) -> Record:
    records = read_records(registry, component)
    if number is None:
        selected = chosen(registry, records, pair)
        if selected is not None:
            return selected
        why = f"No working Build of {component} fits"
    else:
        named = next((record for record in records if record["build"] == number), None)
        if named is not None and named_runnable(registry, named) and fits(named, pair):
            return named
        label = f"{component}@{number}"
        if named is None:
            why = f"{label} is unknown and cannot run on"
        elif not named_runnable(registry, named):
            state = ("is still building" if named["status"] == "building"
                     else "is pruned" if named.get("prunedAt") else "has no executable")
            why = f"{label} {state} and cannot run on"
        else:
            why = f"{label} does not fit"
    available = [record["build"] for record in records if fits(record, pair) and named_runnable(registry, record)]
    raise Refused("no_fit", f"{why} installation layout {INSTALLATION_LAYOUT} and schema revision {pair.revision} "
                            f"(compatibility version {pair.compatibility_version}). "
                            f"Compatible runnable Builds: {', '.join(available) or 'none'}.", available)


def trunks_in(registry: str) -> list[str]:
    """The code names of the Trunks the registry knows, trivial first, then in the order of their names."""
    try:
        with os.scandir(os.path.join(registry, TRUNKS)) as entries:
            codes = [entry.name for entry in entries
                     if code_name(entry.name) and entry.is_dir(follow_symlinks=False)]
    except OSError:
        return []
    return sorted(codes, key=lambda code: (code != DEFAULT_TRUNK, code))


def trunk_list(registry: str, schema: SchemaState, codes: list[str]) -> dict[str, object]:
    """Show the schema state and each Trunk's Build history. Choose only against a verified pair."""
    trunks: list[dict[str, object]] = []
    for code in codes:
        records = read_records(registry, f"{TRUNKS}/{code}")
        selected = chosen(registry, records, schema.pair)
        trunks.append({"trunk": code, "default": code == DEFAULT_TRUNK, "builds": [
            {"build": record["build"], "status": record["status"],
             "installationLayout": installation_layout(record),
             "schemaCompatibility": record.get("schemaCompatibility"),
             "fits": fits(record, schema.pair), "runnable": named_runnable(registry, record),
             "chosen": record is selected}
            for record in records]})
    return {"schema": schema_view(schema), "installationLayout": INSTALLATION_LAYOUT, "trunks": trunks}


def schema_view(schema: SchemaState) -> dict[str, object]:
    view: dict[str, object] = {"status": schema.status}
    if schema.pair is not None:
        view.update(revision=schema.pair.revision, compatibilityVersion=schema.pair.compatibility_version)
    return view


def installed_trunks() -> dict[str, tuple[Path, Record]]:
    directory = Path.home() / "Applications/Arbol/bin"
    prefix = "arbol-trunk-"
    marker = b"# arbol-installed-trunk "
    result = {}
    for entry in sorted(directory.glob(prefix + "*")):
        code = entry.name.removeprefix(prefix)
        if not code_name(code) or entry.is_symlink() or not entry.is_file() or not os.access(entry, os.X_OK):
            continue
        with entry.open("rb") as stream:
            stream.readline(512)
            line = stream.readline(4096)
            payload_line = stream.readline(4096)
        if not line.startswith(marker) or not line.endswith(b"\n"):
            raise ValueError(f"The installed launcher for {code} has no Trunk identity.")
        record = json.loads(line[len(marker):])
        if (not isinstance(record, dict) or record.get("component") != f"{TRUNKS}/{code}"
                or not isinstance(record.get("build"), str) or not BUILD_PATTERN.fullmatch(record["build"])
                or not schema_compatibility(record.get("schemaCompatibility"))):
            raise ValueError(f"The installed launcher for {code} has an invalid Trunk identity.")
        payload = build_payload_directory(build_registry(), record["component"], record["build"])
        if payload.resolve(strict=True) != payload or payload_line != b"# stable-payload " + os.fsencode(payload) + b"\n":
            raise ValueError(f"The installed launcher for {code} names a different payload.")
        result[code] = (entry, record)
    return result


def launch_installed_trunk(args: list[str]) -> int:
    """Use only the Trunk entry points installed alongside the stable app."""
    standard_descriptors()
    try:
        call = read_call(args)
        installed = installed_trunks()
        code = call.trunk or DEFAULT_TRUNK
        if (call.trunk is not None or call.command[0] != LIST) and code not in installed:
            raise Refused("unknown_trunk", f"No Build of {TRUNKS}/{code} is installed.")
        schema = read_schema()
        if call.command[0] == LIST:
            trunks = []
            for name in [code] if call.trunk else installed:
                _, record = installed[name]
                compatible = fits(record, schema.pair)
                trunks.append({"trunk": name, "default": name == DEFAULT_TRUNK, "builds": [{
                    "build": record["build"], "status": "working", "installationLayout": installation_layout(record),
                    "schemaCompatibility": record["schemaCompatibility"], "fits": compatible,
                    "runnable": True, "chosen": compatible,
                }]})
            write_all(1, json_line({"schema": schema_view(schema), "installationLayout": INSTALLATION_LAYOUT,
                                    "trunks": trunks}))
            return 0
        if schema.pair is None:
            raise Refused(*SCHEMA_ERRORS[schema.status])
        entry, record = installed[code]
        compatible = fits(record, schema.pair)
        if not compatible or call.build not in (None, record["build"]):
            raise Refused("no_fit", f"{TRUNKS}/{code} has no matching installed Build.",
                          [record["build"]] if compatible else [])
        if call.command[0] in ("run", VERIFY_START):
            with Admission(admission_runtime()).lease("normal", generation=os.environ.get(GENERATION_ENV)) as lease:
                writer_version(lease, record["component"], record["build"],
                               build_payload_directory(build_registry(), record["component"], record["build"]))
                if call.command[0] == VERIFY_START:
                    write_all(1, json_line({"build": record["build"], "generation": lease.state.generation}))
                    return 0
                os.environ[GENERATION_ENV] = lease.state.generation
                os.environ.pop("ARBOL_EXCHANGE_RUNTIME_DIR", None)
                os.execv(entry, [str(entry), *call.command])
        os.execv(entry, [str(entry), *call.command])
    except AdmissionRefusal as error:
        write_all(1, json_line({"error": {"code": error.code, "message": str(error)}, "available": []}))
        return 1
    except Refused as error:
        write_all(1, json_line({"error": {"code": error.code, "message": str(error)}, "available": error.available}))
        return 1
    except (OSError, ValueError) as error:
        write_all(1, json_line({"error": {"code": "launch_failed", "message": str(error)}, "available": []}))
        return 1


def launch_trunk(registry: str, args: list[str]) -> int:
    """Choose the exact Build and replace this process with its executable."""
    standard_descriptors()
    if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    use_descriptor: int | None = None
    try:
        call = read_call(args)
        code = call.trunk or DEFAULT_TRUNK
        listing_all = call.command[0] == LIST and call.trunk is None
        if not listing_all and not known_trunk(registry, code):
            raise Refused("unknown_trunk", f"No Build of {TRUNKS}/{code} is in the registry.")
        schema = read_schema()
        if call.command[0] == LIST:
            write_all(1, json_line(trunk_list(registry, schema, trunks_in(registry) if listing_all else [code])))
            return 0
        if schema.pair is None:
            raise Refused(*SCHEMA_ERRORS[schema.status])
        component = f"{TRUNKS}/{code}"
        selected = pick_build(registry, component, call.build, schema.pair)
        if call.command[0] in ("run", VERIFY_START):
            with Admission(admission_runtime(registry)).lease("normal", generation=os.environ.get(GENERATION_ENV)) as lease:
                writer_version(lease, component, selected["build"],
                               build_payload_directory(registry, component, selected["build"]))
                if call.command[0] == VERIFY_START:
                    write_all(1, json_line({"build": selected["build"], "generation": lease.state.generation}))
                    return 0
                os.environ[GENERATION_ENV] = lease.state.generation
                if Path(registry).resolve() == build_registry().resolve():
                    os.environ.pop("ARBOL_EXCHANGE_RUNTIME_DIR", None)
                line = warning(component, selected)
                if line is not None:
                    try:
                        write_all(2, readable(line))
                    except OSError:
                        pass
                use_descriptor = hold_build_use(registry, component, selected["build"])
                folder = os.path.join(registry, component, selected["build"])
                entry = registered_entry(registry, selected)
                if entry is None:
                    raise OSError(f"The program of {component}@{selected['build']} is no longer there.")
                record_start(folder)
                signal.signal(signal.SIGPIPE, signal.SIG_DFL)
                signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
                os.execv(entry, [entry, *call.command])
        line = warning(component, selected)
        if line is not None:
            try:
                write_all(2, readable(line))
            except OSError:
                pass
        use_descriptor = hold_build_use(registry, component, selected["build"])
        folder = os.path.join(registry, component, selected["build"])
        entry = registered_entry(registry, selected)
        if entry is None:
            raise OSError(f"The program of {component}@{selected['build']} is no longer there.")
        record_start(folder)
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
        os.execv(entry, [entry, *call.command])
    except (Refused, AdmissionRefusal) as refused:
        try:
            write_all(1, json_line({"error": {"code": refused.code, "message": str(refused)},
                                    "available": getattr(refused, "available", [])}))
        except OSError:
            pass
        return 1
    except Exception as error:
        try:
            write_all(1, json_line({"error": {"code": "launch_failed", "message": str(error)}, "available": []}))
        except OSError:
            pass
        return 1
    finally:
        close_build_use(use_descriptor)
