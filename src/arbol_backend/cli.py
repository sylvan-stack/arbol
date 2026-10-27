"""Single-line public startup protocol with no raw credential/SQL exceptions."""

import asyncio
import json
import os
import sys
from pathlib import Path

from arbol_radar.cli import run as vigor

from .model import Refused, identity, parse
from .server import Backend


def main(args: list[str], package: Path) -> int:
    try:
        for key in list(os.environ):
            if key.startswith("PG"):
                del os.environ[key]
        parsed = parse(args)
        selected = identity(package, parsed)
        if parsed["verb"] == "vigor":  # the read of Subscriptions Vigor; the command line works while no backend runs
            return asyncio.run(vigor(selected, parsed))
        return asyncio.run(Backend(selected).run())
    except Refused as error:
        print(json.dumps({"error": {"code": error.code, "message": str(error)}}, separators=(",", ":")), flush=True)
    except (OSError, ValueError):
        print(
            json.dumps(
                {"error": {"code": "invalid_input", "message": "Cannot open the backend's private files."}},
                separators=(",", ":"),
            ),
            flush=True,
        )
    return 1


def entry(package: Path) -> None:
    raise SystemExit(main(sys.argv[1:], package))
