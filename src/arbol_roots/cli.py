"""The global catalogue's JSON command line (ARC-1, ARC-D67)."""

import sys

from arbol_builds.cli import options
from arbol_builds.launcher import json_line, standard_descriptors, write_all

from .model import Refused, identifier, list_roots, places, selected
from .operations import app, create, fail, ready, remove
from .sql import layout, migrate

USAGE = ("arbol-roots create <root> --name <text> [--from <root>] [--root-contract <version>] "
         "[--database-name <name>] | list | show [<root>] | ready <root> | fail <root> --reason <text> "
         "| app <root> <build> | remove <root> | layout <root> | migrate <root>; "
         "options: --roots-dir <folder>, --settings-dir <folder>, "
         "--registry-dir <folder>, --database-config <file>, --psql <program>, --security <program>")
GLOBAL = ("--roots-dir", "--settings-dir", "--registry-dir", "--database-config", "--psql", "--security")
LOCAL = {"create": ("--name", "--from", "--root-contract", "--database-name"), "fail": ("--reason",)}
COUNTS = {"create": (1,), "list": (0,), "show": (0, 1), "ready": (1,), "fail": (1,), "app": (2,), "remove": (1,),
          "layout": (1,), "migrate": (1,)}


def main(args: list[str]) -> int:
    try:
        if args == ["--help"]:
            write_all(1, json_line({"usage": USAGE}))
            return 0
        words, values = options(args, [*GLOBAL, "--name", "--from", "--root-contract", "--database-name", "--reason"])
        command = words[0] if words else ""
        arguments = words[1:]
        if command not in COUNTS or len(arguments) not in COUNTS[command]:
            raise Refused("invalid_input", USAGE)
        for key in values:
            if key not in GLOBAL and key not in LOCAL.get(command, ()):
                raise Refused("invalid_input", f"Option {key} does not apply to {command}.")
        if arguments:
            identifier(arguments[0])
        paths = places(values)
        result: object
        if command == "list":
            result = list_roots(paths)
        elif command == "show":
            result = selected(paths, arguments[0] if arguments else None)
        elif command == "create":
            result = create(paths, arguments[0], values)
        elif command == "ready":
            result = ready(paths, arguments[0])
        elif command == "fail":
            result = fail(paths, arguments[0], values.get("--reason"))
        elif command == "app":
            result = app(paths, arguments[0], arguments[1])
        elif command == "remove":
            result = remove(paths, arguments[0])
        elif command == "layout":
            result = layout(paths, arguments[0])
        elif command == "migrate":
            result = migrate(paths, arguments[0])
        else:
            raise Refused("invalid_input", f"The {command} command is not available in this development step.")
        write_all(1, json_line(result))
        return 0
    except Refused as error:
        write_all(1, json_line({"error": {"code": error.code, "message": str(error)}}))
    except ValueError as error:
        write_all(1, json_line({"error": {"code": "invalid_input", "message": str(error)}}))
    except Exception as error:
        write_all(1, json_line({"error": {"code": "operation_failed", "message": str(error)}}))
    return 1


def entry() -> None:
    standard_descriptors()
    sys.exit(main(sys.argv[1:]))
