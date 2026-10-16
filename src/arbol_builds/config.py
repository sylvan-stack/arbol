"""Where things are, and what a repository says about its build (BLD-0, "What a repository says about its build")."""

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from .launcher import (
    COMPONENT_PATTERN,
    TRUNKS,
    code_name,
    entry_path,
    js_integer,
    positive,
    refuse_constant,
    root_contracts,
    trunk,
)

KINDS = ("unit", "contract", "live")
# The characters JavaScript's trim() removes, which decided what counted as blank in the Node.js tool.
JS_SPACE = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a" \
    "\u2028\u2029\u202f\u205f\u3000\ufeff"


@dataclass
class Locations:
    registry: str
    bin: str
    repo: str | None = None


def locations() -> Locations:
    home = os.path.expanduser("~")
    return Locations(os.path.join(home, "Library/Application Support/Arbol/builds"), os.path.join(home, ".local/bin"))


def component_name(name: str) -> str:
    if trunk(name):
        if not code_name(name[len(TRUNKS) + 1:]):
            raise ValueError("A Trunk is named arbol-trunk/<code name>: one lower-case word of 1 to 32 letters and "
                             "digits that starts with a letter and is not run, settle or list.")
    elif COMPONENT_PATTERN.fullmatch(name) is None or name == TRUNKS:
        raise ValueError("A component name must contain lower-case letters, digits and separating hyphens.")
    return name


def default_repository(component: str) -> str:
    """~/repos/sylvan-stack/readonly/<component>, and for a Trunk its folder trunks/<code name>/ in arbol-trunk: the
    clones that always hold the last merged main, never the repositories' own folders (BLD-D18)."""
    folder = os.path.join(os.path.expanduser("~"), "repos/sylvan-stack/readonly")
    if trunk(component):
        return os.path.join(folder, TRUNKS, "trunks", component[len(TRUNKS) + 1:])
    return os.path.join(folder, component)


def load_json(path: str) -> Any:
    # Bytes that are not UTF-8 read as U+FFFD, as the Node.js tool read them.
    with open(path, encoding="utf-8", errors="replace") as stream:
        return json.loads(stream.read(), parse_constant=refuse_constant, parse_int=js_integer)


def blank(value: object) -> bool:
    return not isinstance(value, str) or value.strip(JS_SPACE) == ""


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
    if trunk(component) and ("contract" in config or not root_contracts(config.get("rootContracts"))):
        raise ValueError("A Trunk requires rootContracts, the distinct positive whole numbers of the Root Contract "
                         "versions it implements, and lists them in place of contract.")
    if not trunk(component) and "rootContracts" in config:
        raise ValueError("Only a Trunk lists rootContracts.")
    package = load_json(os.path.join(repo, "package.json"))
    version = package.get("version") if isinstance(package, dict) else None
    if not isinstance(version, str) or blank(version):
        raise ValueError("package.json must name the package version.")

    def git(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=repo, check=False, stdin=subprocess.DEVNULL, capture_output=True,
                                encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise ValueError(f"Command failed: git {' '.join(args)}\n{result.stderr}")
        return result.stdout.strip(JS_SPACE)

    source = {"repository": os.path.realpath(os.path.abspath(repo)), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
              "commit": git("rev-parse", "HEAD"), "uncommittedChanges": git("status", "--porcelain") != ""}
    return config, version, source
