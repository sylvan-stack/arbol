"""The quiet observational-hook command line (AGR-1.5)."""

from __future__ import annotations

import json
import os
import sys

from .hooks import handle
from .records import TOOLS


def main(args: list[str]) -> int:
    try:
        if "ARBOL_ROOT" not in os.environ and len(args) == 2 and args[0] == "hook" and args[1] in TOOLS:
            event = json.loads(sys.stdin.read())
            if isinstance(event, dict):
                handle(args[1], event)
    except Exception:
        pass
    return 0


def entry() -> None:
    sys.exit(main(sys.argv[1:]))
