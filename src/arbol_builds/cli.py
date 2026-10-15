"""The command line of arbol-builds (BLD-0, "Building, withdrawing, pruning" and the Interface)."""

import os
import re
import resource
import signal
import sys
from types import FrameType

from .config import JS_SPACE, component_name, locations
from .launcher import json_line, standard_descriptors, write_all
from .service import Stop, build_component, list_builds, prune_builds, show_build, withdraw_build

USAGE = ("arbol-builds build <component> [--repo <folder>] [--root <identifier>] | list [<component>] "
         "| show <component>[@<build>] | withdraw <component>@<build> --reason <text> | prune <component> --keep <n> "
         "[--registry-dir <folder>] [--bin-dir <folder>]; a Trunk is the component arbol-trunk/<code name>")
COMMANDS = ("build", "list", "show", "withdraw", "prune")
SAFE_INTEGER = 2**53 - 1


def unicode_text(value: str) -> str:
    """Text from the command line, with bytes that are not UTF-8 shown as U+FFFD, as the earlier tool did."""
    return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def resolved(path: str) -> str:
    """An absolute path, as JavaScript's resolve() gives it: a leading "//" counts as "/"."""
    absolute = os.path.abspath(path)
    return "/" + absolute.lstrip("/") if absolute.startswith("//") else absolute


def options(args: list[str], allowed: list[str]) -> tuple[list[str], dict[str, str]]:
    """Words in order, and options as --name value or --name=value, each at most once."""
    words: list[str] = []
    values: dict[str, str] = {}
    index = 0
    while index < len(args):
        arg = args[index]
        if not arg.startswith("-"):
            words.append(arg)
            index += 1
            continue
        key, equals, given = arg.partition("=")
        if key not in allowed or key in values:
            raise ValueError(f"Unknown or repeated option: {unicode_text(key)}.")
        if equals:
            value: str | None = given
        else:
            index += 1
            value = args[index] if index < len(args) else None
        if value is None or value == "" or (not equals and value.startswith("--")):
            raise ValueError(f"Option {key} needs a value.")
        values[key] = value
        index += 1
    return words, values


def main(args: list[str]) -> int:
    def output(value: object) -> None:
        write_all(1, json_line(value))

    try:
        if args == ["--help"]:
            output({"usage": USAGE})
            return 0
        words, values = options(args, ["--registry-dir", "--bin-dir", "--repo", "--root", "--reason", "--keep"])
        command = words[0] if words else None
        target = words[1] if len(words) > 1 else None
        if len(words) > 2 or command not in COMMANDS or (command != "list" and not target):
            raise ValueError(USAGE)
        for key in values:
            if ((key in ("--repo", "--root") and command != "build") or (key == "--reason" and command != "withdraw")
                    or (key == "--keep" and command != "prune")):
                raise ValueError(f"Option {key} does not apply to {command}.")
        paths = locations()
        if "--registry-dir" in values:
            paths.registry = resolved(values["--registry-dir"])
        if "--bin-dir" in values:
            paths.bin = resolved(values["--bin-dir"])
        if "--repo" in values:
            paths.repo = resolved(values["--repo"])
        parts = (target or "").split("@")
        component, number, rest = parts[0], (parts[1] if len(parts) > 1 else None), parts[2:]
        if target:
            component_name(component)
        if rest or (number is not None and command not in ("show", "withdraw")):
            raise ValueError("This command takes a component without a build number.")
        if command == "list":
            output(list_builds(paths.registry, target))
        elif command == "show":
            output(show_build(paths.registry, component, number))
        elif command == "withdraw":
            reason = values.get("--reason")
            if not number or reason is None or not reason.strip(JS_SPACE):
                raise ValueError("withdraw requires component@build and --reason <text>.")
            output(withdraw_build(paths.registry, component, number, unicode_text(reason)))
        elif command == "prune":
            keep = values.get("--keep")
            if keep is None or re.fullmatch(r"[1-9][0-9]{0,15}", keep) is None or int(keep) > SAFE_INTEGER:
                raise ValueError("--keep must be a positive whole number.")
            output(prune_builds(paths.registry, component, int(keep)))
        else:
            stop = Stop()

            def request(number: int, frame: FrameType | None) -> None:
                stop.request()

            previous = {name: signal.signal(name, request) for name in (signal.SIGINT, signal.SIGTERM)}
            try:
                record = build_component(component, paths, stop, values.get("--root"))
            finally:
                for name, handler in previous.items():
                    signal.signal(name, handler)
            output(record)
            return 0 if record["status"] == "working" else 1
        return 0
    except Exception as error:
        output({"error": {"code": "builds_failed", "message": str(error)}})
        return 1


def raise_open_files_limit() -> None:
    """Raise the soft limit of open files as Node.js does when it starts; build commands inherit it."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft == hard:
        return
    low, high = soft, (1 << 20 if hard == resource.RLIM_INFINITY else hard)
    if hard == resource.RLIM_INFINITY and soft > 1 << 20:
        # Node's search, in unsigned arithmetic, ends at the hard limit when the soft one is above 2**20.
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
        except (OSError, ValueError):
            pass
        return
    if hard != resource.RLIM_INFINITY:
        low = high
    while True:
        middle = low + (high - low) // 2
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (middle, hard))
            low = middle
        except (OSError, ValueError):
            high = middle
        if low + 1 >= high:
            break


def entry() -> None:
    """Start as Node.js started the earlier tool: standard streams open, SIGINT and SIGTERM unblocked."""
    # Like the earlier tool, a Ctrl-C outside a build ends the program without a traceback, also one that was
    # waiting while SIGINT was blocked.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    standard_descriptors()
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM})
    raise_open_files_limit()
    sys.exit(main(sys.argv[1:]))
