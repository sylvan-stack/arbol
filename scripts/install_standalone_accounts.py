"""Install one sealed, numbered standalone account Driver alongside the registered cohort."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import tempfile
from pathlib import Path
from pwd import getpwuid

from arbol_builds.driver_admission import private_directory
from arbol_builds.driver_payload import load

NAMES = {"arbol-pi-driver": "Arbol Pi Driver", "arbol-mimo-driver": "Arbol MiMo Driver"}
MARKER = "# standalone Arbol account driver"


def install(candidate: Path) -> tuple[str, Path]:
    candidate = candidate.resolve(strict=True)
    record = json.loads((candidate / "build.json").read_bytes())
    component, build = record["component"], record["build"]
    if (component not in NAMES or not isinstance(build, str) or not re.fullmatch("[1-9a-f][0-9a-f]*", build)
            or record["status"] != "working" or record["source"]["uncommittedChanges"] is not False):
        raise ValueError("Select a working numbered Pi or MiMo package built from committed source.")
    payload = load(candidate / "driver-payload", component, build)
    if payload.descriptor["source"]["commit"] != record["source"]["commit"]:
        raise ValueError("The sealed payload and Build record identify different source.")
    home = Path(getpwuid(os.getuid()).pw_dir)
    library = home / ".local/lib/sylvan-stack" / (component + "-accounts")
    library.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_directory(library)
    route = home / "Applications" / NAMES[component] / "bin" / component
    route.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_directory(route.parent)
    target = library / build
    fd = os.open(library / ".install.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not target.exists():
            with tempfile.TemporaryDirectory(dir=library) as scratch:
                stage = Path(scratch) / build
                stage.mkdir(mode=0o700)
                shutil.copytree(payload.root, stage / "driver-payload", symlinks=True)
                if load(stage / "driver-payload", component, build).digest != payload.digest:
                    raise ValueError("The staged standalone Driver payload changed.")
                stage.rename(target)
        installed = load(target / "driver-payload", component, build)
        if installed.digest != payload.digest:
            raise ValueError("The standalone Build number belongs to another payload.")
        if os.path.lexists(route):
            if route.is_symlink() or not route.is_file() or route.stat().st_uid != os.getuid():
                raise ValueError("The standalone Driver route belongs to another installation.")
            if route.read_text().splitlines()[:2] != ["#!/bin/sh", MARKER]:
                raise ValueError("The standalone Driver route belongs to another installation.")
        command = shlex.join([*installed.prefix, "--standalone-accounts"])
        with tempfile.TemporaryDirectory(dir=route.parent) as scratch:
            launcher = Path(scratch) / component
            environment = ""
            if component == "arbol-pi-driver":
                native = route.parent.parent / "Native Pi"
                native_path = f"{native / 'node_modules/.bin'}:{native / 'node-bin'}"
                environment = f'export PATH={shlex.quote(native_path)}:"$PATH"\n'
            launcher.write_text(f'#!/bin/sh\n{MARKER}\n{environment}exec {command} "$@"\n')
            launcher.chmod(0o755)
            os.replace(launcher, route)
    return build, route


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    build, route = install(parser.parse_args().candidate)
    print(json.dumps({"build": build, "command": str(route)}))


if __name__ == "__main__":
    main()
