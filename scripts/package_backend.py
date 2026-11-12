"""Package Arbol with its own interpreter, hash-locked binary libpq and private checks."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend_package import (  # noqa: E402
    ROOT,
    baseline_sha256,
    destination,
    digest,
    metadata,
    source,
    verify,
    write_manifest,
)
from build_support import archive, pin, target  # noqa: E402

sys.path.insert(0, str(ROOT))
from tools.elma_bundle import package as package_elma  # noqa: E402

SOURCE_ONLY_TOP = "tests/top/test_top_roots.py"


def packaged_top(root: Path, inventory: list[dict[str, Any]]) -> set[str]:
    """Select the active Build cases and fail on missing or commented definitions."""
    modules: dict[str, ast.Module] = {}
    for item in inventory:
        if item["tier"] != "top":
            continue
        relative = item["file"]
        if item["kind"] != "python" or item["status"] != "active" or Path(relative).parent != Path("tests/top"):
            raise ValueError(f"Expected an active Python top-tier case: {item['id']}")
        if relative not in modules:
            modules[relative] = ast.parse((root / relative).read_bytes(), filename=relative)
        if not any(isinstance(cls, ast.ClassDef) and cls.name == item["class"] and any(
            isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name == item["name"]
            for method in cls.body
        ) for cls in modules[relative].body):
            raise ValueError(f"Missing top-tier definition: {item['id']}")
    return set(modules) - {SOURCE_ONLY_TOP}


def package(root: Path = ROOT) -> Path:
    folder = destination(root)
    dependencies = metadata(root)
    pinned = pin()
    architecture = target()
    compressed = archive(pinned["distributions"][architecture])
    runtime = folder / "runtime"
    runtime.mkdir(mode=0o700)
    with tarfile.open(compressed, "r:gz") as bundle:
        bundle.extractall(runtime, filter="data")
    interpreter = runtime / "python/bin/python3.14"
    probe = subprocess.check_output(
        [str(interpreter), "-I", "-B", "-c", "import platform;print(platform.python_version())"], text=True, timeout=5
    )
    if probe.strip() != pinned["version"]:
        raise ValueError("The unpacked interpreter differs from its pin.")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    shutil.copytree(root / "src/arbol_installation", folder / "src/arbol_installation", ignore=ignore)
    shutil.copytree(root / "src/arbol_backend", folder / "src/arbol_backend", ignore=ignore)
    shutil.copytree(root / "src/arbol_radar", folder / "src/arbol_radar", ignore=ignore)
    shutil.copytree(root / "tests/backend", folder / "tests/backend", ignore=ignore)
    shutil.copytree(root / "tests/radar", folder / "tests/radar", ignore=ignore)
    shutil.copytree(root / "tests/ui", folder / "tests/ui", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.mjs"))
    # Package the tier selections belonging to the same private Backend image.
    # The original modules now contain shared fixtures rather than case bodies.
    inventory = json.loads((root / "test-tiers.json").read_text())
    selections = {
        item["file"] for item in inventory["tests"]
        if item["tier"] == "mid" and item["kind"] == "python" and (
            item.get("support_file", "").startswith(("tests/backend/", "tests/radar/", "tests/ui/"))
            or item.get("support_file") == "tests/test_backend.py"
        )
    }
    selections.update(packaged_top(root, inventory["tests"]))
    selections.update(("tests/exchange_groups_support.py", "tests/exchange_start_support.py",
                       "tests/exchange_trunk_standin.py"))
    selections.update(("tests/top/__init__.py", "tests/mid/__init__.py",
                       "tests/mid/archived/scripts/check_backend.py"))
    for relative in sorted(selections):
        destination_path = folder / relative
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination_path)
    (folder / "tools").mkdir()
    for name in ("__init__.py", "bridge_relay.py", "elma_bundle.py", "backend_journeys.py", "backend_fault_driver.py"):
        shutil.copy2(root / "tools" / name, folder / "tools" / name)
    shutil.copy2(root / "tests/test_backend.py", folder / "tests/test_backend.py")
    (folder / "scripts").mkdir()
    for name in ("backend_package.py", "check_backend.py", "python-distribution.json"):
        shutil.copy2(root / "scripts" / name, folder / "scripts" / name)
    (folder / "bin").mkdir()
    for name in ("arbol", "arbol_entry.py", "arbol-exchanges", "exchanges_entry.py"):
        shutil.copy2(root / "bin" / name, folder / "bin" / name)
    for name in ("package.json", "pyproject.toml", ".python-version", "uv.lock", "arbol-build.json"):
        shutil.copy2(root / name, folder / name)
    record = json.loads((folder / "build.json").read_text())
    package_record = json.loads((folder / "package.json").read_text())
    package_record["schemaCompatibility"] = record["schemaCompatibility"]
    (folder / "package.json").write_text(json.dumps(package_record, indent=2) + "\n")
    database = root / "database"
    migrations = tomllib.loads((database / "migrations.toml").read_text())["migrations"]
    (folder / "database").mkdir()
    for name in ("migrations.toml", "migrate_schema.py", "database_server.py", "recovery.py", "recovery_release.py",
                 *(migration["file"] for migration in migrations)):
        if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
            raise ValueError("Each migration input must be a file in the database directory.")
        shutil.copy2(database / name, folder / "database" / name)
    baseline = baseline_sha256(folder)
    requirements = subprocess.check_output(
        ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "requirements-txt"],
        cwd=root,
        text=True,
        timeout=30,
    )
    lock = runtime / "requirements.txt"
    lock.write_text(requirements)
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(interpreter),
            "--target",
            str(runtime / "site-packages"),
            "--require-hashes",
            "--no-deps",
            "--only-binary",
            ":all:",
            "-r",
            str(lock),
        ],
        check=True,
        cwd=root,
        timeout=120,
    )
    renderer = package_elma(root, folder / "ui/elma", record["build"])
    write_manifest(
        folder,
        {
            "format": 1,
            "component": "arbol",
            "entry": "bin/arbol",
            "schemaCompatibility": record["schemaCompatibility"],
            "build": record["build"],
            "packageVersion": record["packageVersion"],
            "source": source(root),
            "dependencies": dependencies,
            "python": {
                "version": pinned["version"],
                "target": architecture,
                "archiveSha256": pinned["distributions"][architecture]["sha256"],
                "executable": "runtime/python/bin/python3.14",
                "sha256": digest(interpreter),
            },
            "baselineSha256": baseline,
            "renderer": {"path": "ui/elma", "build": record["build"], "bundleSha256": digest(folder / "ui/elma/bundle.json"),
                         "designSystem": renderer["designSystem"]},
        },
    )
    verify(folder)
    return folder


def main() -> int:
    try:
        print("Packaged Arbol backend in " + str(package()))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, tarfile.TarError) as error:
        print("Cannot package the backend: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
