"""Record and verify the selected Arbol release in private recovery storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

COMMIT = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
LABEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*")
MUTABLE_BUILD_FILES = {"build.log", "last-start", ".use.lock"}


class RecoveryError(ValueError):
    """A recovery gate could not be established."""


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def document(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_bytes())
    if not isinstance(data, dict):
        raise RecoveryError("Expected a JSON object.")
    return data


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_private(path: Path, value: object) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def private_dir(path: Path) -> Path:
    path = path.resolve(strict=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RecoveryError("Recovery storage must be in a directory accessible only to its owner.")
    return path


@contextmanager
def publish_directory(destination: Path) -> Iterator[Path]:
    parent = private_dir(destination.parent)
    destination = parent / destination.name
    if os.path.lexists(destination):
        raise RecoveryError("The recovery output already exists.")
    with tempfile.TemporaryDirectory(prefix=".recovery-", dir=parent) as temporary:
        staging = Path(temporary) / "output"
        staging.mkdir(mode=0o700)
        yield staging
        if os.path.lexists(destination):
            raise RecoveryError("The recovery output already exists.")
        staging.rename(destination)


def relative(value: str) -> Path:
    path = Path(value)
    if not path.parts or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise RecoveryError("An evidence path is not a safe relative path.")
    return path


def tree(folder: Path, *, exclude: frozenset[str] = frozenset()) -> dict[str, object]:
    """Bind file bytes, executable bits and contained symlinks without following directory links."""
    result: dict[str, object] = {}
    for path in sorted(folder.rglob("*")):
        name = path.relative_to(folder).as_posix()
        if name in exclude:
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            link = os.readlink(path)
            if Path(link).is_absolute() or not path.resolve(strict=True).is_relative_to(folder):
                raise RecoveryError("A selected payload has a symlink outside its saved directory.")
            result[name] = {"link": link}
        elif stat.S_ISREG(info.st_mode):
            result[name] = {"sha256": digest(path), "executable": info.st_mode & 0o111}
        elif not stat.S_ISDIR(info.st_mode):
            raise RecoveryError("A selected payload contains a special file.")
    return result


def git(checkout: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(checkout), *args], capture_output=True, timeout=60, check=False,
        env={"HOME": str(Path.home()), "PATH": "/usr/bin:/bin", "GIT_NO_REPLACE_OBJECTS": "1"},
    )
    if result.returncode:
        raise RecoveryError("A recorded Git revision or input is unavailable.")
    return result.stdout


def commit_id(value: object) -> str:
    if not isinstance(value, str) or not COMMIT.fullmatch(value):
        raise RecoveryError("The selected source needs a full Git commit ID.")
    return value


def source_file(checkout: Path, commit: str, prefix: str, name: str) -> bytes:
    return git(checkout, "show", f"{commit}:{prefix}{relative(name).as_posix()}")


def save_sources(checkout: Path, commit: str, destination: Path) -> None:
    # git archive writes directly to the private staging directory.
    git(checkout, "archive", "--format=tar", f"--output={destination}", commit)


def check_hashes(folder: Path, hashes: object) -> None:
    if not isinstance(hashes, dict) or not hashes:
        raise RecoveryError("The package does not record its file hashes.")
    for name, expected in hashes.items():
        path = folder / relative(name)
        if not path.resolve(strict=True).is_relative_to(folder) or digest(path) != expected:
            raise RecoveryError(f"Package evidence differs for {name}.")


def renderer_evidence(
    folder: Path, build: str, checkout: Path, commit: str, design_checkout: Path, *, external: bool,
) -> dict[str, object]:
    renderer = document(folder / "bundle.json")
    if renderer.get("format") != 1 or renderer.get("build") != build:
        raise RecoveryError("The renderer does not belong to the selected Build.")
    if external and renderer.get("sourceCommit") != commit:
        raise RecoveryError("The App renderer differs from its committed source reference.")
    check_hashes(folder, renderer.get("files"))
    if renderer["lockSha256"] != sha(source_file(checkout, commit, "ui/elma/", "package-lock.json")):
        raise RecoveryError("The renderer lock does not match its Git revision.")
    sources = renderer["sources"]
    if not isinstance(sources, dict) or not sources:
        raise RecoveryError("The renderer does not record its source hashes.")
    for name, expected in sources.items():
        if sha(source_file(checkout, commit, "ui/elma/", name)) != expected:
            raise RecoveryError(f"Renderer source evidence differs for {name}.")
    design = renderer["designSystem"]
    design_source = source_file(checkout, commit, "ui/elma/", "design-system/manifest.json")
    if design["manifestSha256"] != sha(design_source) or json.loads(design_source)["commit"] != design["commit"]:
        raise RecoveryError("The renderer design reference does not match its source.")
    design_commit = commit_id(design["commit"])
    git(design_checkout, "cat-file", "-e", design_commit + "^{commit}")
    return {"sourceCommit": commit, "designCommit": design_commit, "lockSha256": renderer["lockSha256"]}


def python_evidence(
    manifest: dict[str, Any], checkout: Path, commit: str, prefix: str, folder: Path,
) -> dict[str, object]:
    python = manifest["python"]
    pin = json.loads(source_file(checkout, commit, prefix, "scripts/python-distribution.json"))
    distribution = pin["distributions"][python["target"]]
    if python["version"] != pin["version"] or python["archiveSha256"] != distribution["sha256"]:
        raise RecoveryError("The packaged interpreter differs from the committed toolchain pin.")
    for field, expected in (("provider", pin["provider"]), ("release", pin["release"]),
                            ("archiveUrl", distribution["url"])):
        if field in python and python[field] != expected:
            raise RecoveryError("The packaged interpreter provenance differs from its pin.")
    path = folder / relative(python["executable"])
    if not path.resolve(strict=True).is_relative_to(folder):
        raise RecoveryError("The package interpreter is outside the selected payload.")
    if digest(path) != python.get("executableSha256", python.get("sha256")):
        raise RecoveryError("The packaged interpreter does not match its digest.")
    lock = source_file(checkout, commit, prefix, "uv.lock")
    packages = {entry["name"]: entry["version"] for entry in tomllib.loads(lock.decode())["package"]}
    dependencies = manifest.get("dependencies", {})
    if any(packages.get(name) != version for name, version in dependencies.items()):
        raise RecoveryError("A packaged dependency differs from its lock.")
    for name in ("package.json", "pyproject.toml", ".python-version", "uv.lock", "arbol-build.json",
                 "scripts/python-distribution.json"):
        path = folder / name
        if path.is_file() and path.read_bytes() != source_file(checkout, commit, prefix, name):
            raise RecoveryError(f"Packaged input differs from its Git revision: {name}.")
    return {"python": python, "uvVersion": pin["uvVersion"], "lockSha256": sha(lock), "dependencies": dependencies}


def capture_build(
    item: dict[str, Any], output: Path, index: int, inventory: dict[str, Any],
) -> dict[str, Any]:
    folder = Path(item["directory"]).resolve(strict=True)
    record = document(folder / "build.json")
    component = record["component"]
    build = record["build"]
    if record.get("status") != "working" or not re.fullmatch(r"[1-9a-z][0-9a-z]*", build):
        raise RecoveryError("Select a working, numbered Build.")
    source = record["source"]
    if source.get("uncommittedChanges") is not False:
        raise RecoveryError("The Build record does not establish clean source; its exact Git inputs are unresolved.")
    checkout = Path(item.get("checkout") or source["repository"]).resolve(strict=True)
    commit = commit_id(source["commit"])
    prefix = git(checkout, "rev-parse", "--show-prefix").decode().strip()
    entry = relative(record["entry"])
    build_config = json.loads(source_file(checkout, commit, prefix, "arbol-build.json"))
    version = json.loads(source_file(checkout, commit, prefix, "package.json"))["version"]
    if (build_config["component"] != component or build_config["entry"] != record["entry"]
            or version != record["packageVersion"] or not os.access(folder / entry, os.X_OK)):
        raise RecoveryError("Build identity, entry or package version differs from its committed configuration.")

    evidence: dict[str, Any] = {}
    manifest_file = folder / "package-manifest.json"
    if manifest_file.is_file():
        manifest = document(manifest_file)
        if (manifest.get("format") != 1 or manifest.get("candidate", False) is not False
                or any(manifest.get(key) != record.get(key)
                       for key in ("component", "build", "entry", "packageVersion", "root"))
                or manifest["source"].get("commit") != commit
                or manifest["source"].get("uncommittedChanges") is not False
                or manifest["source"].get("componentPath", prefix.rstrip("/")) != prefix.rstrip("/")):
            raise RecoveryError("The package manifest differs from the selected Build or its source.")
        check_hashes(folder, manifest["files"])
        evidence["packageManifestSha256"] = digest(manifest_file)
        if "python" in manifest:
            evidence.update(python_evidence(manifest, checkout, commit, prefix, folder))
        if component == "arbol" and inventory["kind"] == "legacy":
            # Packaging read this from another checkout; the Arbol commit cannot identify those bytes.
            packaged_layout = folder / "tests/backend/layout.sql"
            expected = manifest["contractLayoutSha256"]
            if not DIGEST.fullmatch(expected) or digest(packaged_layout) != expected:
                raise RecoveryError("The exact packaged Root Contract SQL is unresolved.")
            evidence["rootContract"] = {"sha256": expected, "path": "tests/backend/layout.sql"}
        if component == "arbol" and "renderer" in manifest:
            renderer = manifest["renderer"]
            bundled = folder / relative(renderer["path"])
            if digest(bundled / "bundle.json") != renderer["bundleSha256"]:
                raise RecoveryError("The packaged renderer manifest differs from the backend package.")
            evidence["renderer"] = renderer_evidence(
                bundled, build, checkout, commit, Path(inventory["designCheckout"]), external=False,
            )
            design = evidence["renderer"]["designCommit"]
            save_sources(Path(inventory["designCheckout"]), design, output / "design-source.tar")
    elif component == "arbol-app":
        # This legacy packager signs the App and embeds a separate renderer receipt instead of package-manifest.json.
        app = folder / "Arbol.app"
        verified = subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(app)],
                                  capture_output=True, check=False, timeout=60)
        if verified.returncode:
            raise RecoveryError("The selected App payload no longer verifies against its code signature.")
        renderer_commit = commit_id(source_file(checkout, commit, prefix, "renderer-source.txt").decode().strip())
        renderer_checkout = Path(inventory["rendererCheckout"])
        design_checkout = Path(inventory["designCheckout"])
        evidence["renderer"] = renderer_evidence(
            app / "Contents/Resources/ui/elma", build, renderer_checkout, renderer_commit,
            design_checkout, external=True,
        )
        save_sources(renderer_checkout, renderer_commit, output / "renderer-source.tar")
        save_sources(design_checkout, evidence["renderer"]["designCommit"], output / "design-source.tar")
        evidence["nativeToolchain"] = "Preserved signed executable; exact compiler version not emitted by this packager."
    else:
        raise RecoveryError("The Build has no verifiable package manifest.")

    package = output / "package"
    exclude = frozenset(MUTABLE_BUILD_FILES)
    before = tree(folder, exclude=exclude)
    shutil.copytree(folder, package, symlinks=True, ignore=lambda path, names: (
        set(names) & exclude if Path(path) == folder else set()
    ))
    if tree(package) != before:
        raise RecoveryError("The selected Build changed while copying.")
    save_sources(checkout, commit, output / "source.tar")
    return {"component": component, "build": build, "root": record.get("root"), "entry": str(entry),
            "packageVersion": version, "sourceCommit": commit, "componentPath": prefix.rstrip("/"),
            "buildConfigurationSha256": sha(source_file(checkout, commit, prefix, "arbol-build.json")),
            "evidence": evidence, "savedAt": f"builds/{index}"}


def copy_configuration(files: dict[str, str], destination: Path) -> list[str]:
    destination.mkdir(mode=0o700)
    for name, source in sorted(files.items()):
        if not LABEL.fullmatch(name):
            raise RecoveryError("Configuration and dependency labels must be simple names.")
        path = Path(source)
        if path.is_symlink() or not path.is_file():
            raise RecoveryError(f"Required configuration or file dependency is unavailable: {name}.")
        target = destination / name
        before = digest(path)
        shutil.copyfile(path, target)
        target.chmod(0o600)
        if digest(target) != before:
            raise RecoveryError(f"A recovery input changed while copying: {name}.")
    return sorted(files)


def record_release(inventory_path: Path, destination: Path) -> str:
    private_dir(inventory_path.parent)
    inventory = document(inventory_path)
    kind = inventory["kind"]
    if kind not in ("legacy", "current") or not isinstance(inventory["builds"], list):
        raise RecoveryError("Select a legacy or current release with an explicit Build inventory.")
    configuration = inventory["configuration"]
    required = {"installation", "root"} if kind == "legacy" else {"installation"}
    if not isinstance(configuration, dict) or not required <= configuration.keys():
        raise RecoveryError("Installation and applicable legacy settings must be saved.")
    with publish_directory(destination) as output:
        builds = []
        problems = []
        for index, item in enumerate(inventory["builds"]):
            build_output = output / "builds" / str(index)
            build_output.mkdir(parents=True, mode=0o700)
            try:
                builds.append(capture_build(item, build_output, index, inventory))
            except RecoveryError as error:
                problems.append(f"Build inventory entry {index + 1}: {error}")
            except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
                problems.append(f"Build inventory entry {index + 1}: required source or package evidence is unreadable.")
        components = {build["component"] for build in builds}
        if "arbol" not in components or (kind == "legacy" and "arbol-root" not in components):
            problems.append("Select Arbol and, for a legacy release, its Root Build.")
        keys = {(build["component"], build["build"]) for build in builds}
        if len(keys) != len(builds):
            problems.append("A selected Build appears more than once.")
        if kind == "legacy" and not any(build["evidence"].get("rootContract") for build in builds):
            problems.append("The legacy Arbol package must preserve its exact external Root Contract SQL.")
        if problems:
            raise RecoveryError("Unresolved release provenance: " + " ".join(problems))
        labels = copy_configuration(configuration, output / "configuration")
        inputs = copy_configuration(inventory.get("inputs", {}), output / "inputs")
        payload = {"format": 1, "kind": kind, "builds": builds, "configuration": labels, "inputs": inputs,
                   "files": tree(output)}
        receipt = output / "release.json"
        write_private(receipt, payload)
        return digest(receipt)


def verify_release(folder: Path, expected: str | None = None) -> tuple[dict[str, Any], str]:
    folder = private_dir(folder)
    path = folder / "release.json"
    if path.is_symlink():
        raise RecoveryError("The release record must be a private regular file.")
    data = path.read_bytes()
    actual = sha(data)
    if expected is not None and actual != expected:
        raise RecoveryError("The release record does not match the snapshot.")
    value = json.loads(data)
    if (not isinstance(value, dict) or value.get("format") != 1 or value.get("kind") not in ("legacy", "current")
            or not value.get("builds") or not value.get("configuration")
            or value.get("files") != tree(folder, exclude=frozenset({"release.json"}))):
        raise RecoveryError("Required release payloads or recovery configuration differ from the release record.")
    return value, actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = record_release(args.inventory, args.output)
    except RecoveryError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
        print("Cannot record release: an inventory or required file could not be read or saved.", file=sys.stderr)
        return 1
    print(json.dumps({"releaseSha256": result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
