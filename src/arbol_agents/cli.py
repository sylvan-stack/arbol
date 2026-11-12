"""The agent-record hook and installation commands."""

from __future__ import annotations

import json
import os
import sys

from .hooks import handle
from .records import TOOLS

USAGE = "Usage: arbol-agents hook <claude-code|codex|kimi-code> | install | uninstall | status [--json]"


def hook(args: list[str]) -> int:
    try:
        if "ARBOL_CHAT" not in os.environ and len(args) == 2 and args[0] == "hook" and args[1] in TOOLS:
            event = json.loads(sys.stdin.read())
            if isinstance(event, dict):
                handle(args[1], event)
    except Exception:
        pass
    return 0


def main(args: list[str]) -> int:
    if args[:1] == ["hook"]:
        return hook(args)
    if not args or args in (["--help"], ["-h"]):
        print(USAGE)
        return 0

    from .installation import configure, status
    from .settings import SettingsError

    try:
        if args in (["install"], ["uninstall"]):
            remove = args == ["uninstall"]
            for tool, count in configure(remove=remove).items():
                verb = "removed" if remove else "added"
                print(f"{tool}: {verb} {count} hook entries")
            if not remove:
                print("Running Claude Code sessions keep their old hooks. Quit and reopen the Codex app once.")
            return 0
        if args in (["status"], ["status", "--json"]):
            return status(as_json="--json" in args)
    except (SettingsError, OSError) as error:
        print(f"arbol-agents: {error}", file=sys.stderr)
        return 1
    print(USAGE, file=sys.stderr)
    return 2


def entry() -> None:
    sys.exit(main(sys.argv[1:]))
