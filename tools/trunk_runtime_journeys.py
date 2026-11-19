"""Build a disposable Arbol runtime from qualified numbered packages for ASD-8."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / relative) for relative in ("", "src", "tests", "scripts")]

from backend.support import SingleInstallation  # noqa: E402
from backend_package import verify as verify_backend  # noqa: E402

from arbol_backend.exchange_start import accepted, wait_reply  # noqa: E402
from arbol_backend.model import Refused, identity  # noqa: E402
from arbol_builds.launcher import BUILD_PATTERN, code_name, executable_entry, layout_fits, valid_record  # noqa: E402
from arbol_builds.service import shebang, write_launcher  # noqa: E402
from arbol_installation.admission import DIRECTORY, STATE, Admission, AdmissionRefusal, runtime_folder  # noqa: E402
from arbol_installation.paths import INSTALLATION_LAYOUT, installation_root  # noqa: E402
from database.archive_volume import ArchiveUnavailable, require_archive  # noqa: E402


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
        self._public_children: list[subprocess.Popen[bytes]] = []
        self.harness_source = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()
        subprocess.run(["git", "diff", "--quiet", arbol.source, "--", "src", "tests/backend/support.py",
                        "scripts/backend_package.py", "tools/backend_fault_driver.py"],
                       cwd=ROOT, check=True, timeout=10)
        subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "tools/trunk_runtime_journeys.py"],
                       cwd=ROOT, check=True, timeout=10)
        if not all(layout_fits(object_file(build.folder / "build.json")) for build in (arbol, trunk)):
            raise ValueError("The current runtime journey requires two layout-2 Builds.")
        verify_backend(arbol.folder)
        super().__init__(arbol.folder)
        try:
            self.runtime = runtime_folder(self.home)
            self.bin = self.home / ".local/bin"
            self.registry = installation_root(self.home) / "builds"
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
        shutil.copytree(self.package / "src/arbol_installation", place.parent / "arbol_installation")
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
            return self.public_start([*selection, "run", "--detach", *args], str(exchange))
        return self._call(self.package / "bin/arbol-exchanges", "start", *selection, *args)

    def public_start(self, arguments: list[str], exchange: str) -> Reply:
        executable = self.bin / "arbol-trunk"
        if not executable.resolve(strict=True).is_relative_to(self.cluster.base):
            raise ValueError("The public journey refuses an executable outside the disposable installation.")
        with tempfile.TemporaryFile(mode="w+b") as output:
            child = subprocess.Popen([str(executable), *arguments], cwd=self.work, env=self.env,
                                     stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
            self._public_children.append(child)
            value = wait_reply(child, output, time.monotonic() + 30)
        if value is None:
            raise ValueError("The public start did not return an acceptance or refusal object.")
        if "error" in value:
            return Reply(child.wait(timeout=5), value)
        if not accepted(value, exchange):
            raise ValueError("The public start did not confirm the requested Exchange identity.")
        return Reply(0, value)

    def close(self) -> None:
        try:
            if self._ready and self._starts:
                for item in self.runtime_call("list").require()["exchanges"]:
                    if item["exchange"] in self._starts and item["process"]["alive"]:
                        self.runtime_call("stop", UUID(item["exchange"]), force=True).require()
                for exchange in sorted(self._starts):
                    self.runtime_call("settle", UUID(exchange)).require()
        finally:
            try:
                for child in self._public_children:
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait(timeout=5)
            finally:
                super().close()


def check_admission_layout(fixture: JourneyInstallation) -> None:
    admission = fixture.runtime / DIRECTORY / STATE
    original = admission.read_bytes()
    incompatible = object_file(admission)
    incompatible["format"] = 1
    staging = admission.with_name(".test-incompatible.json")
    private_object(staging, incompatible)
    staging.replace(admission)
    try:
        try:
            with Admission(fixture.runtime).lease("normal"):
                raise ValueError("The layout-1 admission marker granted a write lease.")
        except AdmissionRefusal:
            pass
    finally:
        private_object(staging, json.loads(original))
        staging.replace(admission)


def verify_layout(fixture: JourneyInstallation, code: str) -> dict[str, object]:
    try:
        require_archive()
    except ArchiveUnavailable:
        pass
    else:
        raise ValueError("The missing-archive journey requires Mercury's archive to be unavailable.")
    if (fixture.home / "Library/Application Support/Arbol").exists():
        raise ValueError("The disposable installation created layout-1 state.")
    isolated = fixture.work / "isolated-runtime"
    isolated.mkdir(mode=0o700)
    if identity(fixture.package, {"--runtime-dir": str(isolated)}, home=fixture.home).folder != isolated:
        raise ValueError("The isolated runtime override was ignored.")
    try:
        identity(fixture.package, {"--runtime-dir": str(fixture.runtime)}, home=fixture.home)
    except Refused as error:
        if error.code != "invalid_input":
            raise
    else:
        raise ValueError("The isolated override reached the installed runtime.")
    check_admission_layout(fixture)

    trunk = fixture.trunk
    record = object_file(trunk.folder / "build.json")
    if (record.get("installationLayout") != INSTALLATION_LAYOUT
            or object_file(trunk.folder / "arbol-build.json").get("installationLayout") != INSTALLATION_LAYOUT):
        raise ValueError("The descriptor and registry must both declare layout 2.")
    number = format(int(trunk.number, 16) + 1, "x")
    legacy = trunk.folder.parent / number
    legacy.mkdir(mode=0o700)
    entry = legacy / trunk.entry
    entry.parent.mkdir(mode=0o700)
    ran = fixture.work / "legacy-ran"
    entry.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(ran))}\nexit 1\n")
    entry.chmod(0o700)
    record.pop("installationLayout")
    record["build"] = number
    private_object(legacy / "build.json", record)

    catalogue = fixture.trunks().require()
    records = next(item["builds"] for item in catalogue["trunks"] if item["trunk"] == code)
    if [(item["build"], item["installationLayout"], item["fits"], item["chosen"]) for item in records] != [
        (number, 1, False, False), (trunk.number, INSTALLATION_LAYOUT, True, True),
    ]:
        raise ValueError("The launcher did not select the compatible default.")
    refusal = fixture._call(fixture.bin / "arbol-trunk", code, "-v", number, "run")
    if (refusal.status != 1 or refusal.value.get("error", {}).get("code") != "no_fit"
            or refusal.value.get("available") != [trunk.number] or ran.exists()):
        raise ValueError("The layout-1 Build was not refused with the compatible alternative.")
    exchanges: list[str] = []
    for selection in (None, trunk.number):
        exchange = uuid4()
        started = fixture.start(exchange, code=code, build=selection, model="complete").require()
        if started.get("build") != trunk.number or started.get("accepted") is not True:
            raise ValueError("The Exchange failed to start on the compatible Build.")
        deadline = time.monotonic() + 30
        while True:
            status = fixture.cluster.sql(f"SELECT state FROM exchanges WHERE id='{exchange}';".encode()).strip()
            if status == b"completed":
                break
            if status != b"open" or time.monotonic() >= deadline:
                raise ValueError(f"The disposable Exchange ended without completion: {status.decode()}")
            time.sleep(0.05)
        exchanges.append(str(exchange))
    return {"legacyRefusal": refusal.value, "completedExchanges": exchanges, "archiveUnavailable": True,
            "admissionRefusedLayout1": True, "isolationPreserved": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arbol-build", type=Path, required=True)
    parser.add_argument("--trunk-build", type=Path, required=True)
    parser.add_argument("--trunk-code", choices=("trivial", "steady"), default="trivial")
    parser.add_argument("--verify-layout", action="store_true")
    options = parser.parse_args()
    try:
        arbol = Build.checked(options.arbol_build, "arbol")
        trunk = Build.checked(options.trunk_build, "arbol-trunk/" + options.trunk_code)
        fixture = JourneyInstallation(arbol, trunk)
        try:
            key = options.trunk_code
            receipt = {"harnessSource": fixture.harness_source, "arbolBuild": arbol.number,
                       "arbolSource": arbol.source, f"{key}Build": trunk.number, f"{key}Source": trunk.source,
                       "inventory": fixture.trunks().require(), "runtime": fixture.runtime_call("list").require()}
            if options.verify_layout:
                receipt["layoutJourney"] = verify_layout(fixture, key)
            print(json.dumps(receipt))
        finally:
            fixture.close()
    except (OSError, KeyError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Cannot prepare the private journey: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
