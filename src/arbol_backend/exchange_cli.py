"""The private installation Exchange command used by backend callers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .exchange_command import parse
from .exchange_context import Refusal, context
from .exchange_launcher import Reply, list_reply
from .exchange_listing import listing
from .exchange_settle import settle
from .exchange_start import start
from .exchange_stop import stop
from .model import Refused


def main(args: list[str], package: Path) -> Reply:
    try:
        command = parse(args)
        installation = context(package, command.options)
        if command.name == "trunks":
            return list_reply(installation, command.code)
        if command.name == "start":
            return start(installation, command)
        if command.name == "settle":
            return settle(installation, command.exchange)
        if command.name == "stop":
            assert command.exchange is not None
            return stop(installation, command.exchange, "--force" in command.options)
        return Reply(listing(installation))
    except Refused as error:
        value: dict[str, Any] = {"error": {"code": error.code, "message": str(error)}}
        if isinstance(error, Refusal) and error.available is not None:
            value["available"] = error.available
        return Reply(value, 1)
    except OSError:
        return Reply({"error": {"code": "runtime_unavailable", "message": "The Exchange runtime could not be opened."}}, 1)


def entry(package: Path) -> None:
    reply = main(sys.argv[1:], package)
    sys.stdout.buffer.write(reply.raw)
    sys.exit(reply.status)
