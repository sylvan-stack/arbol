"""arbol-builds and its launchers (BLD-0.1 to 0.16): the checks named builds.* in BLD-0.

The same checks the TypeScript tool had, under the same names, and the checks of what the
Python tool adds (BLD-D14, BLD-D15). Each one builds a small sample component in a fresh home
folder whose name holds a space and an apostrophe, and starts the tool and the launchers as
programs. No vendor tool is involved.
"""

import json
import os
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arbol_builds.service import reserve  # noqa: E402

PYTHON = sys.executable
ENTRY = str(ROOT / "bin/builds_entry.py")
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
elif args[:1] == ["--bytes"]:
    print(json.dumps({{"args": [os.fsencode(arg).hex() for arg in args[1:]],
                      "probe": os.environb.get(b"PROBE", b"").hex()}}))
else:
    print(json.dumps({{"build": record["build"], "version": record["packageVersion"], "args": args,
                      "cwd": os.getcwd(), "marker": os.environ.get("MARKER"), "pid": os.getpid()}}))
"""
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
        self.configure()
        self.git("init", "-q", "-b", "main")
        self.git("add", ".")
        self.git("-c", "user.name=Build Tests", "-c", "user.email=builds@example.invalid", "commit", "-qm", "Sample")

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
        return subprocess.run(["git", *args], cwd=self.repo, env={**ENV, "HOME": self.home}, check=True,
                              capture_output=True, text=True).stdout.strip()

    def env(self, **extra: str) -> dict[str, str]:
        return {**ENV, "HOME": self.home, **extra}

    def call(self, *args: str) -> Result:
        return subprocess.run([PYTHON, "-I", "-B", ENTRY, "--registry-dir", self.registry, "--bin-dir", self.bin, *args],
                              cwd=self.home, env=self.env(), capture_output=True, timeout=120, check=False)

    def build(self) -> dict[str, Any]:
        result = self.call("build", self.component, "--repo", self.repo)
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
    def test_builds_two_builds(self) -> None:
        """builds.two-builds runs the newest Build and an explicitly named older Build."""
        f = Fixture(self)
        self.assertEqual(f.build()["build"], "1")
        self.assertEqual(f.build()["build"], "2")
        self.assertEqual(document(f.launch())["build"], "2")
        self.assertEqual(document(f.launch("-v", "1"))["build"], "1")
        self.assertEqual([[r["build"], r["default"]] for r in document(f.call("list", f.component))],
                         [["2", True], ["1", False]])
        self.assertEqual(document(f.call("show", f.component))["build"], "2")
        self.assertEqual(document(f.call("show", f"{f.component}@1"))["build"], "1")

    def test_builds_numbering(self) -> None:
        """builds.numbering uses hexadecimal, arbitrary precision, independent components and damaged directories."""
        f = Fixture(self)
        for number in range(1, 18):
            self.assertEqual(reserve(f.registry, f.component)[1], format(number, "x"))
        self.assertEqual(reserve(f.registry, "other")[1], "1")
        os.mkdir(f.path("ffffffffffffffff"))
        self.assertEqual(reserve(f.registry, f.component)[1], "10000000000000000")

    def test_builds_concurrent(self) -> None:
        """builds.concurrent invocations never reserve the same number."""
        f = Fixture(self)
        children = [f.spawn("build", f.component, "--repo", f.repo, "--registry-dir", f.registry, "--bin-dir", f.bin)
                    for _ in range(4)]
        numbers = []
        for child in children:
            output, errors = child.communicate(timeout=120)
            self.assertEqual(child.returncode, 0, output + errors)
            numbers.append(json.loads(output)["build"])
        self.assertEqual(sorted(numbers), ["1", "2", "3", "4"])
        self.assertEqual(document(f.launch())["build"], "4")

    def test_builds_concurrent_mutations(self) -> None:
        """builds.concurrent-mutations serialises record writers and excludes killed reservations from later changes."""
        f = Fixture(self)
        f.build()
        folder = f.path()
        worker = os.path.join(f.home, "writer.py")
        Path(worker).write_text(WRITER, encoding="utf-8")
        Path(folder, "counter.json").write_text("0")
        writers = [subprocess.Popen([PYTHON, "-I", worker, folder], env=ENV) for _ in range(4)]
        for writer in writers:
            self.addCleanup(finish, writer)
        self.assertTrue(all(writer.wait(timeout=120) == 0 for writer in writers))
        self.assertEqual(Path(folder, "counter.json").read_text(), "80")
        Path(worker).write_text(HOLDER, encoding="utf-8")
        holder = subprocess.Popen([PYTHON, "-I", worker, folder], env=ENV, stdout=subprocess.PIPE)
        self.addCleanup(finish, holder)
        self.assertEqual(first_line(holder), b"held\n")
        holder.kill()
        holder.wait()
        self.assertEqual(f.call("withdraw", f"{f.component}@1", "--reason", "after killed writer").returncode, 0)
        self.assertEqual(f.launch("-v", "1").returncode, 0)

    def test_builds_concurrent_prune(self) -> None:
        """builds.concurrent-prune and withdrawal preserve a complete serial outcome."""
        f = Fixture(self)
        for _ in range(3):
            f.build()
        prune = f.spawn("prune", f.component, "--keep", "1", "--registry-dir", f.registry)
        withdraw = f.spawn("withdraw", f"{f.component}@3", "--reason", "concurrent withdrawal",
                           "--registry-dir", f.registry)
        outputs = []
        for child in (prune, withdraw):
            output, errors = child.communicate(timeout=120)
            self.assertEqual(child.returncode, 0, output + errors)
            outputs.append(json.loads(output))
        if "2" in outputs[0]["pruned"]:
            self.assertEqual(f.launch().returncode, 1)
        else:
            self.assertEqual(outputs[0]["pruned"], ["1"])
            self.assertEqual(document(f.launch())["build"], "2")
        self.assertEqual(f.launch("-v", "3").returncode, 0)

    def test_builds_source(self) -> None:
        """builds.source records package, repository, branch, commit and uncommitted changes."""
        f = Fixture(self)
        commit = f.git("rev-parse", "HEAD")
        first = f.build()
        self.assertEqual(first["packageVersion"], "1.2.3")
        self.assertEqual(first["source"], {"repository": f.repo, "branch": "main", "commit": commit,
                                           "uncommittedChanges": False})
        Path(f.repo, "uncommitted.txt").write_text("new")
        self.assertIs(f.build()["source"]["uncommittedChanges"], True)

    def test_builds_folder_alone(self) -> None:
        """builds.folder-alone launches a relocated Build after its source and the tool are out of reach."""
        f = Fixture(self)
        f.build()
        moved = os.path.join(f.home, "moved")
        shutil.copytree(f.path("1"), os.path.join(moved, f.component, "1"), symlinks=True)
        launcher = Path(f.bin, f.component)
        text = launcher.read_text(encoding="utf-8")
        # The launcher holds the standard library only; changing its registry is sufficient.
        self.assertNotIn("from arbol_builds", text)
        self.assertNotIn("import arbol_builds", text)
        launcher.write_text(text.replace(repr(f.registry), repr(moved)), encoding="utf-8")
        shutil.rmtree(f.repo)
        shutil.rmtree(f.registry)
        result = f.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(document(result)["build"], "1")

    def test_builds_failed_check(self) -> None:
        """builds.failed-check keeps its record and log, consumes its number, preserves the default, runs only when named."""
        f = Fixture(self)
        f.build()
        f.configure(checks=[{"name": "unavailable-account", "kind": "live",
                             "command": "echo account-signed-out >&2; exit 1"}])
        result = f.call("build", f.component, "--repo", f.repo)
        self.assertEqual(result.returncode, 1)
        record = document(result)
        self.assertEqual([record["status"], record["build"], record["failure"]["name"]],
                         ["failed", "2", "unavailable-account"])
        self.assertEqual(record["checks"], [{"name": "unavailable-account", "passed": False}])
        self.assertIn("account-signed-out", Path(f.path("2/build.log")).read_text())
        self.assertEqual(document(f.launch())["build"], "1")
        named = f.launch("-v", "2", "text")
        self.assertEqual(named.returncode, 0, named.stdout)
        self.assertEqual([document(named)["build"], document(named)["args"]], ["2", ["text"]])
        self.assertEqual(named.stderr,
                         f"{f.component}@2 is failed: check unavailable-account: Check failed; see build.log.\n".encode())
        f.configure(checks=[{"name": "sample-check", "command": CHECK}])
        self.assertEqual(f.build()["build"], "3")

    def test_builds_failed_command(self) -> None:
        """builds.failed-command and missing entry cannot become working."""
        f = Fixture(self)
        f.configure(build=["echo compile-failed; exit 7"])
        command = document(f.call("build", f.component, "--repo", f.repo))
        self.assertEqual([command["status"], command["failure"]["stage"], command["checks"]], ["failed", "build", []])
        self.assertRegex(Path(f.path("1/build.log")).read_text(), r"compile-failed[\s\S]*Exit: 7")
        f.configure(build=["true"])
        entry = document(f.call("build", f.component, "--repo", f.repo))
        self.assertEqual([entry["status"], entry["failure"]["stage"]], ["failed", "entry"])
        f.configure(build=[BUILD], checks=[{"name": "removed-entry", "command": 'rm "$ARBOL_BUILD_DIR/program.py"'}])
        self.assertEqual(document(f.call("build", f.component, "--repo", f.repo))["status"], "failed")

    def test_builds_description(self) -> None:
        """builds.description passes folder and number to ordered commands and checks against the building entry."""
        f = Fixture(self)
        f.configure(build=[BUILD, 'echo second > "$ARBOL_BUILD_DIR/order"'], checks=[
            {"name": "sample-check", "command": CHECK},
            {"name": "ordered-check", "command": 'test "$(cat "$ARBOL_BUILD_DIR/order")" = second'},
        ], contract=1, dataFormat=2)
        record = f.build()
        self.assertEqual([record["contract"], record["dataFormat"]], [1, 2])
        folder = f.path("1")
        for name in ("build", "check"):
            self.assertEqual(json.loads(Path(folder, f"{name}-environment.json").read_text()),
                             {"number": "1", "dir": folder, "cwd": f.repo})
        self.assertEqual(record["checks"], [{"name": "sample-check", "passed": True},
                                            {"name": "ordered-check", "passed": True}])

    def test_builds_driver_checks(self) -> None:
        """builds.driver-checks requires unit, contract and live checks and fails when the live check fails."""
        f = Fixture(self, "arbol-claude-driver")
        self.assertEqual(f.call("build", f.component, "--repo", f.repo).returncode, 1)
        self.assertFalse(os.path.exists(f.registry))
        f.configure(contract=1, dataFormat=1, checks=[
            {"name": "unit", "kind": "unit", "command": CHECK},
            {"name": "contract", "kind": "contract", "command": CHECK},
            {"name": "one-real-message", "kind": "live", "command": "echo synthetic-live-failure; exit 1"},
        ])
        result = f.call("build", f.component, "--repo", f.repo)
        self.assertEqual([result.returncode, document(result)["status"], document(result)["failure"]["name"]],
                         [1, "failed", "one-real-message"])
        f.configure(checks=[{"name": "unit", "kind": "unit", "command": CHECK},
                            {"name": "contract", "kind": "contract", "command": CHECK},
                            {"name": "live-stand-in", "kind": "live", "command": CHECK}])
        self.assertEqual(f.build()["status"], "working")

    def test_builds_withdraw(self) -> None:
        """builds.withdraw changes the computed default and warns only for an explicit withdrawn Build."""
        f = Fixture(self)
        f.build()
        f.build()
        result = f.call("withdraw", f"{f.component}@2", "--reason", "Bad result on Tuesday")
        self.assertEqual([result.returncode, document(result)["status"]], [0, "withdrawn"])
        self.assertEqual(document(f.launch())["build"], "1")
        named = f.launch("-v", "2")
        self.assertEqual([named.returncode, document(named)["build"]], [0, "2"])
        self.assertIn(b"withdrawn: Bad result on Tuesday", named.stderr)
        self.assertEqual(f.call("withdraw", f"{f.component}@2", "--reason", "again").returncode, 1)

    def test_builds_launch_refusal(self) -> None:
        """builds.launch-refusal lists runnable Builds and consumes -v only in first position."""
        f = Fixture(self)
        f.build()
        f.configure(build=["false"])
        f.call("build", f.component, "--repo", f.repo)
        for args in (["-v", "2"], ["-v", "3"], ["-v"], ["-v", "01"], ["-v", "A"]):
            result = f.launch(*args)
            self.assertEqual([result.returncode, document(result)["error"]["available"]], [1, ["1"]], args)
            self.assertEqual(document(result)["error"]["code"], "build_unavailable")
        self.assertEqual(document(f.launch("run", "-v", "2", "", "a b", "a'b"))["args"],
                         ["run", "-v", "2", "", "a b", "a'b"])
        path = Path(f.path("2/build.json"))
        building = json.loads(path.read_text())
        building["status"] = "building"
        path.write_text(json.dumps(building))
        self.assertEqual(f.launch("-v", "2").returncode, 1)

    def test_builds_streams(self) -> None:
        """builds.streams preserves standard input, output, errors, working folder, environment and exit status."""
        f = Fixture(self)
        f.build()
        data = "ñ\u0000data\nline two\n".encode()
        echo = f.launch("--echo", data=data)
        self.assertEqual([echo.stdout, echo.stderr, echo.returncode], [data, b"diagnostic\n", 0])
        result = document(f.launch("text", marker="custom"))
        self.assertEqual([result["cwd"], result["marker"]], [f.home, "custom"])
        for code in (0, 1, 2, 7, 143):
            self.assertEqual(f.launch("--exit", str(code)).returncode, code)

    def test_builds_signals(self) -> None:
        """builds.signals replaces the launcher process and passes handled and native signals directly."""
        f = Fixture(self)
        f.build()
        for number in (signal.SIGINT, signal.SIGTERM):
            child = subprocess.Popen([os.path.join(f.bin, f.component), "--wait"], env=f.env(), stdout=subprocess.PIPE)
            self.addCleanup(finish, child)
            ready = json.loads(first_line(child))
            self.assertEqual(ready["pid"], child.pid)
            child.send_signal(number)
            code = child.wait(timeout=10)
            self.assertEqual(code, 2 if number == signal.SIGINT else -signal.SIGTERM)

    def test_builds_damaged_record(self) -> None:
        """builds.damaged-record isolates malformed, missing, mismatched and nonexecutable entries."""
        f = Fixture(self)
        f.build()
        f.build()
        path = Path(f.path("2/build.json"))
        original = path.read_text()
        for bad in ("{", "{}", original.replace('"build": "2"', '"build": "9"'),
                    original.replace('"entry": "program.py"', '"entry": "../../outside"'),
                    original.replace('"dataFormat": 1', '"dataFormat": NaN')):
            path.write_text(bad)
            self.assertEqual(document(f.launch())["build"], "1")
            self.assertEqual(len(document(f.call("list"))), 1)
        path.unlink()
        self.assertEqual(document(f.launch())["build"], "1")
        path.write_text(original)
        os.chmod(f.path("2/program.py"), 0o600)
        self.assertEqual(document(f.launch())["build"], "1")

    def test_builds_prune(self) -> None:
        """builds.prune retains records, logs, default and withdrawn Builds and never reuses a number."""
        f = Fixture(self)
        for _ in range(4):
            f.build()
        f.call("withdraw", f"{f.component}@2", "--reason", "keep for diagnosis")
        result = f.call("prune", f.component, "--keep", "1")
        self.assertEqual([result.returncode, document(result)["pruned"]], [0, ["3", "1"]])
        for number in ("1", "3"):
            folder = f.path(number)
            self.assertTrue(json.loads(Path(folder, "build.json").read_text())["prunedAt"])
            self.assertTrue(os.path.exists(os.path.join(folder, "build.log")))
            self.assertFalse(os.path.exists(os.path.join(folder, "program.py")))
            self.assertEqual(f.launch("-v", number).returncode, 1)
            self.assertEqual(f.call("show", f"{f.component}@{number}").returncode, 0)
        self.assertEqual(document(f.launch())["build"], "4")
        self.assertEqual(f.launch("-v", "2").returncode, 0)
        self.assertEqual(document(f.call("prune", f.component, "--keep", "1"))["pruned"], [])
        self.assertEqual(f.build()["build"], "5")
        for keep in ("0", "-1", "1.5", "two"):
            self.assertEqual(f.call("prune", f.component, "--keep", keep).returncode, 1)

    def test_builds_shared_data_format(self) -> None:
        """builds.shared-data-format records declarations while the sample component guards its own shared data."""
        f = Fixture(self)
        f.build()
        f.configure(dataFormat=2)
        f.build()
        state = os.path.join(f.home, "shared-state.json")
        contents = '{"format":2,"value":"unchanged"}'
        Path(state).write_text(contents)
        older = f.launch("-v", "1", "--state", state)
        self.assertEqual([older.returncode, document(older)], [1, {"error": "newer data", "found": 2, "supported": 1}])
        self.assertEqual(f.launch("--state", state).returncode, 0)
        self.assertEqual(Path(state).read_text(), contents)

    def test_builds_paths(self) -> None:
        """builds.paths uses default repository, registry and bin, or explicit paths with spaces and quotes."""
        f = Fixture(self)
        default_repo = os.path.join(f.home, "repos/sylvan-stack", f.component)
        os.makedirs(os.path.dirname(default_repo))
        os.rename(f.repo, default_repo)
        result = subprocess.run([PYTHON, "-I", "-B", ENTRY, "build", f.component], cwd=f.home, env=f.env(),
                                capture_output=True, timeout=120, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(os.path.exists(os.path.join(f.home, "Library/Application Support/Arbol/builds",
                                                    f.component, "1/build.json")))
        launcher = os.path.join(f.home, ".local/bin", f.component)
        started = subprocess.run([launcher], env=ENV, capture_output=True, timeout=60, check=False)
        self.assertEqual(document(started)["build"], "1")

    def test_builds_invalid_description(self) -> None:
        """builds.invalid-description and CLI input refuse without reserving a number."""
        f = Fixture(self)
        for args in ([], ["unknown"], ["build"], ["show", "sample@01"], ["prune", "sample"], ["withdraw", "sample@1"],
                     ["build", "../outside"], ["list", "sample@1"], ["list", "--repo", f.repo], ["list", "--registry-dir"],
                     ["list", "--unknown"], ["list", "--bin-dir=a", "--bin-dir=b"], ["show", ""]):
            result = f.call(*args)
            self.assertEqual(result.returncode, 1, args)
            self.assertEqual(document(result)["error"]["code"], "builds_failed", args)
        patches: list[dict[str, Any]] = [
            {"entry": "../outside"}, {"build": []}, {"checks": []}, {"dataFormat": 0},
            {"checks": [{"name": "same", "command": "true"}, {"name": "same", "command": "true"}]}]
        for patch in patches:
            f.configure(entry="program.py", build=[BUILD], checks=[{"name": "sample-check", "command": CHECK}],
                        dataFormat=1)
            f.configure(**patch)
            self.assertEqual(f.call("build", f.component, "--repo", f.repo).returncode, 1, patch)
            self.assertFalse(os.path.exists(f.registry), patch)

    def test_builds_interrupted_build(self) -> None:
        """builds.interrupted-build keeps a failed record and consumes its reserved number."""
        f = Fixture(self)
        f.configure(build=["echo waiting; while true; do sleep 1; done"])
        child = f.spawn("build", f.component, "--repo", f.repo, "--registry-dir", f.registry, "--bin-dir", f.bin)
        log = Path(f.path("1/build.log"))
        for _ in range(1000):
            if log.exists() and "waiting" in log.read_text():
                break
            time.sleep(0.01)
        child.send_signal(signal.SIGTERM)
        output, _ = child.communicate(timeout=30)
        self.assertEqual(child.returncode, 1)
        record = json.loads(output)
        self.assertEqual(record["status"], "failed")
        self.assertIn("stopped by the caller", record["failure"]["message"])
        self.assertIn("(stopped by caller)", log.read_text())
        f.configure(build=[BUILD])
        self.assertEqual(f.build()["build"], "2")


class Launchers(unittest.TestCase):
    """What the Python launcher does where the Node.js launcher did not (BLD-D15)."""

    def test_builds_launcher_signals(self) -> None:
        """builds.launcher-signals: the Build gets SIGPIPE at its default, as on a direct start."""
        f = Fixture(self, "probe")
        Path(f.repo, "probe.sh").write_text('#!/bin/sh\n(yes; echo "yes ended with $?" >&2) | head -1 > /dev/null\n')
        f.configure(build=['cp probe.sh "$ARBOL_BUILD_DIR/probe.sh"; chmod +x "$ARBOL_BUILD_DIR/probe.sh"'],
                    entry="probe.sh", checks=[{"name": "present", "command": 'test -x "$ARBOL_BUILD_DIR/probe.sh"'}])
        f.build()
        direct = subprocess.run([f.path("1/probe.sh")], env=ENV, capture_output=True, timeout=30, check=False)
        launched = f.launch()
        self.assertEqual(direct.stderr, b"yes ended with 141\n")
        self.assertEqual(launched.stderr, direct.stderr)

    def test_builds_launcher_bytes(self) -> None:
        """builds.launcher-bytes: arguments and environment that are not UTF-8 reach the Build byte for byte."""
        f = Fixture(self)
        f.build()
        arguments = [b"plain", b"caf\xe9", b"\xff\xfe-not-utf8", b"\xe2\x82\xac", b""]
        result = subprocess.run([os.path.join(f.bin, f.component).encode(), b"--bytes", *arguments],
                                env={**{key.encode(): value.encode() for key, value in f.env().items()},
                                     b"PROBE": b"\xff\x80value"},
                                capture_output=True, timeout=60, check=False)
        self.assertEqual(document(result), {"args": [argument.hex() for argument in arguments],
                                            "probe": b"\xff\x80value".hex()})

    def test_builds_launch_failed(self) -> None:
        """builds.launch-failed: a hand-over the system refuses prints launch_failed and ends with 1."""
        f = Fixture(self)
        f.configure(build=['printf "not a program" > "$ARBOL_BUILD_DIR/program.py"; chmod +x "$ARBOL_BUILD_DIR/program.py"'],
                    checks=[{"name": "present", "command": 'test -x "$ARBOL_BUILD_DIR/program.py"'}])
        f.build()
        result = f.launch()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(document(result)["error"]["code"], "launch_failed")
        self.assertIn("Exec format error", document(result)["error"]["message"])


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

    def test_builds_install(self) -> None:
        """builds.install installs an independent tool, with its own Python, that can create a standalone launcher."""
        f = self.f
        result = self.install(f"--bin-dir={self.folder}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installed = os.path.join(self.folder, "arbol-builds")
        python = document(result)["python"]
        self.assertTrue(python.startswith(os.path.join(self.folder, ".arbol-builds/runtime/")))
        os.chmod(installed, 0o600)
        self.assertEqual(self.install(f"--bin-dir={self.folder}", home=False).returncode, 0)
        self.assertEqual(stat.S_IMODE(os.stat(installed).st_mode) & 0o111, 0o111)
        build = subprocess.run([installed, "--registry-dir", f.registry, "build", f.component, "--repo", f.repo,
                                "--bin-dir", f.bin], env=ENV, capture_output=True, timeout=120, check=False)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        self.assertEqual(Path(f.bin, f.component).read_text().split("\n", 1)[0], f"#!{python} -ISB")
        self.assertEqual(document(f.launch())["build"], "1")
        listed = subprocess.run([installed, "list", f"--registry-dir={f.registry}"], env=ENV, capture_output=True,
                                timeout=60, check=False)
        self.assertEqual(listed.returncode, 0)
        self.assertEqual(self.install("--unknown").returncode, 1)
        self.assertEqual(self.install("word").returncode, 1)

    def test_builds_install_refreshes_launchers(self) -> None:
        """builds.install-refreshes-launchers rewrites Node.js and Python launchers and leaves other files alone."""
        f = self.f
        f.build()
        registry = json.dumps(os.path.abspath(f.registry))
        node = (f"#!/usr/bin/env node\nfunction launch(registry, component, args) {{ process.stdout.write('old\\n'); }}\n"
                f"launch({registry}, \"{f.component}\", process.argv.slice(2));\n")
        Path(self.folder, f.component).write_text(node)
        os.chmod(os.path.join(self.folder, f.component), 0o755)
        written = Path(f.bin, f.component).read_text()
        others = {
            "other-tool": "#!/bin/sh\necho other\n",
            "renamed": node,
            "notes.txt": f"launch({registry}, \"notes.txt\", process.argv.slice(2));\n",
            "python-renamed": written,
        }
        for name, text in others.items():
            Path(self.folder, name).write_text(text)
        os.symlink(os.path.join(self.folder, "other-tool"), os.path.join(self.folder, "linked"))
        os.mkdir(os.path.join(self.folder, "folder"))
        # A Python launcher written by this tool is refreshed as well.
        shutil.copy2(os.path.join(f.bin, f.component), os.path.join(self.folder, "second"))
        Path(self.folder, "second").write_text(written.replace(repr(f.component), repr("second")))
        result = self.install(f"--bin-dir={self.folder}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(document(result)["launchers"], ["sample", "second"])
        python = document(result)["python"]
        for name in ("sample", "second"):
            text = Path(self.folder, name).read_text()
            self.assertEqual(text.split("\n", 1)[0], f"#!{python} -ISB")
            self.assertTrue(text.rstrip().endswith(f"launch({os.path.abspath(f.registry)!r}, {name!r}, sys.argv[1:]))"))
        started = subprocess.run([os.path.join(self.folder, f.component)], env=ENV, capture_output=True, timeout=60,
                                 check=False)
        self.assertEqual(document(started)["build"], "1")
        for name, text in others.items():
            self.assertEqual(Path(self.folder, name).read_text(), text, name)
        self.assertTrue(os.path.islink(os.path.join(self.folder, "linked")))

    def test_builds_install_refuses_spaces(self) -> None:
        """builds.install-refuses-spaces: a folder whose path holds a space cannot name the Python in a first line."""
        target = os.path.join(self.folder, "with space")
        result = self.install(f"--bin-dir={target}")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(document(result)["error"]["code"], "install_failed")
        self.assertFalse(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
