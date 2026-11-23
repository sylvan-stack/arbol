"""Prospective ABR-38 fixture authority and external whole-check controller.

This testing module has no CLI, installed-registry mode, import-time IO or
permission to run itself.  Independent body admission precedes every use.
"""

from __future__ import annotations

import fcntl
import math
import os
import re
import signal
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MethodType
from typing import Protocol

from top.driver_state_support import (
    Captured,
    EvidenceRecorder,
    ExactProcess,
    FileImage,
    HelperSpanCollector,
    Object,
    ObservationFailed,
    OwnedChild,
    TerminalSpanCollector,
    digest,
    directory_identity,
    document,
    exact_fields,
    physical_owned,
    read_image,
    signal_verified,
    sync_directory,
    tree_inventory,
)
from top.driver_state_support import (
    canonical as evidence_bytes,
)

from arbol_builds.driver_admission import (
    COMPONENTS,
    Authority,
    Custody,
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
    origin_image: Object

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
                   directory_identity(fixture_root), name, dict(evidence.files[name]))

    def verify(self, evidence: EvidenceRecorder) -> None:
        require(valid_token(self.fixture), "Missing external new-workspace provenance.")
        original = read_image(Path(self.origin_image["path"]))
        require(original.evidence() == self.origin_image, "Original physical workspace evidence changed.")
        require(directory_identity(evidence.root) == evidence.identity, "Transaction recorder origin changed.")
        origin = document(original.raw)
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
class ArchiveImage:
    root: Object
    entries: Mapping[str, Object]

    @classmethod
    def capture(cls, folder: Path) -> ArchiveImage:
        root = directory_identity(folder)
        entries = {str(row["path"]): row for row in tree_inventory(folder)}
        require(directory_identity(folder) == root, "Archive root changed during inventory.")
        return cls(root, entries)

    def evidence(self) -> Object:
        return {"root": self.root, "entries": [self.entries[name] for name in sorted(self.entries)]}


def custody_source_images(authority: Authority) -> dict[str, ArchiveImage]:
    return {name: ArchiveImage.capture(authority.folder / name) for name in ("writers", "handoffs")}


def verify_archive_delta(before: ArchiveImage, after: ArchiveImage, sources: Mapping[str, ArchiveImage],
                         receipt_before: bytes | None) -> None:
    """Independently derive precisely the existing rename/receipt-copy effects."""
    require(before.root == after.root, "Original archive directory identity changed.")
    require(all(after.entries.get(name) == row for name, row in before.entries.items()),
            "A previously retained archive entry disappeared or changed bytes/type/mode/inode.")
    added = set(after.entries) - set(before.entries)
    allowed: set[str] = set()
    custody_roots = {name.split("/", 1)[0] for name in added if name.startswith("custody-")}
    require(len(custody_roots) <= 1, "One actual terminal archive created multiple unexplained groups.")
    for destination in custody_roots:
        require(valid_token(destination.removeprefix("custody-")) and set(sources) == {"writers", "handoffs"},
                "Archive addition is not the exact production terminal-tree shape.")
        root = after.entries[destination]
        exact_fields(root, ("path", "type", "device", "inode"))
        require(root["type"] == "directory", "Custody archive root is not a private actual directory.")
        allowed.add(destination)
        for name, source in sources.items():
            target = destination + "/" + name
            expected_root = {"path": target, "type": "directory",
                             "device": source.root["device"], "inode": source.root["inode"]}
            require(after.entries.get(target) == expected_root, "Archived tree did not retain its source directory inode.")
            allowed.add(target)
            for relative, row in source.entries.items():
                moved = target + "/" + relative
                require(after.entries.get(moved) == {**row, "path": moved},
                        "Actual renamed archive changed a source entry or its inode/bytes.")
                allowed.add(moved)
    receipt_names = {name for name in added if name.startswith("maintenance-")}
    require(len(receipt_names) <= 1, "One actual drain created multiple unexplained receipt copies.")
    if receipt_names:
        require(receipt_before is not None, "Receipt archive has no actual prior canonical receipt.")
        assert receipt_before is not None
        receipt = document(receipt_before)
        validate("maintenance", receipt)
        require(receipt_before == canonical(receipt), "Receipt beforeimage is not canonical production metadata.")
        name = "maintenance-" + digest(receipt_before) + ".json"
        require(receipt_names == {name}, "Receipt archive name differs from the exact old bytes.")
        row = after.entries[name]
        exact_fields(row, ("path", "sha256", "size", "device", "inode", "mode", "type"))
        require(row["type"] == "file" and row["mode"] == 0o600 and row["size"] == len(receipt_before)
                and row["sha256"] == digest(receipt_before), "Actual receipt copy differs from its original bytes.")
        allowed.add(name)
    require(added == allowed, "Unknown archive addition, pending journal or unexplained production effect.")


@dataclass(frozen=True)
class ArchiveWitness:
    """Only captured successful real provider drain effects may intervene."""

    component: str
    before: ArchiveImage
    after: ArchiveImage
    sources: Mapping[str, ArchiveImage]
    receipt_before: bytes | None
    observation: Path
    observation_sha256: str

    def verify(self, workspace: Workspace) -> Object:
        require(self.component in COMPONENTS, "Wrong archive-witness component.")
        image = read_image(self.observation, limit=32 * 1024 * 1024)
        require(image.sha256 == self.observation_sha256, "Original actual-drain observation changed.")
        value = document(image.raw, limit=32 * 1024 * 1024)
        exact_fields(value, ("version", "kind", "component", "registry", "session", "provider", "producer",
                             "gateSha256", "acceptanceSha256", "controlBefore", "controlAfter", "receiptAfter",
                             "process", "returncode", "reaped", "stdout", "before", "after", "sources", "receiptBefore"))
        require(value["version"] == 1 and type(value["version"]) is int
                and value["kind"] == "abr38-actual-provider-drain-archives"
                and value["component"] == self.component and value["registry"] == workspace.registry_identity
                and value["returncode"] == 0 and value["reaped"] is True
                and value["stdout"].get("phase") == "exclusive"
                and value["stdout"].get("component") == self.component
                and value["stdout"].get("session") == value["session"]
                and value["stdout"].get("receipt") == str(Authority(workspace.registry, self.component).folder / "maintenance.json")
                and value["before"] == self.before.evidence() and value["after"] == self.after.evidence()
                and value["sources"] == {name: source.evidence() for name, source in self.sources.items()}
                and value["receiptBefore"] == (None if self.receipt_before is None else self.receipt_before.decode("utf-8")),
                "Archive addition is not the captured exact successful production drain.")
        ExactProcess.read(value["process"])
        payloads: dict[str, Payload] = {}
        for name, component in (("provider", "arbol"), ("producer", self.component)):
            row = value[name]
            record, payload = _registered_payload(workspace.registry, component, row["build"])
            require(payload.digest == row["payloadSha256"]
                    and payload.descriptor["source"] == {"commit": row["sourceCommit"], "tree": row["sourceTree"]}
                    and payload.descriptor["payloadManifestSha256"] == row["manifestSha256"]
                    and record["source"]["uncommittedChanges"] is False,
                    "Actual archive operation source/runtime M-D tuple differs.")
            payloads[name] = payload
        acceptance_hash = value["acceptanceSha256"]
        require(valid_hash(acceptance_hash), "Actual archive acceptance hash is malformed.")
        raw_acceptance = read_bytes(workspace.registry / ".driver-qualification/acceptances" / (acceptance_hash + ".json"))
        acceptance = document(raw_acceptance)
        require(digest(raw_acceptance) == acceptance_hash and raw_acceptance == canonical(acceptance)
                and acceptance["kind"] == "driver-qualification" and acceptance["status"] in ("candidate", "qualified")
                and acceptance["scope"] == str(workspace.registry)
                and acceptance["gateSha256"] == value["gateSha256"]
                and acceptance["providerPayloadSha256"] == payloads["provider"].digest
                and acceptance["producerPayloadSha256"] == payloads["producer"].digest,
                "Actual archive operation issuing acceptance differs.")
        before_control, after_control = value["controlBefore"], value["controlAfter"]
        validate("control", before_control)
        validate("control", after_control)
        receipt_raw = value["receiptAfter"].encode("utf-8")
        receipt = document(receipt_raw)
        validate("maintenance", receipt)
        require(before_control["phase"] in ("draining", "exclusive") and before_control["session"] == value["session"]
                and after_control == {**before_control, "phase": "exclusive"}
                and receipt_raw == canonical(receipt)
                and receipt["component"] == self.component and receipt["session"] == value["session"]
                and receipt["epoch"] == before_control["epoch"] and receipt["gateSha256"] == value["gateSha256"],
                "Actual drain control/receipt changed session, epoch or issuing gate.")
        verify_archive_delta(self.before, self.after, self.sources, self.receipt_before)
        return value


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
    archives: Mapping[str, ArchiveImage]
    generation_image: Object
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
        require(set(evidence.files) <= {workspace.origin_evidence_name},
                "A fixture transaction requires an exclusively new evidence recorder.")
        evidence.write("workspace-origin-handoff.json", {"version": 1, "kind": "abr38-transaction-origin",
                       "fixture": workspace.fixture, "original": workspace.origin_image,
                       "transactionEvidence": evidence.identity})
        self.workspace, self.evidence = workspace, evidence
        self.authorities = {component: Authority(workspace.registry, component) for component in COMPONENTS}
        self._used = False

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

    def _prior_generation(self, old: Baseline, *, selected: bool = True) -> Object:
        folder = self.workspace.registry / ".driver-qualification/fixture-authority"
        image = read_image(folder / ("generation-" + old.generation_sha256 + ".json"), limit=32 * 1024 * 1024)
        require(image.sha256 == old.generation_sha256 and image.evidence() == old.generation_image,
                "Actual prior generation bytes/inode changed.")
        generation = document(image.raw, limit=32 * 1024 * 1024)
        require(image.raw == evidence_bytes(generation, limit=32 * 1024 * 1024)
                and generation["kind"] == "abr38-fixture-generation"
                and generation["fixture"] == self.workspace.fixture
                and generation["registry"] == self.workspace.registry_identity
                and generation["boot"] == old.boot and generation["platform"] == old.platform
                and generation["gateSha256"] == digest(old.gate_bytes)
                and generation["authorityIdentities"] == dict(old.authority_identities)
                and generation["deploymentLock"] == old.deployment_identity
                and generation["locks"] == dict(old.locks)
                and generation["archives"] == {name: archive.evidence() for name, archive in old.archives.items()},
                "Prior generation no longer binds the retained physical fixture/archive lineage.")
        require(read_image(folder / "owner.json").evidence() == generation["ownerImage"],
                "Original immutable fixture genesis provenance changed.")
        if selected:
            require(read(folder / "head.json") == {"version": 1, "kind": "abr38-fixture-head",
                    "fixture": self.workspace.fixture, "generationSha256": old.generation_sha256,
                    "gateSha256": digest(old.gate_bytes)}, "Original selected generation/head differs.")
        return generation

    def _retained_archives(self, old: Baseline, witnesses: Sequence[ArchiveWitness]) -> dict[str, ArchiveImage]:
        self._prior_generation(old)
        require(all(proof.component in COMPONENTS for proof in witnesses), "Unknown archive witness component.")
        expected = dict(old.archives)
        for proof in witnesses:
            observed = proof.verify(self.workspace)
            scope = old.scopes[proof.component]
            require(observed["gateSha256"] == scope.gate.digest
                    and observed["acceptanceSha256"] == scope.acceptance(proof.component)[0]
                    and observed["provider"]["payloadSha256"] == scope.gate.provider.digest
                    and observed["producer"]["payloadSha256"] == scope.producer(proof.component).digest,
                    "Intervening actual drain did not use this unchanged OLD selected tuple group.")
            require(proof.before == expected[proof.component] and proof.after != proof.before,
                    "Actual archive additions do not form the complete previous-generation chain.")
            expected[proof.component] = proof.after
        for component, authority in self.authorities.items():
            require(ArchiveImage.capture(authority.folder / "archive") == expected[component],
                    "Unknown archive deletion/change/addition since the actual prior generation.")
        return expected

    def _healthy(self, old: Baseline, deployment: DeploymentPin, witnesses: Sequence[ArchiveWitness]) -> dict[str, ArchiveImage]:
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
        retained_archives = self._retained_archives(old, witnesses)
        for component, authority in self.authorities.items():
            require(authority.read("control") == {"version": 1, "phase": "normal", "session": None,
                                                  "epoch": old.epochs[component]}, "Old control lineage changed.")
            old.scopes[component].recheck()
            head = read(authority.shared / "fixture-authority/head.json")
            require(head["generationSha256"] == old.generation_sha256, "Fixture generation lineage changed.")
        return retained_archives

    def apply(self, pins: Sequence[TuplePin], *, old: Baseline | None = None,
              completed: Sequence[CompletedLaunch] = (), evolutions: Mapping[str, RecordEvolution] | None = None,
              archive_witnesses: Sequence[ArchiveWitness] = ()) -> Baseline:
        """One fresh/rebind transaction; failures preserve state and cannot resume here."""
        require(not self._used, "A fixture transaction/evidence recorder cannot be reused or resumed.")
        self._used = True
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
                return catalog_section(self.workspace.registry, lambda: self._publish(group, old, completed, deadline, archive_witnesses), deadline=deadline)

    def _validate_group(self, group: PreparedGroup, before: Mapping[str, MarkerImage],
                        epochs: Mapping[str, str], locks: Mapping[str, Object],
                        authority_identities: Mapping[str, Object], deployment: DeploymentPin,
                        archives: Mapping[str, ArchiveImage], old: Baseline | None) -> None:
        self.workspace.verify(self.evidence)
        deployment.verify()
        require(self._authority_identities() == authority_identities, "Stable authority directories were replaced.")
        if old is not None:
            self._prior_generation(old, selected=False)
        for component, authority in self.authorities.items():
            require(ArchiveImage.capture(authority.folder / "archive") == archives[component],
                    "Complete retained archive inventory changed before/after gate-LAST.")
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
                 completed: Sequence[CompletedLaunch], deadline: Deadline,
                 witnesses: Sequence[ArchiveWitness]) -> Baseline:
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
        archive_outputs: dict[str, ArchiveImage] = {}
        expected_old_archives: dict[str, ArchiveImage] = {}
        with fixture_deployment_lock(self.workspace.registry, original=None if old is None else old.deployment_identity) as deployment, ExitStack() as locks:
            deadline.remaining()
            if fresh:
                require({p.name for p in shared.iterdir()} == {"deployment.lock"},
                        "New shared directory has unowned additions.")
                self._new_directories()
                private_directory(shared / "fixture-authority", create=True)
            else:
                assert old is not None
                self._healthy(old, deployment, witnesses)
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
                    expected_old_archives = self._healthy(old, deployment, witnesses)
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
                require(old is None or stable_authorities == old.authority_identities,
                        "Original authority identities changed after closure; no new baseline.")
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
                        archive_before = ArchiveImage.capture(authority.folder / "archive")
                        require(archive_before == expected_old_archives[component],
                                "Archive changed since the serialized OLD beforeimage.")
                        source_before = custody_source_images(authority)
                        archive_terminal(authority, exclusive[component], candidate=old.scopes[component])
                        archive_after = ArchiveImage.capture(authority.folder / "archive")
                        verify_archive_delta(archive_before, archive_after, source_before, None)
                        archive_outputs[component] = archive_after
                        self.evidence.write("terminal-archive-" + component + ".json", {
                            "version": 1, "kind": "abr38-actual-terminal-archive", "component": component,
                            "registry": authority.identity, "control": authority.read("control"),
                            "before": archive_before.evidence(), "after": archive_after.evidence(),
                            "sources": {name: image.evidence() for name, image in source_before.items()},
                            "oldProviderPayloadSha256": old.scopes[component].gate.provider.digest,
                            "oldProducerPayloadSha256": old.scopes[component].producer(component).digest,
                            "independentExclusiveLock": lock_identity(authority, "admission.lock"),
                        }, limit=32 * 1024 * 1024)
                        require(markers(authority) == before[component], "Archival changed normal-admission history.")
                    require(read_bytes(gate_path) == old.gate_bytes, "Old canonical gate changed before withholding.")
                    self.evidence.write_bytes("old-gate.json", old.gate_bytes)
                    remove(gate_path)  # Must precede EVERY new route/selection/epoch mutation.
                else:
                    require(not os.path.lexists(gate_path), "A fresh scope unexpectedly has a gate.")
                    before = {component: markers(authority) for component, authority in self.authorities.items()}
                    archive_outputs = {component: ArchiveImage.capture(authority.folder / "archive")
                                       for component, authority in self.authorities.items()}
                    require(all(not image.entries for image in archive_outputs.values()),
                            "Fresh actual archive directory has unowned additions.")
                new_selection_started = True
                fixture = private_directory(shared / "fixture-authority", create=True)
                acceptances = private_directory(shared / "acceptances", create=True)
                archives = archive_outputs
                require(set(archives) == set(COMPONENTS), "Missing exact terminal-archive result.")
                for component, authority in self.authorities.items():
                    require(ArchiveImage.capture(authority.folder / "archive") == archives[component],
                            "Retained archive changed after actual archival; no refreshed self-baseline.")
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
                    "archives": {component: image.evidence() for component, image in archives.items()},
                    "ownerImage": read_image(fixture / "owner.json").evidence(),
                    "interveningArchiveWitnesses": [{"component": proof.component,
                        "path": str(proof.observation), "sha256": proof.observation_sha256} for proof in witnesses],
                    "evidenceSha256": group.preparation_evidence_sha256,
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
                self._validate_group(group, before, epochs, stable_locks, stable_authorities, deployment, archives, old)
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
                self._validate_group(group, before, epochs, stable_locks, stable_authorities, deployment, archives, old)
                self.evidence.write("committed-generation.json", generation, limit=32 * 1024 * 1024)
                retained = {} if old is None else {
                    component: replace(proof, rebind_generations=(*proof.rebind_generations, generation_hash))
                    for component, proof in old.receipts.items()
                }
                return Baseline(group.gate_bytes, scopes, before, stable_locks, group.images, epochs,
                                generation_hash, str(generation["boot"]), generation["platform"],
                                stable_authorities, deployment.identity, archives,
                                read_image(generation_path, limit=32 * 1024 * 1024).evidence(), retained)
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


_H1_CASES = {component: ("tests/test_subscription_identity.py" if component == "arbol-mimo-driver"
                       else "tests/top/test_top_subscription_identity.py")
             + "::HelperSpanTests.test_helper_independent_lease" for component in COMPONENTS}
_H1_FILES = {"phase-report.json": 1024 * 1024, "local-results.json": 1024 * 1024,
             "helper-span.json": 16 * 1024, "actor-ready.json": 4096, ".fixture-owner.json": 4096}


def _span_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not 0 < len(value) <= 4096:
        raise ObservationFailed("Invalid full H1 inventory list.")
    result: list[str] = []
    for item in value:
        require(isinstance(item, str) and 0 < len(item.encode("utf-8", "strict")) <= 512,
                "Invalid bounded inventory identity.")
        result.append(item)
    require(len(set(result)) == len(result), "Duplicate H1 inventory identity.")
    return tuple(result)


def _span_document(raw: bytes, *, limit: int) -> Object:
    value = document(raw, limit=limit)
    require(raw == evidence_bytes(value, limit=limit), "H1 report is not exact canonical JSONLF.")
    return value


@dataclass(frozen=True)
class H1Schedule:
    """Static admitted full UNIT order, never a selection received over control.

    The gate adapter's source admission supplies its actual prescribed order;
    the observer separately proves exact full membership from packaged inventory.
    Native remains its distinct complete original Mimo gate, not a unit filter.
    """

    phase: InventoryPhase
    order: tuple[str, ...]
    gate_source_sha256: str

    def verify(self, payload: Payload) -> bytes:
        require(payload.component in COMPONENTS and valid_hash(self.gate_source_sha256), "Invalid H1 source schedule.")
        require(_span_ids(list(self.order)) == self.order and frozenset(self.order) == self.phase.selected_ids
                and self.order[-1] == _H1_CASES[payload.component]
                and "H1-span-completion" in self.phase.required_external_ids, "H1 is not the fixed final full-unit case.")
        raw = read_image(payload.root / "test-tiers.json", limit=1024 * 1024, private=False).raw
        require(digest(raw) == self.phase.inventory_sha256, "Actual packaged inventory hash differs.")
        source = read_image(payload.root / "scripts/check_build.py", limit=1024 * 1024, private=False)
        require(source.sha256 == self.gate_source_sha256
                and "scripts/check_build.py" in payload.descriptor["helpers"]
                and "tests/identity_actor.py" in payload.descriptor["helpers"], "Actual runner/helper source grant differs.")
        inventory = document(raw, limit=1024 * 1024)
        require(isinstance(inventory.get("tests"), list), "Actual inventory lacks its fixed tests array.")
        selected: list[str] = []
        all_top: list[str] = []
        for row in inventory["tests"]:
            require(isinstance(row, dict), "Malformed actual inventory entry.")
            if row.get("tier") != "top":
                continue
            require(row.get("status") == "active", "A mandatory original top entry is disabled.")
            name = row.get("test" if payload.component == "arbol-mimo-driver" else "id")
            _span_ids([name])
            all_top.append(name)
            # EXACT unchanged Mimo unit/native split in its original full gate;
            # no caller prefix, selector, filter or prepare-only subset exists.
            if payload.component != "arbol-mimo-driver" or name.startswith("tests/test_"):
                selected.append(name)
        require(len(set(all_top)) == len(all_top) and set(selected) == set(self.order)
                and len(selected) == len(self.order), "H1 schedule omits/adds an actual full-unit top entry.")
        return raw


def reported_h1_custody(component: str, custody: Object) -> Object:
    """Keep the original broker registration material inside its private registry."""
    if component != "arbol-claude-driver":
        return custody
    handoffs = []
    for row in custody["handoffs"]:
        if row["entry"] == "bin/metadata-helper.py":
            handoffs.append({"handoff": row["handoff"], "entry": row["entry"],
                             "contextSha256": row["contextSha256"], "handoffSha256": digest(canonical(row))})
        else:
            handoffs.append(row)
    return {**custody, "handoffs": handoffs}


@dataclass
class PublicInvocations:
    """Immutable case/child evidence kept across the whole-unit H1 and terminal intervals."""

    invocations: set[str] = field(default_factory=set)
    files: dict[Path, FileImage] = field(default_factory=dict)

    def image(self, path: Path, expected_digest: str, limit: int) -> FileImage:
        current = read_image(path, limit=limit)
        require(current.sha256 == expected_digest and path.lstat().st_nlink == 1
                and self.files.get(path, current) == current, "Public case evidence was replaced or linked.")
        self.files[path] = current
        return current

    def recheck(self) -> None:
        for path, original in self.files.items():
            require(read_image(path, limit=max(1, len(original.raw))) == original and path.lstat().st_nlink == 1,
                    "An immutable ordinary-call result or original fixture marker changed.")


def pi_public_case(case_id: str, calls_by_fixture: Mapping[str, list[tuple[str, bool, str | None]]]) -> None:
    base = "tests/top/test_top_subscription_identity.py::"
    proof = ("identity", False, None)
    matched = ("identity", True, None)
    listing = ("list", False, None)
    denied = [("identity", False, "internal"), ("list", False, "internal")]
    expected = {
        base + "LocalCaptureTests.test_concurrent_public_implicit_capture": (1, [proof, proof]),
        base + "LocalCaptureTests.test_interrupted_conversion_refuses_public_identity_and_list": (1, denied),
        base + "LocalCaptureTests.test_public_process_restart_preserves_implicit_proof": (1, [proof, listing, matched]),
        base + "LocalProofLossTests.test_public_identity_and_list_refuse_missing_or_corrupt_root": (2, denied),
        base + "LocalRetentionTests.test_relabel_and_synthetic_binding_keep_original_public_proof":
            (1, [proof, matched, matched]),
    }
    count, sequence = expected.get(case_id, (0, []))
    require(len(calls_by_fixture) == count and all(rows == sequence for rows in calls_by_fixture.values()),
            "Pi ordinary invocation fixtures, operations or expected outcomes differ from the actual fixed case.")


def codex_public_case(case_id: str, fixtures: Mapping[str, list[tuple[list[str], bytes, int, str | None]]]) -> None:
    base = "tests/top/test_top_subscription_identity.py::LocalIdentityTests."
    native = ("identity", "chatgpt")
    matched = (*native, "--expect")
    historical = ("identity", "historical-chatgpt")
    created = ("identity", "historical-created")
    listing = ("list",)
    update = ("update", "chatgpt", "--label", "Preserved record")
    relabel = ("update", "chatgpt", "--label", "Updated label")
    create = ("create", "--family", "chatgpt", "--id", "historical-candidate", "--label", "Additional")
    # These are the source-owned request patterns. A mixed completion order is
    # allowed only for the two indistinguishable contending first captures.
    scenarios: dict[str, list[list[tuple[tuple[str, ...], str | None]]]] = {
        base + "test_signed_out_first_capture_contends_and_restart_accepts_persisted_proof":
            [[(native, None), (native, None), (matched, None)]],
        base + "test_qualified_list_preserves_format1_and_identity_requires_upgrade":
            [[(listing, None), (native, "invalid_input")]],
        base + "test_interrupted_conversion_rejects_proof_and_list_without_repair":
            [[(native, "internal"), (listing, "internal")]] * 2,
        base + "test_native_sign_out_and_removal_refuse_even_with_force_without_changing_proof":
            [[(native, None), (("identity", "ChatGPT Account"), "invalid_input"),
              *((request, "invalid_input") for request in (
                  ("sign-out", "chatgpt"), ("sign-out", "chatgpt", "--force"),
                  ("remove", "chatgpt"), ("remove", "chatgpt", "--force"))), (matched, None)]],
        base + "test_public_removal_retires_only_the_historical_fixture_subscription":
            [[(native, None), (historical, None), (("remove", "historical-chatgpt"), None),
              (historical, "not_found"), (historical, None), (matched, None)]],
        base + "test_relabel_and_recognizing_existing_login_retain_the_original_proof":
            [[(native, None), (relabel, None), (matched, None)]],
        base + "test_missing_sidecar_materializes_a_new_witness_and_rejects_old_expectation":
            [[(native, None), (update, None), (matched, "in_use"), (native, None)]],
        base + "test_corrupt_sidecar_and_lost_or_corrupt_root_refuse_without_regenerating_proof":
            [[(native, None), (update, None), (matched, "internal")],
             *([[(native, None), (update, None), (matched, "internal"), (listing, "internal")]] * 2)],
        base + "test_public_create_cannot_add_a_second_chatgpt_subscription":
            [[(native, None), (create, "invalid_input"), (matched, None)]],
        base + "test_historical_create_journal_settles_only_the_exact_archived_witness":
            [[(native, None), (created, None)], [(native, None), (created, "not_found")], [(native, None)], [(native, None)]],
        "tests/top/test_top_subscription_identity.py::LifetimeRaceTests."
        "test_fresh_list_reaps_a_dead_predecessor_receipt_without_adopting_its_verdict": [[(listing, None)]],
    }
    remaining = list(scenarios.get(case_id, []))
    for calls in fixtures.values():
        actual: list[tuple[tuple[str, ...], str | None]] = []
        proofs: dict[str, list[tuple[str, str]]] = {}
        for request, stdout, status, refusal in calls:
            normalized = tuple(request)
            if "--expect" in request:
                require(len(request) == 4 and request[:3] == ["identity", "chatgpt", "--expect"]
                        and len(request[3].split(".")) == 2 and all(valid_token(p) for p in request[3].split(".")),
                        "Malformed ordinary Codex proof expectation.")
                normalized = tuple(request[:3])
                require("chatgpt" in proofs and ".".join(proofs["chatgpt"][0]) == request[3],
                        "Public expectation differs from this fixture's original native proof.")
            if status == 1:
                result = document(stdout, limit=4096)
                require(set(result) == {"error"} and isinstance(result["error"], dict)
                        and isinstance(refusal, str) and result["error"].get("code") == refusal,
                        "Codex ordinary refusal differs from the original output.")
            else:
                require(status == 0 and refusal is None, "Unexpected Codex ordinary result status.")
                if request[0] == "identity":
                    result = document(stdout, limit=4096)
                    exact_fields(result, ("version", "driver", "subscription", "generation", "witness"))
                    require(len(request) >= 2 and type(result["version"]) is int and result["version"] == 1
                            and result["driver"] == "codex" and result["subscription"] == request[1]
                            and valid_token(result["generation"]) and valid_token(result["witness"]),
                            "Codex returned the wrong ordinary Subscription identity.")
                    proof = (result["generation"], result["witness"])
                    if normalized == matched:
                        require(".".join(proof) == request[3], "Successful Codex expectation changed the returned proof.")
                    proofs.setdefault(request[1], []).append(proof)
                elif request[0] == "list":
                    rows = document(b'{"entries":' + stdout + b'}', limit=4112)["entries"]
                    expected_ids = ["chatgpt"] if case_id.startswith(base) else ["chatgpt", "historical-chatgpt"]
                    require(isinstance(rows, list) and all(isinstance(item, dict) for item in rows)
                            and [(item.get("id"), item.get("state")) for item in rows]
                            == [(identifier, "signed_out") for identifier in expected_ids],
                            "Codex ordinary catalogue has an unexpected account or state.")
                elif request[0] == "update":
                    require(document(stdout, limit=4096).get("label") == request[-1],
                            "Codex ordinary update returned a different label.")
                else:
                    require(normalized == ("remove", "historical-chatgpt") and stdout == b"",
                            "Unexpected successful ordinary Codex operation.")
            actual.append((normalized, refusal))
        require(actual in remaining, "Codex ordinary case omitted, added or substituted an expected call.")
        remaining.remove(actual)
        if "historical-created" in proofs:
            require("chatgpt" in proofs and proofs["historical-created"][0][0] == proofs["chatgpt"][0][0],
                    "Settled historical create returned a different generation from its native fixture.")
        for selector, values in proofs.items():
            require(len({generation for generation, _ in values}) == 1, "Original Codex fixture generation changed.")
            replaced = (selector == "historical-chatgpt" or
                        case_id == base + "test_missing_sidecar_materializes_a_new_witness_and_rejects_old_expectation")
            if replaced:
                require(len(values) == 2 and values[0] != values[1], "Codex replacement failed to change its witness.")
            else:
                require(len(set(values)) == 1, "Codex changed the original retained fixture witness.")
    require(not remaining, "A fixed Codex fixture has no ordinary provider receipts.")


def verify_pi_public_output(request: list[str], stdout: bytes, status: int, refusal: object) -> tuple[str, bool, str | None]:
    require(request in (["list"], ["identity", "zai"]) or
            (len(request) == 4 and request[:3] == ["identity", "zai", "--expect"]
             and len(request[3].split(".")) == 2 and all(valid_token(part) for part in request[3].split("."))),
            "Pi receipt names a command outside the admitted public cases.")
    if status == 1:
        result = document(stdout, limit=65536)
        require(set(result) == {"error"} and isinstance(result["error"], dict)
                and result["error"].get("code") == refusal == "internal", "Changed fixed ordinary Pi refusal.")
        return request[0], len(request) == 4, "internal"
    require(status == 0 and refusal is None, "Unexpected ordinary Pi status.")
    if request == ["list"]:
        entries = document(b'{"entries":' + stdout + b'}', limit=65548)["entries"]
        require(isinstance(entries, list) and all(isinstance(row, dict) for row in entries)
                and [row.get("state") for row in entries if row.get("id") == "zai"] == ["signed_out"],
                "Ordinary restart list did not retain the single signed-out zai Subscription.")
    else:
        result = document(stdout, limit=65536)
        exact_fields(result, ("version", "driver", "subscription", "generation", "witness"))
        require(type(result["version"]) is int and result["version"] == 1 and result["driver"] == "pi"
                and result["subscription"] == "zai" and valid_token(result["generation"]) and valid_token(result["witness"])
                and (len(request) == 2 or request[3] == result["generation"] + "." + result["witness"]),
                "Ordinary Pi identity returned another Subscription or lifetime.")
    return request[0], len(request) == 4, None


@dataclass(frozen=True)
class H1View:
    """Verified report/process/source binding, NOT permission to signal a claim."""

    component: str
    case: str
    root: Path
    root_identity: Object
    images: Mapping[str, FileImage]
    suite: ExactProcess
    helper: ExactProcess
    suite_context: Object
    helper_context: Object
    suite_context_sha256: str
    helper_context_sha256: str
    admission_lock: Object
    custody: Object
    custody_sources: Mapping[str, ArchiveImage]
    public: PublicInvocations

    def recheck_files(self) -> None:
        self.public.recheck()
        require(directory_identity(self.root) == self.root_identity, "H1 fixture root was replaced.")
        for name, old in self.images.items():
            current = read_image(self.root / name, limit=_H1_FILES[name])
            require(current == old and (self.root / name).lstat().st_nlink == 1,
                    "Immutable H1 report/owner/ready evidence was changed or linked.")


@dataclass(frozen=True)
class AdministrativeCapture:
    component: str
    command: str
    session: str
    arguments: Mapping[str, str]
    before_control: Object
    capture: Captured
    archive_witness: ArchiveWitness | None


class TerminalObservations(Protocol):
    """Fixed source-admitted case bodies, never names supplied over control.

    The precontinue body composes H1SpanObservation.bind/positive_precontinue;
    interval supplies the independent original-SH oracle, and finished proves
    the real provider/Suite wait and all local result/resource dataflows.
    Source pins below bind all three actual bound methods before any launch.
    """

    def precontinue(self, controller: WholeCheckController, baseline: Baseline,
                    collector: TerminalSpanCollector, view: H1View, schedule: H1Schedule,
                    ready_raw: bytes) -> None: ...

    def interval(self, controller: WholeCheckController, baseline: Baseline,
                 collector: TerminalSpanCollector, view: TerminalView) -> None: ...

    def finished(self, controller: WholeCheckController, baseline: Baseline,
                 collector: TerminalSpanCollector, view: TerminalView, captured: Captured) -> None: ...


@dataclass(frozen=True)
class TerminalSchedule:
    """Static complete-body admission inputs; no runner filter or wire mode.

    tuple_document is a retained canonical five-tuple document, independently
    reconstructed from this baseline's registered immutable source images. The
    complete helper entry order includes nested helpers, not just direct H1.
    Final source admission must pin these actual bodies together at50/56.
    """

    tuple_document: bytes
    helper_entries: tuple[str, ...]
    helper_wait_statuses: tuple[int, ...]
    producer_support_sha256: str
    producer_admission_sha256: str
    provider_process_sha256: str
    observer_sha256: str
    controller_sha256: str
    collector_sha256: str

    def verify(self, controller: WholeCheckController, baseline: Baseline,
               component: str, observer: TerminalObservations) -> Object:
        controller.scope.recheck()
        require(set(baseline.images) == set(ALL_COMPONENTS), "Missing real five-tuple baseline.")
        tuples: list[Object] = []
        for name in ALL_COMPONENTS:
            image = baseline.images[name]
            pin = image.pin
            current = pin.verify(controller.workspace.registry)
            require(current.payload == image.payload, "Actual registered tuple changed.")
            tuples.append({"component": name, "build": pin.build, "sourceCommit": pin.commit,
                "sourceTree": pin.tree, "payloadSha256": pin.payload_sha256,
                "manifestSha256": image.payload.descriptor["payloadManifestSha256"]})
        require(self.tuple_document == evidence_bytes({"version": 1, "tuples": tuples}, limit=1024 * 1024),
                "Retained terminal tuple document is not the real ordered five-tuple group.")
        payload, provider = controller.scope.producer(component), controller.scope.gate.provider
        require(0 < len(self.helper_entries) <= 4096
                and len(self.helper_wait_statuses) == len(self.helper_entries)
                and all(type(status) is int and -128 <= status <= 255 for status in self.helper_wait_statuses)
                and all(entry in payload.descriptor["helpers"] for entry in self.helper_entries)
                and "tests/identity_actor.py" in self.helper_entries,
                "Missing fixed complete declared helper schedule.")
        if component == "arbol-claude-driver":
            require(self.helper_entries == ("tests/identity_actor.py",) * 10 +
                    ("bin/metadata-helper.py", "tests/identity_actor.py")
                    and self.helper_wait_statuses == (0, 1) * 5 + (0, 0),
                    "Claude requires ten create actors, the real broker and final H1 in order.")
        family = component.removeprefix("arbol-").removesuffix("-driver").replace("-", "_")
        sources: Object = {}
        for subject, name, expected in (
            (payload, "tests/identity_support.py", self.producer_support_sha256),
            (payload, "src/arbol_" + family + "_driver/admission.py", self.producer_admission_sha256),
            (provider, "src/arbol_builds/driver_process.py", self.provider_process_sha256),
            (provider, "tests/top/test_top_driver_state_admission.py", self.observer_sha256),
            (provider, "tests/driver_identity_qualification.py", self.controller_sha256),
            (provider, "tests/top/driver_state_support.py", self.collector_sha256),
        ):
            require(valid_hash(expected), "Missing reviewed terminal source pin.")
            source_image = read_image(subject.root / name, limit=1024 * 1024, private=False)
            require(source_image.sha256 == expected, "Packaged terminal body differs from its reviewed source.")
            sources[name] = source_image.evidence()
        observer_path = (provider.root / "tests/top/test_top_driver_state_admission.py").resolve(strict=True)
        for name in ("precontinue", "interval", "finished"):
            method = getattr(observer, name)
            require(isinstance(method, MethodType) and method.__self__ is observer
                    and Path(method.__func__.__code__.co_filename).resolve(strict=True) == observer_path,
                    "Terminal observer is not the fixed actual packaged case method.")
        for method, name in ((WholeCheckController.run_h1_positive, "tests/driver_identity_qualification.py"),
                             (TerminalSpanCollector.bind_verified_participants, "tests/top/driver_state_support.py")):
            require(Path(method.__code__.co_filename).resolve(strict=True) == (provider.root / name).resolve(strict=True),
                    "Imported terminal controller/collector differs from sealed source.")
        # Couple the actual imported production guard/process modules as well;
        # matching a caller-supplied source hash alone does not establish M/D.
        for module_name, name in ((Authority.__module__, "src/arbol_builds/driver_admission.py"),
                                  (process_identity.__module__, "src/arbol_builds/driver_process.py")):
            location = sys.modules[module_name].__file__
            require(location is not None, "Actual production module lacks physical provenance.")
            assert location is not None
            actual = read_image(Path(location).resolve(strict=True), limit=1024 * 1024, private=False)
            sealed = read_image(provider.root / name, limit=1024 * 1024, private=False)
            require(actual.sha256 == sealed.sha256, "Actual imported production module differs from provider.")
        return {"tuplePinsSha256": digest(self.tuple_document), "sources": sources,
                "producer": payload.digest, "provider": provider.digest,
                "runtime": payload.descriptor["interpreter"], "helperEntries": list(self.helper_entries),
                "helperWaitStatuses": list(self.helper_wait_statuses)}


@dataclass(frozen=True)
class TerminalView:
    h1: H1View
    images: Mapping[str, FileImage]
    intent: Object
    settled: Object
    sources: Object
    markers: MarkerImage
    control: Object
    custody_sources: Mapping[str, ArchiveImage]

    def recheck_files(self) -> None:
        self.h1.recheck_files()
        for name, before in self.images.items():
            after = read_image(self.h1.root / name, limit=max(1, len(before.raw)))
            require(after == before and (self.h1.root / name).lstat().st_nlink == 1,
                    "Terminal evidence was rewritten, replaced or linked.")


def verified_custody_images(authority: Authority, custody: Custody) -> dict[str, ArchiveImage]:
    """Bind the physical writer and handoff trees to the exact reconciled graph under its mutex."""
    sources = custody_source_images(authority)
    expected: dict[str, dict[str, str]] = {"writers": {}, "handoffs": {}}
    for writer in custody.writers:
        expected["writers"][f"{writer['invocation']}/{writer['writer']}.json"] = digest(canonical(writer))
    for handoff in custody.handoffs:
        prefix = handoff["handoff"]
        expected["handoffs"][prefix + ".json"] = digest(canonical(handoff))
        expected["handoffs"][prefix + ".context.json"] = handoff["contextSha256"]
    require(len(expected["writers"]) == len(custody.writers)
            and len(expected["handoffs"]) == 2 * len(custody.handoffs), "Duplicate custody file identity.")
    for name, source in sources.items():
        observed = {path: row["sha256"] for path, row in source.entries.items() if row["type"] == "file"}
        directories = {path for path, row in source.entries.items() if row["type"] == "directory"}
        require(observed == expected[name]
                and directories == ({row["invocation"] for row in custody.writers} if name == "writers" else set()),
                "Physical custody files or invocation directories differ from the reconciled graph.")
        for path in observed:
            row = source.entries[path]
            current = (authority.folder / name / path).lstat()
            require(stat.S_ISREG(current.st_mode) and current.st_nlink == 1
                    and (current.st_dev, current.st_ino) == (row["device"], row["inode"]),
                    "A custody file was replaced or linked during verification.")
    return sources


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

    def _public_call(self, public: PublicInvocations, component: str, root: Path, suite: Object,
                     case_id: str, row: Object, custody: Custody) -> tuple[list[str], bytes]:
        exact_fields(row, ("invocation", "rootWriter", "mainWriter", "handoff", "main", "contextSha256",
                           "rootSha256", "mainSha256", "handoffSha256", "fixture", "fixtureOwnerSha256",
                           "captureSha256", "operation", "argvSha256", "provider", "waitStatus",
                           "stdoutSize", "stdoutSha256", "stderrSize", "stderrSha256", "refusal", "streams"))
        invocation = row["invocation"]
        require(all(valid_token(row[key]) for key in ("invocation", "rootWriter", "mainWriter", "handoff"))
                and invocation != suite["invocation"] and invocation not in public.invocations
                and all(valid_hash(row[key]) for key in ("contextSha256", "rootSha256", "mainSha256", "handoffSha256",
                        "fixtureOwnerSha256", "captureSha256", "argvSha256", "stdoutSha256", "stderrSha256"))
                and isinstance(row["fixture"], str) and re.fullmatch(r"[a-f0-9]{32}", row["fixture"]) is not None
                and row["fixture"] != root.name and row["streams"] == "closed"
                and type(row["waitStatus"]) is int and row["waitStatus"] in (0, 1),
                "Malformed, duplicate or unmatched ordinary provider receipt.")
        fixture = root.parent / row["fixture"]
        owner = public.image(fixture / ".fixture-owner.json", row["fixtureOwnerSha256"], 4096)
        marker = _span_document(owner.raw, limit=4096)
        require(type(marker.get("version")) is int and marker == {"version": 1, "case": fixture.name,
                "component": component, "invocation": suite["invocation"], "parentWriter": suite["writer"],
                "payloadSha256": suite["payloadSha256"]}, "Ordinary fixture marker belongs to another original Suite.")
        capture_name = digest(invocation.encode()) if component == "arbol-codex-driver" else invocation
        actual = public.image(fixture / ("public-" + capture_name + ".json"), row["captureSha256"], 256 * 1024)
        detail = _span_document(actual.raw, limit=256 * 1024)
        exact_fields(detail, ("case", "fixture", "invocation", "request", "stdoutHex", "stderrHex"))
        request = detail["request"]
        require(detail["case"] == case_id and detail["fixture"] == fixture.name and detail["invocation"] == invocation
                and isinstance(request, list) and 0 < len(request) <= 16
                and all(isinstance(word, str) and len(word.encode()) <= 1024 and "\0" not in word for word in request)
                and request[0] == row["operation"], "Ordinary child receipt has a different fixture, request or case.")
        argv = self.fixed_argv(component, self.scope.producer(component).build, "driver",
                               ["--state-dir", str(fixture / "state"), "subscriptions", *request])
        require(digest(evidence_bytes(argv, limit=65536)) == row["argvSha256"], "Original public provider argv changed.")
        require(isinstance(detail["stdoutHex"], str) and len(detail["stdoutHex"]) <= 2 * 65536
                and re.fullmatch(r"(?:[a-f0-9]{2})*", detail["stdoutHex"]) is not None
                and detail["stderrHex"] == "", "Malformed bounded ordinary output.")
        stdout = bytes.fromhex(detail["stdoutHex"])
        require(type(row["stdoutSize"]) is int and row["stdoutSize"] == len(stdout)
                and type(row["stderrSize"]) is int and row["stderrSize"] == 0
                and digest(stdout) == row["stdoutSha256"] and digest(b"") == row["stderrSha256"],
                "Ordinary result stream bytes or published sizes changed.")
        writers = [w for w in custody.writers if w["invocation"] == invocation]
        handoffs = [h for h in custody.handoffs if h["invocation"] == invocation]
        require(len(writers) == 2 and len(handoffs) == 1, "Ordinary call is not a two-writer direct MAIN invocation.")
        roots = [w for w in writers if w["parent"] is None]
        require(len(roots) == 1, "Ordinary invocation has no unique provider root.")
        provider = roots[0]
        main = next(w for w in writers if w is not provider)
        transfer = handoffs[0]
        for writer, label, name in ((provider, "provider", "root"), (main, "main", "main")):
            process = ExactProcess.read(row[label])
            require(writer["phase"] == "terminal" and writer["writer"] == row[name + "Writer"]
                    and {key: writer[key] for key in ("pid", "startedAt")} == process.object() and not process.live()
                    and digest(canonical(writer)) == row[name + "Sha256"],
                    "Ordinary call process or exact terminal writer differs from the original capture.")
        require(transfer["phase"] == "accepted" and transfer["role"] == "main"
                and transfer["entry"] == self.scope.producer(component).descriptor["entry"]
                and transfer["handoff"] == row["handoff"] and transfer["parent"] == provider["writer"] == main["parent"]
                and transfer["child"] == main["writer"] and transfer["contextSha256"] == main["contextSha256"] == row["contextSha256"]
                and transfer["acceptanceSha256"] == suite["acceptanceSha256"]
                and digest(canonical(transfer)) == row["handoffSha256"], "Ordinary MAIN transfer or context changed.")
        # reconcile has already authenticated both the context bytes and the original
        # component, epoch, boot, payload, argv entry and concrete parent/child tuple.
        public.invocations.add(invocation)
        return request, stdout

    def _public_invocations(self, component: str, root: Path, suite: Object, local: Object,
                            custody: Custody) -> PublicInvocations:
        public = PublicInvocations()
        if component == "arbol-pi-driver":
            for entry in local["rows"]:
                case_id = entry["id"]
                if case_id == _H1_CASES[component] or case_id == "tests/top/programs/work_barrier.mjs":
                    continue
                image = public.image(root / ("result-" + entry["resultSha256"] + ".json"), entry["resultSha256"], 65536)
                result = _span_document(image.raw, limit=65536)
                exact_fields(result, ("version", "kind", "id", "publicCalls"))
                require(type(result["version"]) is int and result["version"] == 1
                        and result["kind"] == "abr38-unittest-success" and result["id"] == case_id
                        and isinstance(result["publicCalls"], list) and len(result["publicCalls"]) <= 128,
                        "Ordinary calls are not bound to the actual original unittest result.")
                calls: dict[str, list[tuple[str, bool, str | None]]] = {}
                proofs: dict[str, bytes] = {}
                for row in result["publicCalls"]:
                    require(isinstance(row, dict), "Malformed ordinary call witness.")
                    request, stdout = self._public_call(public, component, root, suite, case_id, row, custody)
                    outcome = verify_pi_public_output(request, stdout, row["waitStatus"], row["refusal"])
                    calls.setdefault(row["fixture"], []).append(outcome)
                    if outcome[0] == "identity" and outcome[2] is None:
                        parsed = canonical(document(stdout, limit=65536))
                        require(proofs.setdefault(row["fixture"], parsed) == parsed,
                                "Pi concurrent capture, relabel or restart changed the original returned proof.")
                pi_public_case(case_id, calls)
        if component == "arbol-codex-driver":
            for entry in local["rows"]:
                case_id = entry["id"]
                if case_id == _H1_CASES[component]:
                    continue
                image = public.image(root / ("result-" + entry["resultSha256"] + ".json"), entry["resultSha256"], 65536)
                wrapper = _span_document(image.raw, limit=65536)
                exact_fields(wrapper, ("version", "kind", "id", "status", "resultHex"))
                require(type(wrapper["version"]) is int and wrapper["version"] == 1
                        and wrapper["kind"] == "abr38-actual-local-result" and wrapper["status"] == "passed"
                        and wrapper["id"] == case_id and isinstance(wrapper["resultHex"], str)
                        and re.fullmatch(r"(?:[a-f0-9]{2})+", wrapper["resultHex"]) is not None,
                        "Codex original success envelope differs.")
                success = _span_document(bytes.fromhex(wrapper["resultHex"]), limit=65536)
                exact_fields(success, ("version", "kind", "id", "publicCallsSha256"))
                require(type(success["version"]) is int and success["version"] == 1 and success["id"] == case_id
                        and success["kind"] == "abr38-unittest-success" and valid_hash(success["publicCallsSha256"]),
                        "Codex public calls are not bound to the actual case result.")
                calls_file = public.image(root / ("public-calls-" + success["publicCallsSha256"] + ".json"),
                                          success["publicCallsSha256"], 1024 * 1024)
                grouped = _span_document(calls_file.raw, limit=1024 * 1024)
                exact_fields(grouped, ("case", "publicCalls"))
                require(grouped["case"] == case_id and isinstance(grouped["publicCalls"], list)
                        and len(grouped["publicCalls"]) <= 128, "Codex public call file belongs to another case.")
                case_calls: dict[str, list[tuple[list[str], bytes, int, str | None]]] = {}
                for row in grouped["publicCalls"]:
                    require(isinstance(row, dict), "Malformed Codex ordinary call witness.")
                    request, stdout = self._public_call(public, component, root, suite, case_id, row, custody)
                    case_calls.setdefault(row["fixture"], []).append((request, stdout, row["waitStatus"], row["refusal"]))
                codex_public_case(case_id, case_calls)
        require({w["invocation"] for w in custody.writers} == {suite["invocation"], *public.invocations}
                and {h["invocation"] for h in custody.handoffs} == {suite["invocation"], *public.invocations},
                "A provider root or accepted handoff is absent from the source-attributed whole-unit call set.")
        return public

    def verify_h1_ready(self, component: str, *, baseline: Baseline, child: OwnedChild,
                        case: str, schedule: H1Schedule, ready_raw: bytes) -> H1View:
        """Read only owned fixture bytes AFTER exact real runtime/M-D validation.

        No State/Accounts/native API, authority borrowing, report trust flag or
        raw metadata read before the actual candidate/source verification.
        """
        self.workspace.verify(self.evidence)
        self.scope.recheck()
        require(component in COMPONENTS and self.scope == baseline.scopes[component]
                and digest(baseline.gate_bytes) == self.scope.gate.digest
                and re.fullmatch(r"[0-9a-f]{32}", case, re.ASCII) is not None,
                "H1 subject/case is not the exact original fixture group.")
        payload = self.scope.producer(component)
        inventory_raw = schedule.verify(payload)
        require(not child.reaped and child.owner.live(parent=os.getpid()), "H1 provider is not actually owned/live.")
        ready = _span_document(ready_raw, limit=4096)
        exact_fields(ready, ("version", "kind", "case", "reportSha256"))
        require(type(ready["version"]) is int and ready["version"] == 1
                and ready["kind"] == "helper-span-ready" and ready["case"] == case
                and valid_hash(ready["reportSha256"]), "Wrong finite H1 ready frame.")
        authority = Authority(self.workspace.registry, component)
        with authority.mutex():
            for expected_identity in baseline.authority_identities.values():
                directory = Path(expected_identity["path"])
                identity = directory_identity(directory)
                info = physical_owned(directory, directory=True)
                require({**identity, "uid": info.st_uid, "mode": stat.S_IMODE(info.st_mode)} == expected_identity,
                        "Original fixture/shared/component authority directory changed.")
            require(lock_identity(authority, "admission.lock") == baseline.locks[component]["admission"]
                    and lock_identity(authority, "control.lock") == baseline.locks[component]["control"],
                    "Original physical H1 authority/locks changed.")
            control = normal_control(authority, epoch=baseline.epochs[component], candidate=self.scope)
            require(control["epoch"] == baseline.epochs[component] and boot_uuid() == baseline.boot,
                    "H1 control epoch/actual boot changed.")
            custody = reconcile(authority, persist_unknown=False, candidate=self.scope)
            require(not custody.unknown and custody.active == 2 and custody.pending == 0,
                    "H1 does not have exactly active Suite + independent helper.")
            roots = [row for row in custody.writers if row["parent"] is None
                     and {key: row[key] for key in ("pid", "startedAt")} == child.owner.object()]
            require(len(roots) == 1 and roots[0]["phase"] == "terminal"
                    and {key: roots[0][key] for key in ("pid", "startedAt")} == child.owner.object(),
                    "Actual fixed provider/root transfer differs from owned Popen.")
            roots_context = [row for row in custody.handoffs if row["parent"] == roots[0]["writer"]
                             and row["invocation"] == roots[0]["invocation"]]
            require(len(roots_context) == 1, "Ambiguous actual whole-unit Suite transfer.")
            suite_handoff = roots_context[0]
            require(suite_handoff["role"] == "helper" and suite_handoff["entry"] == "scripts/check_build.py"
                    and suite_handoff["phase"] == "accepted", "Suite is not the fixed admitted unit helper.")
            suite_raw = read_bytes(authority.folder / "handoffs" / (suite_handoff["handoff"] + ".context.json"))
            suite_context = document(suite_raw)
            normal_context(suite_context)
            require(roots[0] == {"version": 1, "invocation": suite_context["invocation"],
                "writer": suite_context["parent"]["writer"], "parent": None, "component": component,
                "epoch": baseline.epochs[component], "payloadSha256": payload.digest, "boot": baseline.boot,
                **child.owner.object(), "phase": "terminal", "contextSha256": None},
                "Original provider root differs from independent exact process/tuple/epoch/boot bindings.")
            require(valid_token(suite_context["invocation"]), "Invalid actual H1 invocation token.")
            root = self.workspace.registry / ".driver-qualification/fixtures" / suite_context["invocation"] / case
            root_identity = directory_identity(root)
            images: dict[str, FileImage] = {}
            for name, limit in _H1_FILES.items():
                images[name] = read_image(root / name, limit=limit)
                require((root / name).lstat().st_nlink == 1, "Hard-linked H1 fixture evidence is forbidden.")
            owner = _span_document(images[".fixture-owner.json"].raw, limit=4096)
            require(owner == {"version": 1, "case": case, "component": component,
                              "invocation": suite_context["invocation"], "parentWriter": suite_context["writer"],
                              "payloadSha256": payload.digest} and type(owner["version"]) is int,
                    "H1 physical fixture owner differs from actual Suite.")
            base = _span_document(images["phase-report.json"].raw, limit=1024 * 1024)
            exact_fields(base, ("version", "kind", "component", "build", "payloadSha256", "invocation", "writer",
                                "contextSha256", "selected", "pendingExternal", "inventorySha256"))
            require(type(base["version"]) is int and base["version"] == 1
                    and base["kind"] == "abr38-inner-phase-only" and base["component"] == component
                    and base["build"] == payload.build and base["payloadSha256"] == payload.digest
                    and base["invocation"] == suite_context["invocation"] and base["writer"] == suite_context["writer"]
                    and base["contextSha256"] == digest(suite_raw), "Original base report does not bind actual Suite.")
            selected, pending = _span_ids(base["selected"]), _span_ids(base["pendingExternal"])
            schedule.phase.validate(selected, pending, base["inventorySha256"])
            require(selected == schedule.order and digest(inventory_raw) == base["inventorySha256"],
                    "Base report shortened/reordered the actual full local schedule.")
            local = _span_document(images["local-results.json"].raw, limit=1024 * 1024)
            exact_fields(local, ("version", "kind", "component", "inventorySha256", "selectedSha256", "h1CaseId", "rows"))
            require(type(local["version"]) is int and local["version"] == 1
                    and local["kind"] == "abr38-helper-span-local-results" and local["component"] == component
                    and local["inventorySha256"] == base["inventorySha256"]
                    and local["selectedSha256"] == digest(evidence_bytes(list(selected), limit=1024 * 1024))
                    and local["h1CaseId"] == _H1_CASES[component]
                    and isinstance(local["rows"], list) and len(local["rows"]) == len(selected),
                    "Local-results identity/full-order/hash differs.")
            for expected_id, row in zip(selected, local["rows"], strict=True):
                require(isinstance(row, dict), "Invalid bounded local-result row.")
                exact_fields(row, ("id", "localStatus", "helperSpanStatus", "resultSha256"))
                require(row["id"] == expected_id and valid_hash(row["resultSha256"]),
                        "Local result is missing/duplicated/reordered/unexecuted.")
                require((row["localStatus"], row["helperSpanStatus"]) ==
                        (("h1-preconditions-done", "pending") if expected_id == _H1_CASES[component]
                         else ("passed", "not-applicable")),
                        "Failed/skipped/unavailable/pending local work cannot arm H1 or a complete check.")
            public = self._public_invocations(component, root, suite_context, local, custody)
            report = _span_document(images["helper-span.json"].raw, limit=16 * 1024)
            exact_fields(report, ("version", "kind", "case", "component", "phaseReportSha256", "localResultsSha256",
                                  "inventorySha256", "suite", "helper", "actorReadySha256", "admissionLock", "pendingExternal"))
            require(type(report["version"]) is int and report["version"] == 1
                    and report["kind"] == "abr38-preterminal-helper-span" and report["case"] == case
                    and report["component"] == component and images["helper-span.json"].sha256 == ready["reportSha256"]
                    and report["phaseReportSha256"] == images["phase-report.json"].sha256
                    and report["localResultsSha256"] == images["local-results.json"].sha256
                    and report["actorReadySha256"] == images["actor-ready.json"].sha256
                    and report["inventorySha256"] == base["inventorySha256"]
                    and _span_ids(report["pendingExternal"]) == pending
                    and report["admissionLock"] == baseline.locks[component]["admission"],
                    "Supplemental H1 report does not bind immutable original artifacts/scope.")
            require(isinstance(report["admissionLock"], dict), "Invalid original H1 lock identity object.")
            exact_fields(report["admissionLock"], ("device", "inode"))
            require(type(report["admissionLock"]["device"]) is int and report["admissionLock"]["device"] >= 0
                    and type(report["admissionLock"]["inode"]) is int and report["admissionLock"]["inode"] > 0,
                    "H1 lock identity must use actual nonboolean device/inode integers.")
            actor_ready = _span_document(images["actor-ready.json"].raw, limit=4096)
            require(actor_ready == {"version": 1, "kind": "actor-ready", "case": case,
                                    "action": "lease-hold", "window": "H1-independent-lease"}
                    and type(actor_ready["version"]) is int, "Actual actor-ready is not the fixed H1 frame.")
            # Selector is bound by the authored fixed local case, never received
            # as a command/path/dispatch choice over any outer control channel.
            require(isinstance(report["suite"], dict) and isinstance(report["helper"], dict),
                    "Invalid fixed H1 producer/participant objects.")
            exact_fields(report["suite"], ("invocation", "writer", "contextSha256", "pid", "startedAt"))
            exact_fields(report["helper"], ("entry", "invocation", "writer", "handoff", "contextSha256", "pid", "startedAt"))
            helper_id = report["helper"]["handoff"]
            require(valid_token(helper_id), "Invalid canonical helper handoff token.")
            helper_raw = read_bytes(authority.folder / "handoffs" / (helper_id + ".context.json"))
            helper_context = document(helper_raw)
            normal_context(helper_context)
            contexts = ((suite_context, suite_raw, suite_handoff, "scripts/check_build.py"),
                        (helper_context, helper_raw, read(authority.folder / "handoffs" / (helper_id + ".json")),
                         "tests/identity_actor.py"))
            participants: list[ExactProcess] = []
            for context, raw, handoff, entry in contexts:
                validate("handoff", handoff)
                expected_parent = roots[0] if entry == "scripts/check_build.py" else read(
                    authority.folder / "writers" / suite_context["invocation"] / (suite_context["writer"] + ".json"))
                require(context["role"] == "helper" and context["registry"] == str(self.workspace.registry)
                        and context["registrySha256"] == digest(canonical(authority.identity))
                        and context["component"] == component and context["epoch"] == baseline.epochs[component]
                        and context["boot"] == baseline.boot and context["invocation"] == roots[0]["invocation"]
                        and context["payloadSha256"] == payload.digest
                        and context["acceptanceSha256"] == self.scope.acceptance_sha256 and context["entry"] == entry
                        and context["parent"] == {"writer": expected_parent["writer"],
                                                **{key: expected_parent[key] for key in ("pid", "startedAt")}},
                        "Actual helper context does not bind fixed parent/entry/tuple/epoch/boot/acceptance.")
                require(handoff == {"version": 1, "handoff": context["handoff"], "component": component,
                    "invocation": context["invocation"], "parent": context["parent"]["writer"], "child": context["writer"],
                    "epoch": context["epoch"], "payloadSha256": payload.digest, "phase": "accepted", "nonce": context["nonce"],
                    "contextSha256": digest(raw), "role": "helper", "entry": entry,
                    "acceptanceSha256": self.scope.acceptance_sha256, "challenge": handoff["challenge"]}
                        and valid_token(handoff["challenge"]), "Actual accepted ready/go/started handoff differs.")
                writer = read(authority.folder / "writers" / context["invocation"] / (context["writer"] + ".json"))
                expected_writer = {"version": 1, "invocation": context["invocation"], "writer": context["writer"],
                    "parent": context["parent"]["writer"], "component": component, "epoch": context["epoch"],
                    "payloadSha256": payload.digest, "boot": baseline.boot, **context["process"],
                    "phase": "active", "contextSha256": digest(raw)}
                require(writer == expected_writer, "Actual H1 participant is not still ACTIVE with the original context.")
                participant = ExactProcess.read(context["process"])
                require(participant.live(parent=context["parent"]["pid"]), "Actual H1 kernel birth/direct-parent differs.")
                participants.append(participant)
            suite, helper = participants
            require(report["suite"] == {"invocation": suite_context["invocation"], "writer": suite_context["writer"],
                                        "contextSha256": digest(suite_raw), **suite.object()}
                    and report["helper"] == {"entry": "tests/identity_actor.py", "invocation": helper_context["invocation"],
                        "writer": helper_context["writer"], "handoff": helper_context["handoff"],
                        "contextSha256": digest(helper_raw), **helper.object()}, "H1 claimed participants are not actual verified processes.")
            for writer in custody.writers:
                if writer["invocation"] == suite_context["invocation"] and writer["writer"] in (
                        roots[0]["writer"], suite_context["writer"], helper_context["writer"]):
                    continue
                require(writer["phase"] == "terminal" and not ExactProcess.read(
                    {key: writer[key] for key in ("pid", "startedAt")}).live(),
                    "Another metadata helper is not genuinely finished before H1 span.")
            view = H1View(component, case, root, root_identity, images, suite, helper, suite_context, helper_context,
                          digest(suite_raw), digest(helper_raw), lock_identity(authority, "admission.lock"),
                          {"writers": list(custody.writers), "handoffs": list(custody.handoffs)},
                          verified_custody_images(authority, custody), public)
            view.recheck_files()
        self.scope.recheck()
        view.recheck_files()
        require(child.owner.live(parent=os.getpid()) and suite.live(parent=child.owner.pid)
                and helper.live(parent=suite.pid), "H1 process ownership changed during complete report validation.")
        return view

    def verify_terminal_armed(self, component: str, *, baseline: Baseline, collector: TerminalSpanCollector,
                              view: H1View, schedule: H1Schedule, terminal: TerminalSchedule,
                              sources: Object, armed_raw: bytes, original_markers: MarkerImage,
                              original_control: Object) -> TerminalView:
        """Observe preserved bytes/kernel/custody only; never call Suite State.

        STOP/source-coupled provider progress and the raw sole-Suite SH probe
        remain independent case obligations, performed before genuine CONT.
        This validator cannot turn hash receipts into an actual wait by itself.
        """
        self.scope.recheck()
        view.recheck_files()
        require(component == view.component and collector.child.owner.live(parent=os.getpid())
                and view.suite.live(parent=collector.child.owner.pid) and not view.helper.live(),
                "Terminal evidence does not belong to retained actual participants.")
        armed = _span_document(armed_raw, limit=4096)
        exact_fields(armed, ("version", "kind", "case", "intentSha256"))
        require(type(armed["version"]) is int and armed["version"] == 1
                and armed["kind"] == "terminal-close-armed" and armed["case"] == view.case
                and valid_hash(armed["intentSha256"]), "Wrong canonical terminal notification.")
        images: dict[str, FileImage] = {}

        def preserved(name: str, limit: int) -> bytes:
            image = read_image(view.root / name, limit=limit)
            require((view.root / name).lstat().st_nlink == 1, "Linked terminal receipt.")
            images[name] = image
            return image.raw

        intent_raw = preserved("terminal-close-intent.json", 16 * 1024)
        intent = _span_document(intent_raw, limit=16 * 1024)
        exact_fields(intent, ("version", "kind", "case", "component", "tuplePinsSha256", "phaseReportSha256",
                              "settledSha256", "suite", "provider", "admissionLock", "ownLease", "closeSite"))
        family = component.removeprefix("arbol-").removesuffix("-driver")
        require(type(intent["version"]) is int and intent["version"] == 1
                and intent["kind"] == "abr38-terminal-close-intent" and intent["case"] == view.case
                and intent["component"] == component and digest(intent_raw) == armed["intentSha256"]
                and intent["tuplePinsSha256"] == digest(terminal.tuple_document)
                and intent["phaseReportSha256"] == view.images["phase-report.json"].sha256
                and intent["suite"] == {"invocation": view.suite_context["invocation"],
                    "writer": view.suite_context["writer"], "handoff": view.suite_context["handoff"],
                    "contextSha256": view.suite_context_sha256, **view.suite.object()}
                and intent["provider"] == collector.child.owner.object()
                and intent["admissionLock"] == view.admission_lock
                and intent["closeSite"] == family + "-original-admission-close",
                "Terminal intent differs from actual retained source/tuple/context/lock bindings.")
        lease = intent["ownLease"]
        require(isinstance(lease, dict), "Missing saved actual own lease.")
        exact_fields(lease, ("fd", "device", "inode"))
        require(type(lease["fd"]) is int and lease["fd"] >= 3
                and all(type(lease[key]) is int and lease[key] >= 0 for key in ("device", "inode"))
                and {key: lease[key] for key in ("device", "inode")} == view.admission_lock,
                "Saved original own descriptor has another inode or invalid numeric identity.")
        settled_raw = preserved("terminal-close-settled.json", 1024 * 1024)
        settled = _span_document(settled_raw, limit=1024 * 1024)
        exact_fields(settled, ("version", "kind", "component", "inventorySha256", "selectedSha256",
                               "rows", "helpers", "pendingExternal"))
        base = _span_document(view.images["phase-report.json"].raw, limit=1024 * 1024)
        require(type(settled["version"]) is int and settled["version"] == 1
                and settled["kind"] == "abr38-terminal-close-settled" and settled["component"] == component
                and digest(settled_raw) == intent["settledSha256"]
                and settled["inventorySha256"] == schedule.phase.inventory_sha256
                and settled["selectedSha256"] == digest(evidence_bytes(list(schedule.order), limit=1024 * 1024))
                and settled["pendingExternal"] == base["pendingExternal"]
                and isinstance(settled["rows"], list) and len(settled["rows"]) == len(schedule.order) <= 4096
                and isinstance(settled["helpers"], list)
                and len(settled["helpers"]) == len(terminal.helper_entries) <= 4096,
                "Settled report omits/reorders full local work or deferred assertions.")
        provisional = _span_document(view.images["local-results.json"].raw, limit=1024 * 1024)
        for index, (expected_id, original, row) in enumerate(zip(schedule.order, provisional["rows"], settled["rows"], strict=True)):
            require(isinstance(row, dict) and original["id"] == expected_id
                    and (row.get("resultSha256") == original["resultSha256"]) == (expected_id != _H1_CASES[component]),
                    "Completed local result changed, or H1 reused its provisional evidence.")
            exact_fields(row, ("id", "resultSha256"))
            require(row["id"] == expected_id and valid_hash(row["resultSha256"])
                    and digest(preserved(f"terminal-local-{index:04d}.result", 65536)) == row["resultSha256"],
                    "Final actual per-ID local result bytes differ.")
        authority = Authority(self.workspace.registry, component)
        remaining = collector.terminal_interval_ends_at - time.monotonic()
        require(remaining > 0, "Terminal interval expired before mutex acquisition.")
        with authority.mutex(seconds=remaining):
            require(time.monotonic() < collector.terminal_interval_ends_at, "Terminal interval expired before custody.")
            custody = reconcile(authority, persist_unknown=False, candidate=self.scope)
            require(custody.resolved and custody.active == custody.pending == 0
                    and all(row["phase"] == "terminal" for row in custody.writers)
                    and markers(authority) == original_markers
                    and normal_control(authority, epoch=baseline.epochs[component], candidate=self.scope) == original_control
                    and lock_identity(authority, "admission.lock") == view.admission_lock
                    and not os.path.lexists(authority.folder / "taint.json"),
                    "Real terminal/control/marker/lock/custody obligations are incomplete.")
            prior_writers = {(row["invocation"], row["writer"]): row for row in view.custody["writers"]}
            actual_writers = {(row["invocation"], row["writer"]): row for row in custody.writers}
            require(set(actual_writers) == set(prior_writers)
                    and list(custody.handoffs) == view.custody["handoffs"],
                    "Terminal graph adds/removes an actual writer or accepted transfer.")
            for writer, before in prior_writers.items():
                require(actual_writers[writer] == {**before, "phase": "terminal"},
                        "Terminal writer altered original ownership/tuple/context.")
                if writer not in ((view.suite_context["invocation"], view.suite_context["writer"]),
                                  (view.suite_context["invocation"], view.suite_context["parent"]["writer"])):
                    require(not ExactProcess.read({key: before[key] for key in ("pid", "startedAt")}).live(),
                            "Another writer could still hold an independent SH.")
            handoffs = {row["handoff"]: row for row in custody.handoffs
                        if row["invocation"] == view.suite_context["invocation"]
                        and row["handoff"] != view.suite_context["handoff"]}
            seen: set[str] = set()
            for index, (entry, status, row) in enumerate(zip(terminal.helper_entries, terminal.helper_wait_statuses,
                                                            settled["helpers"], strict=True)):
                require(isinstance(row, dict), "Malformed final helper row.")
                exact_fields(row, ("invocation", "writer", "handoff", "contextSha256", "pid", "startedAt",
                                   "waitStatus", "resultSha256", "terminalRecordSha256", "ackEvidenceSha256"))
                require(all(valid_token(row[key]) for key in ("invocation", "writer", "handoff"))
                        and all(valid_hash(row[key]) for key in ("contextSha256", "resultSha256",
                            "terminalRecordSha256", "ackEvidenceSha256"))
                        and type(row["waitStatus"]) is int and row["waitStatus"] == status
                        and row["handoff"] not in seen and row["handoff"] in handoffs,
                        "Missing/duplicate/failed actual helper wait/ACK evidence.")
                seen.add(row["handoff"])
                prefix = f"terminal-helper-{index:04d}."
                if component == "arbol-claude-driver" and index == 10:
                    require(entry == "bin/metadata-helper.py" and
                            not os.path.lexists(view.root / (prefix + "context")),
                            "Private broker registration context must not be copied into reports.")
                    context_raw = read_bytes(authority.folder / "handoffs" / (row["handoff"] + ".context.json"))
                else:
                    context_raw = preserved(prefix + "context", 65536)
                terminal_raw = preserved(prefix + "terminal", 65536)
                result_raw = preserved(prefix + "result", 65536)
                ack_raw = preserved(prefix + "ack", 65536)
                context = document(context_raw, limit=65536)
                normal_context(context)
                handoff = handoffs[row["handoff"]]
                expected_writer = actual_writers.get((row["invocation"], row["writer"]))
                require(expected_writer is not None and handoff["entry"] == entry
                        and handoff["phase"] == "accepted" and handoff["child"] == row["writer"]
                        and handoff["contextSha256"] == row["contextSha256"] == digest(context_raw)
                        and read_bytes(authority.folder / "handoffs" / (row["handoff"] + ".context.json")) == context_raw
                        and evidence_bytes(expected_writer, limit=65536) == terminal_raw
                        and digest(terminal_raw) == row["terminalRecordSha256"]
                        and digest(result_raw) == row["resultSha256"]
                        and digest(ack_raw) == row["ackEvidenceSha256"]
                        and context["entry"] == entry and context["handoff"] == row["handoff"]
                        and context["invocation"] == row["invocation"] == view.suite_context["invocation"]
                        and context["writer"] == row["writer"]
                        and context["process"] == {key: row[key] for key in ("pid", "startedAt")}
                        and context["parent"]["writer"] == handoff["parent"]
                        and all(context[key] == view.suite_context[key] for key in
                            ("component", "epoch", "boot", "payloadSha256", "acceptanceSha256"))
                        and not ExactProcess.read(context["process"]).live(),
                        "Helper receipts do not bind actual completed whole graph/context/source/result.")
                if row["handoff"] == view.helper_context["handoff"]:
                    require(status == 0 and context == view.helper_context,
                            "Positive H1 must really complete with zero wait status and its original context.")
                # Exact returned/joined ACK API and actual owner wait are
                # source-specific duties of the independently pinned oracle;
                # this hash-bound receipt is never itself a success flag.
                _span_document(ack_raw, limit=65536)
            require(seen == set(handoffs) and view.helper_context["handoff"] in seen,
                    "An actual helper is omitted from the complete fixed settlement.")
            terminal_sources = verified_custody_images(authority, custody)
            before, after = view.custody_sources["writers"], terminal_sources["writers"]
            transitioned = {f"{context['invocation']}/{context['writer']}.json"
                            for context in (view.suite_context, view.helper_context)}
            require(terminal_sources["handoffs"] == view.custody_sources["handoffs"]
                    and after.root == before.root and after.entries.keys() == before.entries.keys()
                    and all(after.entries[path] == row for path, row in before.entries.items() if path not in transitioned),
                    "A terminal writer, accepted handoff or immutable context changed since H1.")
        result = TerminalView(view, images, intent, settled, sources, original_markers, original_control, terminal_sources)
        result.recheck_files()
        require(time.monotonic() < collector.terminal_interval_ends_at, "Terminal validation exceeded its interval.")
        return result

    def verify_terminal_closure(self, component: str, *, baseline: Baseline, view: TerminalView) -> None:
        """After real close/waits, acquire fresh EX on the ORIGINAL inode."""
        view.recheck_files()
        authority = Authority(self.workspace.registry, component)
        with authority.mutex():
            custody = reconcile(authority, persist_unknown=False, candidate=self.scope)
            require(custody.resolved and custody.active == custody.pending == 0
                    and all(row["phase"] == "terminal" for row in custody.writers)
                    and markers(authority) == view.markers
                    and normal_control(authority, epoch=baseline.epochs[component], candidate=self.scope) == view.control
                    and lock_identity(authority, "admission.lock") == view.h1.admission_lock,
                    "Final real closure changed original authority or left work pending.")
            descriptor = authority.open_lock("admission.lock")
            try:
                held = os.fstat(descriptor)
                require({"device": held.st_dev, "inode": held.st_ino} == view.h1.admission_lock
                        and held.st_uid == os.getuid() and stat.S_IMODE(held.st_mode) == 0o600
                        and stat.S_ISREG(held.st_mode) and held.st_nlink == 1,
                        "Final raw EX description is not the original private admission inode.")
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise ObservationFailed("Original admission SH remains held after real positive closure.") from error
                # This same mutex and freshly owned original EX delimit the final
                # comparison. A new fully terminal invocation is still foreign.
                final = reconcile(authority, persist_unknown=False, candidate=self.scope)
                require(final.resolved and all(row["phase"] == "terminal" for row in final.writers)
                        and verified_custody_images(authority, final) == view.custody_sources,
                        "Final custody differs from the exact graph verified at the terminal interval.")
                view.recheck_files()
                require(lock_identity(authority, "admission.lock") == view.h1.admission_lock,
                        "Original admission name changed during final raw EX.")
            finally:
                os.close(descriptor)  # Fresh own description only; no foreign unlock.

    def run_h1_positive(self, component: str, *, baseline: Baseline, case: str, schedule: H1Schedule,
                        terminal: TerminalSchedule, terminal_observer: TerminalObservations,
                        environment: Mapping[str, str], observations: Sequence[DeferredObservation], seconds: float) -> None:
        """Full positive unit: H1, genuine terminal interval and ALL deferred work.

        There is no H1-only positive check entry or optional terminal bypass.
        Independent complete-body admission still precedes wiring or use.
        """
        require(not self.reaped and not self.finished_external, "Each H1 check needs its own fresh external controller.")
        self.workspace.verify(self.evidence)
        self.scope.recheck()
        require(component in COMPONENTS and math.isfinite(seconds) and 20 < seconds <= 7200,
                "Invalid exact whole H1 unit budget.")
        require(self.scope == baseline.scopes[component] and digest(baseline.gate_bytes) == self.scope.gate.digest
                and re.fullmatch(r"[0-9a-f]{32}", case, re.ASCII) is not None,
                "H1 launch needs the exact original baseline/case before any spawn.")
        schedule.verify(self.scope.producer(component))
        sources = terminal.verify(self, baseline, component, terminal_observer)
        require(len({item.case_id for item in observations}) == len(observations)
                and {item.case_id for item in observations} == set(schedule.phase.required_external_ids),
                "H1 check lacks a complete static external assertion allocation.")
        from arbol_builds.driver_admission import without_authority
        child = OwnedChild(self.fixed_argv(component, self.scope.producer(component).build, "build-unit"),
                           environment=without_authority(dict(environment)), cwd=self.workspace.registry)
        try:
            collector = TerminalSpanCollector(child, case=case, seconds=seconds)
        except BaseException as setup_error:
            # The actual owned provider already exists. Even collector setup or
            # resource failure must independently attempt stop AND real wait.
            try:
                child.request_stop()
            except BaseException as error:
                setup_error.add_note("H1 setup owned stop: " + type(error).__name__)
            try:
                child.wait_owned(seconds=20)
            except BaseException as error:
                setup_error.add_note("H1 setup owned wait: " + type(error).__name__)
            for stream in (child.process.stdin, child.process.stdout, child.process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except BaseException as error:
                        setup_error.add_note("H1 setup endpoint: " + type(error).__name__)
            raise
        view: H1View | None = None
        participants_bound = False
        try:
            with collector:
                try:
                    ready_raw = collector.ready()
                    view = self.verify_h1_ready(component, baseline=baseline, child=child, case=case,
                                                schedule=schedule, ready_raw=ready_raw)
                    # Retain both future STOP targets BEFORE any fallible IO or
                    # callback. Collector unwind owns unconditional dual CONT,
                    # late mirrored STOP handling and real provider-only wait.
                    collector.bind_verified_participants(suite=view.suite, helper=view.helper)
                    participants_bound = True
                    authority = Authority(self.workspace.registry, component)
                    remaining = collector.deadline - time.monotonic()
                    require(remaining > 0, "H1 capture budget expired before original custody snapshot.")
                    with authority.mutex(seconds=remaining):
                        original_markers = markers(authority)
                        original_control = normal_control(authority, epoch=baseline.epochs[component], candidate=self.scope)
                    self.evidence.write("h1-verified-preterminal.json", {"component": component, "case": case,
                        "provider": child.owner.object(), "suite": view.suite.object(), "helper": view.helper.object(),
                        "suiteContextSha256": view.suite_context_sha256, "helperContextSha256": view.helper_context_sha256,
                        "admissionLock": view.admission_lock, "custody": reported_h1_custody(component, view.custody),
                        "reports": {name: image.evidence() for name, image in view.images.items()},
                        "readyObservedAt": collector.ready_observed_at})
                    current = self.verify_h1_ready(component, baseline=baseline, child=child, case=case,
                                                   schedule=schedule, ready_raw=ready_raw)
                    require(current == view, "H1 reports/custody/ownership changed immediately before continue.")
                    terminal_observer.precontinue(self, baseline, collector, view, schedule, ready_raw)
                    collector.continue_after_validation(report_sha256=view.images["helper-span.json"].sha256)
                    armed_raw = collector.terminal_armed()
                    collector.confirm_terminal_stops()
                    terminal_view = self.verify_terminal_armed(component, baseline=baseline, collector=collector,
                        view=view, schedule=schedule, terminal=terminal, sources=sources, armed_raw=armed_raw,
                        original_markers=original_markers, original_control=original_control)
                    terminal_observer.interval(self, baseline, collector, terminal_view)
                    terminal_view.recheck_files()
                    collector.resume_terminal()
                    captured = collector.finish_positive()
                    require(child.reaped and captured.returncode == 0 and not view.helper.live() and not view.suite.live(),
                            "Positive H1 actual helper/Suite/provider lifetimes did not finish.")
                    self.reaped.append(child)
                    self.require_finished_graph(component)
                    context, context_hash = self._runner_context(component, child)
                    require(context == view.suite_context and context_hash == view.suite_context_sha256,
                            "Finished whole runner is another actual Suite/context.")
                    view.recheck_files()  # Provisional reports cannot be rewritten as whole success.
                    terminal_view.recheck_files()
                    terminal_observer.finished(self, baseline, collector, terminal_view, captured)
                    self.verify_terminal_closure(component, baseline=baseline, view=terminal_view)
                    self.evidence.write("terminal-verified.json", {"component": component, "case": case,
                        "sources": sources, "intent": terminal_view.intent, "settled": terminal_view.settled,
                        "reports": {name: image.evidence() for name, image in terminal_view.images.items()},
                        "originalMarkers": original_markers.evidence(), "control": original_control,
                        "providerReaped": child.reaped, "returncode": captured.returncode}, limit=8 * 1024 * 1024)
                    # In particular the statically admitted H1-span-completion
                    # observer must establish actual direct-child wait/result/ACK
                    # source evidence and every resource, not merely PID absence or
                    # a reported boolean. This is no dynamically dispatched wire ID.
                    for observation in observations:
                        observation.observe(self)
                        self.finished_external.add(observation.case_id)
                    require(self.finished_external == set(schedule.phase.required_external_ids),
                            "H1 positive check returned with a deferred assertion pending.")
                    self.require_finished_graph(component)
                except BaseException as span_error:
                    # The combined collector, unlike H1-only cleanup, must
                    # CONT BOTH retained processes before TERM/wait, including
                    # delayed provider mirroring. Its context exit attempts all
                    # endpoints/targets within the same remaining bounded end.
                    span_error.add_note("Combined H1/terminal failure; retained dual-target cleanup required.")
                    if view is not None and not participants_bound:
                        # No terminal continue/STOP can yet have occurred. A
                        # failed identity binding still owes cleanup of the
                        # already independently verified preterminal targets.
                        try:
                            self._cleanup_h1_failure(collector, view, span_error)
                        except BaseException as cleanup:
                            span_error.add_note("Preterminal binding cleanup unavailable: " + type(cleanup).__name__)
                    raise
        finally:
            original = sys.exception()
            try:
                self.evidence.write("h1-interactive-capture.json", collector.raw_observation(), limit=8 * 1024 * 1024)
            except BaseException as error:
                if original is None:
                    raise
                original.add_note("Private H1 raw evidence unavailable: " + type(error).__name__)

    def _cleanup_h1_failure(self, collector: HelperSpanCollector, view: H1View,
                            original: BaseException) -> None:
        """Cancel verified descendants and the owned provider under one deadline."""
        end = min(collector.end, time.monotonic() + 20)
        collector.end = end  # Context unwind cannot begin a second cleanup budget.
        targets = {"suite": view.suite, "helper": view.helper}
        errors: list[str] = []
        states: dict[str, bool | None] = {}
        attempted: dict[str, bool] = {}
        stdin = collector.child.process.stdin
        if stdin is not None:
            try:
                stdin.close()  # Failure EOF; never a positive Suite continue.
            except BaseException as error:
                errors.append("failure-input:" + type(error).__name__)

        def observe(name: str, owner: ExactProcess) -> bool | None:
            try:
                # Orphan adoption is legitimate: only the retained PID/birth
                # gates this observation, never the former parent's liveness.
                return owner.live()
            except BaseException as error:
                errors.append(name + "-identity:" + type(error).__name__)
                return None

        for name, owner in targets.items():
            attempted[name] = False
            states[name] = observe(name, owner)
            if states[name] is True:
                attempted[name] = True
                try:
                    signal_verified(owner, signal.SIGTERM)  # Fresh birth check at send.
                except BaseException as error:
                    errors.append(name + "-stop:" + type(error).__name__)
        child = collector.child
        try:
            child.request_stop()
        except BaseException as error:
            errors.append("provider-stop:" + type(error).__name__)
        # Join the actual provider in short bounded waits while independently
        # observing each descendant. No descendant is waitpid/reap eligible here.
        while True:
            for name, owner in targets.items():
                if states[name] is True:
                    states[name] = observe(name, owner)
            remaining = end - time.monotonic()
            # Leave the last poll slice to the collector's real owned wait and
            # independent endpoint-closure attempts under this same deadline.
            if remaining <= .05 or (child.reaped and all(value is not True for value in states.values())):
                break
            if not child.reaped:
                try:
                    child.wait_owned(seconds=min(.05, remaining))
                except subprocess.TimeoutExpired:
                    pass
                except BaseException as error:
                    errors.append("provider-wait:" + type(error).__name__)
                    break
            else:
                try:
                    time.sleep(min(.05, remaining))
                except BaseException as error:
                    errors.append("participant-observation-wait:" + type(error).__name__)
                    break
        try:
            provider_cleanup = collector.abort()  # Same end; always closes owned endpoints.
        except BaseException as error:
            errors.append("provider-cleanup:" + type(error).__name__)
            provider_cleanup = {"providerReaped": child.reaped, "cleanupUnresolved": True}
        observation: Object = {"participants": {name: {**owner.object(),
            "sameBirthLive": states[name], "termAttempted": attempted[name],
            "unresolved": states[name] is not False} for name, owner in targets.items()},
            "providerCleanup": provider_cleanup, "errors": errors,
            "budgetExpired": time.monotonic() >= end,
            "observerReapedDescendant": False, "custodyResolutionClaimed": False}
        # Keep verified targets/errors in the original failure even when the
        # private evidence store itself is the reason the span failed.
        original.add_note("Verified H1 failure cleanup: " + repr(observation))
        try:
            self.evidence.write("h1-failed-participants.json", observation)
        except BaseException as error:
            original.add_note("Private H1 participant evidence unavailable: " + type(error).__name__)

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
            archive_before = ArchiveImage.capture(authority.folder / "archive")
            source_before = custody_source_images(authority)
            receipt_before = (read_bytes(authority.folder / "maintenance.json")
                              if os.path.lexists(authority.folder / "maintenance.json") else None)
        child = OwnedChild(argv, environment=without_authority(dict(environment)), cwd=self.workspace.registry)
        captured = self._collect_owned(child, seconds)
        require(captured.returncode == 0, "Actual administrative operation failed; preserve closed state.")
        result = document(captured.stdout)
        require("error" not in result, "Actual administrative operation refused.")
        archive_after = ArchiveImage.capture(authority.folder / "archive")
        witness = None
        if archive_after != archive_before:
            require(command == "drain" and result.get("phase") == "exclusive",
                    "Unaccounted archive mutation outside the actual successful production drain.")
            verify_archive_delta(archive_before, archive_after, source_before, receipt_before)
            def tuple_row(payload: Payload) -> Object:
                _, current = _registered_payload(self.workspace.registry, payload.component, payload.build)
                require(current == payload, "Actual drain payload changed.")
                return {"build": payload.build, "sourceCommit": payload.descriptor["source"]["commit"],
                        "sourceTree": payload.descriptor["source"]["tree"], "payloadSha256": payload.digest,
                        "manifestSha256": payload.descriptor["payloadManifestSha256"]}
            name = "drain-archives-" + uuid.uuid4().hex + ".json"
            raw_hash = self.evidence.write(name, {"version": 1, "kind": "abr38-actual-provider-drain-archives",
                    "component": component, "registry": authority.identity, "session": session,
                    "provider": tuple_row(self.scope.gate.provider), "producer": tuple_row(self.scope.producer(component)),
                    "gateSha256": self.scope.gate.digest,
                    "acceptanceSha256": authority.read("qualification")["acceptanceSha256"],
                    "controlBefore": before_control, "controlAfter": authority.read("control"),
                    "receiptAfter": read_bytes(authority.folder / "maintenance.json").decode("utf-8"),
                    "process": captured.owner.object(), "returncode": captured.returncode, "reaped": child.reaped,
                    "stdout": result, "before": archive_before.evidence(), "after": archive_after.evidence(),
                    "sources": {key: image.evidence() for key, image in source_before.items()},
                    "receiptBefore": None if receipt_before is None else receipt_before.decode("utf-8")},
                    limit=32 * 1024 * 1024)
            witness = ArchiveWitness(component, archive_before, archive_after, source_before, receipt_before,
                                     self.evidence.root / name, raw_hash)
            witness.verify(self.workspace)
        self.last_administration = AdministrativeCapture(component, command, session, dict(arguments),
                                                          before_control, captured, witness)
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
