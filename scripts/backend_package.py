"""Root-scoped Arbol image identity, payload hashes and pinned dependency metadata."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arbol_backend.model import BUILD_ID, ROOT_ID, object_file  # noqa: E402

MUTABLE = {"build.json", "build.log", "last-start", "package-manifest.json"}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): digest(p)
        for p in sorted(folder.rglob("*"))
        if p.is_file()
        and str(p.relative_to(folder)) not in MUTABLE
        and p.suffix != ".pyc"
        and "__pycache__" not in p.parts
    }


def build_record(folder: Path) -> dict[str, Any]:
    record = object_file(folder / "build.json")
    if (
        record.get("component") != "arbol"
        or record.get("entry") != "bin/arbol"
        or not isinstance(record.get("root"), str)
        or not ROOT_ID.fullmatch(record["root"])
        or not isinstance(record.get("build"), str)
        or not BUILD_ID.fullmatch(record["build"])
        or record.get("packageVersion") != object_file(folder / "package.json").get("version")
    ):
        raise ValueError("The Arbol Build identity must match its package.")
    return record


def destination(root: Path) -> Path:
    value = os.environ.get("ARBOL_BUILD_DIR", "")
    if not value or not Path(value).is_absolute():
        raise ValueError("ARBOL_BUILD_DIR must name an absolute newly allocated Build.")
    folder = Path(value).resolve(strict=True)
    root = root.resolve()
    if folder == root or folder in root.parents or root in folder.parents:
        raise ValueError("The Build folder cannot overlap its source.")
    if any(path.name not in {"build.json", "build.log"} for path in folder.iterdir()):
        raise ValueError("The Build folder already contains payload.")
    record = object_file(folder / "build.json")
    if (
        record.get("component") != "arbol"
        or record.get("entry") != "bin/arbol"
        or not isinstance(record.get("root"), str)
        or not ROOT_ID.fullmatch(record["root"])
        or not isinstance(record.get("build"), str)
        or not BUILD_ID.fullmatch(record["build"])
        or record["build"] != os.environ.get("ARBOL_BUILD_NUMBER")
        or record.get("packageVersion") != object_file(root / "package.json").get("version")
    ):
        raise ValueError("The allocated Build must agree with the source and number.")
    return folder


def metadata(root: Path) -> dict[str, str]:
    value = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    pin = object_file(root / "scripts/python-distribution.json")
    if (
        value["name"] != "arbol"
        or value["requires-python"] != "==" + pin["version"]
        or (root / ".python-version").read_text().strip() != pin["version"]
        or value["dependencies"] != ["psycopg[binary]==3.3.6"]
    ):
        raise ValueError("Python and binary database dependencies must match their pins.")
    return {"psycopg": "3.3.6", "psycopg-binary": "3.3.6"}


def source(root: Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True, timeout=10).strip()

    return {
        "commit": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "uncommittedChanges": bool(git("status", "--porcelain")),
    }


def verify(folder: Path) -> None:
    record = build_record(folder)
    manifest = object_file(folder / "package-manifest.json")
    if (
        manifest.get("component") != "arbol"
        or manifest.get("root") != record["root"]
        or manifest.get("build") != record["build"]
        or manifest.get("entry") != record["entry"]
        or manifest.get("packageVersion") != record["packageVersion"]
        or manifest.get("dependencies") != metadata(folder)
        or manifest.get("files") != files(folder)
    ):
        raise ValueError("The packaged image must match its Build identity and every payload hash.")
    python = manifest["python"]
    if (
        python["version"] != object_file(folder / "scripts/python-distribution.json")["version"]
        or python["executable"] != "runtime/python/bin/python3.14"
        or python["sha256"] != digest(folder / python["executable"])
        or not re.fullmatch("[0-9a-f]{64}", manifest["contractLayoutSha256"])
        or manifest["contractLayoutSha256"] != digest(folder / "tests/backend/layout.sql")
    ):
        raise ValueError("The packaged Python or contract test input changed.")
    sys.path.insert(0, str(folder))
    from tools.elma_bundle import verify as verify_renderer
    renderer = verify_renderer(folder / "ui/elma", record["build"])
    if manifest.get("renderer") != {"path": "ui/elma", "build": record["build"],
            "bundleSha256": digest(folder / "ui/elma/bundle.json"), "designSystem": renderer["designSystem"]}:
        raise ValueError("The packaged renderer provenance changed.")
    lock = tomllib.loads((folder / "uv.lock").read_text())
    pins = {p["name"]: p["version"] for p in lock["package"]}
    if any(pins.get(name) != version for name, version in manifest["dependencies"].items()):
        raise ValueError("Packaged dependency versions must agree with uv.lock.")


def write_manifest(folder: Path, value: dict[str, Any]) -> None:
    value["files"] = files(folder)
    (folder / "package-manifest.json").write_text(json.dumps(value, indent=2) + "\n")
