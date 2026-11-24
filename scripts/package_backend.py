"""Package Arbol with its own interpreter, hash-locked binary libpq and private checks."""

from __future__ import annotations

import ast
import json
import os
import shutil
import stat
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


def provider_handlers(root: Path) -> None:
    """A partial source provider cannot be packaged as a complete capability."""
    module = ast.parse((root / "src/arbol_builds/driver_state.py").read_bytes())
    found: list[str] = []
    for node in module.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == "handler":
                if (len(decorator.args) != 1 or decorator.keywords or not isinstance(decorator.args[0], ast.Constant)
                        or not isinstance(decorator.args[0].value, str)):
                    raise ValueError("The provider handler declarations must be fixed strings.")
                found.append(decorator.args[0].value)
    if sorted(found) != ["begin", "deploy", "drain", "execute", "finish", "status"]:
        raise ValueError("The sealed provider requires exactly all six fixed handlers.")


def freeze_provider(folder: Path) -> None:
    for directory, directories, files in os.walk(folder, topdown=False, followlinks=False):
        for name in (*files, *directories):
            path = Path(directory) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                continue
            if stat.S_ISDIR(info.st_mode):
                path.chmod(0o555)
            elif stat.S_ISREG(info.st_mode):
                path.chmod(0o555 if info.st_mode & 0o111 else 0o444)
            else:
                raise ValueError("The provider cannot contain special files.")
    folder.chmod(0o700)


def stage_provider(root: Path, folder: Path, provenance: dict[str, Any]) -> tuple[str, str]:
    """Copy independent bytes, never links to the mutable Backend runtime."""
    provider_handlers(root)
    identity = provenance["source"]
    if identity.get("uncommittedChanges") is not False:
        raise ValueError("A sealed provider requires clean committed source.")
    commit = identity["commit"]
    tree = subprocess.check_output(["git", "rev-parse", commit + "^{tree}"], cwd=root, text=True, timeout=10).strip()
    allocated = json.loads((folder / "build.json").read_text())
    if (not isinstance(allocated.get("source"), dict) or allocated["source"].get("commit") != commit
            or allocated["source"].get("uncommittedChanges") is not False):
        raise ValueError("The allocated Build and sealed provider source must agree.")
    provider = folder / "driver-payload"
    provider.mkdir(mode=0o700)
    # Copy the hash-pinned interpreter and the already installed hash-locked
    # dependencies. copytree creates independent regular files; internal links
    # keep their exact relative spelling and are checked by complete M later.
    shutil.copytree(folder / "runtime", provider / "runtime", symlinks=True)
    for package_name in ("arbol_builds", "arbol_installation"):
        # Export the exact committed package files. Ignored/untracked source
        # files cannot silently become code attributed to this source commit.
        prefix = "src/" + package_name + "/"
        names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", commit, "--", prefix],
                                        cwd=root, text=True, timeout=10).splitlines()
        if not names:
            raise ValueError("The provider source package is missing.")
        for name in names:
            relative = Path(name)
            if not name.startswith(prefix) or relative.is_absolute() or ".." in relative.parts:
                raise ValueError("The committed provider source path is unsafe.")
            original = root / relative
            if not stat.S_ISREG(original.lstat().st_mode):
                raise ValueError("Provider source inputs must be regular files.")
            raw = subprocess.check_output(["git", "show", commit + ":" + name], cwd=root, timeout=10)
            if original.read_bytes() != raw:
                raise ValueError("The committed provider source changed during packaging.")
            output = provider / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(raw)
            shutil.copymode(original, output)
    (provider / "bin").mkdir()
    from arbol_builds import driver_bootstrap, service
    # Reject a cached/source-root generator from a different checkout revision.
    generator_folder = Path(driver_bootstrap.__file__).resolve().parent
    generator_inputs = (Path(driver_bootstrap.__file__).resolve(), Path(service.__file__).resolve(),
                        generator_folder / "driver_admission.py", generator_folder / "driver_payload.py")
    for path in generator_inputs:
        if path.read_bytes() != (provider / "src/arbol_builds" / path.name).read_bytes():
            raise ValueError("The provider generator differs from its committed copied verifier.")
    entry_body = subprocess.check_output(["git", "show", commit + ":bin/driver_state_entry.py"], cwd=root, timeout=10)
    if (generator_folder.parents[1] / "bin/driver_state_entry.py").read_bytes() != entry_body:
        raise ValueError("The provider entry body differs from the committed source.")
    entry = service.early_driver_signals(driver_bootstrap.render_provider_entry())
    compile(entry, "bin/driver_state_entry.py", "exec")
    (provider / "bin/driver_state_entry.py").write_bytes(entry)
    (provider / "provider-provenance.json").write_text(json.dumps({
        "version": 1, "kind": "driver-provider-provenance", "source": {"commit": commit, "tree": tree},
        "python": provenance["python"], "dependencies": provenance["dependencies"],
    }, sort_keys=True, separators=(",", ":")) + "\n")
    if source(root) != identity:
        raise ValueError("The source identity changed while staging the provider.")
    freeze_provider(provider)
    return commit, tree


def finish_provider(folder: Path, commit: str, tree: str) -> None:
    """Outer provenance is settled; M/D introduce no reciprocal digest edge."""
    from arbol_builds.driver_payload import emit
    emit(folder / "driver-payload", component="arbol", build=json.loads((folder / "build.json").read_text())["build"],
         commit=commit, tree=tree, interpreter="runtime/python/bin/python3.14", entry="bin/driver_state_entry.py",
         helpers=[], import_roots=["runtime/python/lib/python3.14", "runtime/python/lib/python3.14/lib-dynload",
                                   "runtime/site-packages", "src"])


def database_operator(folder: Path, operation: str) -> None:
    entry = folder / "bin" / f"arbol-layout-{operation}"
    entry.write_text(
        f"""#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "$root/runtime/python/bin/python3.14" -I -B -c '
import runpy
import sys
from pathlib import Path

root = Path(sys.argv.pop(1))
sys.path[:0] = [str(root / "database"), str(root / "src"), str(root / "runtime/site-packages")]
runpy.run_path(str(root / "database/layout_{operation}.py"), run_name="__main__")
' "$root" "$@"
""",
        encoding="utf-8",
    )
    entry.chmod(0o755)


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
    shutil.copytree(root / "src/arbol_import", folder / "src/arbol_import", ignore=ignore)
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
    package_record["installationLayout"] = record["installationLayout"]
    package_record["schemaCompatibility"] = record["schemaCompatibility"]
    (folder / "package.json").write_text(json.dumps(package_record, indent=2) + "\n")
    database = root / "database"
    migrations = tomllib.loads((database / "migrations.toml").read_text())["migrations"]
    (folder / "database").mkdir()
    for name in ("migrations.toml", "migrate_schema.py", "database_server.py", "install_database_server.py",
                 "probe_database_server.py", "archive_volume.py", "recovery.py", "recovery_release.py",
                 "exchange_format_transition.py", "layout_move.py", "layout_archive.py",
                 *(migration["file"] for migration in migrations)):
        if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
            raise ValueError("Each migration input must be a file in the database directory.")
        shutil.copy2(database / name, folder / "database" / name)
    for operation in ("move", "archive"):
        database_operator(folder, operation)
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
    provenance: dict[str, Any] = {
        "format": 1,
        "component": "arbol",
        "entry": "bin/arbol",
        "installationLayout": record["installationLayout"],
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
    }
    commit, tree = stage_provider(root, folder, provenance)
    write_manifest(folder, provenance)
    finish_provider(folder, commit, tree)
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
