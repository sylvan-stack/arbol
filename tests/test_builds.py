# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""arbol-builds and its launchers (BLD-0.1 to 0.17 and 0.21 to 0.24), and the launcher arbol-trunk
(RCT-0.7 to 0.10): the checks named builds.* in BLD-0 and RCT-0.

The same checks the TypeScript tool had, under the same names, the checks of what the Python
tool adds (BLD-D14, BLD-D15), those of Builds made for a Root and of the Trunks (SYL-155), and
those of the Roots as the launchers read them and of the launcher arbol-trunk (SYL-179).
Each one builds a small sample component in a fresh home
folder whose name holds a space and an apostrophe, and starts the tool and the launchers as
programs. No vendor tool is involved.
"""
import errno
import re
import resource
import shlex
import signal
import threading
import uuid
from unittest import mock


import ast
import json
import os
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arbol_builds import mutation, pruning  # noqa: E402
from arbol_builds.config import component_name  # noqa: E402
from arbol_builds.launcher import milliseconds, record_start, write_all  # noqa: E402
from arbol_builds.roots import current_root, read_root, read_roots, roots_folder  # noqa: E402
from arbol_builds.service import LAUNCHER_MARK, last_start, reserve, write_launcher  # noqa: E402

from arbol_builds.launcher import milliseconds  # noqa: E402
from arbol_builds.service import write_launcher  # noqa: E402

PYTHON = sys.executable
ENTRY = str(ROOT / "bin/builds_entry.py")
TOOL = [PYTHON, "-I", "-B", ENTRY]
INSTALLER = str(ROOT / "scripts/install_builds.py")
ENV = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
ARCHIVE_CACHE = Path.home() / ".cache/arbol-driver-build/python"

PROGRAM = f"""#!{PYTHON} -I
import json, os, signal, sys, time
folder = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(folder, "build.json"), encoding="utf-8") as stream:
    record = json.load(stream)
args = sys.argv[1:]
if args[:1] == ["--echo"]:
    sys.stdout.buffer.write(sys.stdin.buffer.read())
    sys.stderr.write("diagnostic\\n")
elif args[:1] == ["--wait"]:
    def interrupted(number, frame):
        sys.stdout.write("interrupted\\n")
        sys.stdout.flush()
        os._exit(2)
    signal.signal(signal.SIGINT, interrupted)
    print(json.dumps({{"pid": os.getpid()}}), flush=True)
    while True:
        time.sleep(1)
elif args[:1] == ["--state"]:
    with open(args[1], encoding="utf-8") as stream:
        state = json.load(stream)
    if state["format"] > record["dataFormat"]:
        print(json.dumps({{"error": "newer data", "found": state["format"], "supported": record["dataFormat"]}}))
        sys.exit(1)
    print(json.dumps({{"format": state["format"], "build": record["build"]}}))
elif args[:1] == ["--exit"]:
    sys.exit(int(args[1]))
elif args[:1] == ["--environ"]:
    import ctypes
    libc = ctypes.CDLL(None)
    libc._NSGetEnviron.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_char_p))
    environ = libc._NSGetEnviron().contents
    entries = []
    while environ[len(entries)]:
        entries.append(environ[len(entries)].hex())
    print(json.dumps(entries))
elif args[:1] == ["--bytes"]:
    print(json.dumps({{"args": [os.fsencode(arg).hex() for arg in args[1:]],
                      "probe": os.environb.get(b"PROBE", b"").hex()}}))
else:
    print(json.dumps({{"build": record["build"], "version": record["packageVersion"], "args": args,
                      "cwd": os.getcwd(), "marker": os.environ.get("MARKER"), "pid": os.getpid()}}))
"""
# A Trunk's Build: the same program, which first sets aside the --root <root> that arbol-trunk hands it.
TRUNK_PROGRAM = PROGRAM.replace('args = sys.argv[1:]\n', 'args = sys.argv[1:]\nlead = args[:2] if args[:1] == ["--root"] else []\n'
                                'args = args[len(lead):]\n').replace('"args": args,', '"args": lead + args,')
BUILDER = """import json, os, shutil
folder = os.environ["ARBOL_BUILD_DIR"]
shutil.copyfile("program.py", os.path.join(folder, "program.py"))
os.chmod(os.path.join(folder, "program.py"), 0o755)
with open(os.path.join(folder, "build-environment.json"), "w") as stream:
    json.dump({"number": os.environ["ARBOL_BUILD_NUMBER"], "dir": folder, "cwd": os.getcwd()}, stream)
"""
CHECKER = """import json, os, subprocess, sys
folder = os.environ["ARBOL_BUILD_DIR"]
with open(os.path.join(folder, "build.json"), encoding="utf-8") as stream:
    record = json.load(stream)
if record["status"] != "building":
    sys.exit("check must run before working")
result = subprocess.run([os.path.join(folder, record["entry"]), "direct-check"], capture_output=True, text=True)
if result.returncode != 0 or json.loads(result.stdout)["build"] != os.environ["ARBOL_BUILD_NUMBER"]:
    sys.exit("wrong entry")
with open(os.path.join(folder, "check-environment.json"), "w") as stream:
    json.dump({"number": os.environ["ARBOL_BUILD_NUMBER"], "dir": folder, "cwd": os.getcwd()}, stream)
"""
BUILD = f'"{PYTHON}" -I build.py'
CHECK = f'"{PYTHON}" -I check.py'
WRITER = f"""import os, sys, time
sys.path.insert(0, {str(ROOT / "src")!r})
from arbol_builds.mutation import with_mutation_lock
folder = sys.argv[1]
counter = os.path.join(folder, "counter.json")
def bump():
    with open(counter) as stream:
        number = int(stream.read())
    time.sleep(0.002)
    with open(counter, "w") as stream:
        stream.write(str(number + 1))
for _ in range(20):
    with_mutation_lock(folder, bump)
"""
# Starts a program with exactly these arguments and environment entries, given in hex, duplicates included.
EXECVE = """import ctypes, sys
words = [bytes.fromhex(item) for item in sys.argv[1:]]
split = words.index(b"--")
argv = (ctypes.c_char_p * (split + 1))(*words[:split], None)
envp = (ctypes.c_char_p * (len(words) - split))(*words[split + 1:], None)
libc = ctypes.CDLL(None, use_errno=True)
libc.execve(words[0], argv, envp)
sys.exit(f"execve failed: {ctypes.get_errno()}")
"""
SIGNALS = """import json, signal
names = ("SIGHUP", "SIGINT", "SIGQUIT", "SIGTERM", "SIGUSR1")
print(json.dumps({"ignored": [name for name in names if signal.getsignal(getattr(signal, name)) is signal.SIG_IGN],
                  "blocked": sorted(number.name for number in signal.pthread_sigmask(signal.SIG_BLOCK, []))}))
"""
HOLDER = f"""import sys, time
sys.path.insert(0, {str(ROOT / "src")!r})
from arbol_builds.mutation import with_mutation_lock
def hold():
    print("held", flush=True)
    time.sleep(60)
with_mutation_lock(sys.argv[1], hold)
"""

type Result = subprocess.CompletedProcess[bytes]


def document(result: Result) -> Any:
    return json.loads(result.stdout)


def finish(child: subprocess.Popen[bytes]) -> None:
    """Stop a child the test started, if it still runs, and close its pipes."""
    if child.poll() is None:
        child.kill()
    child.wait()
    for stream in (child.stdout, child.stderr):
        if stream is not None:
            stream.close()


class Fixture:
    def __init__(self, test: unittest.TestCase, component: str = "sample") -> None:
        self.test = test
        self.component = component
        self.home = os.path.realpath(tempfile.mkdtemp(prefix="Arbol's builds "))
        test.addCleanup(self.remove)
        self.repo = os.path.join(self.home, "repository")
        self.registry = os.path.join(self.home, "registry")
        self.bin = os.path.join(self.home, "bin")
        os.mkdir(self.repo)
        files = {"package.json": '{"version":"1.2.3"}\n', "program.py": PROGRAM, "build.py": BUILDER, "check.py": CHECKER}
        for name, text in files.items():
            Path(self.repo, name).write_text(text, encoding="utf-8")
        self.config: dict[str, Any] = {"component": component, "build": [BUILD], "entry": "program.py",
                                       "checks": [{"name": "sample-check", "command": CHECK}], "dataFormat": 1}
        if component.startswith("arbol-trunk/"):
            self.config["rootContracts"] = [1]
        self.configure()
        self.git("init", "-q", "-b", "main")
        self.git("add", ".")
        self.git("commit", "-qm", "Sample")

    def remove(self) -> None:
        for folder, _, _ in os.walk(self.home):
            try:
                os.chmod(folder, 0o700)
            except OSError:
                pass
        shutil.rmtree(self.home, ignore_errors=True)

    def configure(self, **patch: Any) -> None:
        self.config.update(patch)
        Path(self.repo, "arbol-build.json").write_text(json.dumps(self.config), encoding="utf-8")

    def git(self, *args: str) -> str:
        # Git keeps the caller's configured identity and hooks; only the programs under test use the fake home.
        return subprocess.run(["git", *args], cwd=self.repo, env={**ENV, "HOME": str(Path.home())}, check=True,
                              capture_output=True, text=True).stdout.strip()

    def env(self, **extra: str) -> dict[str, str]:
        return {**ENV, "HOME": self.home, **extra}

    def call(self, *args: str) -> Result:
        return subprocess.run([PYTHON, "-I", "-B", ENTRY, "--registry-dir", self.registry, "--bin-dir", self.bin, *args],
                              cwd=self.home, env=self.env(), capture_output=True, timeout=120, check=False)

    def build(self, *args: str) -> dict[str, Any]:
        result = self.call("build", self.component, "--repo", self.repo, *args)
        self.test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record: dict[str, Any] = document(result)
        return record

    def launch(self, *args: str, data: bytes = b"", marker: str = "caller") -> Result:
        return subprocess.run([os.path.join(self.bin, self.component), *args], cwd=self.home,
                              env=self.env(MARKER=marker), input=data, capture_output=True, timeout=60, check=False)

    def spawn(self, *args: str) -> subprocess.Popen[bytes]:
        child = subprocess.Popen([PYTHON, "-I", "-B", ENTRY, *args], cwd=self.home, env=self.env(),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.test.addCleanup(finish, child)
        return child

    def path(self, *parts: str) -> str:
        return os.path.join(self.registry, self.component, *parts)


def run_tool(f: Fixture, *args: str | bytes, cwd: str | None = None) -> Result:
    """The tool started from the checkout with exactly these arguments."""
    return subprocess.run([*TOOL, *args], cwd=cwd or f.home, env=f.env(), capture_output=True, timeout=120,
                          check=False)


def wait_until(condition: Callable[..., object], *args: Any, seconds: float = 10.0) -> None:
    end = time.monotonic() + seconds
    while not condition(*args):
        if time.monotonic() > end:
            raise AssertionError("The condition did not come true in time.")
        time.sleep(0.01)


def waiting(log: Path) -> bool:
    """Whether the sample's long-running command has started: it prints a line "waiting" into the log."""
    return log.exists() and "\nwaiting\n" in log.read_text()


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def mode(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def first_line(child: subprocess.Popen[bytes], seconds: float = 10.0) -> bytes:
    assert child.stdout is not None
    end = time.monotonic() + seconds
    line = b""
    while not line.endswith(b"\n"):
        ready, _, _ = select.select([child.stdout], [], [], max(end - time.monotonic(), 0))
        if not ready:
            raise AssertionError("The process did not become ready.")
        chunk = os.read(child.stdout.fileno(), 1)
        if not chunk:
            raise AssertionError("The process ended before it was ready.")
        line += chunk
    return line


class Builds(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


class Roots(unittest.TestCase):
    """Builds made for a Root, and the Trunks as components of their own (SYL-155)."""


class Launchers(unittest.TestCase):
    """What the Python launcher does where the Node.js launcher did not (BLD-D15)."""


def root_record(root: str, status: str = "working", created: str = "2026-10-15T09:30:00.000Z",
                contract: object = 1, **extra: Any) -> dict[str, Any]:
    """A Root's record as ARC-1 gives it."""
    return {"root": root, "name": root.title(), "status": status, "createdAt": created, "database": f"arbol_{root}",
            "app": "1", "rootContract": contract, **extra}


def write_root(roots: str, record: object, folder: str | None = None) -> None:
    """root.json in the Root's folder, made by hand: a record, or the text given."""
    name = folder or (record["root"] if isinstance(record, dict) else "")
    os.makedirs(os.path.join(roots, name), exist_ok=True)
    Path(roots, name, "root.json").write_text(record if isinstance(record, str) else json.dumps(record),
                                              encoding="utf-8")


class Trunks:
    """A home of the test's own with Roots and Trunk Builds made by hand, a registry, and the launcher arbol-trunk."""

    def __init__(self, test: unittest.TestCase) -> None:
        self.test = test
        self.home = os.path.realpath(tempfile.mkdtemp(prefix="Arbol's trunks "))
        test.addCleanup(shutil.rmtree, self.home, True)
        self.registry = os.path.join(self.home, "registry")
        self.bin = os.path.join(self.home, "bin")
        self.roots = os.path.join(self.home, "Library/Application Support/Arbol/roots")
        self.launcher = os.path.join(self.bin, "arbol-trunk")
        write_launcher(self.bin, self.registry, "arbol-trunk")

    def root(self, root: str, contract: int, created: str, status: str = "working") -> None:
        write_root(self.roots, root_record(root, status, created, contract))

    def build(self, code: str, number: str, contracts: list[int], status: str = "working",
              **extra: Any) -> dict[str, Any]:
        """A Build record of arbol-trunk/<code> with the sample program, as arbol-builds would have left it."""
        folder = os.path.join(self.registry, "arbol-trunk", code, number)
        os.makedirs(folder, exist_ok=True)
        record: dict[str, Any] = {
            "component": f"arbol-trunk/{code}", "build": number, "packageVersion": "1.0.0", "status": status,
            "startedAt": "2026-10-16T09:00:00.000Z",
            "source": {"repository": "/repos/arbol-trunk", "branch": "main", "commit": "0" * 40,
                       "uncommittedChanges": False},
            "entry": "program.py", "checks": [{"name": "unit", "passed": status in ("working", "withdrawn")}],
            "rootContracts": contracts}
        if status != "building":
            record["finishedAt"] = "2026-10-16T09:01:00.000Z"
        if status == "withdrawn":
            record["withdrawn"] = {"at": "2026-10-16T10:00:00.000Z", "reason": "bad answers"}
        record.update(extra)
        Path(folder, "build.json").write_text(json.dumps(record, indent=2))
        Path(folder, "program.py").write_text(TRUNK_PROGRAM)
        os.chmod(os.path.join(folder, "program.py"), 0o755)
        return record

    def env(self, **extra: str) -> dict[str, str]:
        return {**ENV, "HOME": self.home, **extra}

    def run(self, *args: str, data: bytes = b"", marker: str = "caller") -> Result:
        return subprocess.run([self.launcher, *args], cwd=self.home, env=self.env(MARKER=marker), input=data,
                              capture_output=True, timeout=60, check=False)

    def started(self, *args: str) -> list[object]:
        """The Build the launcher started, and the arguments it handed it."""
        result = self.run(*args)
        self.test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        started = document(result)
        return [started["build"], started["args"]]


def top_level_names(path: Path) -> tuple[dict[str, str], list[str]]:
    """The names a module binds at its top level, each with what binds it, and the names it imports from this
    package, which a launcher takes from the text before it."""
    bound: dict[str, str] = {}
    relative: list[str] = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            bound[node.name] = "definition"
        elif isinstance(node, ast.Assign):
            bound.update((target.id, "definition") for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, (ast.AnnAssign, ast.TypeAlias)):
            target = node.target if isinstance(node, ast.AnnAssign) else node.name
            if isinstance(target, ast.Name):
                bound[target.id] = "definition"
        elif isinstance(node, ast.Import):
            bound.update((alias.asname or alias.name, f"import {alias.name}") for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            bound.update((alias.asname or alias.name, f"from {node.module} import {alias.name}")
                         for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            relative.extend(alias.name for alias in node.names)
    return bound, relative


class PruningRoots(unittest.TestCase):
    def trunk_command(self, f: Trunks, *args: str) -> Result:
        return subprocess.run([*TOOL, *args, "--registry-dir", f.registry], cwd=f.home, env=f.env(),
                              capture_output=True, timeout=30, check=False)


class RootComponents(unittest.TestCase):
    def fixture(self, component: str = "arbol-root") -> Fixture:
        f = Fixture(self, component)
        roots = os.path.join(f.home, "Library/Application Support/Arbol/roots")
        write_root(roots, root_record("sapling", "working", "2026-10-16T09:00:00.000Z"))
        write_root(roots, root_record("second", "working", "2026-10-16T10:00:00.000Z"))
        return f


class TrunkLauncher(unittest.TestCase):
    """The Roots as the launchers read them, and the launcher arbol-trunk (SYL-179; RCT-0.7 to 0.10, BLD-D17)."""


class Locking(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


class StartRecords(unittest.TestCase):
    """BLD-0.24: recording a launch is best effort, including named Builds and Trunks."""

    def timestamp(self, path: Path, before: int) -> str:
        raw = path.read_text()
        self.assertRegex(raw, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\n$")
        value = milliseconds(raw.strip())
        assert value is not None
        self.assertLessEqual(before, value)
        self.assertLessEqual(value, time.time_ns() // 1_000_000)
        return raw


@unittest.skipUnless((ARCHIVE_CACHE / "d15291f940cfecd2e54010d5e37d2e03aa192f076a65d26ab741372fff2dabfe.tar.gz").exists()
                     or os.environ.get("ARBOL_PYTHON_ARCHIVE_CACHE"), "the pinned Python archive is not cached")
class Install(unittest.TestCase):
    """Installing the tool with its pinned Python, and rewriting the launchers (BLD-D14, BLD-D15)."""

    def setUp(self) -> None:
        self.f = Fixture(self)
        self.folder = os.path.realpath(tempfile.mkdtemp(prefix="arbol-install-"))
        self.addCleanup(shutil.rmtree, self.folder, True)

    def install(self, *args: str, home: bool = True) -> Result:
        env = {**ENV, "ARBOL_PYTHON_ARCHIVE_CACHE": os.environ.get("ARBOL_PYTHON_ARCHIVE_CACHE", str(ARCHIVE_CACHE))}
        if home:
            env["HOME"] = self.f.home
        return subprocess.run([PYTHON, "-I", "-B", INSTALLER, *args], env=env, capture_output=True, timeout=300,
                              check=False)


# Archived complete imports; restore needed names in their original scope, not at this file tail.
