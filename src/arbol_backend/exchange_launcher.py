"""Use the installed Trunk selector and its exact executable handoff."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from arbol_installation.paths import INSTALLATION_LAYOUT

from .exchange_admission import GENERATION_ENV
from .exchange_command import Command
from .exchange_context import Context, Refusal
from .model import BUILD_ID, schema_compatibility

MAX_REPLY = 1024 * 1024
SCHEMA_ERRORS = {
    "unavailable": "database_unavailable",
    "uninitialized": "schema_uninitialized",
    "invalid": "schema_invalid",
}


@dataclass(frozen=True)
class Reply:
    value: dict[str, Any]
    status: int = 0

    @property
    def raw(self) -> bytes:
        return (json.dumps(self.value, ensure_ascii=True, separators=(",", ":")) + "\n").encode()


def object_line(line: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except (UnicodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def command_reply(context: Context, arguments: list[str], *, timeout: float,
                  generation: str | None = None) -> Reply:
    executable = context.bin_dir / "arbol-trunk"
    environment = context.environment()
    if generation is not None:
        environment[GENERATION_ENV] = generation
    try:
        result = subprocess.run([str(executable), *arguments], env=environment, stdin=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, stdout=subprocess.PIPE, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise Refusal("no_answer", "The Trunk command did not answer within its time limit.") from None
    except (OSError, ValueError):
        raise Refusal("trunk_unavailable", "The installed Trunk launcher could not be started.") from None
    value = object_line(result.stdout) if len(result.stdout) <= MAX_REPLY else None
    if value is None or (result.returncode and not isinstance(value.get("error"), dict)):
        raise Refusal("trunk_unavailable", "The Trunk launcher did not return a usable reply.")
    return Reply(value, 1 if "error" in value else 0)


def list_reply(context: Context, code: str | None, *, timeout: float = 12.0) -> Reply:
    return command_reply(context, [code, "list"] if code else ["list"], timeout=timeout)


def select_build(context: Context, command: Command, *, timeout: float) -> str | Reply:
    if command.code is None:
        raise Refusal("invalid_input", "A start must select a Trunk.")
    number = command.options.get("-v")
    reply = list_reply(context, command.code, timeout=timeout)
    if reply.status:
        return reply
    try:
        schema = reply.value["schema"]
        status = schema["status"]
        if status in SCHEMA_ERRORS:
            raise Refusal(SCHEMA_ERRORS[status], "Cannot select a Trunk without a verified installed schema.")
        layout = reply.value["installationLayout"]
        revision, compatibility = schema["revision"], schema["compatibilityVersion"]
        if (type(layout) is not int or layout != INSTALLATION_LAYOUT
                or type(revision) is not int or revision < 1 or type(compatibility) is not int or compatibility < 1):
            raise ValueError
        entries = reply.value["trunks"]
        if status != "ready" or not isinstance(entries, list) or len(entries) != 1 or entries[0]["trunk"] != command.code:
            raise ValueError
        records = entries[0]["builds"]
        if not isinstance(records, list):
            raise ValueError
        numbers: set[str] = set()
        for record in records:
            build = record["build"]
            record_layout = record["installationLayout"]
            if (not isinstance(build, str) or not BUILD_ID.fullmatch(build) or build in numbers
                    or type(record_layout) is not int or record_layout < 1
                    or not isinstance(record["status"], str)
                    or any(type(record[field]) is not bool for field in ("fits", "runnable", "chosen"))):
                raise ValueError
            fits = record_layout == layout and any(
                version == compatibility and minimum <= revision
                for version, minimum in schema_compatibility(record["schemaCompatibility"])
            )
            if record["fits"] != fits:
                raise ValueError
            numbers.add(build)
        chosen = [record for record in records if record["chosen"]]
        if len(chosen) > 1 or any(not row["fits"] or not row["runnable"] or row["status"] != "working" for row in chosen):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise Refusal("trunk_unavailable", "The Trunk launcher returned an unreadable inventory.") from None
    available = [record["build"] for record in records if record["fits"] and record["runnable"]]
    if number is not None:
        if number in available:
            return number
        raise Refusal("no_fit", f"{command.code}@{number} is unavailable for the installed layout and schema.", available)
    if chosen:
        return str(chosen[0]["build"])
    raise Refusal("no_fit", f"No working Build of {command.code} fits the installed layout and schema.", available)
