"""The command line of arbol-builds (BLD-0, "Building, withdrawing, pruning" and the Interface)."""

import os
import re
import resource
import signal
import sys
from pathlib import Path
from types import FrameType

from arbol_installation.build_output import contains_path, empty_run, evidence_destination, release_run, save_evidence

from .config import JS_SPACE, component_name, default_repository, locations
from .launcher import json_line, standard_descriptors, write_all
from .service import (
    Stop,
    build_component,
    build_details,
    list_builds,
    lock_build,
    prune_builds,
    show_build,
    withdraw_build,
)
from .unused import prune_unused

USAGE = ("arbol-builds build <component> [--repo <folder>] [--release-to <new-evidence-directory>] "
         "| list [<component>] | show <component>[@<build>] "
         "| withdraw <component>@<build> --reason <text> "
         "| lock <component>@<build> | unlock <component>@<build> | prune <component> --keep <n> | prune --unused "
         "[--registry-dir <folder>] [--bin-dir <folder>] | release-run <run-directory> --evidence <report>"
         "; a Trunk is the component arbol-trunk/<code name>")
COMMANDS = ("build", "list", "show", "withdraw", "prune", "lock", "unlock")
SAFE_INTEGER = 2**53 - 1


def unicode_text(value: str) -> str:
    """Text from the command line, with bytes that are not UTF-8 shown as U+FFFD, as the earlier tool did."""
    return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def resolved(path: str) -> str:
    """An absolute path, as JavaScript's resolve() gives it: a leading "//" counts as "/"."""
    absolute = os.path.abspath(path)
    return "/" + absolute.lstrip("/") if absolute.startswith("//") else absolute


def options(args: list[str], allowed: list[str], flags: set[str] | None = None) -> tuple[list[str], dict[str, str]]:
    """Words, value options and explicit boolean flags, each given at most once."""
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
        if flags is not None and key in flags:
            if equals:
                raise ValueError(f"Flag {key} takes no value.")
            values[key] = "true"
            index += 1
            continue
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
        if args[:1] == ["driver-state"]:
            from .driver_state import command as driver_state_command
            return driver_state_command(args[1:], locations().registry)
        if args[:1] == ["release-run"]:
            words, values = options(args[1:], ["--evidence"])
            if len(words) != 1 or "--evidence" not in values:
                raise ValueError("Usage: arbol-builds release-run <run-directory> --evidence <report>.")
            requested_run = Path(words[0]).expanduser().absolute()
            queued = release_run(Path.home(), requested_run, Path(values["--evidence"]))
            output({"run": str(requested_run), "queued": str(queued)})
            return 0
        if args == ["--help"]:
            output({"usage": USAGE})
            return 0
        words, values = options(
            args, ["--registry-dir", "--bin-dir", "--repo", "--reason", "--keep", "--unused", "--release-to"],
            {"--unused"},
        )
        command = words[0] if words else None
        target = words[1] if len(words) > 1 else None
        unused = command == "prune" and "--unused" in values
        if len(words) > 2 or command not in COMMANDS or (command != "list" and not target and not unused):
            raise ValueError(USAGE)
        if "--unused" in values and (command != "prune" or len(words) > 1 or "--keep" in values):
            raise ValueError("--unused applies only to prune without a component or --keep.")
        for key in values:
            if ((key in ("--repo", "--release-to") and command != "build")
                    or (key == "--reason" and command != "withdraw")
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
        if rest or (number is not None and command not in ("show", "withdraw", "lock", "unlock")):
            raise ValueError("This command takes a component without a build number.")
        if command == "list":
            output(list_builds(paths.registry, target))
        elif command == "show":
            output(build_details(paths.registry, show_build(paths.registry, component, number)))
        elif command == "withdraw":
            reason = values.get("--reason")
            if not number or reason is None or not reason.strip(JS_SPACE):
                raise ValueError("withdraw requires component@build and --reason <text>.")
            output(withdraw_build(paths.registry, component, number, unicode_text(reason)))
        elif command in ("lock", "unlock"):
            if not number:
                raise ValueError(f"{command} requires component@build.")
            output(lock_build(paths.registry, component, number, command == "lock"))
        elif command == "prune" and unused:
            output(prune_unused(paths))
        elif command == "prune":
            keep = values.get("--keep")
            if keep is None or re.fullmatch(r"[1-9][0-9]{0,15}", keep) is None or int(keep) > SAFE_INTEGER:
                raise ValueError("--keep must be a positive whole number.")
            output(prune_builds(paths.registry, component, int(keep), bin_dir=paths.bin))
        else:
            home = Path.home()
            archive = None
            run = None
            run_info = None
            if "--release-to" in values:
                registry = Path(paths.registry)
                run = registry.parent
                if (not {"--registry-dir", "--bin-dir"} <= values.keys() or registry.name != "registry"
                        or Path(paths.bin) != run / "bin"):
                    raise ValueError("--release-to requires isolated registry and bin siblings in one new run.")
                if contains_path(run, {Path(paths.repo or default_repository(component)).resolve()}):
                    raise ValueError("The Build's source must be outside a run that will be released.")
                run_info = empty_run(home, run)
                archive = evidence_destination(home, Path(values["--release-to"]))
            stop = Stop(check_group_exit=archive is not None)

            def request(number: int, frame: FrameType | None) -> None:
                stop.request()

            previous = {name: signal.signal(name, request) for name in (signal.SIGINT, signal.SIGTERM)}
            try:
                record = build_component(component, paths, stop)
            finally:
                for name, handler in previous.items():
                    signal.signal(name, handler)
            if archive is not None and run is not None:
                cleanup: dict[str, str] = {"run": str(run)}
                try:
                    if stop.requested or not stop.groups_ended:
                        raise ValueError("The Build did not confirm that all command groups ended normally.")
                    folder = Path(paths.registry) / component / record["build"]
                    save_evidence(home, archive, folder / "build.json", folder / "build.log")
                    cleanup["evidence"] = str(archive)
                    cleanup["queued"] = str(release_run(home, run, archive / "build.json", expected=run_info))
                except (OSError, ValueError) as error:
                    cleanup["error"] = str(error)
                output({**record, "runRelease": cleanup})
                return 0 if record["status"] == "working" and "queued" in cleanup else 1
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
