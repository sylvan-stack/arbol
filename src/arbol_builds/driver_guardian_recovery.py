"""Recover the audited interrupted guardians of the installed layout-2 cohort."""

from __future__ import annotations

import os
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from pwd import getpwuid

from arbol_installation.paths import build_registry

from .driver_admission import (
    COMPONENTS,
    Authority,
    ClosedGuardian,
    Object,
    Refusal,
    _documents,
    canonical,
    canonical_uuid,
    deployment_mutex,
    fields,
    fresh_install,
    private_directory,
    publish,
    read,
    read_bytes,
    reconcile,
    sha256,
    sync_directory,
    valid_hash,
)
from .driver_payload import pin_payloads, verify_acceptance, verify_gate
from .driver_process import boot_uuid
from .driver_replacement import RECEIPT_LIMIT, _bound_packages, _normal, _promotion, _promotion_path
from .driver_state import _immutable, _use_current
from .launcher import open_use_guard

# This sealed launcher publishes a pending handoff before spawning and never writes Driver state.
AUDITED_PROVIDER = "3dc4ae75852506d0943d1b5906e018732c640fd99ff8d04fac3c0fb65279c3f8"
TREES = ("writers", "handoffs", "normal-admissions")
ENTRIES = (*TREES, "taint.json")


def _fingerprint(path: Path) -> str:
    if path.name == "taint.json":
        return sha256(read_bytes(path))
    tree = private_directory(path)
    records: list[Object] = []
    if path.name == "writers":
        folders = sorted(tree.iterdir())
        if not folders or len(folders) > 100000:
            raise Refusal("The guardian recovery writer inventory is outside its bounds.")
        for folder in folders:
            documents = _documents(folder)
            if not documents or len(records) + len(documents) > 100000:
                raise Refusal("The guardian recovery writer inventory is incomplete or outside its bounds.")
            records.extend({"name": str(item.relative_to(tree)), "sha256": sha256(read_bytes(item))}
                           for item in documents)
    else:
        records = [{"name": item.name, "sha256": sha256(read_bytes(item))} for item in _documents(tree)]
    return sha256(canonical({"records": records}))


def _prove(authority: Authority, lease: int, row: Object, boot: str) -> Object:
    component = authority.component
    epoch, digest = row["epoch"], row["payloadSha256"]
    acceptance = authority.read("qualification")["acceptanceSha256"]
    taint = authority.read("taint")
    if (taint["component"] != component or taint["epoch"] != epoch or taint["boot"] != boot
            or taint["reason"] != "custody-loss" or taint["payloadSha256"] is not None
            or any(next(private_directory(authority.folder / name).iterdir(), None) is not None
                   for name in ("archive", "sessions"))):
        raise Refusal(f"{component} has custody outside the audited guardian recovery cases.")

    observed = reconcile(authority, boot=boot, persist_unknown=False)
    active = [writer for writer in observed.writers if writer["phase"] == "active"]
    if not observed.unknown or len(active) != 1 or active[0]["parent"] is not None:
        raise Refusal(f"{component} has no single interrupted root guardian.")
    guardian = active[0]
    custody = reconcile(authority, boot=boot, persist_unknown=False,
                        closed_guardian=ClosedGuardian(lease, guardian["invocation"], guardian["writer"]))
    if not custody.resolved:
        raise Refusal(f"{component} has an outstanding or unverified writer or handoff.")

    invocations: dict[str, list[Object]] = defaultdict(list)
    for writer in custody.writers:
        if writer["payloadSha256"] != digest:
            raise Refusal(f"{component} has custody from another Build.")
        invocations[writer["invocation"]].append(writer)
    handoffs = {handoff["invocation"]: handoff for handoff in custody.handoffs}
    if (len(handoffs) != len(custody.handoffs) or handoffs.keys() - invocations.keys()
            or taint["invocation"] in invocations):
        raise Refusal(f"{component} does not have the audited invocation and taint bindings.")

    expected_markers: dict[str, Object] = {}
    for invocation, writers in invocations.items():
        handoff = handoffs.get(invocation)
        if handoff is None:
            if writers != [guardian]:
                raise Refusal(f"{component} has a different invocation without a handoff.")
            continue
        child = next((writer for writer in writers if writer["writer"] == handoff["child"]), None)
        parent = next((writer for writer in writers if writer["writer"] == handoff["parent"]), None)
        if (len(writers) != 2 or handoff["phase"] != "accepted" or handoff["role"] != "main"
                or handoff["acceptanceSha256"] != acceptance or child is None or child["phase"] != "terminal"
                or parent is None or parent["parent"] is not None):
            raise Refusal(f"{component} has an invocation outside the audited main handoff shape.")
        expected_markers[invocation + ".json"] = {
            "version": 1, "kind": "driver-normal-admission", "component": component, "epoch": epoch,
            "boot": boot, "invocation": invocation, "build": row["build"], "payloadSha256": digest, "checkpoint": None,
        }
    markers = _documents(authority.folder / "normal-admissions")
    if {marker.name for marker in markers} != expected_markers.keys() or any(
            read(marker) != expected_markers[marker.name] for marker in markers):
        raise Refusal(f"{component} admission markers do not account for every invocation.")
    return {"component": component, "epoch": epoch, "invocation": guardian["invocation"],
            "writer": guardian["writer"],
            "case": "terminal-child" if guardian["invocation"] in handoffs else "before-handoff",
            "entries": {name: _fingerprint(authority.folder / name) for name in ENTRIES}}


def _archive(authority: Authority, row: Object, session: str, *, verify_only: bool) -> None:
    archive = private_directory(authority.folder / "archive")
    destination = private_directory(archive / ("guardian-recovery-" + session), create=not verify_only)
    for name in ENTRIES:
        source, saved = authority.folder / name, destination / name
        expected = row["entries"][name]
        if not os.path.lexists(saved):
            if verify_only or _fingerprint(source) != expected:
                raise Refusal(f"{authority.component} original custody evidence is missing or changed.")
            source.rename(saved)
            sync_directory(destination)
            sync_directory(authority.folder)
        if _fingerprint(saved) != expected:
            raise Refusal(f"{authority.component} archived custody evidence changed.")
        if verify_only:
            continue
        if name in TREES:
            live = private_directory(source, create=True)
            if next(live.iterdir(), None) is not None:
                raise Refusal(f"{authority.component} has new custody while admission is closed.")
        elif os.path.lexists(source):
            raise Refusal(f"{authority.component} has a new custody taint.")


def recover_guardians(registry: Path, session: str) -> Object:
    home = Path(getpwuid(os.getuid()).pw_dir)
    if registry != build_registry(home) or not canonical_uuid(session):
        raise Refusal("Guardian recovery requires the canonical stable registry and a session UUID.")
    authorities = [Authority(registry, name) for name in COMPONENTS]
    shared = authorities[0].shared
    with deployment_mutex(registry), ExitStack() as locks:
        current = fresh_install(registry)
        gate = verify_gate(registry)
        boot = boot_uuid()
        if (current is None or gate.provider.digest != AUDITED_PROVIDER or current["gateSha256"] != gate.digest
                or current["registrySha256"] != sha256(canonical(authorities[0].identity))
                or any(os.path.lexists(shared / name) for name in ("deployment.json", "fresh-preparation.json"))):
            raise Refusal("Guardian recovery requires the audited installed Driver gate and no other deployment.")
        receipts = shared / "guardian-recoveries"
        journal = receipts / (session + ".json")
        complete = receipts / (session + ".complete.json")
        try:
            proof = read(journal, limit=RECEIPT_LIMIT) if os.path.lexists(receipts) else None
        except FileNotFoundError:
            proof = None
        before: Object = current
        if proof is not None:
            fields(proof, "version kind session boot providerPayloadSha256 installed components")
            recorded = proof["installed"]
            if (not isinstance(recorded, dict) or proof["kind"] != "driver-guardian-recovery"
                    or proof["session"] != session or proof["providerPayloadSha256"] != gate.provider.digest
                    or not canonical_uuid(proof["boot"])):
                raise Refusal("The recorded guardian recovery identity changed.")
            before = recorded
            if current not in (before, {**before, "phase": "staging", "promotionSha256": sha256(canonical(proof))}):
                raise Refusal("This UUID does not own the current Driver installation fence.")
        if before["phase"] != "complete":
            raise Refusal("Another Driver installation operation is staged.")

        packages = _bound_packages(registry, home, before, gate)
        promotion = _promotion(registry, before, packages)
        if canonical(promotion) != read_bytes(_promotion_path(shared, before), limit=RECEIPT_LIMIT):
            raise Refusal("The installed Driver promotion record changed.")
        locks.enter_context(pin_payloads(registry, [gate.provider]))
        for authority in authorities:
            build = packages[authority.component].build
            use = open_use_guard(str(registry), authority.component, build, exclusive=True)
            locks.callback(os.close, use)
            _use_current(authority, build, use)
        for authority in authorities:
            locks.enter_context(authority.mutex())
        leases: list[int] = []
        for authority, row in zip(authorities, before["components"], strict=True):
            lease = authority.lease(exclusive=True)
            locks.callback(os.close, lease)
            leases.append(lease)
            if (authority.read("control") != _normal(row) or os.path.lexists(authority.folder / "maintenance.json")
                    or verify_acceptance(authority, packages[authority.component])["evidenceSha256"]
                    != before["promotionSha256"]):
                raise Refusal(f"{authority.component} no longer has the audited control and acceptance.")
        if _bound_packages(registry, home, before, gate) != packages:
            raise Refusal("The installed Driver packages changed under the recovery locks.")

        if current == before and not os.path.lexists(complete):
            rows = [_prove(authority, lease, row, boot)
                    for authority, lease, row in zip(authorities, leases, before["components"], strict=True)]
            prepared = {"version": 1, "kind": "driver-guardian-recovery", "session": session, "boot": boot,
                        "providerPayloadSha256": gate.provider.digest, "installed": before, "components": rows}
            private_directory(receipts, create=True)
            _immutable(journal, canonical(prepared), limit=RECEIPT_LIMIT)
            proof = prepared
            publish(shared / "fresh-install.json",
                    {**before, "phase": "staging", "promotionSha256": sha256(canonical(proof))})
            current = fresh_install(registry)
        if proof is None:
            raise Refusal("The closed guardian recovery proof is missing.")
        finished = {"version": 1, "kind": "driver-guardian-recovery-complete", "session": session,
                    "proofSha256": sha256(canonical(proof))}
        verify_only = current == before
        if verify_only and read(complete) != finished:
            raise Refusal("The completed guardian recovery receipt changed.")
        staged = {**before, "phase": "staging", "promotionSha256": finished["proofSha256"]}
        if not verify_only and (current != staged or proof["boot"] != boot):
            raise Refusal("The closed guardian recovery fence or Mac boot changed.")
        for authority, install_row, recovered in zip(authorities, before["components"], proof["components"], strict=True):
            if (recovered["component"] != authority.component or recovered["epoch"] != install_row["epoch"]
                    or set(recovered["entries"]) != set(ENTRIES)
                    or not all(valid_hash(value) for value in recovered["entries"].values())):
                raise Refusal("The recorded component recovery inventory is invalid.")
            _archive(authority, recovered, session, verify_only=verify_only)
        if not verify_only:
            _immutable(complete, canonical(finished))
            publish(shared / "fresh-install.json", before)
        return {**finished, "receipt": str(journal),
                "components": [{"component": row["component"], "case": row["case"]} for row in proof["components"]]}
