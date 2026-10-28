"""Package Arbol with its own interpreter, hash-locked binary libpq and private checks."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend_package import ROOT, destination, digest, metadata, source, verify, write_manifest  # noqa: E402
from build_support import archive, pin, target  # noqa: E402

sys.path.insert(0, str(ROOT))
from tools.elma_bundle import package as package_elma  # noqa: E402


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
    shutil.copytree(root / "src/arbol_backend", folder / "src/arbol_backend", ignore=ignore)
    shutil.copytree(root / "src/arbol_radar", folder / "src/arbol_radar", ignore=ignore)
    shutil.copytree(root / "tests/backend", folder / "tests/backend", ignore=ignore)
    shutil.copytree(root / "tests/radar", folder / "tests/radar", ignore=ignore)
    shutil.copytree(root / "tests/ui", folder / "tests/ui", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.mjs"))
    (folder / "tools").mkdir()
    for name in ("__init__.py", "bridge_relay.py", "elma_bundle.py", "backend_journeys.py"):
        shutil.copy2(root / "tools" / name, folder / "tools" / name)
    shutil.copy2(root / "tests/test_backend.py", folder / "tests/test_backend.py")
    (folder / "scripts").mkdir()
    for name in ("backend_package.py", "check_backend.py", "python-distribution.json"):
        shutil.copy2(root / "scripts" / name, folder / "scripts" / name)
    (folder / "bin").mkdir()
    for name in ("arbol", "arbol_entry.py"):
        shutil.copy2(root / "bin" / name, folder / "bin" / name)
    for name in ("package.json", "pyproject.toml", ".python-version", "uv.lock", "arbol-build.json"):
        shutil.copy2(root / name, folder / name)
    contract = Path.home() / "repos/sylvan-stack/readonly/arbol-root/contract/1/layout.sql"
    if not contract.is_file():
        # A private test HOME changes no source input: locate the same stack's merged readonly copy.
        contract = next(
            (
                parent / "readonly/arbol-root/contract/1/layout.sql"
                for parent in root.resolve().parents
                if (parent / "readonly/arbol-root/contract/1/layout.sql").is_file()
            ),
            contract,
        )
    if not contract.is_file():
        raise ValueError("The merged readonly Root Contract layout is required as test input.")
    shutil.copy2(contract, folder / "tests/backend/layout.sql")
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
    record = json.loads((folder / "build.json").read_text())
    renderer = package_elma(root, folder / "ui/elma", record["build"])
    write_manifest(
        folder,
        {
            "format": 1,
            "component": "arbol",
            "entry": "bin/arbol",
            "root": record["root"],
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
            "contractLayoutSha256": digest(contract),
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
