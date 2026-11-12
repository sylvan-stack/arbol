"""Arbol image identity, schema compatibility, payload hashes and pinned dependencies."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arbol_backend.model import BUILD_ID, object_file, schema_compatibility  # noqa: E402

MUTABLE = {"build.json", "build.log", "last-start", "package-manifest.json"}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def baseline_sha256(folder: Path) -> str:
    database = folder / "database"
    entries = tomllib.loads((database / "migrations.toml").read_text())["migrations"]
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
        raise ValueError("The migration manifest does not declare the canonical baseline.")
    baseline = entries[0]
    if (baseline.get("id") != "arbol-baseline" or baseline.get("revision") != 1
            or baseline.get("predecessor") != 0 or baseline.get("compatibility_version") != 1
            or baseline.get("file") != "001-baseline.sql"):
        raise ValueError("The migration manifest does not declare the canonical baseline.")
    actual = digest(database / "001-baseline.sql")
    if actual != baseline.get("sha256"):
        raise ValueError("The canonical baseline does not match its migration digest.")
    return actual


def files(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): digest(p)
        for p in sorted(folder.rglob("*"))
        if p.is_file()
        and str(p.relative_to(folder)) not in MUTABLE
        and p.suffix != ".pyc"
        and "__pycache__" not in p.parts
    }


def compatibility(folder: Path, record: dict[str, Any]) -> tuple[tuple[int, int], ...]:
    declared = schema_compatibility(object_file(folder / "arbol-build.json").get("schemaCompatibility"))
    if dict(declared) != dict(schema_compatibility(record.get("schemaCompatibility"))):
        raise ValueError("The Build and source must declare the same schema compatibility.")
    return declared


def build_record(folder: Path) -> dict[str, Any]:
    record = object_file(folder / "build.json")
    if (
        record.get("component") != "arbol"
        or record.get("entry") != "bin/arbol"
        or "root" in record
        or not isinstance(record.get("build"), str)
        or not BUILD_ID.fullmatch(record["build"])
        or record.get("packageVersion") != object_file(folder / "package.json").get("version")
    ):
        raise ValueError("The Arbol Build identity must match its package.")
    declared = compatibility(folder, record)
    if dict(declared) != dict(schema_compatibility(object_file(folder / "package.json").get("schemaCompatibility"))):
        raise ValueError("The Build and package must declare the same schema compatibility.")
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
        or "root" in record
        or not isinstance(record.get("build"), str)
        or not BUILD_ID.fullmatch(record["build"])
        or record["build"] != os.environ.get("ARBOL_BUILD_NUMBER")
        or record.get("packageVersion") != object_file(root / "package.json").get("version")
    ):
        raise ValueError("The allocated Build must agree with the source and number.")
    compatibility(root, record)
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
        or "root" in manifest
        or dict(schema_compatibility(manifest.get("schemaCompatibility"))) != dict(compatibility(folder, record))
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
        or manifest.get("baselineSha256") != baseline_sha256(folder)
    ):
        raise ValueError("The packaged Python or canonical baseline changed.")
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
