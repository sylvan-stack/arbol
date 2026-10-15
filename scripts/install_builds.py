"""Install arbol-builds with its pinned Python, and rewrite the launchers already installed.

    uv run --no-sync python scripts/install_builds.py [--bin-dir <folder>]

BLD-0, "Where the build tool and the launchers are", with BLD-D14 and BLD-D15. Into
`<folder>/.arbol-builds` go the pinned standalone CPython that every Build carries, unpacked once
from the checked archive, and the package arbol_builds, compiled. `<folder>/arbol-builds` starts
the tool with that Python. Every launcher already in the folder, written by this tool or by the
earlier Node.js tool, is written again with the current launcher code, for the same component
and registry. Any other file there is left as it is.
"""

from __future__ import annotations

import ast
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path
from types import FrameType

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_support import ROOT, archive, pin, target  # noqa: E402

sys.path.insert(0, str(ROOT / "src"))
from arbol_builds.cli import options  # noqa: E402
from arbol_builds.config import locations  # noqa: E402
from arbol_builds.launcher import json_line, write_all  # noqa: E402
from arbol_builds.service import LAUNCHER_MARK, atomic_write, shebang, write_launcher  # noqa: E402

USAGE = "Usage: uv run --no-sync python scripts/install_builds.py [--bin-dir <folder>]"
NODE_LAUNCH = re.compile(r'launch\(("(?:[^"\\\n]|\\.)*"), ("(?:[^"\\\n]|\\.)*"), process\.argv\.slice\(2\)\);')
NODE_FILES = ("cli.js", "config.js", "records.js", "service.js", "mutation.js", "package.json")
LAUNCHER_LIMIT = 1024 * 1024


def probe(python: Path) -> str:
    """The version the interpreter reports, or nothing when it is missing or does not start."""
    try:
        result = subprocess.run([str(python), "-I", "-B", "-c", "import platform; print(platform.python_version())"],
                                capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def runtime_folder(library: Path) -> Path:
    """Where the pinned Python goes: a folder named after its version and archive digest."""
    pinned = pin()
    return library / "runtime" / f"{pinned['version']}-{pinned['distributions'][target()]['sha256'][:12]}"


def runtime(library: Path) -> Path:
    """The pinned Python, unpacked once and reused by later installs."""
    pinned = pin()
    distribution = pinned["distributions"][target()]
    folder = runtime_folder(library)
    python = folder / "python/bin/python3.14"
    if probe(python) != pinned["version"]:
        compressed = archive(distribution)
        unpacking = library / "runtime" / f".unpacking-{uuid.uuid4()}"
        unpacking.mkdir(parents=True)
        try:
            with tarfile.open(compressed, "r:gz") as bundle:
                bundle.extractall(unpacking, filter="data")
            if probe(unpacking / "python/bin/python3.14") != pinned["version"]:
                raise ValueError("The unpacked interpreter does not report the pinned Python version.")
            if folder.exists():
                shutil.rmtree(folder)
            unpacking.rename(folder)
        finally:
            shutil.rmtree(unpacking, ignore_errors=True)
    # Bytecode is made here once, so that the tool and the launchers, started with -B, compile nothing.
    subprocess.run([str(python), "-I", "-m", "compileall", "-q", "-j", "0", str(folder / "python/lib/python3.14")],
                   check=True, capture_output=True)
    return python


def install_package(library: Path, python: Path) -> None:
    staging = library / f".arbol_builds-{uuid.uuid4()}"
    shutil.copytree(ROOT / "src/arbol_builds", staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    try:
        subprocess.run([str(python), "-I", "-m", "compileall", "-q", str(staging)], check=True, capture_output=True)
        package = library / "arbol_builds"
        previous = library / f".arbol_builds-previous-{uuid.uuid4()}"
        if package.exists():
            package.rename(previous)
        staging.rename(package)
        shutil.rmtree(previous, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def served(path: Path) -> tuple[str, str] | None:
    """The registry and component of a launcher written by this tool or by the earlier Node.js tool."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > LAUNCHER_LIMIT:
            return None
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    last = text.rstrip("\n").rsplit("\n", 1)[-1]
    registry: object = None
    component: object = None
    try:
        if text.startswith("#!/usr/bin/env node\n") and "\nfunction launch(" in text:
            match = NODE_LAUNCH.fullmatch(last)
            if match is None:
                return None
            registry, component = json.loads(match[1]), json.loads(match[2])
        elif text.startswith("#!") and text.split("\n", 2)[1:2] == [LAUNCHER_MARK]:
            call = ast.parse(last, mode="eval").body
            if (not isinstance(call, ast.Call) or len(call.args) != 1 or not isinstance(call.args[0], ast.Call)
                    or len(call.args[0].args) != 3):
                return None
            registry, component = (ast.literal_eval(node) for node in call.args[0].args[:2])
        else:
            return None
    except (ValueError, SyntaxError):
        return None
    if component != path.name or not isinstance(registry, str) or not os.path.isabs(registry):
        return None
    return registry, path.name


def install(args: list[str]) -> dict[str, object]:
    words, values = options(args, ["--bin-dir"])
    if words:
        raise ValueError(USAGE)
    folder = Path(os.path.abspath(values.get("--bin-dir", locations().bin)))
    library = folder / ".arbol-builds"
    try:
        # Checked before anything changes: the tool and the launchers must be able to name this Python.
        first = shebang(str(runtime_folder(library) / "python/bin/python3.14"))
    except ValueError:
        raise ValueError(f"arbol-builds cannot be installed in {folder}: the programs it writes name their Python "
                         "in their first line, which cannot hold a space or a '#', nor a long path.") from None
    library.mkdir(parents=True, exist_ok=True)
    with open(library / ".install.lock", "w") as lock:
        # One install at a time; leftovers of an install that was stopped are removed first.
        fcntl.flock(lock, fcntl.LOCK_EX)
        for leftover in [*library.glob("runtime/.unpacking-*"), *library.glob(".arbol_builds-*")]:
            shutil.rmtree(leftover, ignore_errors=True)
        for leftover in folder.glob("arbol-builds.*.tmp"):
            leftover.unlink(missing_ok=True)
        python = runtime(library)
        install_package(library, python)
        program = folder / "arbol-builds"
        atomic_write(str(program), (f"{first}\nimport sys\nsys.path.insert(0, {str(library)!r})\n"
                                    "from arbol_builds.cli import entry\nentry()\n").encode(), 0o755)
        os.chmod(program, 0o755)
        launchers: list[str] = []
        for path in sorted(folder.iterdir()):
            found = served(path)
            if found is not None:
                write_launcher(str(folder), found[0], found[1], str(python))
                launchers.append(found[1])
        # The earlier Node.js tool goes last, once its replacement and every launcher are in place.
        for name in NODE_FILES:
            (library / name).unlink(missing_ok=True)
    return {"bin": str(folder), "program": str(program), "python": str(python), "launchers": launchers}


def stopped(number: int, frame: FrameType | None) -> None:
    raise SystemExit(128 + number)  # so that the cleanup of an unfinished step runs


def main() -> int:
    for number in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, stopped)
    try:
        write_all(1, json_line(install(sys.argv[1:])))
        return 0
    except Exception as error:
        write_all(1, json_line({"error": {"code": "install_failed", "message": str(error)}}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
