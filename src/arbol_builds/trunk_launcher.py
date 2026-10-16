"""The launcher arbol-trunk, which starts every Trunk (RCT-0, "The command arbol-trunk"; BLD-0, BLD-D17).

arbol-builds writes the text of launcher.py, of roots.py and of this module, followed by one call of
launch_trunk(), into the file arbol-trunk: that file is the launcher (service.launcher_source). This module
therefore uses the standard library only; there, the imports from the package below are left out, and the names
they import are those of the text before it.
"""

import os
import signal

from .launcher import (
    BUILD_PATTERN,
    COMMAND_WORDS,
    TRUNKS,
    Record,
    code_name,
    executable_entry,
    json_line,
    named_runnable,
    read_records,
    readable,
    root_identifier,
    runnable,
    standard_descriptors,
    warning,
    write_all,
)
from .roots import current_root, read_root, read_roots, roots_folder

DEFAULT_TRUNK = "trivial"
LIST = "list"  # the one command the launcher answers itself


class Refused(Exception):
    """A call the launcher refuses: one line { error: { code, message }, available } and exit status 1."""

    def __init__(self, code: str, message: str, available: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.available = available or []


class Call:
    """A call read: the value of --root when it is the first argument, the code name, the value of -v, and the
    command with everything after it. A plain class, since importing dataclasses would slow every start."""

    def __init__(self, root: str | None, trunk: str | None, build: str | None, command: list[str]) -> None:
        self.root = root
        self.trunk = trunk
        self.build = build
        self.command = command


def read_call(args: list[str]) -> Call:
    """[--root <root>] [<code name>] [-v <build>] <command> …: --root only first, and a code name is never -v, a
    command word or an argument that begins with "-" (BLD-D17)."""
    index = 0
    root: str | None = None
    trunk: str | None = None
    build: str | None = None
    if args[:1] == ["--root"]:
        root = args[1] if len(args) > 1 else ""
        index = 2
    if index < len(args) and args[index] not in COMMAND_WORDS and not args[index].startswith("-"):
        trunk = args[index]
        index += 1
    if args[index:index + 1] == ["-v"]:
        build = args[index + 1] if index + 1 < len(args) else ""
        index += 2
    call = Call(root, trunk, build, args[index:])
    if not call.command:
        raise Refused("invalid_input", "No command: arbol-trunk [--root <root>] [<code name>] [-v <build>] "
                                       "<command> …, where the command is run, settle or list.")
    if call.command[0] == LIST and (call.build is not None or len(call.command) > 1):
        raise Refused("invalid_input", "list takes no -v and nothing after it: arbol-trunk [--root <root>] "
                                       "[<code name>] list.")
    return call


def shown(value: str) -> str:
    """An argument as it may be shown: bytes that are not UTF-8 as U+FFFD."""
    return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def the_root(name: str | None) -> Record:
    """The Root named with --root, or else the current Root (BLD-D17)."""
    folder = roots_folder()
    if name is None:
        record = current_root(read_roots(folder))
        if record is None:
            raise Refused("unknown_root", "No Root is named and none is working, so there is no current Root: "
                                          "name one with --root <root>.")
        return record
    if not root_identifier(name):
        raise Refused("unknown_root", f"{shown(name)!r} is not a Root identifier: one lower-case word of letters and "
                                      "digits.")
    named = read_root(folder, name)
    if named is None:
        raise Refused("unknown_root", f"There is no Root {name}: {os.path.join(folder, name, 'root.json')} is "
                                      "missing or damaged.")
    return named


def known_trunk(registry: str, code: str) -> bool:
    """A Trunk the registry knows: a folder in builds/arbol-trunk/ named by a code name."""
    folder = os.path.join(registry, TRUNKS, code)
    return code_name(code) and os.path.isdir(folder) and not os.path.islink(folder)


def fits(record: Record, root: Record) -> bool:
    """A Trunk Build fits a Root when its rootContracts hold the Root's version (RCT-0)."""
    return int(root["rootContract"]) in {int(number) for number in record["rootContracts"]}


def chosen(registry: str, records: list[Record], root: Record) -> Record | None:
    """The newest working Build that fits the Root and has its program: the Build run starts (RCT-0.7)."""
    return next((record for record in records
                 if record["status"] == "working" and runnable(registry, record) and fits(record, root)), None)


def pick_build(registry: str, component: str, number: str | None, root: Record) -> Record:
    """The Build to start, or no_fit, with the runnable Builds of the Trunk that fit the Root (RCT-0.9)."""
    records = read_records(registry, component)
    available = [record["build"] for record in records if named_runnable(registry, record) and fits(record, root)]
    version = int(root["rootContract"])
    if number is None:
        selected = chosen(registry, records, root)
        if selected is None:
            raise Refused("no_fit", f"No working Build of {component} fits the Root {root['root']}, which uses Root "
                                    f"Contract version {version}. Builds that fit: {', '.join(available) or 'none'}.",
                          available)
        return selected
    named = (next((record for record in records if record["build"] == number), None)
             if BUILD_PATTERN.fullmatch(number) else None)
    if named is None or not named_runnable(registry, named):
        why = ("is not a build number" if not BUILD_PATTERN.fullmatch(number)
               else "is unknown" if named is None else "is still building" if named["status"] == "building"
               else "is pruned" if named.get("prunedAt") else "has no program to run")
        raise Refused("no_fit", f"Build {shown(number)!r} of {component} {why}. Builds that fit the Root "
                                f"{root['root']}: {', '.join(available) or 'none'}.", available)
    if not fits(named, root):
        versions = ", ".join(str(int(item)) for item in named["rootContracts"])
        raise Refused("no_fit", f"{component}@{number} does not fit the Root {root['root']}: it implements Root "
                                f"Contract versions {versions}, and the Root uses {version}. Builds that fit: "
                                f"{', '.join(available) or 'none'}.", available)
    return named


def launch_trunk(registry: str, args: list[str]) -> int:
    """Choose the Root, the Trunk and the Build, and replace this process with the Build's program, handing it
    --root <root> before the command; return a status only when it cannot."""
    standard_descriptors()
    # A Ctrl-C while the Build is being chosen ends the launcher quietly, as in launch().
    if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        call = read_call(args)
        root = the_root(call.root)
        code = call.trunk or DEFAULT_TRUNK
        if not known_trunk(registry, code):
            raise Refused("unknown_trunk", f"There is no Trunk {shown(code)!r}: no Build of {TRUNKS}/{shown(code)} is "
                                           "in the registry.")
        component = f"{TRUNKS}/{code}"
        selected = pick_build(registry, component, call.build, root)
        line = warning(component, selected)
        if line is not None:
            try:
                write_all(2, readable(line))
            except OSError:
                pass  # the warning is a courtesy; the Build starts without it
        entry = executable_entry(os.path.join(registry, component, selected["build"]), selected.get("entry"))
        if entry is None:
            raise OSError(f"The program of {component}@{selected['build']} is no longer there.")
        # Python ignores these two signals when it starts; a direct start would leave them at their default.
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
        # execv passes the process's own environment exactly as the caller gave it.
        os.execv(entry, [entry, "--root", root["root"], *call.command])
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
