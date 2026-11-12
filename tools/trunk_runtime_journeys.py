"""Build a disposable Arbol runtime from qualified numbered packages for ASD-8."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / relative) for relative in ("", "src", "tests", "scripts")]

from backend.support import SingleInstallation  # noqa: E402
from backend_package import verify as verify_backend  # noqa: E402

from arbol_builds.launcher import BUILD_PATTERN, code_name, executable_entry, valid_record  # noqa: E402
from arbol_builds.service import shebang, write_launcher  # noqa: E402


@dataclass(frozen=True)
class Build:
    folder: Path
    number: str
    component: str
    entry: str
    source: str

    @classmethod
    def checked(cls, folder: Path, component: str) -> Build:
        folder = folder.resolve(strict=True)
        record = object_file(folder / "build.json")
        number = record.get("build")
        if (not isinstance(number, str) or not valid_record(record, component, number)
                or record.get("status") != "working" or record.get("prunedAt")):
            raise ValueError(f"A qualified working {component} Build is required.")
        entry = record["entry"]
        if executable_entry(str(folder), entry) is None:
            raise ValueError(f"The {component} Build executable is unavailable.")
        package = object_file(folder / "package-manifest.json")
        source = record.get("source", {}).get("commit")
        if (not isinstance(source, str) or any(package.get(key) != record.get(key)
                                               for key in ("build", "entry", "component", "schemaCompatibility"))):
            raise ValueError(f"The {component} package does not match the numbered Build.")
        return cls(folder, number, component, entry, source)


def object_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}.")
    return value


def private_object(path: Path, value: dict[str, Any]) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
        stream.write("\n")


@dataclass(frozen=True)
class Reply:
    status: int
    value: dict[str, Any]

    def require(self) -> dict[str, Any]:
        if self.status != 0:
            raise ValueError(f"Private runtime command refused: {self.value}")
        return self.value


class JourneyInstallation(SingleInstallation):
    """The runtime, installed launchers and pruning tool use one private HOME."""

    def __init__(self, arbol: Build, trunk: Build) -> None:
        self._ready = False
        self._starts: set[str] = set()
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
        if revision != arbol.source:
            raise ValueError("Run the fixture from the pinned source revision of the qualified Arbol Build.")
        subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "src/arbol_builds", "src/arbol_installation",
                        "tools/trunk_runtime_journeys.py", "tools/backend_fault_driver.py"], cwd=ROOT, check=True, timeout=10)
        verify_backend(arbol.folder)
        super().__init__(arbol.folder)
        try:
            self.runtime = self.home / "Library/Application Support/Arbol/runtime"
            self.bin = self.home / ".local/bin"
            self.registry = self.cluster.base / "registry"
            self.requests = self.cluster.base / "requests"
            self.driver_control = self.cluster.base / "driver-control"
            for path in (self.runtime, self.bin, self.registry, self.requests, self.driver_control):
                path.mkdir(parents=True, mode=0o700)
            self.env = {key: value for key, value in self.env.items() if not key.startswith(("ARBOL_", "PG"))}
            self.env["PATH"] = str(self.bin) + ":/usr/bin:/bin:/usr/sbin:/sbin"
            self.require_private()
            self.arbol = self.stage(arbol)
            self.trunk = self.stage(trunk)
            self.package = self.arbol.folder
            self.stage_tools()
            self.open_admission()
            self._ready = True
        except BaseException:
            self.close()
            raise

    def options(self) -> list[str]:
        # The installed paths are under the private HOME, including for pruning.
        return []

    def require_private(self) -> None:
        base = self.cluster.base.resolve(strict=True)
        for place in (base, self.home, self.runtime, self.bin, self.registry, self.cluster.socket, self.work,
                      self.settings, self.requests, self.driver_control):
            info = place.lstat()
            if (place.resolve(strict=True) != place or not place.is_relative_to(base)
                    or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise ValueError("The journey target must be an owner-only path inside this fixture.")
        if self.home == Path.home().resolve() or self.env["HOME"] != str(self.home):
            raise ValueError("The journey refuses the caller's installation.")
        config = self.settings / "database.json"
        if config.is_symlink() or object_file(config) != {"address": self.cluster.server_address,
                                                         "database": self.cluster.database}:
            raise ValueError("The journey refuses a different PostgreSQL target.")

    def stage(self, build: Build) -> Build:
        place = self.registry / build.component / build.number
        place.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        # Relocatable internal symlinks are permitted in the packaged Python.
        for path in build.folder.rglob("*"):
            if path.is_symlink() and (Path(os.readlink(path)).is_absolute()
                                      or not path.resolve().is_relative_to(build.folder)):
                raise ValueError(f"A packaged symlink points outside {build.component}.")
        shutil.copytree(build.folder, place, symlinks=True)
        return Build.checked(place, build.component)

    def stage_tools(self) -> None:
        place = self.bin / ".arbol-builds/schema"
        shutil.copytree(self.package / "runtime/site-packages", place)
        database = self.package / "database"
        migrations = tomllib.loads((database / "migrations.toml").read_text())["migrations"]
        for name in ("migrate_schema.py", "database_server.py", "migrations.toml", *(entry["file"] for entry in migrations)):
            if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}:
                raise ValueError("The release names a schema input outside its database directory.")
            shutil.copy2(database / name, place / name)
        for component in ("arbol", "arbol-trunk"):
            write_launcher(str(self.bin), str(self.registry), component, sys.executable)
        tool = self.bin / "arbol-builds"
        tool.write_text(f"{shebang(sys.executable)}\nimport sys\nsys.path.insert(0, {str(ROOT / 'src')!r})\n"
                        "from arbol_builds.cli import entry\nentry()\n")
        tool.chmod(0o700)
        self.driver_calls = self.driver_control / "runs.log"
        driver = self.bin / "arbol-journey-fixture-driver"
        command = shlex.join([sys.executable, "-I", "-B", str(ROOT / "tools/backend_fault_driver.py"),
                              "--control-dir", str(self.driver_control)])
        driver.write_text("#!/bin/sh\n" + 'if [ "${1:-}" = run ]; then printf "%s\\n" run >> '
                          + shlex.quote(str(self.driver_calls)) + '; fi\nexec ' + command + ' "$@"\n')
        driver.chmod(0o700)

    def _call(self, executable: Path, *arguments: str, timeout: float = 30) -> Reply:
        self.require_private()
        if not executable.resolve(strict=True).is_relative_to(self.cluster.base):
            raise ValueError("The journey refuses an executable outside the disposable installation.")
        result = subprocess.run([str(executable), *arguments], cwd=self.work, env=self.env, check=False,
                                capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout)
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError("Expected one JSON object from the private runtime.")
        return Reply(result.returncode, value)

    def trunks(self) -> Reply:
        return self._call(self.bin / "arbol-trunk", "list")

    def prune(self, *, code: str | None = None, keep: int = 1) -> Reply:
        if code is not None and not code_name(code):
            raise ValueError("Expected a Trunk code name for pruning.")
        target = ["--unused"] if code is None else [f"arbol-trunk/{code}", "--keep", str(keep)]
        return self._call(self.bin / "arbol-builds", "prune", *target, "--registry-dir", str(self.registry),
                          "--bin-dir", str(self.bin))

    def runtime_call(self, command: str, exchange: UUID | None = None, *, force: bool = False) -> Reply:
        if (command not in ("list", "stop", "settle") or (command == "stop" and exchange is None)
                or (command == "list" and exchange is not None) or (force and command != "stop")):
            raise ValueError("Expected list, stop or settle on the private Exchange runtime.")
        args = [command]
        if exchange is not None:
            args.append(str(exchange))
        if force:
            args.append("--force")
        return self._call(self.package / "bin/arbol-exchanges", *args, timeout=90)

    def start(self, exchange: UUID, *, code: str = "trivial", build: str | None = None, model: str = "hold",
              public: bool = False) -> Reply:
        if not code_name(code) or (build is not None and not BUILD_PATTERN.fullmatch(build)):
            raise ValueError("Expected a Trunk code and optional numbered Build.")
        self.require_private()
        request = self.requests / f"{exchange}.json"
        if os.path.lexists(request):
            info = request.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                raise ValueError("The journey refuses a nonprivate request file.")
        else:
            private_object(request, {"message": "Run the deterministic ASD-8 fixture.",
                                     "workingFolder": str(self.work), "route": {"driver": "journey-fixture",
                                     "subscription": "private-fixture", "model": model}})
        self._starts.add(str(exchange))
        selection = [code, "-v", build] if build is not None else [code]
        args = ["--exchange", str(exchange), "--request", str(request)]
        if public:
            return self._call(self.bin / "arbol-trunk", *selection, "run", "--detach", *args)
        return self._call(self.package / "bin/arbol-exchanges", "start", *selection, *args)

    def close(self) -> None:
        try:
            if self._ready and self._starts:
                for item in self.runtime_call("list").require()["exchanges"]:
                    if item["exchange"] in self._starts and item["process"]["alive"]:
                        self.runtime_call("stop", UUID(item["exchange"]), force=True).require()
        finally:
            super().close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arbol-build", type=Path, required=True)
    parser.add_argument("--trunk-build", type=Path, required=True)
    options = parser.parse_args()
    try:
        arbol = Build.checked(options.arbol_build, "arbol")
        trunk = Build.checked(options.trunk_build, "arbol-trunk/trivial")
        fixture = JourneyInstallation(arbol, trunk)
        try:
            print(json.dumps({"arbolBuild": arbol.number, "arbolSource": arbol.source, "trivialBuild": trunk.number,
                              "trivialSource": trunk.source, "inventory": fixture.trunks().require(),
                              "runtime": fixture.runtime_call("list").require()}))
        finally:
            fixture.close()
    except (OSError, KeyError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Cannot prepare the private journey: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
