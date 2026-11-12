"""Select a Trunk Build for the installed database (ARC-4.3).

The generated arbol-trunk launcher embeds this module after the registry and schema readers.
"""

import os
import signal

from .launcher import (
    BUILD_PATTERN,
    COMMAND_WORDS,
    TRUNKS,
    Record,
    close_build_use,
    code_name,
    default_record,
    executable_entry,
    hold_build_use,
    json_line,
    named_runnable,
    read_records,
    readable,
    record_start,
    standard_descriptors,
    warning,
    write_all,
)
from .schema_state import SCHEMA_ERRORS, SchemaPair, SchemaState, read_schema

DEFAULT_TRUNK = "trivial"
LIST = "list"


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
    if args and args[0] not in COMMAND_WORDS and not args[0].startswith("-"):
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
    if not command or command[0] not in COMMAND_WORDS:
        raise Refused("invalid_input", "Use arbol-trunk [<code name>] [-v <build>] <run|settle|list> …")
    if command[0] == LIST and (build is not None or len(command) > 1):
        raise Refused("invalid_input", "list takes no -v or trailing arguments.")
    return Call(trunk, build, command)


def shown(value: str) -> str:
    """Show command line bytes outside UTF-8 as U+FFFD."""
    return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def known_trunk(registry: str, code: str) -> bool:
    folder = os.path.join(registry, TRUNKS, code)
    return code_name(code) and os.path.isdir(folder) and not os.path.islink(folder)


def fits(record: Record, pair: SchemaPair | None) -> bool:
    """The installed compatibility version matches, and the installed revision meets the Build's minimum."""
    return pair is not None and any(
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
    raise Refused("no_fit", f"{why} the installed schema at revision {pair.revision} "
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
             "schemaCompatibility": record.get("schemaCompatibility"),
             "fits": fits(record, schema.pair), "runnable": named_runnable(registry, record),
             "chosen": record is selected}
            for record in records]})
    schema_view: dict[str, object] = {"status": schema.status}
    if schema.pair is not None:
        schema_view.update(revision=schema.pair.revision, compatibilityVersion=schema.pair.compatibility_version)
    return {"schema": schema_view, "trunks": trunks}


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
        line = warning(component, selected)
        if line is not None:
            try:
                write_all(2, readable(line))
            except OSError:
                pass
        use_descriptor = hold_build_use(registry, component, selected["build"])
        folder = os.path.join(registry, component, selected["build"])
        entry = executable_entry(folder, selected.get("entry"))
        if entry is None:
            raise OSError(f"The program of {component}@{selected['build']} is no longer there.")
        record_start(folder)
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
        os.execv(entry, [entry, *call.command])
    except Refused as refused:
        try:
            write_all(1, json_line({"error": {"code": refused.code, "message": str(refused)},
                                    "available": refused.available}))
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
