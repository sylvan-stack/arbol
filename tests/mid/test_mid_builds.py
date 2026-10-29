"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_builds as _support
from test_builds import (BUILD ,CHECK ,Callable ,ENV ,EXECVE ,Fixture ,HOLDER ,LAUNCHER_MARK ,PYTHON ,Path ,ROOT ,Result ,SIGNALS ,TOOL ,Trunks ,WRITER ,alive ,document ,finish ,first_line ,json ,milliseconds ,os ,resource ,root_record ,shlex ,shutil ,signal ,stat ,subprocess ,threading ,time ,uuid ,wait_until ,waiting ,write_all ,write_root)


class Builds(_support.Builds):


# TEST-TIER-BEGIN tests/test_builds.py::Builds.test_builds_concurrent
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
# TEST-TIER-END tests/test_builds.py::Builds.test_builds_concurrent

# TEST-TIER-BEGIN tests/test_builds.py::Builds.test_builds_concurrent_mutations
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
# TEST-TIER-END tests/test_builds.py::Builds.test_builds_concurrent_mutations


# TEST-TIER-BEGIN tests/test_builds.py::Builds.test_builds_folder_alone
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
# TEST-TIER-END tests/test_builds.py::Builds.test_builds_folder_alone

# TEST-TIER-BEGIN tests/test_builds.py::Builds.test_builds_failed_check
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
        self.assertTrue(Path(f.path("2/build.log")).read_text().endswith(
            "\nFAILED check unavailable-account: Check failed; see build.log.\n"))
        self.assertEqual(document(f.launch())["build"], "1")
        named = f.launch("-v", "2", "text")
        self.assertEqual(named.returncode, 0, named.stdout)
        self.assertEqual([document(named)["build"], document(named)["args"]], ["2", ["text"]])
        self.assertEqual(named.stderr,
                         f"{f.component}@2 is failed: check unavailable-account: Check failed; see build.log.\n".encode())
        f.configure(checks=[{"name": "sample-check", "command": CHECK}])
        self.assertEqual(f.build()["build"], "3")
# TEST-TIER-END tests/test_builds.py::Builds.test_builds_failed_check


# TEST-TIER-BEGIN tests/test_builds.py::Builds.test_builds_stopped_commands
    def test_builds_stopped_commands(self) -> None:
        """builds.stopped-commands: SIGINT or SIGTERM sends SIGTERM to the whole process group of the running command."""
        f = Fixture(self)
        # A member of the group other than the shell notes the SIGTERM it receives.
        f.configure(build=['(trap \'echo term > "$ARBOL_BUILD_DIR/term"; exit 0\' TERM; sleep 300 & wait) & '
                           'echo $! > "$ARBOL_BUILD_DIR/child"; echo waiting; wait'])
        for number, build in ((signal.SIGINT, "1"), (signal.SIGTERM, "2")):
            with self.subTest(signal=number.name):
                child = f.spawn("build", f.component, "--repo", f.repo, "--registry-dir", f.registry,
                                "--bin-dir", f.bin)
                log = Path(f.path(build, "build.log"))
                wait_until(waiting, log)
                background = int(Path(f.path(build, "child")).read_text())
                child.send_signal(number)
                output, _ = child.communicate(timeout=30)
                self.assertEqual(child.returncode, 1)
                record = json.loads(output)
                self.assertEqual([record["status"], record["failure"]["stage"]], ["failed", "build"])
                self.assertIn("Exit: SIGTERM (stopped by caller)", log.read_text())
                wait_until(Path(f.path(build, "term")).exists)
                wait_until(lambda pid: not alive(pid), background)
# TEST-TIER-END tests/test_builds.py::Builds.test_builds_stopped_commands

# TEST-TIER-BEGIN tests/test_builds.py::Builds.test_builds_stop_kills
    def test_builds_stop_kills(self) -> None:
        """builds.stop-kills: a command that ignores SIGTERM is killed two seconds after the build is stopped."""
        f = Fixture(self)
        f.configure(build=['trap "" TERM; echo waiting; while true; do sleep 1; done'])
        child = f.spawn("build", f.component, "--repo", f.repo, "--registry-dir", f.registry, "--bin-dir", f.bin)
        log = Path(f.path("1/build.log"))
        wait_until(waiting, log)
        stopped = time.monotonic()
        child.send_signal(signal.SIGTERM)
        output, _ = child.communicate(timeout=30)
        self.assertTrue(1.5 <= time.monotonic() - stopped < 10, time.monotonic() - stopped)
        self.assertEqual([child.returncode, json.loads(output)["status"]], [1, "failed"])
        self.assertIn("Exit: SIGKILL (stopped by caller)", log.read_text())
# TEST-TIER-END tests/test_builds.py::Builds.test_builds_stop_kills


# TEST-TIER-BEGIN tests/test_builds.py::Builds.test_builds_command_environment
    def test_builds_command_environment(self) -> None:
        """builds.command-environment: commands read no input and start with every signal at its default,
        none blocked, and the raised open-files limit, whatever the caller gave the tool."""
        f = Fixture(self)
        Path(f.repo, "signals.py").write_text(SIGNALS)
        f.configure(build=[BUILD, 'cat > "$ARBOL_BUILD_DIR/input"', 'ulimit -n > "$ARBOL_BUILD_DIR/files"',
                           f'"{PYTHON}" -I signals.py > "$ARBOL_BUILD_DIR/signals"'])

        hard = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
        if hard != resource.RLIM_INFINITY and hard <= 256:
            self.skipTest("the open-files limit cannot be lowered and raised here")

        def restricted(soft: int) -> Callable[[], None]:
            def prepare() -> None:
                for number in (signal.SIGHUP, signal.SIGINT, signal.SIGQUIT, signal.SIGUSR1):
                    signal.signal(number, signal.SIG_IGN)
                signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1, signal.SIGTERM})
                resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
            return prepare

        def build(soft: int) -> str:
            result = subprocess.run([*TOOL, "--registry-dir", f.registry, "--bin-dir", f.bin, "build", f.component,
                                     "--repo", f.repo], cwd=f.home, env=f.env(), input=b"caller data",
                                    capture_output=True, timeout=120, check=False, preexec_fn=restricted(soft))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return str(document(result)["build"])

        number = build(256)
        self.assertEqual(Path(f.path(number, "input")).read_bytes(), b"")
        files = Path(f.path(number, "files")).read_text().strip()
        if hard == resource.RLIM_INFINITY:
            self.assertGreater(int(files), 256)
            # Above 2**20 the Node.js tool raised the soft limit to the hard one.
            self.assertEqual(Path(f.path(build(1 << 21), "files")).read_text().strip(), "unlimited")
        else:
            self.assertEqual(int(files), hard)
        self.assertEqual(json.loads(Path(f.path(number, "signals")).read_text()), {"ignored": [], "blocked": []})
# TEST-TIER-END tests/test_builds.py::Builds.test_builds_command_environment


class Launchers(_support.Launchers):
# TEST-TIER-BEGIN tests/test_builds.py::Launchers.test_builds_launcher_signals
    def test_builds_launcher_signals(self) -> None:
        """builds.launcher-signals: the Build gets SIGPIPE and SIGXFSZ at their default, as on a direct start."""
        f = Fixture(self, "probe")
        Path(f.repo, "probe.sh").write_text('#!/bin/sh\n(yes; echo "yes ended with $?" >&2) | head -1 > /dev/null\n'
                                            '(ulimit -f 0; printf x > "$(dirname "$0")/written")\n'
                                            'echo "write ended with $?" >&2\n')
        f.configure(build=['cp probe.sh "$ARBOL_BUILD_DIR/probe.sh"; chmod +x "$ARBOL_BUILD_DIR/probe.sh"'],
                    entry="probe.sh", checks=[{"name": "present", "command": 'test -x "$ARBOL_BUILD_DIR/probe.sh"'}])
        f.build()
        direct = subprocess.run([f.path("1/probe.sh")], env=ENV, capture_output=True, timeout=30, check=False)
        launched = f.launch()

        def ended(result: Result) -> list[bytes]:
            # The shell also reports the signal, with a process number that differs from run to run.
            return [line for line in result.stderr.splitlines() if b" ended with " in line]

        self.assertEqual(ended(direct), [b"yes ended with 141", b"write ended with 153"])
        self.assertEqual(ended(launched), ended(direct))
# TEST-TIER-END tests/test_builds.py::Launchers.test_builds_launcher_signals

# TEST-TIER-BEGIN tests/test_builds.py::Launchers.test_builds_launcher_bytes
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
        helper = os.path.join(f.home, "execve.py")
        Path(helper).write_text(EXECVE)
        environment = [b"PATH=/usr/bin:/bin", b"LANG=en_US.UTF-8", b"DUP=first", b"DUP=second", b"NOEQUALS",
                       b"X=\xff\xfe"]

        def environ(program: str) -> list[bytes]:
            words = [program.encode(), b"--environ", b"--", *environment]
            started = subprocess.run([PYTHON, "-I", helper, *(word.hex() for word in words)], capture_output=True,
                                     timeout=60, check=False)
            self.assertEqual(started.returncode, 0, started.stderr)
            # macOS adds this one when it is missing, on a direct start too.
            return [bytes.fromhex(entry) for entry in document(started)
                    if not bytes.fromhex(entry).startswith(b"__CF_USER_TEXT_ENCODING=")]

        self.assertEqual(environ(os.path.join(f.bin, f.component)), environment)
        self.assertEqual(environ(f.path("1/program.py")), environment)
# TEST-TIER-END tests/test_builds.py::Launchers.test_builds_launcher_bytes


# TEST-TIER-BEGIN tests/test_builds.py::Launchers.test_builds_nonblocking_output
    def test_builds_nonblocking_output(self) -> None:
        """builds.nonblocking-output: output reaches a pipe the caller left non-blocking in full."""
        f = Fixture(self)
        f.build()
        record = json.loads(Path(f.path("1/build.json")).read_text())
        for number in range(2, 302):
            os.mkdir(f.path(format(number, "x")))
            Path(f.path(format(number, "x"), "build.json")).write_text(json.dumps({**record, "build": format(number, "x")}))
        reading, writing = os.pipe()
        os.set_blocking(writing, False)
        lister = subprocess.Popen([*TOOL, "list", "--registry-dir", f.registry], cwd=f.home, env=f.env(),
                                  stdout=writing, stderr=subprocess.PIPE)
        self.addCleanup(finish, lister)
        os.close(writing)
        time.sleep(0.5)  # the caller reads late: the pipe fills
        with os.fdopen(reading, "rb") as stream:
            listed = stream.read()
        self.assertEqual(lister.wait(timeout=60), 0)
        self.assertGreater(len(listed), 1 << 17)
        self.assertEqual(len(json.loads(listed)), 301)
        read_end, write_end = os.pipe()
        os.set_blocking(write_end, False)
        data = os.urandom(1 << 20)
        received = bytearray()

        def drain() -> None:
            while chunk := os.read(read_end, 65536):
                received.extend(chunk)
                time.sleep(0.001)

        reader = threading.Thread(target=drain)
        reader.start()
        try:
            write_all(write_end, data)
        finally:
            os.close(write_end)
            reader.join(timeout=60)
            os.close(read_end)
        self.assertEqual(bytes(received), data)
# TEST-TIER-END tests/test_builds.py::Launchers.test_builds_nonblocking_output


class PruningRoots(_support.PruningRoots):

# TEST-TIER-BEGIN tests/test_builds.py::PruningRoots.test_builds_prune_versions_protects_a_runnable_fallback_and_locked_builds
    def test_builds_prune_versions_protects_a_runnable_fallback_and_locked_builds(self) -> None:
        """builds.prune-version-fallback: missing newer executables do not expose the last runnable fit."""
        f = Trunks(self)
        f.root("sapling", 1, "2026-10-16T09:00:00.000Z")
        f.root("second", 2, "2026-10-16T10:00:00.000Z")
        for number, versions in (("1", [1]), ("2", [1, 2]), ("3", [2]), ("4", [3])):
            f.build("alpha", number, versions)
        Path(f.registry, "arbol-trunk/alpha/3/program.py").unlink()
        self.assertEqual(self.trunk_command(f, "lock", "arbol-trunk/alpha@1").returncode, 0)
        result = self.trunk_command(f, "prune", "arbol-trunk/alpha", "--keep", "1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(document(result)["pruned"], ["3"])
        self.assertEqual(f.started("--root", "second", "alpha", "run")[0], "2")
        self.assertEqual(f.started("--root", "sapling", "alpha", "run")[0], "2")
        self.assertEqual(self.trunk_command(f, "unlock", "arbol-trunk/alpha@1").returncode, 0)
        self.assertEqual(document(self.trunk_command(f, "prune", "arbol-trunk/alpha", "--keep", "1"))["pruned"],
                         ["1"])
# TEST-TIER-END tests/test_builds.py::PruningRoots.test_builds_prune_versions_protects_a_runnable_fallback_and_locked_builds

# TEST-TIER-BEGIN tests/test_builds.py::PruningRoots.test_builds_prune_versions_refuses_unresolved_root_records_before_any_build_mutation
    def test_builds_prune_versions_refuses_unresolved_root_records_before_any_build_mutation(self) -> None:
        """builds.prune-version-refusal: an unknown retained version refuses the whole prune without changes."""
        f = Trunks(self)
        f.root("sapling", 1, "2026-10-16T09:00:00.000Z")
        for number in ("1", "2", "3"):
            f.build("alpha", number, [1])
        write_root(f.roots, "{", "damaged")
        Path(f.roots, "pipe").mkdir()
        os.mkfifo(Path(f.roots, "pipe/root.json"))
        before = {path: path.read_bytes() for path in Path(f.registry).rglob("*") if path.is_file()}
        result = self.trunk_command(f, "prune", "arbol-trunk/alpha", "--keep", "1")
        self.assertEqual(result.returncode, 1)
        error = document(result)["error"]
        self.assertEqual(error["code"], "builds_failed")
        self.assertIn("damaged, pipe", error["message"])
        self.assertIn("versions are unknown", error["message"])
        self.assertEqual({path: path.read_bytes() for path in Path(f.registry).rglob("*") if path.is_file()}, before)
        write_root(f.roots, root_record("damaged", "failed"))
        Path(f.roots, "pipe/root.json").unlink()
        self.assertEqual(document(self.trunk_command(f, "prune", "arbol-trunk/alpha", "--keep", "1"))["pruned"],
                         ["2", "1"])
# TEST-TIER-END tests/test_builds.py::PruningRoots.test_builds_prune_versions_refuses_unresolved_root_records_before_any_build_mutation


# TEST-TIER-BEGIN tests/test_builds.py::PruningRoots.test_builds_prune_roots_keeps_damaged_root_identities_runnable_fallbacks_and_locked_builds
    def test_builds_prune_roots_keeps_damaged_root_identities_runnable_fallbacks_and_locked_builds(self) -> None:
        """builds.prune-root-retention: missing records protect nothing; damaged records and locks still do."""
        f = Fixture(self, "arbol-root")
        roots = os.path.join(f.home, "Library/Application Support/Arbol/roots")
        for name in ("removed", "sapling", "sapling", "second", "third"):
            f.build("--root", name)
        write_root(roots, "{", "sapling")
        write_root(roots, root_record("another"), "second")
        write_root(roots, root_record("third"))
        Path(roots, "removed").mkdir()  # a folder without root.json is no longer retained
        Path(f.path("3/program.py")).unlink()
        result = f.call("prune", f.component, "--keep", "1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(document(result)["pruned"], ["3", "1"])
        for number in ("2", "4", "5"):
            self.assertTrue(Path(f.path(number, "program.py")).is_file())
        self.assertEqual(f.call("lock", "arbol-root@2").returncode, 0)
        for name in ("sapling", "second"):
            Path(roots, name, "root.json").unlink()
        self.assertEqual(document(f.call("prune", f.component, "--keep", "1"))["pruned"], ["4"])
        self.assertTrue(Path(f.path("2/program.py")).is_file())
        self.assertEqual(f.call("unlock", "arbol-root@2").returncode, 0)
        self.assertEqual(document(f.call("prune", f.component, "--keep", "1"))["pruned"], ["2"])
# TEST-TIER-END tests/test_builds.py::PruningRoots.test_builds_prune_roots_keeps_damaged_root_identities_runnable_fallbacks_and_locked_builds


class RootComponents(_support.RootComponents):


# TEST-TIER-BEGIN tests/test_builds.py::RootComponents.test_builds_root_pass_through_preserves_arguments_streams_pid_signals_and_status
    def test_builds_root_pass_through_preserves_arguments_streams_pid_signals_and_status(self) -> None:
        """builds.root-pass-through adds no Root argument and preserves the caller's process contract."""
        f = self.fixture()
        f.build("--root", "sapling")
        args = ["command", "two words", "", "--root", "second", "-v", "999"]
        result = f.launch("--root", "sapling", "-v", "1", *args, marker="root caller")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        value = document(result)
        self.assertEqual((value["build"], value["args"], value["cwd"], value["marker"]),
                         ("1", args, f.home, "root caller"))
        raw = b"bytes\x00\xff\nsecond line\n"
        echo = f.launch("--root", "sapling", "--echo", data=raw)
        self.assertEqual((echo.returncode, echo.stdout, echo.stderr), (0, raw, b"diagnostic\n"))
        self.assertEqual(f.launch("--root", "sapling", "--exit", "23").returncode, 23)
        child = subprocess.Popen([os.path.join(f.bin, f.component), "--root", "sapling", "--wait"],
                                 cwd=f.home, env=f.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(finish, child)
        self.assertEqual(json.loads(first_line(child))["pid"], child.pid)
        child.send_signal(signal.SIGINT)
        output, errors = child.communicate(timeout=10)
        self.assertEqual((child.returncode, output, errors), (2, b"interrupted\n", b""))
        stamp = Path(f.path("1/last-start")).read_text().strip()
        self.assertIsNotNone(milliseconds(stamp))
# TEST-TIER-END tests/test_builds.py::RootComponents.test_builds_root_pass_through_preserves_arguments_streams_pid_signals_and_status


class Locking(_support.Locking):

# TEST-TIER-BEGIN tests/test_builds.py::Locking.test_builds_lock_and_prune_in_separate_processes_have_both_serial_orders
    def test_builds_lock_and_prune_in_separate_processes_have_both_serial_orders(self) -> None:
        """builds.lock-prune-race: holding each first mutation proves both serialized outcomes."""
        for first_operation in ("lock", "prune"):
            with self.subTest(first=first_operation):
                f = Fixture(self)
                for _ in range(3):
                    f.build()
                worker = Path(f.home, "mutation.py")
                worker.write_text("import json,sys\n"
                                  f"sys.path.insert(0,{str(ROOT / 'src')!r})\n"
                                  "from arbol_builds import service\n"
                                  "registry,component,operation=sys.argv[1:]\n"
                                  "original=service.save_unlocked\n"
                                  "def held(folder,record):\n"
                                  " if record['build']=='1':\n"
                                  "  print('held',flush=True);sys.stdin.readline()\n"
                                  " original(folder,record)\n"
                                  "service.save_unlocked=held\n"
                                  "result=(service.lock_build(registry,component,'1',True) if operation=='lock'"
                                  " else service.prune_builds(registry,component,1))\n"
                                  "print(json.dumps(result))\n")
                first = subprocess.Popen([PYTHON, "-I", "-B", str(worker), f.registry, f.component, first_operation],
                                         env=f.env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
                self.addCleanup(finish, first)
                self.assertEqual(first_line(first), b"held\n")
                args = (["prune", f.component, "--keep", "1"] if first_operation == "lock"
                        else ["lock", f"{f.component}@1"])
                second = f.spawn(*args, "--registry-dir", f.registry)
                deadline = time.monotonic() + 10
                writers = Path(f.path(".writers"))
                while not list(writers.glob(f"{second.pid}-*.json")) and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(list(writers.glob(f"{second.pid}-*.json")))
                self.assertIsNone(second.poll())
                assert first.stdin is not None
                first.stdin.write(b"go\n")
                first.stdin.flush()
                output, errors = first.communicate(timeout=30)
                self.assertEqual(first.returncode, 0, output + errors)
                output, errors = second.communicate(timeout=30)
                record = json.loads(Path(f.path("1/build.json")).read_text())
                if first_operation == "lock":
                    self.assertEqual(second.returncode, 0, output + errors)
                    self.assertEqual(json.loads(output)["pruned"], ["2"])
                    self.assertIn("lockedAt", record)
                    self.assertNotIn("prunedAt", record)
                    self.assertTrue(Path(f.path("1/program.py")).is_file())
                else:
                    self.assertEqual(second.returncode, 1, output + errors)
                    self.assertIn("pruned", json.loads(output)["error"]["message"])
                    self.assertIn("prunedAt", record)
                    self.assertNotIn("lockedAt", record)
                    self.assertFalse(Path(f.path("1/program.py")).exists())
# TEST-TIER-END tests/test_builds.py::Locking.test_builds_lock_and_prune_in_separate_processes_have_both_serial_orders

# TEST-TIER-BEGIN tests/test_builds.py::Locking.test_builds_in_flight_writes_preserve_a_lock_and_a_later_unlock
    def test_builds_in_flight_writes_preserve_a_lock_and_a_later_unlock(self) -> None:
        """builds.lock-building: stale lifecycle writes cannot undo a concurrent mark or its removal."""
        f = Fixture(self)
        gate = Path(f.repo, "gate.py")
        gate.write_text("from pathlib import Path\nimport sys,time\n"
                        f"home=Path({f.home!r}); phase=sys.argv[1]\n"
                        "(home/(phase+'-ready')).touch()\n"
                        "while not (home/(phase+'-go')).exists():time.sleep(.01)\n")
        command = f"{shlex.quote(PYTHON)} -I -B {shlex.quote(str(gate))}"
        f.configure(build=[BUILD, command + " build"], checks=[
            {"name": "sample-check", "command": CHECK}, {"name": "later-check", "command": command + " check"}])
        child = f.spawn("build", f.component, "--repo", f.repo, "--registry-dir", f.registry, "--bin-dir", f.bin)

        def ready(phase: str) -> None:
            path = Path(f.home, phase + "-ready")
            deadline = time.monotonic() + 15
            while not path.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(path.exists(), f"Build did not reach {phase}: {child.poll()}")

        ready("build")
        result = f.call("lock", f"{f.component}@1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        mark = document(result)["lockedAt"]
        self.assertEqual(document(result)["status"], "building")
        Path(f.home, "build-go").touch()
        ready("check")
        after_first_write = json.loads(Path(f.path("1/build.json")).read_text())
        self.assertEqual(after_first_write["lockedAt"], mark)
        self.assertEqual(after_first_write["checks"], [{"name": "sample-check", "passed": True}])
        self.assertEqual(f.call("unlock", f"{f.component}@1").returncode, 0)
        Path(f.home, "check-go").touch()
        output, errors = child.communicate(timeout=30)
        self.assertEqual(child.returncode, 0, output + errors)
        finished = json.loads(output)
        self.assertEqual(finished["status"], "working")
        self.assertNotIn("lockedAt", finished)
        self.assertEqual(finished, json.loads(Path(f.path("1/build.json")).read_text()))
# TEST-TIER-END tests/test_builds.py::Locking.test_builds_in_flight_writes_preserve_a_lock_and_a_later_unlock


class StartRecords(_support.StartRecords):

# TEST-TIER-BEGIN tests/test_builds.py::StartRecords.test_builds_last_start_write_failure
    def test_builds_last_start_write_failure(self) -> None:
        """builds.last-start-write-failure: read-only folder, directory target and file-size limit never stop a Build."""
        f = Fixture(self)
        f.build()
        folder = Path(f.path("1"))
        saved = folder / "last-start"
        previous = b"2026-01-01T00:00:00.000Z\n"
        saved.write_bytes(previous)
        os.chmod(folder, 0o500)
        try:
            self.assertEqual(document(f.launch())["build"], "1")
            self.assertEqual(saved.read_bytes(), previous)
        finally:
            os.chmod(folder, 0o700)

        def no_file_bytes() -> None:
            resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))

        result = subprocess.run([str(Path(f.bin, f.component))], env=f.env(), capture_output=True,
                                preexec_fn=no_file_bytes, timeout=10, check=False)
        self.assertEqual([result.returncode, document(result)["build"]], [0, "1"], result.stderr)
        self.assertEqual(saved.read_bytes(), previous)
        saved.unlink()
        saved.mkdir()
        self.assertEqual(document(f.launch())["build"], "1")
        self.assertTrue(saved.is_dir())
        self.assertEqual(list(folder.glob("last-start.*.tmp")), [])
# TEST-TIER-END tests/test_builds.py::StartRecords.test_builds_last_start_write_failure


class Install(_support.Install):
# TEST-TIER-BEGIN tests/test_builds.py::Install.test_builds_install
    def test_builds_install(self) -> None:
        """builds.install installs an independent tool, with its own Python, that can create a standalone launcher."""
        f = self.f
        result = self.install(f"--bin-dir={self.folder}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installed = os.path.join(self.folder, "arbol-builds")
        installed_roots = os.path.join(self.folder, "arbol-roots")
        python = document(result)["python"]
        self.assertEqual(document(result)["rootsProgram"], installed_roots)
        self.assertEqual(Path(installed_roots).read_text().split("\n", 1)[0], f"#!{python} -ISB")
        self.assertTrue(python.startswith(os.path.join(self.folder, ".arbol-builds/runtime/")))
        os.chmod(installed, 0o600)
        os.chmod(installed_roots, 0o600)
        self.assertEqual(self.install(f"--bin-dir={self.folder}", home=False).returncode, 0)
        self.assertEqual(stat.S_IMODE(os.stat(installed).st_mode) & 0o111, 0o111)
        self.assertEqual(stat.S_IMODE(os.stat(installed_roots).st_mode) & 0o111, 0o111)
        build = subprocess.run([installed, "--registry-dir", f.registry, "build", f.component, "--repo", f.repo,
                                "--bin-dir", f.bin], env=ENV, capture_output=True, timeout=120, check=False)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        self.assertEqual(Path(f.bin, f.component).read_text().split("\n", 1)[0], f"#!{python} -ISB")
        self.assertEqual(document(f.launch())["build"], "1")
        listed = subprocess.run([installed, "list", f"--registry-dir={f.registry}"], env=ENV, capture_output=True,
                                timeout=60, check=False)
        self.assertEqual(listed.returncode, 0)
        from test_roots import database_fixture

        paths = database_fixture(self)
        made_root = subprocess.run([installed_roots, "create", "sapling", "--name", "Private installed Root",
                                    "--roots-dir", str(paths.roots), "--settings-dir", str(paths.settings),
                                    "--registry-dir", str(paths.registry), "--database-config", str(paths.database_config),
                                    "--psql", paths.psql, "--security", paths.security],
                                   env={**ENV, "HOME": str(paths.home)}, capture_output=True, timeout=60, check=False)
        self.assertEqual(made_root.returncode, 0, made_root.stdout + made_root.stderr)
        self.assertEqual((document(made_root)["status"], document(made_root)["app"]), ("preparing", "0"))
        self.assertTrue((paths.roots / "sapling/root.json").is_file())
        self.assertEqual(self.install("--unknown").returncode, 1)
        self.assertEqual(self.install("word").returncode, 1)
# TEST-TIER-END tests/test_builds.py::Install.test_builds_install

# TEST-TIER-BEGIN tests/test_builds.py::Install.test_builds_install_refreshes_launchers
    def test_builds_install_refreshes_launchers(self) -> None:
        """builds.install-refreshes-launchers rewrites Node.js and Python launchers, arbol-trunk among them, leaves
        other files alone, and removes the earlier Node.js tool and the leftovers of a stopped install."""
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
            # Marked like a launcher, but its last line does not parse as one.
            "arbol-a": f"#!/x/python -ISB\n{LAUNCHER_MARK}\nsys.exit(launch({{[]: 1}}, \"arbol-a\", sys.argv[1:]))\n",
            "arbol-b": f"#!/x/python -ISB\n{LAUNCHER_MARK}\nsys.exit(start({registry}, \"arbol-b\", sys.argv[1:]))\n",
            "arbol-c": f"#!/x/python -ISB\n{LAUNCHER_MARK}\nsys.exit(launch_trunk({registry}, \"arbol-c\", []))\n",
            "arbol-d": f"#!/x/python -ISB\n{LAUNCHER_MARK}\nsys.exit(launch_root({registry}, \"arbol-d\", []))\n",
            # The Trunks' launcher under another name.
            "trunks-renamed": f"#!/x/python -ISB\n{LAUNCHER_MARK}\nsys.exit(launch_trunk({registry}, sys.argv[1:]))\n",
        }
        # The launcher arbol-trunk of an earlier install: only its last line, which names the registry, is kept.
        Path(self.folder, "arbol-trunk").write_text(f"#!/x/python -ISB\n{LAUNCHER_MARK}\nprint('old')\n"
                                                    f"sys.exit(launch_trunk({registry}, sys.argv[1:]))\n")
        for name, text in others.items():
            Path(self.folder, name).write_text(text)
        os.symlink(os.path.join(self.folder, "other-tool"), os.path.join(self.folder, "linked"))
        os.mkdir(os.path.join(self.folder, "folder"))
        # A Python launcher written by this tool is refreshed as well.
        shutil.copy2(os.path.join(f.bin, f.component), os.path.join(self.folder, "second"))
        Path(self.folder, "second").write_text(written.replace(repr(f.component), repr("second")))
        # A link named after the component it serves is left as a link, and its target as it is.
        outside = Path(f.home, "outside-third")
        outside.write_text(written.replace(repr(f.component), repr("third")))
        os.symlink(outside, os.path.join(self.folder, "third"))
        library = Path(self.folder, ".arbol-builds")
        library.mkdir()
        old = ["cli.js", "service.js", "package.json"]
        for name in old:
            Path(library, name).write_text("// the earlier tool\n")
        leftovers = [Path(library, f".arbol_builds-{uuid.uuid4()}"), Path(library, f".arbol_roots-{uuid.uuid4()}"),
                     Path(library, "runtime", f".unpacking-{uuid.uuid4()}")]
        for leftover in leftovers:
            leftover.mkdir(parents=True)
        ended = subprocess.Popen(["/usr/bin/true"])
        ended.wait()
        leftovers += [Path(self.folder, f"arbol-builds.1.{uuid.uuid4()}.tmp"),
                      Path(self.folder, f"arbol-roots.1.{uuid.uuid4()}.tmp"),
                      Path(self.folder, f"{f.component}.{ended.pid}.{uuid.uuid4()}.tmp")]
        for leftover in leftovers[-3:]:
            leftover.write_text("unfinished")
        # A launcher that a running build is writing stays.
        writing = Path(self.folder, f"{f.component}.{os.getpid()}.{uuid.uuid4()}.tmp")
        writing.write_text("being written")
        root_fixtures = [Fixture(self, component) for component in ("arbol", "arbol-root")]
        for fixture in root_fixtures:
            fixture.build("--root", "sapling")
            write_root(os.path.join(fixture.home, "Library/Application Support/Arbol/roots"), root_record("sapling"))
            text = Path(fixture.bin, fixture.component).read_text()
            if fixture.component == "arbol":
                # An older generic launcher upgrades; the other exercises future recognition of launch_root.
                text = text.replace("sys.exit(launch_root(", "sys.exit(launch(")
            Path(self.folder, fixture.component).write_text(text)
        result = self.install(f"--bin-dir={self.folder}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(document(result)["launchers"], ["arbol", "arbol-root", "arbol-trunk", "sample", "second"])
        python = document(result)["python"]
        for name in ("sample", "second"):
            text = Path(self.folder, name).read_text()
            self.assertEqual(text.split("\n", 1)[0], f"#!{python} -ISB")
            self.assertTrue(text.rstrip().endswith(f"launch({os.path.abspath(f.registry)!r}, {name!r}, sys.argv[1:]))"))
        for fixture in root_fixtures:
            text = Path(self.folder, fixture.component).read_text()
            self.assertEqual(text.split("\n", 1)[0], f"#!{python} -ISB")
            self.assertTrue(text.rstrip().endswith(
                f"launch_root({fixture.registry!r}, {fixture.component!r}, sys.argv[1:]))"))
            started_root = subprocess.run([os.path.join(self.folder, fixture.component), "--root", "sapling", "probe"],
                                          env=fixture.env(), capture_output=True, timeout=60, check=False)
            self.assertEqual(started_root.returncode, 0, started_root.stdout + started_root.stderr)
            self.assertEqual((document(started_root)["build"], document(started_root)["args"]), ("1", ["probe"]))
        # arbol-trunk holds the current code for the same registry, and runs with the installed Python.
        trunks = Path(self.folder, "arbol-trunk").read_text()
        self.assertEqual(trunks.split("\n", 1)[0], f"#!{python} -ISB")
        self.assertTrue(trunks.rstrip().endswith(f"launch_trunk({os.path.abspath(f.registry)!r}, sys.argv[1:]))"))
        self.assertNotIn("print('old')", trunks)
        self.assertIn("def launch_trunk(", trunks)
        write_root(os.path.join(f.home, "Library/Application Support/Arbol/roots"), root_record("sapling"))
        listed = subprocess.run([os.path.join(self.folder, "arbol-trunk"), "list"], env={**ENV, "HOME": f.home},
                                capture_output=True, timeout=60, check=False)
        self.assertEqual([listed.returncode, document(listed)], [0, {"root": "sapling", "rootContract": 1, "trunks": []}])
        started = subprocess.run([os.path.join(self.folder, f.component)], env=ENV, capture_output=True, timeout=60,
                                 check=False)
        self.assertEqual(document(started)["build"], "1")
        self.assertTrue(Path(f.path("1/last-start")).is_file())
        t = Trunks(self)
        t.build("trivial", "1", [1])
        shutil.copytree(Path(t.registry, "arbol-trunk"), Path(f.registry, "arbol-trunk"))
        started_trunk = subprocess.run([os.path.join(self.folder, "arbol-trunk"), "run"],
                                       env={**ENV, "HOME": f.home}, capture_output=True, timeout=60, check=False)
        self.assertEqual([started_trunk.returncode, document(started_trunk)["build"]], [0, "1"])
        self.assertTrue(Path(f.registry, "arbol-trunk/trivial/1/last-start").is_file())
        inventory = subprocess.run([os.path.join(self.folder, "arbol-builds"), "show", "arbol-trunk/trivial@1",
                                    "--registry-dir", f.registry], env=ENV, capture_output=True, timeout=60, check=False)
        self.assertEqual(document(inventory)["lastStart"],
                         Path(f.registry, "arbol-trunk/trivial/1/last-start").read_text().strip())
        for name, text in others.items():
            self.assertEqual(Path(self.folder, name).read_text(), text, name)
        self.assertTrue(os.path.islink(os.path.join(self.folder, "linked")))
        self.assertTrue(os.path.islink(os.path.join(self.folder, "third")))
        self.assertEqual(outside.read_text(), written.replace(repr(f.component), repr("third")))
        for path in [*(library / name for name in old), *leftovers]:
            self.assertFalse(path.exists(), path)
        self.assertEqual(writing.read_text(), "being written")
# TEST-TIER-END tests/test_builds.py::Install.test_builds_install_refreshes_launchers
