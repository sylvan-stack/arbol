"""Prospective isolated launcher signal cases for ABR-38.

Each case uses its own real registered disposable Build cohort. Review and
integration precede execution. Importing this module launches no processes.
"""

from __future__ import annotations

import fcntl
import os
import select
import signal
import struct
import subprocess
import tempfile
import termios
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import IO, Literal

from driver_identity_qualification import WholeCheckController, require
from test_builds import Fixture

from arbol_builds.driver_admission import Authority, reconcile, without_authority
from arbol_builds.driver_payload import SUBTREE, registered, verify_acceptance, verify_gate
from arbol_builds.driver_process import process_identity
from arbol_builds.launcher import executable_entry, named_runnable, valid_record
from top.driver_state_support import (
    Captured,
    ExactProcess,
    Object,
    OwnedChild,
    OwnedPTY,
    digest,
    document,
    read_image,
    signal_verified,
    tree_inventory,
)

COMPONENT = "arbol-codex-driver"
LEGACY_SOURCE = "bee148e24dbee6e82bf3a728e993d60af964b698"
SignalCase = Literal["ignored-int", "pending-int", "pending-term"]

PREPARE_SIGNAL = """import os
import signal
import sys

case, *argv = sys.argv[1:]
if case == "ignored-int":
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.pthread_sigmask(signal.SIG_SETMASK, set())
elif case in ("pending-int", "pending-term"):
    selected = signal.SIGINT if case == "pending-int" else signal.SIGTERM
    signal.signal(selected, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_SETMASK, {selected})
else:
    raise SystemExit(125)
os.write(1, b"R")
if os.read(0, 1) != b"G":
    raise SystemExit(125)
os.execv(argv[0], argv)
"""


def _until(end: float) -> float:
    seconds = end - time.monotonic()
    require(seconds > 0, "The exact signal observation deadline expired.")
    return seconds


def _proc_signals(owner: ExactProcess, *, end: float) -> tuple[int, int]:
    require(owner.live(parent=os.getpid()), "Signal observation target changed before ps.")
    result = subprocess.run(["/bin/ps", "-p", str(owner.pid), "-o", "pid=,ppid=,blocked=,pending="],
                            stdin=subprocess.DEVNULL, capture_output=True,
                            env={"LC_ALL": "C"}, timeout=min(2, _until(end)), check=False)
    fields = result.stdout.split()
    require(result.returncode == 0 and not result.stderr and len(fields) == 4
            and fields[:2] == [str(owner.pid).encode(), str(os.getpid()).encode()]
            and owner.live(parent=os.getpid()), "The kernel signal observations lack the exact owned process.")
    return int(fields[2], 16), int(fields[3], 16)


def _wait_control_open(owner: ExactProcess, lock: Path, *, end: float) -> None:
    """Observe the exact open control inode after dispatch, while we hold its lock."""
    observed = lock.lstat()
    while owner.live(parent=os.getpid()):
        result = subprocess.run(["/usr/sbin/lsof", "-nP", "-a", "-p", str(owner.pid), "-Fpin", str(lock)],
                                stdin=subprocess.DEVNULL, capture_output=True,
                                env={"LC_ALL": "C"}, timeout=min(2, _until(end)), check=False)
        if result.returncode == 0 and not result.stderr:
            rows = result.stdout.splitlines()
            current = lock.lstat()
            require(rows.count(b"p" + str(owner.pid).encode()) == 1
                    and b"i" + str(observed.st_ino).encode() in rows
                    and b"n" + os.fsencode(lock) in rows
                    and (current.st_dev, current.st_ino) == (observed.st_dev, observed.st_ino)
                    and owner.live(parent=os.getpid()), "The launcher did not open the original control inode.")
            return
        require(result.returncode == 1 and not result.stdout and not result.stderr,
                "The fixed control-lock observer failed.")
        time.sleep(min(0.025, _until(end)))
    require(False, "The exact launcher exited before reaching the real control lock.")


def _prepare_child(controller: WholeCheckController, case: SignalCase, argv: list[str],
                   environment: dict[str, str]) -> OwnedChild:
    interpreter, isolation, _ = controller.scope.gate.provider.prefix
    return OwnedChild([interpreter, isolation, "-c", PREPARE_SIGNAL, case, *argv],
                      environment=environment, cwd=controller.workspace.fixture_root)


def _start_exec(child: OwnedChild, case: SignalCase, *, end: float) -> Object:
    stdout, stdin = child.process.stdout, child.process.stdin
    require(stdout is not None and stdin is not None, "The controlled child lacks its initial pipes.")
    assert stdout is not None and stdin is not None
    require(bool(select.select([stdout], [], [], _until(end))[0]) and os.read(stdout.fileno(), 1) == b"R",
            "The real pre-exec setup did not reach its barrier.")
    number = signal.SIGTERM if case == "pending-term" else signal.SIGINT
    bit = 1 << (number - 1)
    blocked_before, pending_before = _proc_signals(child.owner, end=end)
    expected = 0 if case == "ignored-int" else bit
    require(blocked_before == expected and pending_before == 0, "Unexpected inherited pre-exec mask or pending set.")
    if expected:
        signal_verified(child.owner, number)
        require(_proc_signals(child.owner, end=end) == (bit, bit), "The exact supplied signal did not become pending.")
    require(os.write(stdin.fileno(), b"G") == 1, "The exact process did not receive its exec permission.")
    return {"signal": int(number), "blocked": expected, "pendingAtExec": expected}


def _signal_environment(controller: WholeCheckController) -> dict[str, str]:
    home = controller.workspace.fixture_root / "signal-home"
    home.mkdir(mode=0o700)
    tools = home / "bin"
    tools.mkdir(mode=0o700)
    return without_authority({"HOME": str(home), "PATH": str(tools), "LC_ALL": "C"})


def _retire_failed_child(child: OwnedChild) -> None:
    # EOF refuses an unstarted exec. An already-execed local command may finish
    # after the caller releases its private barrier; a timeout remains failure.
    stdin = child.process.stdin
    if stdin is not None and not stdin.closed:
        stdin.close()
    try:
        child.wait_owned(seconds=10)
    finally:
        for stream in (child.process.stdout, child.process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def _collect(controller: WholeCheckController, child: OwnedChild, *, end: float, name: str) -> Captured:
    captured = controller._collect_owned(child, _until(end))
    controller.evidence.write_bytes(name + "-stdout.bin", captured.stdout)
    controller.evidence.write_bytes(name + "-stderr.bin", captured.stderr)
    require(child.reaped and not child.owner.live(), "The observed outer process was not actually reaped.")
    return captured


def _named_normal_entry(controller: WholeCheckController, authority: Authority, legacy_build: str | None,
                        legacy_entry_sha256: str | None) -> tuple[Path, str, Object]:
    scope = controller.scope
    require(verify_gate(scope.registry).digest == scope.gate.digest, "The emitted route lacks its original installed gate.")
    route = next(row for row in scope.gate.document["components"] if row["component"] == COMPONENT)
    launcher = Path(route["launcher"])
    require(launcher.parent == controller.workspace.bin
            and launcher.resolve(strict=True) == launcher
            and read_image(launcher, private=False).sha256 == route["launcherSha256"],
            "The real emitted launcher differs from the sealed gate route.")
    if legacy_build is None:
        producer = scope.producer(COMPONENT)
        require(registered(scope.registry, COMPONENT, producer.build) == producer,
                "The qualified producer is not available through real named launch.")
        verify_acceptance(authority, producer)
        return launcher, producer.build, {"kind": "qualified", "payload": producer.digest}
    folder = scope.registry / COMPONENT / legacy_build
    require(folder.parent == scope.registry / COMPONENT and folder.resolve(strict=True) == folder
            and not os.path.lexists(folder / SUBTREE), "The legacy Build is not the genuine format-one layout.")
    image = read_image(folder / "build.json", private=False)
    record = document(image.raw)
    require(valid_record(record, COMPONENT, legacy_build) and named_runnable(str(scope.registry), record)
            and record["source"]["commit"] == LEGACY_SOURCE and record["source"]["uncommittedChanges"] is False,
            "The real numbered legacy Build differs from the pinned clean source.")
    entry = executable_entry(str(folder), record["entry"])
    require(entry is not None and legacy_entry_sha256 is not None, "The legacy executable has no independently pinned bytes.")
    assert entry is not None
    executable = read_image(Path(entry), private=False)
    require(executable.sha256 == legacy_entry_sha256, "The exact legacy executable changed.")
    return launcher, legacy_build, {"kind": "legacy", "build": image.evidence(), "entry": executable.evidence()}


def normal_inherited_signal(controller: WholeCheckController, case: SignalCase, *,
                            legacy_build: str | None = None, legacy_entry_sha256: str | None = None) -> Object:
    """Run one exact legacy or qualified normal route with its inherited signal state."""
    controller.workspace.verify(controller.evidence)
    controller.scope.recheck()
    authority = Authority(controller.workspace.registry, COMPONENT)
    launcher, build, selection = _named_normal_entry(controller, authority, legacy_build, legacy_entry_sha256)
    state = controller.workspace.fixture_root / "signal-state"
    require(not os.path.lexists(state), "Normal signal cases use a fresh private State.")
    argv = [str(launcher), "-v", build, "--state-dir", str(state), "info"]
    env = _signal_environment(controller)
    end = time.monotonic() + 60
    child = _prepare_child(controller, case, argv, env)
    try:
        with authority.mutex(seconds=_until(end)):
            require(authority.read("control")["phase"] == "normal", "The normal route must start open.")
            initial = _start_exec(child, case, end=end)
            lock_path = authority.folder / "control.lock"
            _wait_control_open(child.owner, lock_path, end=end)
            blocked, pending = _proc_signals(child.owner, end=end)
            require((blocked, pending) == (initial["blocked"], initial["pendingAtExec"]),
                    "Normal dispatch changed the caller's blocked or pending set.")
            if case == "ignored-int":
                signal_verified(child.owner, signal.SIGINT)
                require(_proc_signals(child.owner, end=end) == (0, 0),
                        "SIGINT was neither ignored nor retained in the expected normal envelope.")
        captured = _collect(controller, child, end=end, name="normal-signal")
    except BaseException as error:
        try:
            _retire_failed_child(child)
        except (OSError, subprocess.TimeoutExpired) as cleanup:
            error.add_note(f"Owned normal signal cleanup remains unresolved: {cleanup}")
        raise
    require(captured.returncode == 0 and not captured.stderr, "The real normal invocation did not survive.")
    response = document(captured.stdout)
    require(response.get("build") == build and response.get("stateDirectory") == str(state),
            "The real normal command selected a different Build or State.")
    with authority.mutex(seconds=_until(end)):
        if legacy_build is not None:
            taint = authority.read("taint")
            require(taint["reason"] == "legacy", "Legacy exec did not retain its real custody obligation.")
            custody: Object = {"legacyTaint": taint}
        else:
            graph = reconcile(authority, persist_unknown=False, candidate=controller.scope)
            roots = [row for row in graph.writers if row["parent"] is None and row["phase"] == "terminal"
                     and {key: row[key] for key in ("pid", "startedAt")} == child.owner.object()]
            require(graph.resolved and len(roots) == 1, "The successful qualified launch lacks its own terminal root.")
            mains = [row for row in graph.handoffs if row["parent"] == roots[0]["writer"]
                     and row["invocation"] == roots[0]["invocation"] and row["role"] == "main"
                     and row["phase"] == "accepted"]
            require(len(mains) == 1, "The qualified signal case did not reach the actual MAIN transfer.")
            custody = {"terminalRoot": roots[0], "acceptedMain": mains[0]}
    result = {"case": case, "argv": argv, "selection": selection, "preExec": initial, "blockedAtControl": blocked,
              "pendingAtControl": pending, "provider": child.owner.object(), "reapedExit": captured.returncode,
              "response": response, "custody": custody}
    controller.evidence.write("normal-inherited-signal.json", result)
    return result


def administrative_pending_signal(controller: WholeCheckController,
                                  case: Literal["pending-int", "pending-term"]) -> Object:
    """Compare an actual read-only status invocation with the same pending-signal route."""
    controller.workspace.verify(controller.evidence)
    controller.scope.recheck()
    scope = controller.scope
    authority = Authority(scope.registry, COMPONENT)
    env = _signal_environment(controller)
    argv = [*scope.gate.provider.prefix, "driver-state", "status", "--registry-dir", str(scope.registry),
            "--component", COMPONENT, "--session", str(uuid.uuid4())]
    end = time.monotonic() + 60
    before = tree_inventory(authority.folder)
    baseline = OwnedChild(argv, environment=env, cwd=controller.workspace.fixture_root)
    control = _collect(controller, baseline, end=end, name="administrative-control")
    require(control.returncode == 0 and not control.stderr and document(control.stdout).get("phase") == "normal"
            and tree_inventory(authority.folder) == before, "The original read-only administrative control failed.")
    child = _prepare_child(controller, case, argv, env)
    try:
        initial = _start_exec(child, case, end=end)
        captured = _collect(controller, child, end=end, name="administrative-signal")
    except BaseException as error:
        try:
            _retire_failed_child(child)
        except (OSError, subprocess.TimeoutExpired) as cleanup:
            error.add_note(f"Owned administrative signal cleanup remains unresolved: {cleanup}")
        raise
    require(captured.returncode == -initial["signal"] and not captured.stdout and not captured.stderr
            and tree_inventory(authority.folder) == before,
            "The actual pending signal did not terminate the administrative command before its handler changed authority.")
    scope.recheck()
    result = {"case": case, "argv": argv, "preExec": initial, "control": document(control.stdout),
              "provider": child.owner.object(), "reapedSignal": -captured.returncode, "authorityPreserved": True}
    controller.evidence.write("administrative-pending-signal.json", result)
    return result


PTY_JOB = r"""import json
import os
import signal
import subprocess
import sys
import termios

role, *argv = sys.argv[1:]
assert role in ("foreground", "background")
assert os.tcgetpgrp(0) == os.getpgrp()
attrs = termios.tcgetattr(0)
attrs[1] &= ~termios.OPOST
attrs[3] = (attrs[3] | termios.ICANON) & ~(termios.ECHO | termios.TOSTOP)
attrs[6][termios.VEOF] = b"\x04"
termios.tcsetattr(0, termios.TCSANOW, attrs)

reader, writer = os.pipe()
barrier = (
    "import os,sys\n"
    "fd=int(sys.argv[1]); argv=sys.argv[2:]\n"
    "if os.read(fd,1)!=b'G': raise SystemExit(125)\n"
    "os.close(fd); os.execv(argv[0],argv)\n"
)
try:
    try:
        job = subprocess.Popen([sys.executable, "-ISB", "-c", barrier, str(reader), *argv],
                               pass_fds=(reader,), process_group=0)
    finally:
        os.close(reader)

    def promote(*_):
        assert job.poll() is None and os.getpgid(job.pid) == job.pid
        old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTTOU})
        try:
            os.tcsetpgrp(0, job.pid)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, old)

    signal.signal(signal.SIGUSR1, promote)
    if role == "foreground":
        promote()
    print(json.dumps({"job": job.pid, "role": role}), flush=True)
    assert os.write(writer, b"G") == 1
finally:
    os.close(writer)

status = job.wait(timeout=48)
print(json.dumps({"job": job.pid, "status": status}), flush=True)
print("@ABR38-done", flush=True)
"""


def _terminal_state(process: ExactProcess, parent: int, *, end: float) -> tuple[int, int, str]:
    require(process.live(parent=parent), "The observed PTY process identity changed.")
    result = subprocess.run(["/bin/ps", "-p", str(process.pid), "-o", "pid=,ppid=,pgid=,tpgid=,stat="],
                            stdin=subprocess.DEVNULL, capture_output=True, env={"LC_ALL": "C"},
                            timeout=min(2, _until(end)), check=False)
    values = result.stdout.split()
    require(result.returncode == 0 and not result.stderr and len(values) == 5
            and values[:2] == [str(process.pid).encode(), str(parent).encode()]
            and process.live(parent=parent), "The kernel PTY observation lacks the exact process.")
    return int(values[2]), int(values[3]), values[4].decode("ascii")


def _wait_terminal(process: ExactProcess, parent: int, foreground: int, *, stopped: bool | None, end: float) -> Object:
    while True:
        group, selected, status = _terminal_state(process, parent, end=end)
        if selected == foreground and (stopped is None or status.startswith("T") == stopped):
            require(group == process.pid, "The PTY job did not retain its own exact process group.")
            return {"process": process.object(), "group": group, "foreground": selected, "status": status}
        time.sleep(min(0.025, _until(end)))


def _active_launcher_main(controller: WholeCheckController, authority: Authority, job: ExactProcess,
                          parent: int, *, end: float) -> ExactProcess:
    while job.live(parent=parent):
        with authority.mutex(seconds=_until(end)):
            graph = reconcile(authority, persist_unknown=False, candidate=controller.scope)
            roots = [row for row in graph.writers if row["parent"] is None and row["phase"] == "terminal"
                     and {name: row[name] for name in ("pid", "startedAt")} == job.object()]
            if roots:
                root = roots[0]
                handoffs = [row for row in graph.handoffs if row["invocation"] == root["invocation"]
                            and row["parent"] == root["writer"] and row["role"] == "main" and row["phase"] == "accepted"]
                if handoffs:
                    require(not graph.unknown and len(roots) == len(handoffs) == 1,
                            "The launcher has ambiguous terminal authority.")
                    rows = [row for row in graph.writers if row["invocation"] == root["invocation"]
                            and row["writer"] == handoffs[0]["child"] and row["phase"] == "active"]
                    require(len(rows) == 1, "The accepted MAIN does not have its own active row.")
                    main = ExactProcess.read({name: rows[0][name] for name in ("pid", "startedAt")})
                    require(main.live(parent=job.pid), "The actual MAIN is not a live child of its launcher.")
                    return main
        time.sleep(min(0.025, _until(end)))
    raise RuntimeError("The exact launcher exited before its MAIN could be observed.")


def qualified_pty_job(controller: WholeCheckController, role: Literal["foreground", "background"]) -> Object:
    """Exercise the real job transitions and close stdin without a vendor request."""
    controller.workspace.verify(controller.evidence)
    controller.scope.recheck()
    authority = Authority(controller.workspace.registry, COMPONENT)
    launcher, build, selection = _named_normal_entry(controller, authority, None, None)
    state = controller.workspace.fixture_root / "pty-state"
    require(not os.path.lexists(state), "The PTY job needs its own fresh State.")
    argv = [str(launcher), "-v", build, "--state-dir", str(state), "run", "--request", "-"]
    interpreter, isolation, _ = controller.scope.gate.provider.prefix
    end = time.monotonic() + 45
    pty = OwnedPTY([interpreter, isolation, "-c", PTY_JOB, role, *argv],
                   environment=_signal_environment(controller), cwd=controller.workspace.fixture_root)
    job = main = None
    try:
        ready = document(pty.read_until(b"\n", seconds=_until(end)))
        require(ready.get("role") == role and type(ready.get("job")) is int, "Invalid PTY supervisor start record.")
        job = ExactProcess.read(process_identity(ready["job"]))
        main = _active_launcher_main(controller, authority, job, pty.owner.pid, end=end)
        foreground = main.pid if role == "foreground" else pty.owner.pid
        initial = _wait_terminal(main, job.pid, foreground, stopped=None if role == "background" else False, end=end)
        if not initial["status"].startswith("T"):
            signal_verified(main, signal.SIGSTOP)
        released = job.pid if role == "foreground" else pty.owner.pid
        stopped_main = _wait_terminal(main, job.pid, released, stopped=True, end=end)
        stopped_job = _wait_terminal(job, pty.owner.pid, released, stopped=True, end=end)
        if role == "background":
            pty.signal(signal.SIGUSR1)
            _wait_terminal(job, pty.owner.pid, job.pid, stopped=True, end=end)
        signal_verified(job, signal.SIGCONT)
        resumed = _wait_terminal(main, job.pid, main.pid, stopped=False, end=end)
        # A nonobject JSON request or canonical terminal EOF both fail before
        # account inspection or a vendor call, with different public errors.
        pty.write(b"[]\n" if role == "foreground" else b"\x04")
        output = pty.read_until(b"\n@ABR38-done\n", seconds=_until(end))
        controller.evidence.write_bytes("pty-job-output.bin", output)
        require(pty.reap(seconds=_until(end)) == 0 and not job.live() and not main.live(),
                "The exact supervisor or its job did not terminate and settle.")
        records = output.splitlines()
        require(len(records) == 3 and records[-1] == b"@ABR38-done", "Unexpected output on the real PTY.")
        event, exit_record = map(document, records[:2])
        message = "The request must be a JSON object." if role == "foreground" else "The request could not be read as JSON."
        require(exit_record == {"job": job.pid, "status": 1} and event.get("type") == "finished"
                and event.get("outcome") == "failed"
                and event.get("error") == {"code": "invalid_input", "message": message, "retryable": False},
                "The real terminal input or EOF did not propagate through the launcher to its Driver.")
        controller.require_finished_graph(COMPONENT)
        result = {"case": role, "argv": argv, "selection": selection, "initial": initial, "stoppedMain": stopped_main,
                  "stoppedLauncher": stopped_job, "resumed": resumed, "event": event, "launcherExit": exit_record}
        controller.evidence.write("pty-job.json", result)
        return result
    except BaseException as error:
        if not pty.reaped:
            try:
                if job is not None and job.live(parent=pty.owner.pid):
                    signal_verified(job, signal.SIGCONT)
                    signal_verified(job, signal.SIGTERM)
                if main is not None and job is not None and main.live(parent=job.pid):
                    signal_verified(main, signal.SIGCONT)
            except (OSError, ValueError, RuntimeError) as cleanup:
                error.add_note(f"Owned PTY signal cleanup remains unresolved: {cleanup}")
            try:
                pty.close()
                pty.reap(seconds=5)
            except (OSError, subprocess.TimeoutExpired) as cleanup:
                error.add_note(f"Owned PTY shutdown remains unresolved: {cleanup}")
        raise
    finally:
        pty.close()


def non_driver_launcher_compatibility(fixture: Fixture, *, default_build: str, named_build: str) -> Object:
    """Use the existing disposable sample Build program through its real launcher."""
    require(fixture.component == "sample" and default_build != named_build,
            "The non-Driver control requires two distinct actual sample Builds.")
    scope = Path(fixture.home)
    launcher = Path(fixture.bin) / fixture.component
    original_launcher = read_image(launcher, private=False)
    default = fixture.launch("observe-default", marker="default environment")
    named = fixture.launch("-v", named_build, "observe-named", marker="named environment")
    for call, build, argument, marker in (
        (default, default_build, "observe-default", "default environment"),
        (named, named_build, "observe-named", "named environment"),
    ):
        response = document(call.stdout)
        require(call.returncode == 0 and not call.stderr and response.get("build") == build
                and response.get("args") == [argument] and response.get("cwd") == str(scope)
                and response.get("marker") == marker, "The non-Driver route changed selection, argv, cwd or environment.")
    data = bytes(range(256)) * 4096
    with tempfile.TemporaryFile(dir=fixture.home) as stdin:
        stdin.write(data)
        stdin.seek(0)
        captured, padding, _ = _output_under_pressure([str(launcher), "-v", named_build, "--echo"],
                                                      stdin=stdin, cwd=scope, environment=fixture.env(),
                                                      max_output=len(data))
    require(captured.returncode == 0 and captured.stderr == b"diagnostic\n" and captured.stdout == data,
            "The non-Driver launcher lost bytes, EOF, diagnostics or exit status under output backpressure.")
    observation = {"prefilledBytes": padding, "inputSha256": digest(data), "outputSha256": digest(captured.stdout)}
    exit_status = fixture.launch("-v", named_build, "--exit", "37")
    require(exit_status.returncode == 37 and not exit_status.stdout and not exit_status.stderr
            and read_image(launcher, private=False) == original_launcher,
            "The real non-Driver launcher changed exit status or the original launcher bytes.")
    return {"launcher": original_launcher.evidence(), "default": document(default.stdout),
            "named": document(named.stdout), "streams": observation, "exitStatus": exit_status.returncode}


def qualified_stdout_backpressure(controller: WholeCheckController) -> Object:
    """Keep stdout saturated until the exact admitted MAIN consumes its input."""
    controller.workspace.verify(controller.evidence)
    controller.scope.recheck()
    authority = Authority(controller.workspace.registry, COMPONENT)
    launcher, build, selection = _named_normal_entry(controller, authority, None, None)
    state = controller.workspace.fixture_root / "backpressure-state"
    require(not os.path.lexists(state), "The output-backpressure trial needs fresh State.")
    argv = [str(launcher), "-v", build, "--state-dir", str(state), "run", "--request", "-"]
    reader, writer = os.pipe()
    try:
        try:
            require(os.write(writer, b"[]\n") == 3, "The real stdin pipe did not receive its complete input.")
        finally:
            os.close(writer)

        def queued_input() -> int:
            return int(struct.unpack("i", fcntl.ioctl(reader, termios.FIONREAD, struct.pack("i", 0)))[0])

        require(queued_input() == 3, "The original stdin beforeimage is missing.")

        def observe(provider: ExactProcess, end: float) -> Object:
            main = _active_launcher_main(controller, authority, provider, os.getpid(), end=end)
            while queued_input() != 0:
                require(main.live(parent=provider.pid), "MAIN settled before consuming the pipe input.")
                time.sleep(min(0.025, _until(end)))
            require(main.live(parent=provider.pid), "The real MAIN exited before the stdout drain began.")
            return {"provider": provider.object(), "main": main.object(), "stdinBytesConsumed": 3}

        captured, padding, before_drain = _output_under_pressure(argv, stdin=reader,
            cwd=controller.workspace.fixture_root, environment=_signal_environment(controller),
            max_output=8192, observe=observe)
    finally:
        os.close(reader)
    controller.evidence.write_bytes("qualified-backpressure-stdout.bin", captured.stdout)
    controller.evidence.write_bytes("qualified-backpressure-stderr.bin", captured.stderr)
    event = document(captured.stdout)
    require(captured.returncode == 1 and not captured.stderr and event.get("type") == "finished"
            and event.get("outcome") == "failed"
            and event.get("error") == {"code": "invalid_input", "message": "The request must be a JSON object.",
                                      "retryable": False},
            "The qualified provider lost the Driver's finished event or actual exit under output backpressure.")
    controller.require_finished_graph(COMPONENT)
    result = {"argv": argv, "selection": selection, "beforeDrain": before_drain, "prefilledBytes": padding,
              "event": event, "reapedExit": captured.returncode}
    controller.evidence.write("qualified-backpressure.json", result)
    return result


def _output_under_pressure(argv: list[str], *, stdin: IO[bytes] | int, cwd: Path,
                           environment: dict[str, str], max_output: int,
                           observe: Callable[[ExactProcess, float], Object] | None = None
                           ) -> tuple[Captured, int, Object | None]:
    """Exercise the actual launcher with an independently saturated output pipe."""
    end = time.monotonic() + 40
    reader, writer = os.pipe()
    child: subprocess.Popen[bytes] | None = None
    failure: BaseException | None = None
    try:
        os.set_blocking(writer, False)
        padding = 0
        chunk = 4096
        while padding < 1024 * 1024:
            _until(end)
            try:
                padding += os.write(writer, b"P" * chunk)
            except BlockingIOError:
                if chunk == 1:
                    break
                chunk = 1
        require(0 < padding < 1024 * 1024 and not select.select([], [writer], [], 0)[1],
                "The owned output pipe did not reach its bounded nonwritable state.")
        os.set_blocking(writer, True)
        child = subprocess.Popen(argv, stdin=stdin, stdout=writer, stderr=subprocess.PIPE, env=environment, cwd=cwd)
        owner = ExactProcess.read(process_identity(child.pid))
        before = None if observe is None else observe(owner, end)
        require(owner.live(parent=os.getpid()) and not select.select([], [writer], [], 0)[1],
                "The exact launcher is not live with its externally saturated pipe.")
        os.close(writer)
        writer = -1
        output = bytearray()
        limit = padding + max_output
        while True:
            require(bool(select.select([reader], [], [], _until(end))[0]), "Timed out draining the real output pipe.")
            part = os.read(reader, min(65536, limit + 1 - len(output)))
            if not part:
                break
            output.extend(part)
            require(len(output) <= limit, "Unexpected bytes in the shared stdout stream.")
        _, stderr = child.communicate(timeout=_until(end))
        require(output.startswith(b"P" * padding) and not owner.live(), "The pipe prefix or exact outer wait changed.")
        return Captured(child.returncode, bytes(output[padding:]), stderr, owner), padding, before
    except BaseException as error:
        failure = error
        raise
    finally:
        if writer >= 0:
            os.close(writer)
        os.close(reader)
        if child is not None and child.returncode is None:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired as cleanup:
                assert failure is not None
                failure.add_note(f"Owned output capture did not reap its child: {cleanup}")
            finally:
                if child.stderr is not None:
                    child.stderr.close()
