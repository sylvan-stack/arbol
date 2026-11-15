"""Prospective ABR-38 closed-rollout, genuine-transition and retention cases.

The pre-boot and post-boot bodies are separate. This module never requests a
restart, supplies a replacement boot identity, or enables an owner caller.
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from driver_identity_qualification import TuplePin, require
from top.driver_state_support import (
    EvidenceRecorder,
    ExactProcess,
    Object,
    OwnedChild,
    canonical,
    digest,
    directory_identity,
    document,
    physical_owned,
    read_image,
    tree_inventory,
)
from top.test_top_driver_state_maintenance import Execute, MetadataArchive

from arbol_builds.driver_admission import (
    COMPONENTS,
    Authority,
    canonical_uuid,
    publish_bytes,
    reconcile,
    valid_token,
    without_authority,
)
from arbol_builds.driver_payload import resolve_candidate
from arbol_builds.driver_process import boot_uuid

_CUSTODY = ("writers", "handoffs", "normal-admissions", "archive", "taint.json", "maintenance.json")
_REFUSED = {"error": {"code": "builds_failed", "message": "Driver maintenance refused; preserve closed recovery authority."}}
_LIMIT = 32 * 1024 * 1024
_BUILT_INS = dict(zip(COMPONENTS, ("anthropic", "chatgpt", "xiaomi", "zai"), strict=True))

# The real provider publishes the first differing route. A one-shot observer
# interrupts before the second publication and delegates all rollback calls.
_PARTIAL = """\
import os
import sys

entry, evidence, *arguments = sys.argv[1:]
if arguments[:2] != ['driver-state', 'deploy']:
    raise SystemExit(96)
sys.argv[:] = [entry, *arguments]
sys.modules['__main__'].__file__ = entry
published = 0

def observe(frame, event, value):
    if (event != 'call' or frame.f_code.co_name != 'deploy'
            or frame.f_globals.get('__name__') != 'arbol_builds.driver_state'):
        return
    from arbol_builds import service
    original = service.publish_driver_route
    def publish(target, previous, desired):
        global published
        published += 1
        if published == 2:
            service.publish_driver_route = original
            raise OSError('ABR-38 interruption before second launcher publication')
        result = original(target, previous, desired)
        if published == 1:
            import hashlib
            import json
            with open(target, 'rb') as stream:
                actual = stream.read(1024 * 1024 + 1)
            data = {'target': str(target), 'publishedSha256': hashlib.sha256(actual).hexdigest(),
                    'bytesMatch': actual == desired[0], 'mode': os.stat(target).st_mode & 0o7777}
            descriptor = os.open(evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, 'w') as output:
                output.write(json.dumps(data, sort_keys=True, separators=(',', ':')) + '\\n')
                output.flush()
                os.fsync(output.fileno())
        return result
    service.publish_driver_route = publish

sys.setprofile(observe)
with open(entry, 'rb') as packaged:
    source = compile(packaged.read(), entry, 'exec')
exec(source, vars(sys.modules['__main__']))
"""


def _raw_image(path: Path) -> Object | None:
    if not os.path.lexists(path):
        return None
    mode = path.lstat().st_mode
    if stat.S_ISDIR(mode):
        return {"root": directory_identity(path), "entries": tree_inventory(path)}
    return read_image(path, limit=_LIMIT).evidence()


def _private_path(path: Path, root: Path, *, directory: bool) -> None:
    require(path.is_relative_to(root) and path != root, "Rollout observation escaped the disposable fixture.")
    physical_owned(path, directory=directory)


@dataclass(frozen=True)
class Caller:
    """Exact private executable belonging to the caller named in the manifest."""

    name: str
    route: Path
    executable: Path

    def disabled(self, root: Path) -> Object:
        _private_path(self.executable, root, directory=False)
        image = read_image(self.executable)
        require(image.mode == 0o600 and not os.access(self.executable, os.X_OK),
                "The actual disposable caller is still executable.")
        return image.evidence()


@dataclass(frozen=True)
class Rollout:
    root: Path
    registry: Path
    bin: Path
    provider: TuplePin
    producers: tuple[TuplePin, ...]
    manifest: Path
    callers: Path
    disabled_callers: tuple[Caller, ...]
    session: str
    environment: Mapping[str, str]

    @property
    def shared(self) -> Path:
        return self.registry / ".driver-qualification"

    @property
    def deployment(self) -> Path:
        return self.shared / "deployment.json"

    def authority(self, component: str) -> Authority:
        return Authority(self.registry, component)

    def paths(self, record: Object) -> Path:
        checkpoint = record["checkpoint"]
        require(record["session"] == self.session and valid_token(checkpoint), "Wrong rollout session or checkpoint.")
        return self.shared / "deployments" / self.session / str(checkpoint)

    def verify(self) -> Object:
        physical_owned(self.root, directory=True)
        _private_path(self.registry, self.root, directory=True)
        _private_path(self.bin, self.root, directory=True)
        _private_path(self.manifest, self.root, directory=False)
        _private_path(self.callers, self.root, directory=False)
        require(self.registry != self.bin and not self.bin.is_relative_to(self.registry)
                and canonical_uuid(self.session) and self.provider.component == "arbol"
                and tuple(pin.component for pin in self.producers) == COMPONENTS,
                "Invalid exact five-tuple disposable rollout.")
        provider = self.provider.verify(self.registry)
        images = [pin.verify(self.registry).evidence() for pin in self.producers]
        gate = read_image(self.manifest)
        gate_value = document(gate.raw)
        routes = gate_value["components"]
        require(gate_value["providerPayloadSha256"] == provider.payload.digest
                and [(row["component"], row["launcher"]) for row in routes]
                == [(name, str(self.bin / name)) for name in COMPONENTS],
                "Gate does not bind the exact sealed provider and four owned routes.")
        caller_bytes = read_image(self.callers)
        callers = document(caller_bytes.raw)
        require(bool(self.disabled_callers) and callers == {"version": 1, "callers": [
            {"name": caller.name, "route": str(caller.route), "disabled": True} for caller in self.disabled_callers]}
            and {caller.route for caller in self.disabled_callers} == {self.bin / component for component in COMPONENTS},
            "The manifest does not bind every independently observed disabled caller.")
        return {"registry": directory_identity(self.registry), "bin": directory_identity(self.bin),
                "gate": gate.evidence(), "callers": caller_bytes.evidence(),
                "disabledCallers": {caller.name: caller.disabled(self.root) for caller in self.disabled_callers},
                "provider": provider.evidence(), "producers": images}

    def capture(self, evidence: EvidenceRecorder, name: str, arguments: Sequence[str], *,
                partial: Path | None = None, refused: bool = False) -> Object:
        provider = self.provider.verify(self.registry).payload
        argv = list(provider.prefix)
        if partial is not None:
            require(arguments[:2] == ["driver-state", "deploy"] and partial.is_relative_to(self.root)
                    and not os.path.lexists(partial), "Wrong fixed partial-publication scope.")
            argv = [*argv[:2], "-c", _PARTIAL, argv[2], str(partial)]
        child = OwnedChild([*argv, *arguments], environment=without_authority(dict(self.environment)), cwd=self.registry)
        try:
            result = child.collect(seconds=120)
        finally:
            if not child.reaped:
                child.request_stop()
                child.wait_owned(seconds=20)
        evidence.write(name + ".json", {
            "arguments": list(arguments), "prefix": list(provider.prefix), "owner": result.owner.object(),
            "reaped": child.reaped, "exit": result.returncode, "stdoutHex": result.stdout.hex(),
            "stderrHex": result.stderr.hex(), "partialObserverSha256": digest(_PARTIAL.encode()) if partial else None,
        })
        value = document(result.stdout)
        require(child.reaped and not result.stderr and (result.returncode == 1 and value == _REFUSED if refused
                                                        else result.returncode == 0 and "error" not in value),
                "The actual rollout command returned the wrong protocol disposition.")
        return value

    def command(self, evidence: EvidenceRecorder, label: str, command: str, *, component: str | None = None,
                arguments: Mapping[str, str] | None = None, refused: bool = False, partial: Path | None = None) -> Object:
        argv = ["driver-state", command, "--registry-dir", str(self.registry), "--session", self.session]
        if component is not None:
            require(component in COMPONENTS, "Unexpected rollout component.")
            argv.extend(("--component", component))
        if command == "deploy":
            argv.extend(("--manifest", str(self.manifest), "--callers", str(self.callers)))
        for key, value in sorted((arguments or {}).items()):
            argv.extend(("--" + key, value))
        return self.capture(evidence, label, argv, refused=refused, partial=partial)

    def controls(self) -> dict[str, Object]:
        return {component: self.authority(component).read("control") for component in COMPONENTS}

    def custody(self) -> dict[str, Object]:
        return {component: {name: _raw_image(self.authority(component).folder / name) for name in _CUSTODY}
                for component in COMPONENTS}

    def locks(self) -> dict[str, Object]:
        return {component: {name: read_image(self.authority(component).folder / name).evidence()
                            for name in ("control.lock", "admission.lock")} for component in COMPONENTS}

    def actual_routes(self) -> dict[str, Object | None]:
        return {component: (read_image(self.bin / component, limit=1024 * 1024, private=False).evidence()
                            if os.path.lexists(self.bin / component) else None) for component in COMPONENTS}

    def require_closed(self, record: Object, *, phase: Literal["draining", "exclusive"]) -> None:
        require([row["component"] for row in record["components"]] == list(COMPONENTS), "Missing closed component.")
        for row in record["components"]:
            component = row["component"]
            require(self.authority(component).read("control") == {
                "version": 1, "phase": phase, "session": self.session, "epoch": row["epoch"],
            }, "A component does not retain its exact original closed epoch.")

    def refuse_new(self, evidence: EvidenceRecorder, label: str, *, component: str) -> None:
        stage = self.root / ("refused-state-" + uuid.uuid4().hex)
        before = self.custody()
        command = ["--qualification-launch", str(self.registry), component,
                   next(pin.build for pin in self.producers if pin.component == component), "driver", "--",
                   "--state-dir", str(stage), "info"]
        self.capture(evidence, label, command, refused=True)
        require(not os.path.lexists(stage) and self.custody() == before,
                "A closed rollout admitted a new writer or modified custody.")


def _target_inputs(subject: Rollout, targets: Mapping[str, Execute]) -> Object:
    require(set(targets) == set(COMPONENTS) and len({path for item in targets.values() for path in
            (item.state, item.backup)}) == 2 * len(COMPONENTS), "Incomplete or shared conversion targets.")
    result: Object = {}
    for pin in subject.producers:
        target = targets[pin.component]
        require(target.operation == "upgrade" and target.source is None and target.subscription is None,
                "All-four continuation needs prepared format 1 conversion targets.")
        for path in (target.state, target.backup):
            _private_path(path, subject.root, directory=True)
            require(not path.is_relative_to(subject.registry) and not subject.registry.is_relative_to(path),
                    "Recovery target overlaps the registered authorities.")
        require(read_image(target.state / "format").raw.strip() == b"1" and not tree_inventory(target.backup),
                "Recovery needs original format 1 bytes and empty output per component.")
        result[pin.component] = {"arguments": target.arguments(pin.build), "state": _raw_image(target.state),
                                 "backup": _raw_image(target.backup)}
    return result


def prepare_transition(subject: Rollout, evidence: EvidenceRecorder, *, targets: Mapping[str, Execute]) -> str:
    """Freeze actual preconditions before asking for a separate real transition."""
    inputs = subject.verify()
    target_inputs = _target_inputs(subject, targets)
    old_boot = boot_uuid()
    deploy = subject.command(evidence, "closed-deploy", "deploy")
    record = document(read_image(subject.deployment).raw)
    require(deploy == {"version": 1, "session": subject.session, "phase": "awaiting-boot",
                       "checkpoint": record["checkpoint"], "callersMayEnable": False}
            and record["phase"] == "awaiting-boot" and record["oldBoot"] == old_boot
            and record["newBoot"] is None and record["registrySha256"] == digest(canonical(inputs["registry"]))
            and record["gateSha256"] == inputs["gate"]["sha256"]
            and record["callersSha256"] == inputs["callers"]["sha256"], "Invalid real pre-boot checkpoint.")
    subject.require_closed(record, phase="draining")
    folder = subject.paths(record)
    before_checkpoint = read_image(folder / "checkpoint.json")
    checkpoint = document(before_checkpoint.raw)
    require(all(checkpoint[key] == record[key] for key in (
                "session", "checkpoint", "registrySha256", "gateSha256", "callersSha256", "oldBoot"))
            and read_image(folder / "manifest.json").sha256 == inputs["gate"]["sha256"]
            and read_image(folder / "callers.json").sha256 == inputs["callers"]["sha256"],
            "Actual checkpoint lost its original gate, callers, boot or own session.")
    custody = subject.custody()
    require(any(image["taint.json"] is not None or (image["writers"] is not None and image["writers"]["entries"])
                for image in custody.values()), "Missing actual old custody or legacy taint before transition.")
    routes = subject.actual_routes()
    for row in record["components"]:
        route = routes[row["component"]]
        require(route is not None and route["sha256"] == row["launcherSha256"],
                "The actual emitted route does not match the closed checkpoint.")
    for component in COMPONENTS:
        subject.refuse_new(evidence, "before-boot-refusal-" + component, component=component)
    subject.command(evidence, "unchanged-boot-refusal", "drain", component=COMPONENTS[0], refused=True)
    require(boot_uuid() == old_boot and read_image(folder / "checkpoint.json") == before_checkpoint
            and document(read_image(subject.deployment).raw) == record and subject.custody() == custody
            and not os.path.lexists(folder / "recovery.json") and subject.verify() == inputs
            and _target_inputs(subject, targets) == target_inputs,
            "Same-boot refusal changed the input checkpoint, callers or old custody.")
    return evidence.write("genuine-transition-before.json", {
        "record": record, "recordSha256": digest(canonical(record)), "checkpoint": before_checkpoint.evidence(),
        "inputs": inputs, "targets": target_inputs, "custody": custody, "locks": subject.locks(), "routes": routes,
    })


CheckpointFault = Literal["wrong-checkpoint", "malformed-boot", "admission-fingerprint"]


def refuse_altered_checkpoint(subject: Rollout, evidence: EvidenceRecorder, *, fault: CheckpointFault) -> None:
    """A separate disposable negative subject never becomes a transition input."""
    inputs = subject.verify()
    actual_boot = boot_uuid()
    record = document(read_image(subject.deployment).raw)
    folder = subject.paths(record)
    require(record["phase"] == "awaiting-boot" and record["oldBoot"] == actual_boot and record["newBoot"] is None
            and not os.path.lexists(folder / "recovery.json"), "Wrong isolated checkpoint fault subject.")
    path = subject.deployment if fault == "malformed-boot" else folder / "checkpoint.json"
    original = read_image(path)
    value = document(original.raw)
    if fault == "wrong-checkpoint":
        value["callersSha256"] = digest(b"ABR-38 wrong saved caller hash")
    elif fault == "admission-fingerprint":
        value["components"][0]["admissionsSha256"] = digest(b"ABR-38 wrong normal-admissions hash")
    else:
        require(fault == "malformed-boot", "Unknown fixed checkpoint fault.")
        value["oldBoot"] = "not-a-boot-uuid"
    evidence.write_bytes("original-checkpoint-input.json", original.raw)
    publish_bytes(path, canonical(value))
    injected = read_image(path)
    custody = subject.custody()
    for operation in ("begin", "drain"):
        subject.command(evidence, "changed-checkpoint-" + operation, operation, component=COMPONENTS[0], refused=True)
    require(read_image(path) == injected and not os.path.lexists(folder / "recovery.json")
            and subject.verify() == inputs and boot_uuid() == actual_boot and subject.custody() == custody,
            "Rejected recorded UUID/checkpoint changed the real boot, custody or caller inputs.")
    subject.require_closed(record, phase="draining")


def partial_publication_failure(subject: Rollout, evidence: EvidenceRecorder) -> None:
    inputs = subject.verify()
    gate = document(read_image(subject.manifest).raw)
    before = subject.actual_routes()
    before_gate = _raw_image(subject.shared / "gate.json")
    require(sum(_contents(before[row["component"]]) != (row["launcherSha256"], 0o755)
                for row in gate["components"]) >= 2,
            "Partial publication requires two genuinely differing launcher targets.")
    boot = boot_uuid()
    partial = subject.root / ("interrupted-route-" + subject.session + ".json")
    subject.command(evidence, "partial-deploy-refusal", "deploy", refused=True, partial=partial)
    published = document(read_image(partial).raw)
    failed = document(read_image(subject.deployment).raw)
    expected = next(row for row in gate["components"] if row["launcher"] == published["target"])
    after = subject.actual_routes()
    require(published["bytesMatch"] is True and published["publishedSha256"] == expected["launcherSha256"]
            and published["mode"] == 0o755 and failed["phase"] == "failed-closed"
            and failed["oldBoot"] == boot == boot_uuid() and failed["newBoot"] is None
            and all(_contents(before[name]) == _contents(after[name]) for name in COMPONENTS)
            and _contents(_raw_image(subject.shared / "gate.json")) == _contents(before_gate)
            and not os.path.lexists(subject.paths(failed) / "checkpoint.json") and subject.verify() == inputs,
            "Partial genuine publication did not return to its exact safe route bytes and disabled callers.")
    subject.require_closed(failed, phase="draining")


def _contents(image: Object | None) -> tuple[object, object] | None:
    return None if image is None else (image["sha256"], image["mode"])


def _verify_archived_custody(subject: Rollout, record: Object, current_boot: str, before: Object) -> Object:
    observed: Object = {}
    for component in COMPONENTS:
        folder = subject.authority(component).folder / "boot-archive" / record["checkpoint"]
        inventory = read_image(folder / "inventory.json")
        manifest = document(inventory.raw)
        require(manifest["component"] == component and manifest["oldBoot"] == record["oldBoot"]
                and manifest["newBoot"] == current_boot and manifest["session"] == subject.session
                and manifest["checkpoint"] == record["checkpoint"]
                and [row["name"] for row in manifest["entries"]] == list(_CUSTODY)
                and document(read_image(folder / "complete.json").raw) == {
                    "version": 1, "kind": "driver-boot-custody-complete", "inventorySha256": inventory.sha256,
                }, "Boot recovery did not publish the exact archive receipt.")
        for name in _CUSTODY:
            original = before["custody"][component][name]
            archived = _raw_image(folder / name)
            require(_same_moved_entry(original, archived, folder / name),
                    "Boot archive does not preserve actual old custody bytes and identities.")
        observed[component] = {"inventorySha256": inventory.sha256, "manifest": manifest}
    return observed


def _same_moved_entry(original: Object | None, archived: Object | None, new: Path) -> bool:
    if original is None or archived is None:
        return original is None and archived is None
    if "root" not in original:
        return archived == {**original, "path": str(new)}
    return archived == {"root": {**original["root"], "path": str(new)}, "entries": original["entries"]}


def resume_genuine_transition(subject: Rollout, evidence: EvidenceRecorder, *, previous: Path, previous_sha256: str,
                               targets: Mapping[str, Execute]) -> Object:
    """Execute only under the later reviewed, explicitly scoped real boot continuation."""
    _private_path(previous, subject.root, directory=False)
    before_raw = read_image(previous, limit=_LIMIT)
    require(before_raw.sha256 == previous_sha256 and set(targets) == set(COMPONENTS),
            "Wrong frozen pre-boot evidence or incomplete recovery target set.")
    before = document(before_raw.raw, limit=_LIMIT)
    record = before["record"]
    new_boot = boot_uuid()
    require(canonical_uuid(new_boot) and canonical_uuid(record["oldBoot"]) and new_boot != record["oldBoot"]
            and read_image(subject.deployment).sha256 == before["recordSha256"] and subject.verify() == before["inputs"]
            and subject.custody() == before["custody"] and subject.locks() == before["locks"]
            and subject.actual_routes() == before["routes"] and _target_inputs(subject, targets) == before["targets"],
            "No genuine kernel transition with the original closed scope and old custody.")
    subject.require_closed(record, phase="draining")
    folder = subject.paths(record)
    require(read_image(folder / "checkpoint.json").evidence() == before["checkpoint"]
            and not os.path.lexists(folder / "recovery.json"), "The original pre-journal checkpoint is unavailable.")
    for component in COMPONENTS:
        begin = subject.command(evidence, "new-boot-begin-" + component, "begin", component=component)
        require(begin["phase"] == "draining" and begin["session"] == subject.session
                and subject.custody() == before["custody"] and not os.path.lexists(folder / "recovery.json")
                and read_image(subject.deployment).sha256 == before["recordSha256"],
                "Same-session begin on the new boot altered the old custody before drain.")
        subject.refuse_new(evidence, "new-boot-closed-" + component, component=component)

    for component in COMPONENTS:
        reply = subject.command(evidence, "new-boot-drain-" + component, "drain", component=component)
        require(reply["phase"] == "exclusive" and reply["session"] == subject.session,
                "Genuine boot recovery did not drain the actual component.")
    subject.require_closed(record, phase="exclusive")
    recovery = document(read_image(folder / "recovery.json").raw)
    recovered = document(read_image(subject.deployment).raw)
    require(recovered["phase"] == "boot-verified" and recovered["oldBoot"] == record["oldBoot"]
            and recovered["newBoot"] == new_boot and recovery["newBoot"] == new_boot
            and recovery["phase"] == "complete" and recovery["components"] == [
                {"component": component, "phase": "archived"} for component in COMPONENTS]
            and read_image(folder / "checkpoint.json").evidence() == before["checkpoint"]
            and subject.locks() == before["locks"], "Recovery did not retain the original stable checkpoint and locks.")
    archived = _verify_archived_custody(subject, record, new_boot, before)

    results = {}
    for pin in subject.producers:
        target = targets[pin.component]
        actual = subject.command(evidence, "execute-" + pin.component, "execute", component=pin.component,
                                 arguments=target.arguments(pin.build))
        path = subject.authority(pin.component).folder / "sessions" / subject.session / "result.json"
        image = read_image(path)
        result = document(image.raw)
        archive = MetadataArchive.read(target.backup / "before")
        require(actual["phase"] == "exclusive" and actual["result"] == str(path)
                and result["component"] == pin.component and result["session"] == subject.session
                and result["epoch"] == subject.authority(pin.component).read("control")["epoch"]
                and result["payloadSha256"] == pin.payload_sha256 and result["operation"] == "upgrade"
                and result["stateDirectorySha256"] == digest(str(target.state).encode())
                and result["backupSha256"] == archive.sha256 and archive.format == 1
                and read_image(target.state / "format").raw == b"2\n"
                and document(read_image(target.state / "identity.json").raw)["generation"] == result["generation"],
                "Exact format conversion and result binding were lost before all-four finish.")
        marker = read_image(target.state / "identity-maintenance.json").raw
        marker_value = document(marker)
        require(marker_value["attempt"] == result["attempt"] and marker_value["phase"] == "complete"
                and marker_value["backupSha256"] == archive.sha256, "Wrong actual completed local marker.")
        results[pin.component] = (image, result, marker)

    for component in COMPONENTS:
        image, result, marker = results[component]
        response = subject.command(evidence, "finish-" + component, "finish", component=component,
                                   arguments={"result": str(image.path)})
        if component != COMPONENTS[-1]:
            require(response["phase"] == "exclusive" and response["callersMayEnable"] is False
                    and response["deployment"] == "awaiting-components",
                    "An early component finish signalled readiness.")
            subject.require_closed(record, phase="exclusive")
            for name in COMPONENTS:
                subject.refuse_new(evidence, "not-all-ready-" + component + "-" + name, component=name)
        else:
            require(response["phase"] == "normal" and response["callersMayEnable"] is True
                    and response["deployment"] == "complete", "Final finish did not reach the actual global commit.")
        history = image.path.parent / "attempts" / result["attempt"]
        require(image == read_image(image.path) and read_image(history / "finished-marker.json").raw == marker
                and not os.path.lexists(targets[component].state / "identity-maintenance.json")
                and result["format"] == 2, "Finish changed a verified result or left the original marker active.")

    reopened = document(read_image(folder / "reopen.json").raw)
    final = document(read_image(subject.deployment).raw)
    require(reopened["phase"] == "complete" and final["phase"] == "complete" and final["newBoot"] == new_boot
            and subject.verify() == before["inputs"] and subject.locks() == before["locks"],
            "The all-four commit did not preserve the original gate, locks and disabled callers.")
    require([row["component"] for row in reopened["components"]] == list(COMPONENTS),
            "Reopening did not atomically account for all components.")
    for row in reopened["components"]:
        component = row["component"]
        image, result, _ = results[component]
        require(row["resultSha256"] == image.sha256 and row["attempt"] == result["attempt"]
                and row["epoch"] == result["epoch"] and row["nextEpoch"] != row["epoch"]
                and subject.authority(component).read("control") == {
                    "version": 1, "phase": "normal", "session": None, "epoch": row["nextEpoch"],
                }, "A reopened component has the wrong result or normal epoch.")
    proofs: Object = {}
    for pin in subject.producers:
        component = pin.component
        subscription = _BUILT_INS[component]
        command = ["--qualification-launch", str(subject.registry), component, pin.build, "driver", "--",
                   "--state-dir", str(targets[component].state), "subscriptions", "identity", subscription]
        proof = subject.capture(evidence, "reopened-proof-" + component, command)
        require(proof.get("subscription") == subscription and valid_token(proof.get("witness"))
                and proof.get("generation") == results[component][1]["generation"],
                "A completed rollout did not admit fresh proof from the exact converted State.")
        proofs[component] = proof
    output = {"beforeSha256": previous_sha256, "newBoot": new_boot, "archive": archived,
              "reopen": reopened, "proofs": proofs}
    evidence.write("genuine-transition-after.json", output)
    return output


PruningPath = Literal["keep", "unused"]


@dataclass(frozen=True)
class RetainedHelper:
    pin: TuplePin
    owner: ExactProcess
    writer: str

    def observe(self, subject: Rollout) -> Object:
        authority = subject.authority(self.pin.component)
        digest_value = authority.read("qualification")["acceptanceSha256"]
        scope = resolve_candidate(subject.registry, self.pin.component, self.pin.build, digest_value)
        require(scope.producer(self.pin.component).digest == self.pin.payload_sha256,
                "The live-helper retention subject changed its accepted payload.")
        with authority.mutex():
            custody = reconcile(authority, persist_unknown=False, candidate=scope)
            records = [row for row in custody.writers if row["writer"] == self.writer and row["phase"] == "active"
                       and {key: row[key] for key in ("pid", "startedAt")} == self.owner.object()]
            require(not custody.unknown and len(records) == 1 and self.owner.live(),
                    "The independently verified retained helper is not genuinely active.")
            transfers = [row for row in custody.handoffs if row["child"] == self.writer and row["phase"] == "accepted"
                         and row["role"] == "helper" and row["payloadSha256"] == self.pin.payload_sha256]
            require(len(transfers) == 1 and records[0]["parent"] == transfers[0]["parent"],
                    "Build retention was not exercised with the actual accepted helper transfer.")
            fd = authority.open_lock("admission.lock")
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    raise AssertionError("The live admitted helper did not exclude a fresh EX.")
            finally:
                os.close(fd)
        return {"writer": records[0], "handoff": transfers[0], "process": self.owner.object()}


@dataclass(frozen=True)
class PruningFixture:
    """Real exact inputs old enough for the two ordinary removal paths."""

    program: Path
    program_sha256: str
    retained: tuple[TuplePin, ...]
    removable_component: str
    removable_build: str
    removable_entry: Path
    settings: Path
    helper: RetainedHelper | None = None

    def observe(self, subject: Rollout, evidence: EvidenceRecorder, path: PruningPath, *, closed: bool = False) -> None:
        require(bool(self.retained) and self.removable_component in (*COMPONENTS, "arbol")
                and self.program.is_relative_to(subject.registry / "arbol" / subject.provider.build)
                and self.removable_entry.is_relative_to(subject.registry / self.removable_component / self.removable_build)
                and not any((pin.component, pin.build) == (self.removable_component, self.removable_build)
                            for pin in self.retained), "Invalid fixed pruning controls.")
        command = read_image(self.program, private=False, limit=1024 * 1024)
        require(command.sha256 == self.program_sha256 and command.mode & 0o100 != 0,
                "The exact ordinary Builds CLI changed.")
        registry = subject.registry
        deployment = _raw_image(subject.deployment)
        if closed:
            require(deployment is not None and document(read_image(subject.deployment).raw)["phase"] in (
                "staged", "closed-installed", "awaiting-boot", "boot-verified", "maintaining", "failed-closed",
            ), "Closed retention requires an actual unfinished deployment.")
        elif self.helper is None:
            require(subject.provider in self.retained and read_image(subject.shared / "gate.json").raw
                    == read_image(subject.manifest).raw, "Provider retention requires the current exact gate reference.")
        else:
            require(self.helper.pin in self.retained, "The genuine helper's Build must be checked after pruning.")
        helper = self.helper.observe(subject) if self.helper is not None else None
        before = {(pin.component, pin.build): pin.verify(registry).evidence() for pin in self.retained}
        guard = read_image(self.removable_entry, limit=_LIMIT, private=False)
        control_record = registry / self.removable_component / self.removable_build / "build.json"
        control_before = read_image(control_record, private=False)
        require(not document(control_before.raw).get("prunedAt"),
                "The actual removable sibling must start unpruned.")

        environment = without_authority(dict(subject.environment))
        home = Path(environment["HOME"])
        _private_path(home, subject.root, directory=True)
        require(self.settings == home / ".arbol/arbol-builds.json", "Unused settings escaped the owned HOME.")
        _private_path(self.settings, home, directory=False)
        days = document(read_image(self.settings).raw)["removeUnusedAfterDays"]
        require(type(days) in (int, float) and days > 0, "The unused collection route is disabled.")
        for key, value in environment.items():
            if key.startswith("ARBOL_") and value.startswith("/"):
                require(Path(value).is_relative_to(subject.root), "Pruning runtime input escaped the fixture.")
        operands = [self.removable_component, "--keep", "1"] if path == "keep" else ["--unused"]
        if path == "keep":
            require(all(pin.component == self.removable_component for pin in self.retained),
                    "Per-component prune must actually reach every retained tuple under test.")
        argv = [str(self.program), "prune", *operands, "--registry-dir", str(registry), "--bin-dir", str(subject.bin)]
        child = OwnedChild(argv, environment=environment, cwd=registry)
        try:
            result = child.collect(seconds=90)
        finally:
            if not child.reaped:
                child.request_stop()
                child.wait_owned(seconds=20)
        evidence.write("ordinary-prune-" + path + ".json", {
            "argv": argv, "process": result.owner.object(), "reaped": child.reaped, "exit": result.returncode,
            "stdoutHex": result.stdout.hex(), "stderrHex": result.stderr.hex(), "sibling": guard.evidence(),
            "protected": [{"component": key[0], "build": key[1], "image": value} for key, value in before.items()],
        })
        require(child.reaped and result.returncode == 0 and not result.stderr,
                "Ordinary pruning failed or fell back to an unavailable runtime.")
        values = json.loads(result.stdout)
        rows = [values] if path == "keep" else values
        require(isinstance(rows, list) and all(isinstance(row, dict) and not any(row.get(key) for key in (
                    "maintenance", "runtimeUnavailable", "activeExchanges", "schemaStatus")) for row in rows),
                "Ordinary pruning did not independently reach the expected deletion path.")
        pruned = {row["component"]: row["pruned"] for row in rows}
        require(all(pin.build not in pruned[pin.component] and pin.verify(registry).evidence() == before[(pin.component, pin.build)]
                    for pin in self.retained) and _raw_image(subject.deployment) == deployment,
                "Pruning changed an exact pinned input or deployment authority.")
        if self.helper is not None:
            require(self.helper.observe(subject) == helper, "Pruning broke a genuinely active accepted helper reference.")
        if closed:
            require(self.removable_build not in pruned[self.removable_component]
                    and read_image(control_record, private=False) == control_before
                    and read_image(self.removable_entry, limit=_LIMIT, private=False) == guard,
                    "An unfinished rollout lost a recovery Build.")
        else:
            require(self.removable_build in pruned[self.removable_component]
                    and bool(document(read_image(control_record, private=False).raw)["prunedAt"])
                    and not os.path.lexists(self.removable_entry),
                    "Pruning did not distinguish exact retained inputs from an actual removable sibling.")
