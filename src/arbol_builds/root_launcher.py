"""Root-bound arbol/arbol-root selection (BLD-0.18/0.19, BLD-D21).

Only these two standalone launchers embed this module, after launcher.py and roots.py.
The existing plain and Trunk launchers keep their own text and selection.
"""

import os
import signal

from .launcher import (
    BUILD_PATTERN,
    Record,
    close_build_use,
    default_record,
    executable_entry,
    hold_build_use,
    json_line,
    named_runnable,
    read_records,
    readable,
    record_start,
    root_identifier,
    standard_descriptors,
    warning,
    write_all,
)
from .roots import current_root, read_root, read_roots, roots_folder


class RootRefused(Exception):
    def __init__(self, code: str, message: str, available: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.available = available or []


def root_text(value: str) -> str:
    return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def select_root(name: str | None) -> Record:
    """A named retained Root in any state, or the current working Root; never another fallback."""
    folder = roots_folder()
    if name is None:
        record = current_root(read_roots(folder))
        if record is None:
            raise RootRefused("unknown_root", "No Root is named and none is working; name one with --root <root>.")
        return record
    if not root_identifier(name):
        raise RootRefused("unknown_root", f"{root_text(name)!r} is not a Root identifier: one lower-case word "
                                           "of letters and digits.")
    record = read_root(folder, name)
    if record is None:
        raise RootRefused("unknown_root", f"Root {root_text(name)} has no readable valid root.json in {folder}.")
    return record


def root_default_record(registry: str, records: list[Record], root: str) -> Record | None:
    return default_record(registry, [record for record in records if record.get("root") == root])


def root_available(registry: str, records: list[Record], root: str | None) -> list[str]:
    return [record["build"] for record in records if root is not None and record.get("root") == root
            and named_runnable(registry, record)]


class RootCall:
    def __init__(self, root: str | None, build: str | None, command: list[str]) -> None:
        self.root = root
        self.build = build
        self.command = command


def read_root_call(args: list[str]) -> RootCall:
    index = 0
    root: str | None = None
    build: str | None = None
    if args[:1] == ["--root"]:
        root = args[1] if len(args) > 1 else ""
        index = 2
    if args[index:index + 1] == ["-v"]:
        build = args[index + 1] if index + 1 < len(args) else ""
        index += 2
    return RootCall(root, build, args[index:])


def select_root_build(registry: str, component: str, records: list[Record],
                      root: str | None, number: str | None) -> Record:
    if root is not None and not root_identifier(root):
        # Validate syntax before considering a named Build, without choosing an implicit Root.
        select_root(root)
    if number is not None:
        named = (next((record for record in records if record["build"] == number), None)
                 if BUILD_PATTERN.fullmatch(number) else None)
        if named is None or not named_runnable(registry, named):
            suffix = f" for Root {root}" if root is not None else ""
            raise RootRefused("build_unavailable", f"No runnable Build {component}@{root_text(number)}{suffix}.",
                              root_available(registry, records, root))
        own = named["root"]
        if root is not None and root != own:
            raise RootRefused("invalid_input", f"Build {component}@{number} belongs to Root {own}, "
                                              f"but --root names {root}.")
        select_root(own)
        return named
    selected = select_root(root)["root"]
    found = root_default_record(registry, records, selected)
    if found is None:
        raise RootRefused("build_unavailable", f"{component} has no runnable working Build for Root {selected}.",
                          root_available(registry, records, selected))
    return found


def launch_root(registry: str, component: str, args: list[str]) -> int:
    standard_descriptors()
    if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    use_descriptor: int | None = None
    try:
        call = read_root_call(args)
        records = read_records(registry, component)
        selected = select_root_build(registry, component, records, call.root, call.build)
        line = warning(component, selected)
        if line is not None:
            try:
                write_all(2, readable(line))
            except OSError:
                pass
        folder = os.path.join(registry, component, selected["build"])
        entry = executable_entry(folder, selected.get("entry"))
        if entry is None:
            raise OSError(f"The program of {component}@{selected['build']} is no longer there.")
        use_descriptor = hold_build_use(registry, component, selected["build"])
        record_start(folder)
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
        os.execv(entry, [entry, *call.command])
    except RootRefused as error:
        write_all(1, json_line({"error": {"code": error.code, "message": str(error), "available": error.available}}))
    except Exception as error:
        try:
            write_all(1, json_line({"error": {"code": "launch_failed", "message": str(error)}}))
        except OSError:
            pass
    finally:
        close_build_use(use_descriptor)
    return 1
