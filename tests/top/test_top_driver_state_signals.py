"""Prospective isolated launcher signal cases for ABR-38.

Each case uses its own real registered disposable Build cohort. Review and
integration precede execution. Importing this module launches no processes.
"""

from __future__ import annotations

import os
import select
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Literal

from driver_identity_qualification import WholeCheckController, require

from arbol_builds.driver_admission import Authority, reconcile, without_authority
from arbol_builds.driver_payload import SUBTREE, registered, verify_acceptance, verify_gate
from arbol_builds.launcher import executable_entry, named_runnable, valid_record
from top.driver_state_support import (
    Captured,
    ExactProcess,
    Object,
    OwnedChild,
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
