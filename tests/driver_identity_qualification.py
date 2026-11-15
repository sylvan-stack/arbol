"""Prospective ABR-38 fixture authority and external whole-check controller.

This testing module has no CLI, installed-registry mode, import-time IO or
permission to run itself.  Independent body admission precedes every use.
"""

from __future__ import annotations

import fcntl
import math
import os
import re
import stat
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from top.driver_state_support import (
    Captured,
    EvidenceRecorder,
    ExactProcess,
    Object,
    ObservationFailed,
    OwnedChild,
    digest,
    directory_identity,
    document,
    exact_fields,
    physical_owned,
    read_image,
    sync_directory,
    tree_inventory,
)
from top.driver_state_support import (
    canonical as evidence_bytes,
)

from arbol_builds.driver_admission import (
    COMPONENTS,
    Authority,
    admission_fingerprint,
    archive_terminal,
    canonical,
    lock_identity,
    normal_context,
    normal_control,
    private_directory,
    publish,
    read,
    read_bytes,
    reconcile,
    remove,
    sha256,
    token,
    valid_hash,
    valid_token,
    validate,
)
from arbol_builds.driver_payload import (
    CandidateScope,
    Payload,
    _candidate_acceptance,
    _candidate_payload,
    _gate_document,
    _registered_payload,
    request_binding,
    resolve_candidate,
)
from arbol_builds.driver_process import boot_uuid, process_identity
from arbol_builds.launcher import open_use_guard
from arbol_builds.mutation import with_mutation_lock
from arbol_builds.service import driver_launcher_source, driver_route_bytes, publish_driver_route

ALL_COMPONENTS = ("arbol", *COMPONENTS)
BUILD = re.compile(r"[1-9a-f][0-9a-f]*\Z", re.ASCII)
SELECTORS = frozenset(("driver", "build-unit", "build-native", "native-probe-death",
                       "native-temporary-run-death", "native-post-delete-death"))
MIMO_ONLY = SELECTORS - {"driver", "build-unit"}
FORBIDDEN_AUTHORITY = ("deployment.json", "recovery.json", "checkpoint.json")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ObservationFailed(reason)


def platform_identity() -> Object:
    machine = os.uname()
    require(machine.sysname == "Darwin", "Qualification requires the actual supported platform.")
    return {"system": machine.sysname, "release": machine.release, "machine": machine.machine}


@dataclass(frozen=True)
class Deadline:
    end: float

    @classmethod
    def after(cls, seconds: float) -> Deadline:
        require(math.isfinite(seconds) and 0 < seconds <= 120, "Invalid fixture transaction bound.")
        return cls(time.monotonic() + seconds)

    def remaining(self) -> float:
        remaining = self.end - time.monotonic()
        require(remaining > 0, "Fixture transaction deadline exceeded; preserve partial evidence.")
        return remaining


@dataclass(frozen=True)
class TuplePin:
    component: str
    build: str
    commit: str
    tree: str
    payload_sha256: str
    check_names: tuple[str, ...]

    def verify(self, registry: Path) -> RegisteredImage:
        require(self.component in ALL_COMPONENTS and BUILD.fullmatch(self.build) is not None,
                "Invalid fixed registered tuple selector.")
        require(valid_hash(self.payload_sha256) and bool(self.check_names)
                and len(set(self.check_names)) == len(self.check_names), "Invalid immutable tuple expectation.")
        record, payload = _registered_payload(registry, self.component, self.build)
        require(payload.digest == self.payload_sha256
                and payload.descriptor["source"] == {"commit": self.commit, "tree": self.tree},
                "Registered source or immutable payload differs.")
        raw = read_bytes(registry / self.component / self.build / "build.json")
        require(document(raw)["source"]["uncommittedChanges"] is False, "Build input is not actually clean.")
        return RegisteredImage(self, payload, record, raw)


@dataclass(frozen=True)
class RegisteredImage:
    pin: TuplePin
    payload: Payload
    record: Object
    record_bytes: bytes

    def evidence(self) -> Object:
        return {"component": self.pin.component, "build": self.pin.build, "sourceCommit": self.pin.commit,
                "sourceTree": self.pin.tree, "payloadSha256": self.payload.digest,
                "manifestSha256": self.payload.descriptor["payloadManifestSha256"],
                "recordSnapshotSha256": digest(self.record_bytes), "record": self.record,
                "entry": self.payload.descriptor["entry"], "interpreter": self.payload.descriptor["interpreter"]}


@dataclass(frozen=True)
class RecordEvolution:
    before_sha256: str
    after_sha256: str
    evidence_name: str


def verify_record_evolution(before: RegisteredImage, after: RegisteredImage, witness: RecordEvolution,
                            evidence: EvidenceRecorder) -> None:
    """Record hashes are snapshots; only independently witnessed service fields evolve."""
    require(before.pin == after.pin and before.payload == after.payload, "Immutable tuple changed between snapshots.")
    require(digest(before.record_bytes) == witness.before_sha256
            and digest(after.record_bytes) == witness.after_sha256, "Record witness does not bind both snapshots.")
    require(witness.evidence_name in evidence.files, "Missing actual service command/outcome witness.")
    trace = document(read_image(evidence.root / witness.evidence_name, limit=1024 * 1024).raw,
                     limit=1024 * 1024)
    exact_fields(trace, ("version", "kind", "component", "build", "beforeRecordSha256", "afterRecordSha256",
                         "sourceCommit", "checkOutcomes", "status", "finishedAt", "logSha256"))
    require(type(trace["version"]) is int and trace["version"] == 1 and trace["kind"] == "abr38-service-evolution"
            and trace["component"] == after.pin.component and trace["build"] == after.pin.build
            and trace["sourceCommit"] == after.pin.commit
            and trace["beforeRecordSha256"] == witness.before_sha256
            and trace["afterRecordSha256"] == witness.after_sha256
            and trace["checkOutcomes"] == after.record["checks"][len(before.record["checks"]):]
            and trace["status"] == after.record["status"]
            and trace["finishedAt"] == after.record.get("finishedAt"), "Actual service evolution trace differs.")
    log = read_image(after.payload.root.parent / "build.log", limit=32 * 1024 * 1024)
    require(trace["logSha256"] == log.sha256, "Service trace does not bind actual current command log.")
    allowed = {"checks", "status", "finishedAt", "failure"}
    require({k: v for k, v in before.record.items() if k not in allowed}
            == {k: v for k, v in after.record.items() if k not in allowed}, "Non-lifecycle record field changed.")
    old_checks, new_checks = before.record["checks"], after.record["checks"]
    require(new_checks[:len(old_checks)] == old_checks, "A prior check outcome was rewritten.")
    require(tuple(row["name"] for row in new_checks) == after.pin.check_names[:len(new_checks)],
            "Service checks do not follow the original full descriptor.")
    require(before.record["status"] == "building" and after.record["status"] in ("building", "failed", "working"),
            "Unexplained service status transition.")
    if after.record["status"] == "working":
        require(len(new_checks) == len(after.pin.check_names) and all(row["passed"] is True for row in new_checks),
                "A working record lacks its complete own checks.")
    if after.record["status"] != "building":
        require(isinstance(after.record.get("finishedAt"), str), "Final service timestamp is missing.")


@dataclass(frozen=True)
class Workspace:
    registry: Path
    bin: Path
    fixture: str
    creator: ExactProcess
    registry_identity: Object
    bin_identity: Object
    fixture_root_identity: Object
    origin_evidence_name: str

    @property
    def fixture_root(self) -> Path:
        return self.registry.parent / "fixtures"

    @classmethod
    def create(cls, parent: Path, evidence: EvidenceRecorder) -> Workspace:
        """Create an actual new owned scope before any real Build writes its catalogue."""
        physical_owned(parent, directory=True)
        fixture = token()
        root = parent / ("subject-" + fixture)
        root.mkdir(mode=0o700)
        registry, binary, fixture_root = root / "builds", root / "bin", root / "fixtures"
        registry.mkdir(mode=0o700)
        binary.mkdir(mode=0o700)
        fixture_root.mkdir(mode=0o700)
        sync_directory(root)
        sync_directory(parent)
        creator = ExactProcess.read(process_identity(os.getpid()))
        name = "workspace-origin.json"
        evidence.write(name, {"version": 1, "fixture": fixture, "registry": directory_identity(registry),
                              "bin": directory_identity(binary), "fixtureRoot": directory_identity(fixture_root),
                              "creator": creator.object(),
                              "boot": boot_uuid(), "platform": platform_identity(), "emptyAtCreation": True})
        return cls(registry, binary, fixture, creator, directory_identity(registry), directory_identity(binary),
                   directory_identity(fixture_root), name)

    def verify(self, evidence: EvidenceRecorder) -> None:
        require(valid_token(self.fixture) and self.origin_evidence_name in evidence.files,
                "Missing external new-workspace provenance.")
        origin = document(read_image(evidence.root / self.origin_evidence_name).raw)
        require(origin["fixture"] == self.fixture and origin["registry"] == self.registry_identity
                and origin["bin"] == self.bin_identity and origin["fixtureRoot"] == self.fixture_root_identity
                and origin["creator"] == self.creator.object()
                and origin["emptyAtCreation"] is True, "Workspace creation evidence differs.")
        require(directory_identity(self.registry) == self.registry_identity
                and directory_identity(self.bin) == self.bin_identity
                and directory_identity(self.fixture_root) == self.fixture_root_identity, "Workspace physical identity changed.")
        require(origin["boot"] == boot_uuid() and origin["platform"] == platform_identity(),
                "Fixture boot/platform changed; this is not a reset operation.")


@dataclass(frozen=True)
class MarkerImage:
    files: Mapping[str, bytes]
    fingerprint: str

    def evidence(self) -> Object:
        return {"inventory": [{"name": name, "sha256": digest(raw), "size": len(raw)}
                              for name, raw in sorted(self.files.items())], "fingerprint": self.fingerprint}


def markers(authority: Authority) -> MarkerImage:
    folder = authority.folder / "normal-admissions"
    result: dict[str, bytes] = {}
    if os.path.lexists(folder):
        private_directory(folder)
        for count, path in enumerate(sorted(folder.iterdir())):
            require(count < 100000 and path.name.endswith(".json") and valid_token(path.stem),
                    "Unsafe or unbounded normal-admission inventory.")
            result[path.name] = read_bytes(path)
    # This actual validator hashes all markers without rewriting their epochs.
    return MarkerImage(result, admission_fingerprint(authority))


@dataclass(frozen=True)
class CompletedLaunch:
    component: str
    invocation: str
    marker_sha256: str
    evidence_name: str
    provider: ExactProcess


def verify_marker_additions(authority: Authority, old: MarkerImage, current: MarkerImage,
                            scope: CandidateScope, completed: Sequence[CompletedLaunch],
                            evidence: EvidenceRecorder) -> None:
    require(all(current.files.get(name) == raw for name, raw in old.files.items()),
            "A historical normal-admission marker was deleted or changed.")
    added = set(current.files) - set(old.files)
    accounts = {row.invocation + ".json": row for row in completed if row.component == authority.component}
    require(set(accounts) == added, "Unaccounted normal-admission addition or unused launch account.")
    custody = reconcile(authority, persist_unknown=False, candidate=scope)
    require(custody.resolved, "Actual launch graph is unresolved.")
    control = authority.read("control")
    for name in sorted(added):
        account = accounts[name]
        require(account.evidence_name in evidence.files and digest(current.files[name]) == account.marker_sha256,
                "Missing independent actual launch evidence.")
        marker = document(current.files[name])
        require(marker["component"] == authority.component and marker["invocation"] == account.invocation
                and marker["epoch"] == control["epoch"] and marker["boot"] == boot_uuid()
                and marker["build"] == scope.producer(authority.component).build
                and marker["payloadSha256"] == scope.producer(authority.component).digest,
                "New marker is not the actual old-scope launch.")
        roots = [row for row in custody.writers if row["invocation"] == account.invocation and row["parent"] is None]
        require(len(roots) == 1 and roots[0]["phase"] == "terminal"
                and {k: roots[0][k] for k in ("pid", "startedAt")} == account.provider.object()
                and not account.provider.live(), "Actual provider root was not legitimately completed/reaped.")
        for handoff in (row for row in custody.handoffs if row["invocation"] == account.invocation):
            require(handoff["phase"] == "accepted", "A launch still has a pending handoff.")
            context = read(authority.folder / "handoffs" / (handoff["handoff"] + ".context.json"))
            normal_context(context)
            require(sha256(canonical(context)) == handoff["contextSha256"]
                    and context["registry"] == str(authority.registry), "Actual launch context changed.")


@dataclass(frozen=True)
class CompletedReceipt:
    """Original issuing bindings plus an actual external provider-finish witness."""

    component: str
    session: str
    attempt: str
    receipt_sha256: str
    provider: TuplePin
    producer: TuplePin
    gate_sha256: str
    acceptance_sha256: str
    registry_identity: Object
    observation: Path
    observation_sha256: str
    rebind_generations: tuple[str, ...] = ()


def verify_completed_receipt(authority: Authority, proof: CompletedReceipt, *, current_epoch: str) -> Object:
    from arbol_builds.driver_admission import canonical_uuid
    require(proof.component == authority.component and canonical_uuid(proof.session) and valid_token(proof.attempt)
            and proof.registry_identity == authority.identity, "Historical receipt scope differs.")
    raw = read_bytes(authority.folder / "maintenance.json")
    receipt = document(raw)
    validate("maintenance", receipt)
    require(raw == canonical(receipt) and digest(raw) == proof.receipt_sha256
            and receipt["component"] == proof.component and receipt["session"] == proof.session
            and receipt["gateSha256"] == proof.gate_sha256, "Retained canonical receipt changed.")
    # Resolve the genuine issuing images, not the later selected gate/producer.
    issuing_provider = proof.provider.verify(authority.registry)
    issuing_producer = proof.producer.verify(authority.registry)
    require(proof.provider.component == "arbol" and proof.producer.component == authority.component,
            "Historical receipt issuing components differ.")
    acceptance_raw = read_bytes(authority.shared / "acceptances" / (proof.acceptance_sha256 + ".json"))
    acceptance = document(acceptance_raw)
    exact_fields(acceptance, ("version", "kind", "status", "scope", "contract", "providerPayloadSha256",
                              "producerPayloadSha256", "gateSha256", "platform", "evidenceSha256"))
    require(digest(acceptance_raw) == proof.acceptance_sha256 and acceptance_raw == canonical(acceptance)
            and type(acceptance["version"]) is int and acceptance["version"] == 1
            and acceptance["kind"] == "driver-qualification" and acceptance["status"] in ("candidate", "qualified")
            and acceptance["contract"] == "DRV-browser-identity-1"
            and acceptance["scope"] == str(authority.registry)
            and acceptance["providerPayloadSha256"] == issuing_provider.payload.digest
            and acceptance["producerPayloadSha256"] == issuing_producer.payload.digest
            and acceptance["gateSha256"] == proof.gate_sha256, "Historical issuing acceptance differs.")
    folder = private_directory(authority.folder / "sessions" / proof.session)
    history = private_directory(folder / "attempts" / proof.attempt)
    require(not os.path.lexists(folder / "operation.json"), "An actual operation is still pending.")
    context_raw = read_bytes(folder / "contexts" / (proof.attempt + ".json"))
    request_raw = read_bytes(folder / "contexts" / (proof.attempt + ".request.json"))
    context, binding = document(context_raw), document(request_raw)
    validate("context", context)
    request_binding(binding, context)
    operation, result = read(history / "operation.json"), read(history / "result.json")
    validate("operation", operation)
    validate("result", result)
    require(context_raw == read_bytes(history / "context.json") and request_raw == read_bytes(history / "request.json")
            and read(folder / "result.json") == result, "Historical context/request/result pointers differ.")
    require(context["component"] == proof.component and context["session"] == proof.session
            and context["attempt"] == proof.attempt and context["epoch"] == receipt["epoch"]
            and context["registry"] == str(authority.registry) and context["gateSha256"] == proof.gate_sha256
            and context["payloadSha256"] == issuing_producer.payload.digest
            and context["acceptanceSha256"] == proof.acceptance_sha256
            and binding["build"] == proof.producer.build
            and context["receiptSha256"] == digest(raw) and operation["receiptSha256"] == digest(raw),
            "Receipt does not bind the actual issuing operation/context.")
    require(all(operation.get(key) == value for key, value in context.items()),
            "Historical operation is not the exact context chain.")
    for key in ("component", "session", "epoch", "attempt", "operation", "payloadSha256", "generation"):
        require(result[key] == context[key], "Actual result/context binding differs.")
    require(result["stateDirectorySha256"] == digest(context["stateDirectory"].encode())
            and result["backupSha256"] == operation["backupSha256"], "Actual result/backup/state binding differs.")
    finish = read(history / "finish.json")
    exact_fields(finish, ("version", "kind", "component", "session", "epoch", "attempt", "generation",
                          "resultSha256", "contextSha256", "requestSha256", "markerSha256", "nextEpoch", "phase"))
    require(type(finish["version"]) is int and finish["version"] == 1
            and finish["kind"] == "driver-maintenance-finish" and finish["phase"] in ("ready", "complete")
            and all(finish[key] == context[key] for key in ("component", "session", "epoch", "attempt", "generation"))
            and finish["resultSha256"] == digest(canonical(result)) and finish["contextSha256"] == digest(context_raw)
            and finish["requestSha256"] == digest(request_raw)
            and valid_token(finish["nextEpoch"]) and finish["nextEpoch"] != receipt["epoch"],
            "Historical finish is incomplete or bound to another attempt.")
    marker_raw = read_bytes(history / "marker.json")
    require(read_bytes(history / "finished-marker.json") == marker_raw
            and finish["markerSha256"] == digest(marker_raw), "Finished marker archive differs.")
    observed_image = read_image(proof.observation, limit=1024 * 1024)
    require(observed_image.sha256 == proof.observation_sha256, "External actual finish observation changed.")
    observed = document(observed_image.raw, limit=1024 * 1024)
    exact_fields(observed, ("version", "kind", "component", "session", "attempt", "receiptSha256",
                            "contextSha256", "requestSha256", "resultSha256", "markerSha256", "gateSha256",
                            "providerPayloadSha256", "producerPayloadSha256", "acceptanceSha256", "registry",
                            "providerProcess", "returncode", "reaped", "stdout", "normalFinishRetry", "targetState"))
    require(type(observed["version"]) is int and observed["version"] == 1
            and observed["kind"] == "abr38-actual-provider-finish" and observed["returncode"] == 0
            and observed["reaped"] is True and observed["component"] == proof.component
            and observed["session"] == proof.session and observed["attempt"] == proof.attempt
            and observed["receiptSha256"] == digest(raw) and observed["registry"] == authority.identity
            and observed["providerPayloadSha256"] == issuing_provider.payload.digest
            and observed["producerPayloadSha256"] == issuing_producer.payload.digest
            and observed["acceptanceSha256"] == proof.acceptance_sha256
            and observed["gateSha256"] == proof.gate_sha256
            and all(observed[key] == finish[key] for key in (
                "contextSha256", "requestSha256", "resultSha256", "markerSha256")),
            "Missing genuine issuing provider finish evidence.")
    ExactProcess.read(observed["providerProcess"])
    output = observed["stdout"]
    require(isinstance(output, dict) and output.get("phase") == "normal"
            and output.get("component") == proof.component and output.get("session") == proof.session,
            "Actual provider did not acknowledge normal finish.")
    require(finish["phase"] == "complete" or observed["normalFinishRetry"] is True,
            "A ready journal alone is not an actual accepted normal finish retry.")
    target = observed["targetState"]
    exact_fields(target, ("stateDirectory", "formatSha256", "identitySha256", "maintenanceMarkerAbsent"))
    require(target["stateDirectory"] == context["stateDirectory"]
            and valid_hash(target["formatSha256"]) and valid_hash(target["identitySha256"])
            and target["maintenanceMarkerAbsent"] is True, "Actual finish target-state observation is incomplete.")
    epoch = finish["nextEpoch"]
    for generation_hash in proof.rebind_generations:
        require(valid_hash(generation_hash), "Invalid retained rebind lineage hash.")
        generation_raw = read_bytes(authority.shared / "fixture-authority" / ("generation-" + generation_hash + ".json"),
                                    limit=32 * 1024 * 1024)
        require(digest(generation_raw) == generation_hash, "Retained rebind generation changed.")
        generation = document(generation_raw, limit=32 * 1024 * 1024)
        row = generation["controls"][authority.component]
        require(generation["kind"] == "abr38-fixture-generation" and generation["registry"] == authority.identity
                and row["beforeEpoch"] == epoch and valid_token(row["afterEpoch"]),
                "Unexplained epoch lineage after actual finish.")
        epoch = row["afterEpoch"]
    require(epoch == current_epoch, "Retained receipt has no complete finish/rebind path to current epoch.")
    return finish


@dataclass(frozen=True)
class Baseline:
    gate_bytes: bytes
    scopes: Mapping[str, CandidateScope]
    markers: Mapping[str, MarkerImage]
    locks: Mapping[str, Object]
    images: Mapping[str, RegisteredImage]
    epochs: Mapping[str, str]
    generation_sha256: str
    boot: str
    platform: Object
    authority_identities: Mapping[str, Object]
    deployment_identity: Object
    receipts: Mapping[str, CompletedReceipt] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedGroup:
    images: Mapping[str, RegisteredImage]
    routes: Mapping[str, tuple[bytes, int]]
    before_routes: Mapping[str, tuple[bytes, int] | None]
    gate: Object
    gate_bytes: bytes
    acceptances: Mapping[str, Object]
    acceptance_hashes: Mapping[str, str]
    preparation_evidence_sha256: str


def catalog_section[T](registry: Path, action: Callable[[], T], *, deadline: Deadline) -> T:
    """Use actual record serialization, never write a replacement build.json."""
    def enter(index: int) -> T:
        if index == len(ALL_COMPONENTS):
            return action()
        # The actual reservation API has its own30sec bound; do not begin it
        # with less than that left in the transaction budget.
        require(deadline.remaining() >= 30, "Insufficient bounded record-reservation time.")
        return with_mutation_lock(str(registry / ALL_COMPONENTS[index]), lambda: enter(index + 1))
    return enter(0)


@contextmanager
def use_pins(registry: Path, pins: Sequence[TuplePin]) -> Iterator[dict[str, RegisteredImage]]:
    require(len(pins) == 5 and {pin.component for pin in pins} == set(ALL_COMPONENTS), "Expected exactly five real tuples.")
    with ExitStack() as stack:
        images: dict[str, RegisteredImage] = {}
        for pin in sorted(pins, key=lambda item: (item.component, item.build)):
            descriptor = open_use_guard(str(registry), pin.component, pin.build)
            stack.callback(os.close, descriptor)
            named = (registry / pin.component / ".uses" / pin.build).lstat()
            held = os.fstat(descriptor)
            require((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)
                    and held.st_uid == os.getuid() and stat.S_IMODE(held.st_mode) == 0o600,
                    "Independent Build-use guard identity differs.")
            images[pin.component] = pin.verify(registry)
        yield images


@dataclass(frozen=True)
class DeploymentPin:
    """One test-owned independent EX description of the actual shared lock."""

    path: Path
    descriptor: int
    identity: Object

    def verify(self) -> None:
        physical_owned(self.path.parent, directory=True)
        held, named = os.fstat(self.descriptor), self.path.lstat()
        for value in (held, named):
            require(stat.S_ISREG(value.st_mode) and value.st_uid == os.getuid()
                    and stat.S_IMODE(value.st_mode) == 0o600, "Deployment lock is not private regular owned evidence.")
        actual = {"path": str(self.path), "device": held.st_dev, "inode": held.st_ino,
                  "uid": held.st_uid, "mode": stat.S_IMODE(held.st_mode)}
        require((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino) and actual == self.identity,
                "Original deployment lock description or named identity changed.")


@contextmanager
def fixture_deployment_lock(registry: Path, *, original: Object | None) -> Iterator[DeploymentPin]:
    """Use the same genuine file/schema/flock boundary; never nest production EX.

    Production deployment_mutex yields None. This testing-only owner exposes
    only its own description, so identity checks cannot pretend to inspect a
    production descriptor or silently acquire EX on a replacement lock.
    """
    shared = private_directory(registry / ".driver-qualification")
    path = shared / "deployment.lock"
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    if original is None:
        flags |= os.O_CREAT | os.O_EXCL  # New fixture genesis only.
    descriptor = os.open(path, flags, 0o600)
    try:
        held = os.fstat(descriptor)
        identity: Object = {"path": str(path), "device": held.st_dev, "inode": held.st_ino,
                            "uid": held.st_uid, "mode": stat.S_IMODE(held.st_mode)}
        pin = DeploymentPin(path, descriptor, identity)
        pin.verify()
        require(original is None or identity == original, "Cannot lock an unknown replacement deployment file.")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pin.verify()
        os.fsync(descriptor)
        sync_directory(shared)
        yield pin
    finally:
        os.close(descriptor)


class FixtureAuthority:
    """No subject SH, deployment mode, resume, arbitrary patch or taint clearing."""

    def __init__(self, workspace: Workspace, evidence: EvidenceRecorder) -> None:
        workspace.verify(evidence)
        self.workspace, self.evidence = workspace, evidence
        self.authorities = {component: Authority(workspace.registry, component) for component in COMPONENTS}

    def _locks(self) -> dict[str, Object]:
        return {component: {"control": lock_identity(authority, "control.lock"),
                            "admission": lock_identity(authority, "admission.lock")}
                for component, authority in self.authorities.items()}

    def _authority_identities(self) -> dict[str, Object]:
        shared = self.workspace.registry / ".driver-qualification"
        paths = {"shared": shared, "fixture": shared / "fixture-authority",
                 **{component: authority.folder for component, authority in self.authorities.items()}}
        result: dict[str, Object] = {}
        for name, path in paths.items():
            identity = directory_identity(path)
            info = physical_owned(path, directory=True)
            require((identity["device"], identity["inode"]) == (info.st_dev, info.st_ino),
                    "Authority directory changed during identity observation.")
            result[name] = {**identity, "uid": info.st_uid, "mode": stat.S_IMODE(info.st_mode)}
        return result

    def _prepare(self, images: Mapping[str, RegisteredImage]) -> PreparedGroup:
        routes: dict[str, tuple[bytes, int]] = {}
        before: dict[str, tuple[bytes, int] | None] = {}
        provider = images["arbol"].payload
        for component in COMPONENTS:
            path = self.workspace.bin / component
            before[component] = driver_route_bytes(path)
            routes[component] = (driver_launcher_source(str(self.workspace.registry), component, str(path), provider), 0o755)
        gate: Object = {"version": 1, "kind": "driver-gate", "providerPayloadSha256": provider.digest,
                        "components": [{"component": component, "launcher": str(self.workspace.bin / component),
                                        "launcherSha256": digest(routes[component][0])} for component in COMPONENTS]}
        gate_raw = canonical(gate)
        preparation = self.evidence.write("preparation-inputs.json", {
            "version": 1, "kind": "abr38-preparation-only", "registry": self.workspace.registry_identity,
            "images": [images[name].evidence() for name in ALL_COMPONENTS], "gate": gate,
            "platform": platform_identity(), "boot": boot_uuid(), "qualificationPassed": False,
        })
        acceptances: dict[str, Object] = {}
        hashes: dict[str, str] = {}
        for component in COMPONENTS:
            value: Object = {"version": 1, "kind": "driver-qualification", "status": "candidate",
                             "scope": str(self.workspace.registry), "contract": "DRV-browser-identity-1",
                             "providerPayloadSha256": provider.digest, "producerPayloadSha256": images[component].payload.digest,
                             "gateSha256": digest(gate_raw), "platform": platform_identity(), "evidenceSha256": preparation}
            acceptances[component], hashes[component] = value, digest(canonical(value))
        return PreparedGroup(images, routes, before, gate, gate_raw, acceptances, hashes, preparation)

    def _assert_no_special_authority(self, old: Baseline | None = None) -> None:
        shared = self.workspace.registry / ".driver-qualification"
        for name in FORBIDDEN_AUTHORITY:
            require(not os.path.lexists(shared / name), "Existing deployment/recovery/checkpoint is not fixture genesis/rebind.")
        for authority in self.authorities.values():
            for name in ("taint.json", "archive/custody-pending.json"):
                require(not os.path.lexists(authority.folder / name), "Tainted or pending authority cannot rebind.")
            if os.path.lexists(authority.folder / "maintenance.json"):
                require(old is not None and authority.component in old.receipts,
                        "Maintenance is active/unresolved without independently bound completed evidence.")
                assert old is not None
                verify_completed_receipt(authority, old.receipts[authority.component],
                                         current_epoch=old.epochs[authority.component])

    def _new_directories(self) -> None:
        for authority in self.authorities.values():
            require(not os.path.lexists(authority.folder), "Existing authority cannot be initialized as fresh.")
            private_directory(authority.folder, create=True)
            for name in ("writers", "handoffs", "sessions", "archive"):
                private_directory(authority.folder / name, create=True)
            for name in ("control.lock", "admission.lock"):
                descriptor = os.open(authority.folder / name, os.O_RDWR | os.O_CREAT | os.O_EXCL
                                     | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            sync_directory(authority.folder)

    def _healthy(self, old: Baseline, deployment: DeploymentPin) -> None:
        self.workspace.verify(self.evidence)
        deployment.verify()
        require(deployment.identity == old.deployment_identity
                and self._authority_identities() == old.authority_identities,
                "Original shared/component/fixture directories or deployment lock changed.")
        require(read_bytes(self.workspace.registry / ".driver-qualification/gate.json") == old.gate_bytes,
                "Old selected gate changed.")
        require(old.boot == boot_uuid() and old.platform == platform_identity(), "Boot/platform changed before rebind.")
        require(self._locks() == old.locks, "Stable authority lock inode changed.")
        owner = read(self.workspace.registry / ".driver-qualification/fixture-authority/owner.json")
        require(owner["authorityIdentities"] == dict(old.authority_identities)
                and owner["deploymentLock"] == old.deployment_identity,
                "Original genesis authority identity provenance changed.")
        self._assert_no_special_authority(old)
        for component, authority in self.authorities.items():
            require(authority.read("control") == {"version": 1, "phase": "normal", "session": None,
                                                  "epoch": old.epochs[component]}, "Old control lineage changed.")
            old.scopes[component].recheck()
            head = read(authority.shared / "fixture-authority/head.json")
            require(head["generationSha256"] == old.generation_sha256, "Fixture generation lineage changed.")

    def apply(self, pins: Sequence[TuplePin], *, old: Baseline | None = None,
              completed: Sequence[CompletedLaunch] = (), evolutions: Mapping[str, RecordEvolution] | None = None) -> Baseline:
        """One fresh/rebind transaction; failures preserve state and cannot resume here."""
        deadline = Deadline.after(120)
        self.workspace.verify(self.evidence)
        with use_pins(self.workspace.registry, pins) as images:
            group = self._prepare(images)
            if old is not None:
                for name, previous in old.images.items():
                    # Only a same-number image can have legitimate lifecycle snapshot evolution.
                    current = group.images[name]
                    if previous.pin == current.pin and previous.record_bytes != current.record_bytes:
                        if evolutions is None or name not in evolutions:
                            raise ObservationFailed("Unwitnessed service record evolution.")
                        verify_record_evolution(previous, current, evolutions[name], self.evidence)
                # Resolve/pin all old declared images before short publication locks too.
            with ExitStack() as old_guards:
                if old is not None:
                    old_guards.enter_context(use_pins(self.workspace.registry, [image.pin for image in old.images.values()]))
                    retained_pins = {(pin.component, pin.build): pin for proof in old.receipts.values()
                                     for pin in (proof.provider, proof.producer)}
                    for pin in retained_pins.values():
                        descriptor = open_use_guard(str(self.workspace.registry), pin.component, pin.build)
                        old_guards.callback(os.close, descriptor)
                        held = os.fstat(descriptor)
                        named = (self.workspace.registry / pin.component / ".uses" / pin.build).lstat()
                        require((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)
                                and held.st_uid == os.getuid() and stat.S_IMODE(held.st_mode) == 0o600,
                                "Historical issuing image guard differs.")
                        pin.verify(self.workspace.registry)
                return catalog_section(self.workspace.registry, lambda: self._publish(group, old, completed, deadline), deadline=deadline)

    def _validate_group(self, group: PreparedGroup, before: Mapping[str, MarkerImage],
                        epochs: Mapping[str, str], locks: Mapping[str, Object],
                        authority_identities: Mapping[str, Object], deployment: DeploymentPin) -> None:
        self.workspace.verify(self.evidence)
        deployment.verify()
        require(self._authority_identities() == authority_identities, "Stable authority directories were replaced.")
        require(self._locks() == locks, "Authority lock descriptions were replaced.")
        require(_gate_document(group.gate_bytes) == group.gate, "Actual routes do not match staged canonical gate.")
        provider = _candidate_payload(self.workspace.registry, "arbol", group.images["arbol"].payload.digest)
        require(provider == group.images["arbol"].payload, "Actual registered provider changed.")
        for component, authority in self.authorities.items():
            selected, acceptance = _candidate_acceptance(self.workspace.registry, component)
            require(selected == group.acceptance_hashes[component] and acceptance == group.acceptances[component],
                    "Actual candidate acceptance group differs.")
            require(_candidate_payload(self.workspace.registry, component, acceptance["producerPayloadSha256"])
                    == group.images[component].payload, "Actual registered producer changed.")
            require(authority.read("control") == {"version": 1, "phase": "normal", "session": None,
                                                  "epoch": epochs[component]}, "New control differs.")
            require(markers(authority) == before[component], "Current complete marker before-image changed.")
        for image in group.images.values():
            require(image.pin.verify(self.workspace.registry).record_bytes == image.record_bytes,
                    "Actual record changed during serialized publication.")

    def _publish(self, group: PreparedGroup, old: Baseline | None,
                 completed: Sequence[CompletedLaunch], deadline: Deadline) -> Baseline:
        shared = self.workspace.registry / ".driver-qualification"
        fresh = old is None
        if fresh:
            require(not os.path.lexists(shared), "Existing or partial authority is never fresh.")
            for authority in self.authorities.values():
                require(not os.path.lexists(authority.folder), "Unexpected existing component authority.")
            shared.mkdir(mode=0o700)
            sync_directory(shared.parent)
        else:
            private_directory(shared)
        transaction = token()
        session = str(uuid.uuid4())
        gate_path = shared / "gate.json"
        new_selection_started = False
        new_gate_published = False
        epochs: dict[str, str] = {}
        before: dict[str, MarkerImage] = {}
        with fixture_deployment_lock(self.workspace.registry, original=None if old is None else old.deployment_identity) as deployment, ExitStack() as locks:
            deadline.remaining()
            if fresh:
                require({p.name for p in shared.iterdir()} == {"deployment.lock"},
                        "New shared directory has unowned additions.")
                self._new_directories()
                private_directory(shared / "fixture-authority", create=True)
            else:
                assert old is not None
                self._healthy(old, deployment)
            for authority in self.authorities.values():
                locks.enter_context(authority.mutex(seconds=min(20, deadline.remaining())))
            exclusive: dict[str, int] = {}
            try:
                self._assert_no_special_authority(old)
                for component in COMPONENTS:
                    require(driver_route_bytes(self.workspace.bin / component) == group.before_routes[component],
                            "Conditional actual route before-image changed.")
                if not fresh:
                    assert old is not None
                    # The earlier preflight is not a serialization boundary:
                    # a genuine begin can close admission before these mutexes.
                    # All four are now held, so revalidate the COMPLETE original
                    # normal controls/scopes/permitted receipt lineage before
                    # writing even the first transaction-owned draining control.
                    self._healthy(old, deployment)
                    for component, authority in self.authorities.items():
                        authority.write("control", {"version": 1, "phase": "draining", "session": session,
                                                    "epoch": old.epochs[component]})
                for component, authority in self.authorities.items():
                    deadline.remaining()
                    descriptor = authority.lease(exclusive=True)
                    exclusive[component] = descriptor
                    locks.callback(os.close, descriptor)
                stable_locks = self._locks()
                stable_authorities = self._authority_identities()
                deployment.verify()
                if not fresh:
                    assert old is not None
                    for component, authority in self.authorities.items():
                        custody = reconcile(authority, candidate=old.scopes[component])
                        require(custody.resolved, "Old actual writer graph is not terminal.")
                        before[component] = markers(authority)
                        verify_marker_additions(authority, old.markers[component], before[component],
                                                old.scopes[component], completed, self.evidence)
                        self.evidence.write("markers-before-" + component + ".json", {
                            **before[component].evidence(),
                            "documents": {name: raw.decode("utf-8") for name, raw in before[component].files.items()},
                        })
                    for component, authority in self.authorities.items():
                        deadline.remaining()
                        authority.write("control", {"version": 1, "phase": "exclusive", "session": session,
                                                    "epoch": old.epochs[component]})
                        archive_terminal(authority, exclusive[component], candidate=old.scopes[component])
                        require(markers(authority) == before[component], "Archival changed normal-admission history.")
                    require(read_bytes(gate_path) == old.gate_bytes, "Old canonical gate changed before withholding.")
                    self.evidence.write_bytes("old-gate.json", old.gate_bytes)
                    remove(gate_path)  # Must precede EVERY new route/selection/epoch mutation.
                else:
                    require(not os.path.lexists(gate_path), "A fresh scope unexpectedly has a gate.")
                    before = {component: markers(authority) for component, authority in self.authorities.items()}
                new_selection_started = True
                fixture = private_directory(shared / "fixture-authority", create=True)
                acceptances = private_directory(shared / "acceptances", create=True)
                archives = {component: tree_inventory(authority.folder / "archive")
                            for component, authority in self.authorities.items()}
                for component, authority in self.authorities.items():
                    deadline.remaining()
                    raw = canonical(group.acceptances[component])
                    path = acceptances / (group.acceptance_hashes[component] + ".json")
                    if path.exists():
                        require(read_bytes(path) == raw, "Content-addressed acceptance collision.")
                    else:
                        publish(path, group.acceptances[component])
                    authority.write("qualification", {"version": 1, "component": component,
                                                       "acceptanceSha256": group.acceptance_hashes[component]})
                    publish_driver_route(self.workspace.bin / component, group.before_routes[component],
                                         group.routes[component])
                    epoch = token()
                    while old is not None and epoch == old.epochs[component]:
                        epoch = token()
                    epochs[component] = epoch
                    authority.write("control", {"version": 1, "phase": "normal", "session": None, "epoch": epoch})
                if fresh:
                    owner: Object = {"version": 1, "kind": "abr38-fixture-owner", "fixture": self.workspace.fixture,
                                     "registry": self.workspace.registry_identity, "bin": self.workspace.bin_identity,
                                     "authorityIdentities": stable_authorities, "deploymentLock": deployment.identity,
                                     "creator": self.workspace.creator.object(), "boot": boot_uuid(),
                                     "platform": platform_identity(), "sourceInputsSha256": group.preparation_evidence_sha256,
                                     "initialInventorySha256": digest(evidence_bytes({"records": [
                                         image.evidence() for image in group.images.values()], "routes": {
                                             component: None if raw is None else {"sha256": digest(raw[0]), "mode": raw[1]}
                                             for component, raw in group.before_routes.items()}}, limit=32 * 1024 * 1024))}
                    publish(fixture / "owner.json", owner)
                else:
                    owner = read(fixture / "owner.json")
                    require(owner["fixture"] == self.workspace.fixture
                            and owner["registry"] == self.workspace.registry_identity
                            and owner["bin"] == self.workspace.bin_identity, "Original fixture ownership changed.")
                generation: Object = {
                    "version": 1, "kind": "abr38-fixture-generation", "fixture": self.workspace.fixture,
                    "transaction": transaction, "parentSha256": None if old is None else old.generation_sha256,
                    "registry": self.workspace.registry_identity, "boot": boot_uuid(), "platform": platform_identity(),
                    "tuples": [group.images[name].evidence() for name in ALL_COMPONENTS],
                    "routeBeforeSha256": {component: None if raw is None else digest(raw[0])
                                          for component, raw in group.before_routes.items()},
                    "routeAfterSha256": {component: digest(raw[0]) for component, raw in group.routes.items()},
                    "gateSha256": digest(group.gate_bytes), "acceptances": dict(group.acceptance_hashes),
                    "controls": {component: {"beforeEpoch": None if old is None else old.epochs[component],
                                              "afterEpoch": epochs[component]} for component in COMPONENTS},
                    "locks": stable_locks, "authorityIdentities": stable_authorities,
                    "deploymentLock": deployment.identity, "normalAdmissions": {
                        component: {"before": image.evidence(), "after": markers(self.authorities[component]).evidence()}
                        for component, image in before.items()},
                    "archives": archives, "evidenceSha256": group.preparation_evidence_sha256,
                }
                # This is immutable fixture provenance, not production grant/empty-custody evidence.
                generation_bytes = evidence_bytes(generation, limit=32 * 1024 * 1024)
                generation_hash = digest(generation_bytes)
                from arbol_builds.driver_admission import publish_bytes
                generation_path = fixture / ("generation-" + generation_hash + ".json")
                require(not generation_path.exists(), "A fixture transaction cannot overwrite its history.")
                publish_bytes(generation_path, generation_bytes, limit=32 * 1024 * 1024)
                publish(fixture / "head.json", {"version": 1, "kind": "abr38-fixture-head", "fixture": self.workspace.fixture,
                                                "generationSha256": generation_hash, "gateSha256": digest(group.gate_bytes)})
                self._validate_group(group, before, epochs, stable_locks, stable_authorities, deployment)
                deadline.remaining()
                require(owner["boot"] == boot_uuid() and owner["platform"] == platform_identity(), "Actual machine changed.")
                publish(gate_path, group.gate)  # The sole NEW group publication point, LAST.
                new_gate_published = True
                scopes: dict[str, CandidateScope] = {}
                for component, authority in self.authorities.items():
                    scopes[component] = resolve_candidate(self.workspace.registry, component,
                                                          group.images[component].pin.build,
                                                          group.acceptance_hashes[component])
                    normal_control(authority, epoch=epochs[component], candidate=scopes[component])
                    require(reconcile(authority, candidate=scopes[component]).resolved,
                            "Actual postcommit custody is not resolved.")
                    require(markers(authority) == before[component], "Postcommit marker inventory changed under EX.")
                self._validate_group(group, before, epochs, stable_locks, stable_authorities, deployment)
                self.evidence.write("committed-generation.json", generation, limit=32 * 1024 * 1024)
                retained = {} if old is None else {
                    component: replace(proof, rebind_generations=(*proof.rebind_generations, generation_hash))
                    for component, proof in old.receipts.items()
                }
                return Baseline(group.gate_bytes, scopes, before, stable_locks, group.images, epochs,
                                generation_hash, str(generation["boot"]), generation["platform"],
                                stable_authorities, deployment.identity, retained)
            except BaseException:
                # OLD partial closure leaves its exact OLD group, not a mixed NEW success.
                # From withholding onward no partial NEW group may remain admitted.
                if new_selection_started and new_gate_published:
                    if read_bytes(gate_path) == group.gate_bytes:
                        remove(gate_path)
                    else:
                        raise ObservationFailed("Unknown gate after failure; preserve partial authority.") from None
                raise


class DeferredObservation(Protocol):
    """Authored static case objects, never callable names received over a wire."""

    @property
    def case_id(self) -> str: ...

    def observe(self, controller: WholeCheckController) -> None: ...


@dataclass(frozen=True)
class InventoryPhase:
    selected_ids: frozenset[str]
    required_external_ids: frozenset[str]
    inventory_sha256: str

    def validate(self, selected: Sequence[str], pending: Sequence[str], inventory_sha256: str) -> None:
        require(len(set(selected)) == len(selected) and frozenset(selected) == self.selected_ids,
                "Inner phase did not execute the complete admitted inventory.")
        require(len(set(pending)) == len(pending) and frozenset(pending) == self.required_external_ids,
                "Required deferred assertions disappeared or were added dynamically.")
        require(inventory_sha256 == self.inventory_sha256, "Inner phase inventory bytes differ.")


@dataclass(frozen=True)
class AdministrativeCapture:
    component: str
    command: str
    session: str
    arguments: Mapping[str, str]
    before_control: Object
    capture: Captured


class WholeCheckController:
    """External no-SH owner: local runner status is never a complete check pass."""

    def __init__(self, workspace: Workspace, scope: CandidateScope, evidence: EvidenceRecorder) -> None:
        workspace.verify(evidence)
        require(scope.registry == workspace.registry, "Controller subject scope differs.")
        scope.recheck()
        self.workspace, self.scope, self.evidence = workspace, scope, evidence
        self.reaped: list[OwnedChild] = []
        self.finished_external: set[str] = set()
        self.last_administration: AdministrativeCapture | None = None

    def fixed_argv(self, component: str, build: str, selector: str, tail: Sequence[str] = ()) -> list[str]:
        require(component in COMPONENTS and selector in SELECTORS and BUILD.fullmatch(build) is not None,
                "Invalid finite candidate dispatch.")
        require(selector == "driver" or not tail, "Only driver accepts ordinary CLI arguments.")
        require(component == "arbol-mimo-driver" or selector not in MIMO_ONLY, "Mimo-only selector on another component.")
        payload = self.scope.producer(component)
        require(payload.build == build, "Candidate command selected another Build.")
        return [*self.scope.gate.provider.prefix, "--qualification-launch", str(self.workspace.registry),
                component, build, selector, "--", *tail]

    def run_whole_runner(self, component: str, *, native: bool, environment: Mapping[str, str],
                         phase: InventoryPhase, report: Path, observations: Sequence[DeferredObservation],
                         seconds: float) -> None:
        """No prepare selector/filter: every pending oracle must finish before return."""
        require(math.isfinite(seconds) and 0 < seconds <= 7200, "Invalid complete-runner finite budget.")
        selector = "build-native" if native else "build-unit"
        argv = self.fixed_argv(component, self.scope.producer(component).build, selector)
        from arbol_builds.driver_admission import without_authority
        expected_root = self.workspace.registry / ".driver-qualification/fixtures"
        require(report.is_absolute() and report.is_relative_to(expected_root) and ".." not in report.parts
                and not os.path.lexists(report), "Inner report is not a fresh owned observation.")
        child = OwnedChild(argv, environment=without_authority(dict(environment)), cwd=self.workspace.registry)
        captured = self._collect_owned(child, seconds)
        self.evidence.write_bytes("inner-stdout.txt", captured.stdout)
        self.evidence.write_bytes("inner-stderr.txt", captured.stderr)
        require(child.reaped and captured.returncode == 0, "Complete inner local phase failed; no outer check success.")
        self.require_finished_graph(component)
        result = document(read_image(report, limit=1024 * 1024).raw, limit=1024 * 1024)
        exact_fields(result, ("version", "kind", "component", "build", "payloadSha256", "invocation", "writer",
                              "contextSha256", "selected", "pendingExternal", "inventorySha256"))
        require(type(result["version"]) is int and result["version"] == 1
                and result["kind"] == "abr38-inner-phase-only", "Not a local-phase report.")
        context, context_hash = self._runner_context(component, child)
        require(result["component"] == component and result["build"] == self.scope.producer(component).build
                and result["payloadSha256"] == self.scope.producer(component).digest
                and result["invocation"] == context["invocation"] and result["writer"] == context["writer"]
                and result["contextSha256"] == context_hash, "Phase report belongs to another actual runner.")
        require(isinstance(result["selected"], list) and all(isinstance(x, str) for x in result["selected"])
                and isinstance(result["pendingExternal"], list)
                and all(isinstance(x, str) for x in result["pendingExternal"]), "Malformed inventory phase identities.")
        phase.validate(result["selected"], result["pendingExternal"], result["inventorySha256"])
        require(len({item.case_id for item in observations}) == len(observations)
                and {item.case_id for item in observations} == set(phase.required_external_ids),
                "Static external oracle allocation differs from actual full inventory.")
        for observation in observations:
            observation.observe(self)
            self.finished_external.add(observation.case_id)
        require(self.finished_external == set(phase.required_external_ids), "An external assertion remains pending.")
        self.require_finished_graph(component)

    def _collect_owned(self, child: OwnedChild, seconds: float) -> Captured:
        try:
            result = child.collect(seconds=seconds)
            self.reaped.append(child)
            return result
        except BaseException:
            # Normal cancellation of the verified owned provider; never kill a guessed actor/group.
            # A failed join preserves active/unknown custody and cannot become a check pass.
            try:
                child.request_stop()
                child.wait_owned(seconds=20)
                self.reaped.append(child)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                pass
            raise

    def _runner_context(self, component: str, child: OwnedChild) -> tuple[Object, str]:
        authority = Authority(self.workspace.registry, component)
        with authority.mutex():
            custody = reconcile(authority, persist_unknown=False, candidate=self.scope)
            roots = [row for row in custody.writers if row["parent"] is None and row["phase"] == "terminal"
                     and {key: row[key] for key in ("pid", "startedAt")} == child.owner.object()]
            require(child.reaped and len(roots) == 1, "Actual provider root disposition is ambiguous.")
            candidates = [row for row in custody.handoffs if row["invocation"] == roots[0]["invocation"]
                          and row["parent"] == roots[0]["writer"] and row["phase"] == "accepted"
                          and row["role"] == "helper" and row["entry"] == "scripts/check_build.py"]
            require(len(candidates) == 1, "Whole runner transfer is not the fixed direct helper.")
            handoff = candidates[0]
            raw = read_bytes(authority.folder / "handoffs" / (handoff["handoff"] + ".context.json"))
            context = document(raw)
            normal_context(context)
            require(digest(raw) == handoff["contextSha256"]
                    and context["parent"]["pid"] == child.owner.pid
                    and context["parent"]["startedAt"] == child.owner.started_at
                    and context["registry"] == str(self.workspace.registry), "Actual runner context changed.")
            return context, digest(raw)

    def require_finished_graph(self, component: str) -> None:
        """The parent may be terminal while helpers still run; inspect the whole graph."""
        require(component in COMPONENTS, "Invalid component graph.")
        authority = Authority(self.workspace.registry, component)
        with authority.mutex():
            custody = reconcile(authority, persist_unknown=False, candidate=self.scope)
            require(custody.resolved and custody.active == 0 and custody.pending == 0,
                    "A real subject writer/helper/ACK remains active or unknown.")
            require(all(row["phase"] == "terminal" for row in custody.writers), "A writer has not genuinely finished.")
            require(not os.path.lexists(authority.folder / "taint.json"), "Subject is tainted; no local phase recovery.")
            require(all(child.reaped for child in self.reaped), "An owned provider was not actually reaped.")
            # Actual EX boundary, not an empty inventory/PID/EOF claim.
            descriptor = authority.lease(exclusive=True)
            os.close(descriptor)

    def maintenance(self, component: str, command: str, *, session: str,
                    arguments: Mapping[str, str], environment: Mapping[str, str], seconds: float = 120) -> Object:
        """Original fixed administrative API; no fixture receipt/reset shortcut."""
        require(command in ("begin", "drain", "execute", "finish", "status"), "Invalid fixed maintenance command.")
        self.require_finished_graph(component)
        from arbol_builds.driver_admission import canonical_uuid, without_authority
        require(canonical_uuid(session), "Invalid administrative session.")
        required = {"begin": set(), "drain": set(), "status": set(),
                    "execute": {"build", "state-dir", "operation", "backup"}, "finish": {"result"}}[command]
        allowed = required | ({"source", "subscription"} if command == "execute" else set())
        require(required <= set(arguments) <= allowed, "Invalid typed administrative arguments.")
        if command == "execute":
            operation = arguments["operation"]
            require(operation in ("upgrade", "identity-reset", "restore", "identity-recover")
                    and ("source" in arguments) == (operation == "restore")
                    and ("subscription" in arguments) == (operation == "identity-recover")
                    and arguments["build"] == self.scope.producer(component).build, "Wrong exact operation/Build.")
        for key in ("state-dir", "backup", "source"):
            if key in arguments:
                path = Path(arguments[key])
                require(path.is_absolute() and path.is_relative_to(self.workspace.fixture_root)
                        and ".." not in path.parts, "Maintenance path escaped actual fixture scope.")
        if command == "finish":
            expected = Authority(self.workspace.registry, component).folder / "sessions" / session / "result.json"
            require(arguments["result"] == str(expected), "Finish requires its exact actual session result, not a copy.")
        argv = [*self.scope.gate.provider.prefix, "driver-state", command, "--registry-dir", str(self.workspace.registry),
                "--component", component, "--session", session]
        for key in sorted(arguments):
            argv.extend(("--" + key, arguments[key]))
        authority = Authority(self.workspace.registry, component)
        with authority.mutex():
            before_control = authority.read("control")
        child = OwnedChild(argv, environment=without_authority(dict(environment)), cwd=self.workspace.registry)
        captured = self._collect_owned(child, seconds)
        require(captured.returncode == 0, "Actual administrative operation failed; preserve closed state.")
        result = document(captured.stdout)
        require("error" not in result, "Actual administrative operation refused.")
        self.last_administration = AdministrativeCapture(component, command, session, dict(arguments),
                                                          before_control, captured)
        return result


    def completed_receipt(self, *, component: str, session: str, attempt: str,
                          provider_pin: TuplePin, producer_pin: TuplePin) -> CompletedReceipt:
        """Capture actual normal finish output, never manufacture a finish from its journal."""
        observed = self.last_administration
        require(observed is not None, "No actual administrative finish was observed.")
        assert observed is not None
        require(observed.component == component and observed.command == "finish" and observed.session == session
                and observed.capture.returncode == 0
                and any(child.reaped and child.owner == observed.capture.owner for child in self.reaped),
                "The last actual reaped provider was not this finish.")
        require(component in COMPONENTS and valid_token(attempt), "Invalid actual finish identity.")
        authority = Authority(self.workspace.registry, component)
        self.scope.recheck()
        provider = provider_pin.verify(self.workspace.registry)
        producer = producer_pin.verify(self.workspace.registry)
        require(provider.payload == self.scope.gate.provider and producer.payload == self.scope.producer(component),
                "Finish witness does not use its actual issuing images.")
        raw = read_bytes(authority.folder / "maintenance.json")
        receipt = document(raw)
        validate("maintenance", receipt)
        history = authority.folder / "sessions" / session / "attempts" / attempt
        finish = read(history / "finish.json")
        context = read(history / "context.json")
        validate("context", context)
        state = Path(context["stateDirectory"])
        require(state.is_relative_to(self.workspace.fixture_root),
                "Historical finish observation cannot read owner state.")
        physical_owned(state, directory=True)
        target: Object = {"stateDirectory": str(state), "formatSha256": digest(read_bytes(state / "format")),
                           "identitySha256": digest(read_bytes(state / "identity.json")),
                           "maintenanceMarkerAbsent": not os.path.lexists(state / "identity-maintenance.json")}
        normal_retry = (observed.before_control["phase"] == "normal"
                        and observed.before_control["session"] is None
                        and observed.before_control["epoch"] == finish["nextEpoch"])
        value: Object = {"version": 1, "kind": "abr38-actual-provider-finish", "component": component,
                         "session": session, "attempt": attempt, "receiptSha256": digest(raw),
                         **{key: finish[key] for key in (
                             "contextSha256", "requestSha256", "resultSha256", "markerSha256")},
                         "gateSha256": self.scope.gate.digest, "providerPayloadSha256": provider.payload.digest,
                         "producerPayloadSha256": producer.payload.digest,
                         "acceptanceSha256": context["acceptanceSha256"], "registry": authority.identity,
                         "providerProcess": observed.capture.owner.object(), "returncode": observed.capture.returncode,
                         "reaped": True, "stdout": document(observed.capture.stdout),
                         "normalFinishRetry": normal_retry, "targetState": target}
        name = "finish-" + digest(canonical(context))[:16] + ".json"
        observation_hash = self.evidence.write(name, value)
        proof = CompletedReceipt(component, session, attempt, digest(raw), provider_pin, producer_pin,
                                 self.scope.gate.digest, context["acceptanceSha256"], authority.identity,
                                 self.evidence.root / name, observation_hash)
        with authority.mutex():
            control = authority.read("control")
            require(control["phase"] == "normal" and control["session"] is None,
                    "Actual finish has not reopened normal control.")
            verify_completed_receipt(authority, proof, current_epoch=control["epoch"])
        return proof
