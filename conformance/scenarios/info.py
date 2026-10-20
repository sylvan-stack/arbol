"""What every scenario checks about `info` and the vendor tool's version (DRV-0)."""

from __future__ import annotations

import re
from typing import Any

from ..check import check, equal, object_, text
from ..harness import ScenarioHome
from ..js import JSObject


def inspect_info(value: Any) -> tuple[JSObject, JSObject, str]:
    info = object_("info result", value)
    name = text("info Driver name", info["driver"])
    check("Supported Driver identity", name in ("claude", "codex", "pi"), "claude, codex or pi", name)
    tool = object_("info tool", info["tool"])
    equal("Vendor tool name", tool["name"], name)
    text("Oldest supported tool version", tool["oldestSupported"])
    return info, tool, name


def version_order(found: str, needed: str) -> int:
    for version in (found, needed):
        check("Tool version format", re.fullmatch(r"\d+\.\d+\.\d+", version, re.ASCII) is not None,
              "a three-part tool version", version)
    left = [int(part) for part in found.split(".")]
    right = [int(part) for part in needed.split(".")]
    for index in range(3):
        if left[index] != right[index]:
            return -1 if left[index] < right[index] else 1
    return 0


async def version_records(home: ScenarioHome, part: str) -> None:
    records = await home.received()
    check("Stand-in was used", len(records) > 0, "at least one stand-in version probe", records)
    for record in records:
        equal("Stand-in scenario", record["scenario"], home.id)
        equal("Stand-in part", record["part"], part)
        equal("Only version probes reached the tool", record["arguments"], ["--version"])
        check("Version probe working folder", home.contains(record["workingDirectory"]), "a folder in the scenario home",
              record["workingDirectory"])
