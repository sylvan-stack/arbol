# Test implementations moved to tests/mid/archived/conformance/scenarios/c32.py.
"""C32: command line, identity and development checks (DRV-0, DRV-1, DRV-5)."""

from __future__ import annotations

import re
from typing import Any

from ..check import ScenarioError, check, equal, text
from ..harness import Scenario, ScenarioHome
from ..js import UNDEFINED, JSObject, join, text_of
from .info import inspect_info, version_order, version_records


async def run(home: ScenarioHome) -> None:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


def assign(value: Any, key: str, field: Any) -> None:
    """`value.key = field` in strict JavaScript: an array takes it but leaves it out of its JSON text; null and other
    primitives throw V8's TypeError."""
    if isinstance(value, dict):
        value[key] = field
    elif value is None:
        raise ScenarioError(f"Cannot set properties of null (setting '{key}')")
    elif not isinstance(value, list):
        kind = "string" if isinstance(value, str) else "boolean" if isinstance(value, bool) else "number"
        raise ScenarioError(f"Cannot create property '{key}' on {kind} '{text_of(value)}'")


async def check_driver_info(home: ScenarioHome) -> None:
    await home.part("info")
    identity: Any = UNDEFINED
    for override in (False, True):
        state = join(home.home, "explicit-state") if override else None
        reply = await home.json(["--state-dir", state, "info"] if state is not None else ["info"])
        equal("info exit status", reply.process["status"], 0)
        info, tool, name = inspect_info(reply.result)
        equal("Contract version", info["contract"], 2 if name in ("claude", "pi") else 1)
        version = text("Package version", info["version"])
        check("Package version format", re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", version, re.ASCII) is not None,
              "a semantic package version", version)
        build = text("Build number", info["build"])
        check("Build number format", re.fullmatch(r"(?:0|[1-9a-f][0-9a-f]*)", build) is not None,
              "a hexadecimal Build number, or 0 for a source checkout", build)
        equal("State directory", info["stateDirectory"],
              state if state is not None else join(home.home, "Library", "Application Support", "Arbol", "drivers", name))
        equal("Settings filename", info["settingsFile"], join(home.home, ".arbol", f"arbol-{name}-driver.json"))
        equal("Supported tool path", tool["path"], home.tool_path)
        equal("Supported tool version", tool["supported"], True)
        found = text("Reported tool version", tool["version"])
        needed = text("Oldest supported tool version", tool["oldestSupported"])
        check("Supported version meets the support boundary", version_order(found, needed) >= 0,
              f"a version at least {needed}", found)
        current = JSObject(driver=name, version=version, build=build, contract=info["contract"])
        if identity is UNDEFINED:
            identity = current
        else:
            equal("Identity is stable with a state override", current, identity)
        await version_records(home, "info")
        for record in await home.received():
            equal("Reported version matches the stand-in", tool["version"], record["toolVersion"])


c32 = Scenario("C32", "Command line, identity and development checks",
               "all commands and options, JSON/file/stdin requests, text output, unknown input, exit codes, secret-input "
               "refusal and build/probe commands; Keychain steps also checked by C2/C3",
               ["DRV-0.1", "DRV-0.11", "DRV-0.12", "DRV-0.13", "DRV-0.14", "DRV-0.15", "DRV-1.23", "DRV-1.26", "DRV-5.3",
                "DRV-5.4", "DRV-5.6", "DRV-5.8", "DRV-5.10"], run)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
