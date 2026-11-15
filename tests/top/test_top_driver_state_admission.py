"""Prospective real admission cases; no registration, CLI or execution on import.

The later admitted outer check supplies a genuinely new registered subject per
case.  This is not a path/selector exposed to Driver callers.  Inputs are actual
immutable packages and exclusively owned disposable state, never owner profiles.
The external observer holds no subject Session/SH.  Full-body admission is pending.
"""

from __future__ import annotations

import os
import signal
import struct
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from unittest.mock import patch

from driver_identity_qualification import Baseline, Workspace, require

import arbol_builds.driver_process as provider_process
from arbol_builds.driver_admission import (
    Authority,
    Refusal,
    canonical,
    normal_control,
    publish,
    read,
    read_bytes,
    reconcile,
    sha256,
    token,
    without_authority,
    writer_path,
)
from arbol_builds.driver_process import Frames, Guardian, process_identity
from top.driver_state_support import (
    EvidenceRecorder,
    ExactProcess,
    Object,
    ObservationFailed,
    OwnedChild,
    digest,
    document,
    physical_owned,
    signal_verified,
    tree_inventory,
)

COMPONENT = "arbol-codex-driver"
ContextFault = Literal["context-hash", "registry", "epoch", "own-parent", "entry", "payload", "acceptance", "nonce"]
GoFault = Literal["nonce", "challenge", "context-hash", "replay"]
CancellationWindow = Literal["offer", "ready", "go", "started"]
_NEGATIVE_SERIALIZATION = threading.Lock()


@dataclass(frozen=True)
class AdmissionSubject:
    """Only a later admitted static fixture constructor can supply these objects."""

    workspace: Workspace
    baseline: Baseline
    evidence: EvidenceRecorder
    environment: Mapping[str, str]

    @property
    def authority(self) -> Authority:
        return Authority(self.workspace.registry, COMPONENT)

    def verify_unused(self) -> None:
        self.workspace.verify(self.evidence)
        self.baseline.scopes[COMPONENT].recheck()
        require(self.baseline.scopes[COMPONENT].registry == self.workspace.registry,
                "Subject is not this real registered candidate scope.")
        # Source identity alone cannot authorize a provider from another package.
        provider = self.baseline.scopes[COMPONENT].gate.provider
        require(Path(provider_process.__file__).resolve().is_relative_to(provider.root),
                "The real parent implementation must come from the exact provider payload.")
        with self.authority.mutex():
            control = normal_control(self.authority, candidate=self.baseline.scopes[COMPONENT])
            custody = reconcile(self.authority, persist_unknown=False, candidate=self.baseline.scopes[COMPONENT])
            require(control["epoch"] == self.baseline.epochs[COMPONENT] and custody.resolved
                    and not custody.writers and not custody.handoffs,
                    "A failure case cannot reuse a used, tainted or unknown subject.")
        require(not os.path.lexists(self.state), "Each actual identity command needs a fresh owned State.")
        physical_owned(self.workspace.fixture_root, directory=True)

    @property
    def state(self) -> Path:
        return self.workspace.fixture_root / "admission-state"

    def argv(self) -> list[str]:
        # This signed-out local proof command does not consult/discover native auth.
        return ["--state-dir", str(self.state), "subscriptions", "identity", "chatgpt"]

    def guardian(self) -> Guardian:
        self.verify_unused()
        scope = self.baseline.scopes[COMPONENT]
        return Guardian.admit(self.authority, scope.producer(COMPONENT), candidate=scope)

    def snapshot(self) -> Object:
        return {"stateAbsent": not os.path.lexists(self.state),
                "fixture": tree_inventory(self.workspace.fixture_root)}

    def closed_observation(self) -> Object:
        """A failed protocol stays unknown/closed; no sampling, drain or reset."""
        with self.authority.mutex():
            custody = reconcile(self.authority, candidate=self.baseline.scopes[COMPONENT])
            require(custody.unknown or os.path.lexists(self.authority.folder / "taint.json"),
                    "Uncertain failed transfer was not retained.")
            try:
                normal_control(self.authority, candidate=self.baseline.scopes[COMPONENT])
            except Refusal:
                pass
            else:
                raise ObservationFailed("A failed transfer still admits ordinary work.")
            return {"unknown": custody.unknown, "active": custody.active, "pending": custody.pending,
                    "control": self.authority.read("control"),
                    "taint": read(self.authority.folder / "taint.json")}


@dataclass
class DirectChild:
    """Actual Guardian child handle, not a PID learned from output/EOF."""

    process: subprocess.Popen[bytes] | None = None
    identity: ExactProcess | None = None
    reaped: bool = False

    def prepared(self, child: subprocess.Popen[bytes], identity: Object) -> None:
        require(self.process is None, "A case cannot replace its independently observed child.")
        owner = ExactProcess.read(identity)
        require(owner.pid == child.pid and owner.live(parent=os.getpid()), "Actual child birth/parent differs.")
        self.process, self.identity = child, owner

    def wait(self) -> int:
        require(self.process is not None and self.identity is not None, "No real spawned child was observed.")
        assert self.process is not None
        result = self.process.wait(timeout=25)
        self.reaped = True
        return result

    def cleanup(self) -> None:
        if self.process is None or self.reaped:
            return
        if self.process.poll() is None:
            assert self.identity is not None
            # An exact owned PID only; no group, terminal inference or guessed kill.
            signal_verified(self.identity, signal.SIGCONT)
            signal_verified(self.identity, signal.SIGTERM)
        self.wait()


@contextmanager
def parent_wire(send: Callable[[Frames, Object], None], receive: Callable[[Frames], Object]) -> Iterator[None]:
    """Instrument the real parent wire, never return synthetic peer success.

    The independent immutable child still performs its own actual parsing,
    descriptor/parent/lease/State admission.  No child code is patched.  The
    original receive is always used by callers.  Exact finite faults below are
    testing triggers, not production algorithms or a generic callable dispatcher.
    """
    require(threading.current_thread() is threading.main_thread()
            and not any(t.is_alive() for t in threading.enumerate() if t is not threading.current_thread()),
            "Wire instrumentation requires an isolated single-threaded external case controller.")
    with _NEGATIVE_SERIALIZATION, patch.object(Frames, "send", send), patch.object(Frames, "receive", receive):
        yield


def wrong_context_refuses_before_ready(subject: AdmissionSubject, fault: ContextFault) -> None:
    """Semantic mutations rebind the offered hash, so a hash mismatch cannot mask them."""
    require(fault in ("context-hash", "registry", "epoch", "own-parent", "entry", "payload", "acceptance", "nonce"),
            "Unknown fixed context fault.")
    guardian = subject.guardian()
    child = DirectChild()
    before = subject.snapshot()
    observed: list[Object] = []
    sent = False
    original_send, original_receive = Frames.send, Frames.receive

    def send(frames: Frames, value: Object) -> None:
        nonlocal sent
        require(value["type"] == "offer" and not sent, "Invalid context-case parent wire phase.")
        sent = True
        assert guardian.handoff is not None
        path = subject.authority.folder / "handoffs" / (guardian.handoff + ".context.json")
        context = read(path)
        changed = dict(context)
        if fault == "context-hash":
            offered = {**value, "contextSha256": "0" * 64}
        else:
            if fault == "registry":
                changed["registry"] = str(subject.workspace.bin)
            elif fault == "epoch":
                changed["epoch"] = token()
            elif fault == "own-parent":
                changed["parent"] = {"writer": context["parent"]["writer"], **process_identity(os.getppid())}
            elif fault == "entry":
                changed["entry"] = "scripts/check_build.py"
            elif fault == "payload":
                changed["payloadSha256"] = "0" * 64
            elif fault == "acceptance":
                changed["acceptanceSha256"] = "0" * 64
            elif fault == "nonce":
                changed["nonce"] = token()
            changed_hash = sha256(canonical(changed))
            with subject.authority.mutex():
                publish(path, changed)
                handoff_path = subject.authority.folder / "handoffs" / (guardian.handoff + ".json")
                pending = read(handoff_path)
                # Rebind the hash, preserving the genuinely minted pending
                # identity. A semantic mismatch cannot be masked by raw hashing.
                pending = {**pending, "contextSha256": changed_hash}
                publish(handoff_path, pending)
            offered = {**value, "contextSha256": changed_hash}
        subject.evidence.write("offered-mutation.json", {"fault": fault, "original": context,
                                                        "offeredContext": changed, "offer": offered})
        original_send(frames, offered)

    def receive(frames: Frames) -> Object:
        value = original_receive(frames)
        observed.append(value)
        # Parent-side original digest checks must not hide erroneous child ready.
        raise ObservationFailed("Child sent a peer frame for an invalid semantic context.")

    refused = False
    try:
        with parent_wire(send, receive):
            try:
                guardian.spawn_main(subject.argv(), environment=without_authority(dict(subject.environment)),
                                    prepared=child.prepared)
            except Refusal:
                refused = True
        require(refused and sent and not observed, "No exact actual child-side refusal was observed.")
        require(child.wait() != 0, "Invalid admission exited successfully.")
        require(subject.snapshot() == before, "Invalid admission reached State before refusing.")
        with subject.authority.mutex():
            own = subject.authority.folder / "writers" / guardian.invocation
            require({p.name for p in own.iterdir()} == {guardian.writer + ".json"},
                    "Invalid context registered a child metadata writer.")
        subject.evidence.write("context-refusal.json", {"fault": fault, "child": child.identity.object()
                               if child.identity is not None else None, "reaped": child.reaped,
                               "before": before, "after": subject.snapshot(), "custody": subject.closed_observation()})
    finally:
        child.cleanup()


def wrong_go_or_replay_refuses_before_state(subject: AdmissionSubject, fault: GoFault) -> None:
    """A real ready and persisted child writer precede the single corrupted go.

    Parent SH is still held here; EX contention alone cannot prove child SH.
    The distinct positive begin case probes EX only after real parent release.
    """
    require(fault in ("nonce", "challenge", "context-hash", "replay"), "Unknown fixed go fault.")
    guardian, child = subject.guardian(), DirectChild()
    before = subject.snapshot()
    ready: Object | None = None
    started: list[Object] = []
    altered = False
    original_send, original_receive = Frames.send, Frames.receive

    def send(frames: Frames, value: Object) -> None:
        nonlocal altered
        if value["type"] == "offer":
            original_send(frames, value)
            return
        require(value["type"] == "go" and ready is not None and not altered, "Wrong go mutation phase.")
        altered = True
        with subject.authority.mutex():
            row = read_writer_actual(subject, guardian)
            require(row["phase"] == "active", "No actual independent child writer preceded go.")
        changed = dict(value)
        if fault == "nonce":
            changed["nonce"] = token()
        elif fault == "challenge":
            changed["challenge"] = token()
        elif fault == "context-hash":
            changed["contextSha256"] = "0" * 64
        if fault == "replay":
            # Both complete originals are queued in one write; no scheduler gap
            # between separate sends can turn a replay test into an ordinary go.
            raw = canonical(value)
            frames._timeout()
            frames.socket.sendall((struct.pack("!I", len(raw)) + raw) * 2)
        else:
            original_send(frames, changed)
        subject.evidence.write("go-mutation.json", {"fault": fault, "ready": ready, "go": changed})

    def receive(frames: Frames) -> Object:
        nonlocal ready
        value = original_receive(frames)
        if ready is None:
            require(value["type"] == "ready", "Actual child did not first send ready.")
            ready = value
        else:
            started.append(value)
        return value

    try:
        refused = False
        with parent_wire(send, receive):
            try:
                guardian.spawn_main(subject.argv(), environment=without_authority(dict(subject.environment)),
                                    prepared=child.prepared)
            except Refusal:
                refused = True
        require(ready is not None and altered, "The intended real ready/go boundary was not reached.")
        require(child.wait() != 0, "Corrupted/replayed go did not fail in the real child.")
        require(refused or fault == "replay", "Wrong go was accepted by the real parent.")
        require(not started or (fault == "replay" and len(started) == 1 and started[0]["type"] == "started"),
                "A bad challenge/nonce/context advanced to started.")
        require(subject.snapshot() == before, "Corrupted/replayed handshake reached State.")
        subject.evidence.write("go-refusal.json", {"fault": fault, "ready": ready, "started": started,
                                                  "parentRefused": refused, "reaped": child.reaped,
                                                  "custody": subject.closed_observation()})
    finally:
        child.cleanup()



def cancel_at_real_wire_boundary(subject: AdmissionSubject, window: CancellationWindow) -> None:
    """Cancel a verified real child at one literal observed transfer boundary.

    This is SIGTERM cancellation, not parent death or a fabricated terminal.
    A started-window scheduling miss fails rather than becoming a later window.
    """
    require(window in ("offer", "ready", "go", "started"), "Unknown finite cancellation window.")
    guardian, child = subject.guardian(), DirectChild()
    before = subject.snapshot()
    original_send, original_receive = Frames.send, Frames.receive
    triggered = False
    peer_frames: list[Object] = []

    def cancel(phase: str) -> None:
        nonlocal triggered
        if phase != window:
            return
        require(not triggered and child.identity is not None and child.process is not None,
                "Cancellation target/window is not the actual prepared child.")
        triggered = True
        assert child.identity is not None and child.process is not None
        # STOP makes the externally witnessed before-State condition stable.
        signal_verified(child.identity, signal.SIGSTOP)
        deadline = time.monotonic() + 10
        while True:
            stopped, status = os.waitpid(child.process.pid, os.WUNTRACED | os.WNOHANG)
            if stopped:
                require(stopped == child.process.pid and os.WIFSTOPPED(status), "Real cancellation child exited before STOP.")
                break
            require(time.monotonic() < deadline, "Cancellation STOP was not acknowledged.")
            time.sleep(.005)
        require(subject.snapshot() == before, "Missed cancellation boundary before actual State access.")
        signal_verified(child.identity, signal.SIGTERM)
        signal_verified(child.identity, signal.SIGCONT)
        subject.evidence.write("cancellation-trigger.json", {"window": window, "process": child.identity.object(),
                                                            "signal": int(signal.SIGTERM), "before": before})

    def send(frames: Frames, value: Object) -> None:
        cancel(str(value["type"]))
        original_send(frames, value)

    def receive(frames: Frames) -> Object:
        value = original_receive(frames)
        peer_frames.append(value)
        cancel(str(value["type"]))
        return value

    try:
        failure: str | None = None
        with parent_wire(send, receive):
            try:
                guardian.spawn_main(subject.argv(), environment=without_authority(dict(subject.environment)),
                                    prepared=child.prepared)
            except (Refusal, OSError) as error:
                failure = type(error).__name__
        require(triggered, "The specified real protocol cancellation boundary was not reached.")
        require(child.wait() != 0 and child.reaped, "Cancellation did not end/reap the actual child.")
        require(subject.snapshot() == before, "Cancelled admission reached State.")
        # An accepted terminal is possible only if genuinely published by the
        # product. No test writes terminal, clears taint or samples away unknown.
        with subject.authority.mutex():
            custody = reconcile(subject.authority, candidate=subject.baseline.scopes[COMPONENT])
            require(custody.unknown or (custody.resolved and all(row["phase"] == "terminal" for row in custody.writers)),
                    "Cancellation lost its pending/active obligation without real completion.")
            if custody.unknown:
                try:
                    normal_control(subject.authority, candidate=subject.baseline.scopes[COMPONENT])
                except Refusal:
                    pass
                else:
                    raise ObservationFailed("Unknown cancelled transfer still admits normal work.")
        subject.evidence.write("cancellation-outcome.json", {"window": window, "peerFrames": peer_frames,
                                "actualParentFailure": failure, "transferred": guardian.transferred,
                                "reaped": child.reaped, "unknown": custody.unknown,
                                "active": custody.active, "pending": custody.pending, "after": subject.snapshot()})
    finally:
        child.cleanup()

def read_writer_actual(subject: AdmissionSubject, guardian: Guardian) -> Object:
    require(guardian.handoff is not None, "No actual pending handoff.")
    assert guardian.handoff is not None
    handoff = read(subject.authority.folder / "handoffs" / (guardian.handoff + ".json"))
    return read(writer_path(subject.authority, guardian.invocation, handoff["child"]))


def begin_vs_independently_admitted_write(subject: AdmissionSubject) -> None:
    """STOP an actual acknowledged child before State, then begin without cancelling it.

    A missed scheduling window fails; no sleep/retry converts it into evidence.
    The later fixed actor lease-hold path can provide a stronger admitted barrier,
    but is not presumed implemented or used by this prospective source.
    """
    guardian, child = subject.guardian(), DirectChild()
    original_send, original_receive = Frames.send, Frames.receive
    session = str(uuid.uuid4())
    saw_started = False

    def receive(frames: Frames) -> Object:
        nonlocal saw_started
        value = original_receive(frames)
        if value["type"] == "started":
            require(not saw_started and child.identity is not None and child.process is not None,
                    "No exact actual started child.")
            saw_started = True
            assert child.identity is not None
            signal_verified(child.identity, signal.SIGSTOP)
            assert child.process is not None
            deadline = time.monotonic() + 10
            while True:
                stopped, status = os.waitpid(child.process.pid, os.WUNTRACED | os.WNOHANG)
                if stopped:
                    require(stopped == child.process.pid and os.WIFSTOPPED(status), "Child did not actually stop.")
                    break
                require(time.monotonic() < deadline, "Exact child STOP acknowledgement timed out.")
                time.sleep(.005)
            require(not os.path.lexists(subject.state), "Missed pre-State window; no race claim.")
        return value

    try:
        with parent_wire(original_send, receive):
            guardian.spawn_main(subject.argv(), environment=without_authority(dict(subject.environment)),
                                prepared=child.prepared)
        require(saw_started and guardian.transferred and guardian.lease < 0 and guardian.build_use < 0,
                "The real independent child was not acknowledged before parent release.")
        with subject.authority.mutex():
            try:
                descriptor = subject.authority.lease(exclusive=True)
            except BlockingIOError:
                pass
            else:
                os.close(descriptor)
                raise ObservationFailed("Parent release also released the child's independent lease.")
        scope = subject.baseline.scopes[COMPONENT]
        argv = [*scope.gate.provider.prefix, "driver-state", "begin", "--registry-dir", str(subject.workspace.registry),
                "--component", COMPONENT, "--session", session]
        begin = OwnedChild(argv, environment=without_authority(dict(subject.environment)), cwd=subject.workspace.registry)
        captured = begin.collect(seconds=30)
        require(captured.returncode == 0 and begin.reaped and document(captured.stdout)["phase"] == "draining",
                "Actual begin did not close normal admission while preserving the accepted child.")
        with subject.authority.mutex():
            require(subject.authority.read("control") == {"version": 1, "phase": "draining", "session": session,
                                                          "epoch": guardian.epoch}, "Begin rotated the admitted epoch.")
        try:
            Guardian.admit(subject.authority, guardian.payload, candidate=scope)
        except Refusal:
            pass
        else:
            raise ObservationFailed("New normal admission succeeded after begin.")
        assert child.identity is not None
        signal_verified(child.identity, signal.SIGCONT)
        require(child.wait() == 0, "Already acknowledged local identity write could not finish while draining.")
        root = document(read_bytes(subject.state / "identity.json"))
        proof = document(read_bytes(subject.state / "subscriptions/chatgpt/identity.json"))
        require(root["generation"] and proof["witness"], "The actual admitted command did not persist identity evidence.")
        with subject.authority.mutex():
            custody = reconcile(subject.authority, persist_unknown=False, candidate=scope)
            require(custody.resolved and custody.active == custody.pending == 0
                    and all(row["phase"] == "terminal" for row in custody.writers), "Admitted write did not really finish.")
            descriptor = subject.authority.lease(exclusive=True)
            os.close(descriptor)
        subject.evidence.write("begin-admitted-write.json", {"child": child.identity.object(), "reaped": child.reaped,
                                "begin": document(captured.stdout), "generation": root["generation"],
                                "proofSha256": digest(canonical(proof)), "state": tree_inventory(subject.state)})
    finally:
        child.cleanup()


# Late ready/go/started Guardian-parent SIGKILL remains an explicit unimplemented
# trigger until an admitted independent subject controller route is established.
# Killing this external whole-check controller/Suite, arbitrary -c/module/path
# dispatch, timing-only polling, orderly error-as-death and synthetic terminal
# metadata are not substitutes.  Step4 is not complete on these bodies alone.
