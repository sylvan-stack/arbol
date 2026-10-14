"""Where things are, and what a repository says about its build (BLD-0, "What a repository says about its build")."""

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from .launcher import COMPONENT_PATTERN, entry_path, positive, refuse_constant

KINDS = ("unit", "contract", "live")


@dataclass
class Locations:
    registry: str
    bin: str
    repo: str | None = None


def locations() -> Locations:
    home = os.path.expanduser("~")
    return Locations(os.path.join(home, "Library/Application Support/Arbol/builds"), os.path.join(home, ".local/bin"))


def component_name(name: str) -> str:
    if COMPONENT_PATTERN.fullmatch(name) is None:
        raise ValueError("A component name must contain lower-case letters, digits and separating hyphens.")
    return name


def load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as stream:
        return json.loads(stream.read(), parse_constant=refuse_constant)


def blank(value: object) -> bool:
    return not isinstance(value, str) or value.strip() == ""


def description(repo: str, component: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """The repository's arbol-build.json, its package version and where the source comes from."""
    config = load_json(os.path.join(repo, "arbol-build.json"))
    if (not isinstance(config, dict) or not config or config.get("component") != component
            or not isinstance(config.get("build"), list) or not config["build"]
            or any(blank(command) for command in config["build"])
            or entry_path("/build", config.get("entry")) is None
            or not isinstance(config.get("checks"), list) or not config["checks"]):
        raise ValueError("Invalid arbol-build.json: expected this component, nonempty build commands, "
                         "a relative executable entry and named checks.")
    names: set[str] = set()
    for check in config["checks"]:
        if (not isinstance(check, dict) or blank(check.get("name")) or check["name"] in names
                or blank(check.get("command")) or ("kind" in check and check["kind"] not in KINDS)):
            raise ValueError("Invalid or duplicate check in arbol-build.json.")
        names.add(check["name"])
    for key in ("contract", "dataFormat"):
        if key in config and not positive(config[key]):
            raise ValueError("contract and dataFormat must be positive whole numbers.")
    if component.endswith("-driver") and ("contract" not in config or "dataFormat" not in config or any(
            not any(check.get("kind") == kind for check in config["checks"]) for kind in KINDS)):
        raise ValueError("A Driver requires contract, dataFormat and unit, contract and live checks.")
    package = load_json(os.path.join(repo, "package.json"))
    version = package.get("version") if isinstance(package, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ValueError("package.json must name the package version.")

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=repo, check=True, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True).stdout.strip()

    source = {"repository": os.path.realpath(os.path.abspath(repo)), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
              "commit": git("rev-parse", "HEAD"), "uncommittedChanges": git("status", "--porcelain") != ""}
    return config, version, source
