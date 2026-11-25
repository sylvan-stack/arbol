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
    _exclusive,
    canonical,
    canonical_uuid,
    decode,
    deployment_mutex,
    fields,
    fresh_install,
    normal_context,
    private_directory,
    publish,
    read,
    read_bytes,
    reconcile,
    sha256,
    sync_directory,
    valid_hash,
    valid_token,
    validate,
)
from .driver_payload import Payload, pin_payloads, verify_acceptance, verify_gate
from .driver_process import boot_uuid, matches
from .driver_replacement import RECEIPT_LIMIT, _bound_packages, _normal, _promotion, _promotion_path
from .driver_state import _immutable, _use_current
from .launcher import open_use_guard

# This sealed launcher publishes a pending handoff before spawning and never writes Driver state.
AUDITED_PROVIDER = "3dc4ae75852506d0943d1b5906e018732c640fd99ff8d04fac3c0fb65279c3f8"
# This sealed Claude entry waits for a durable accepted transfer before entering the CLI.
AUDITED_CLAUDE = "1572a8a2cf8e6fb10894e0ed63adc9a9bcd37f55a38160cf182d13a7ca13ce57"
CLAUDE = "arbol-claude-driver"
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


def _prior_marker(authority: Authority, marker: Object) -> None:
    """Account for a previous-epoch marker through its retained terminal custody."""
    invocation = marker["invocation"]
    if not valid_token(invocation) or not valid_hash(marker["payloadSha256"]):
        raise Refusal("An earlier Claude admission marker cannot be verified.")
    key = {name: marker[name] for name in ("component", "epoch", "invocation", "payloadSha256")}
    found = 0
    for archive in sorted(private_directory(authority.folder / "archive").glob("custody-*")):
        root = private_directory(private_directory(archive) / "writers") / invocation
        if not os.path.lexists(root):
            continue
        writers = [read(path) for path in _documents(root)]
        for writer in writers:
            validate("writer", writer)
        if (len(writers) != 2 or any(writer["phase"] != "terminal" or writer["boot"] != marker["boot"]
                                   or any(writer[name] != value for name, value in key.items()) for writer in writers)):
            raise Refusal("An earlier Claude admission lacks its two terminal writers.")
        handoffs = [read(path) for path in _documents(archive / "handoffs") if not path.name.endswith(".context.json")]
        related = [handoff for handoff in handoffs if handoff.get("invocation") == invocation]
        if len(related) != 1:
            raise Refusal("An earlier Claude admission lacks one archived transfer.")
        handoff = related[0]
        validate("handoff", handoff)
        by_writer = {writer["writer"]: writer for writer in writers}
        parent, child = by_writer.get(handoff["parent"]), by_writer.get(handoff["child"])
        if (parent is None or child is None or parent["parent"] is not None or child["parent"] != parent["writer"]
                or handoff["phase"] != "accepted" or handoff["role"] != "main" or not valid_hash(child["contextSha256"])
                or handoff["contextSha256"] != child["contextSha256"]
                or any(handoff[name] != value for name, value in key.items())):
            raise Refusal("An earlier Claude admission differs from its archived transfer.")
        found += 1
    if found != 1:
        raise Refusal("An earlier Claude admission lacks one terminal custody archive.")


def _prove_pending_claude(authority: Authority, lease: int, row: Object, payload: Payload, boot: str) -> Object:
    _exclusive(authority, lease)
    component, epoch, digest = authority.component, row["epoch"], row["payloadSha256"]
    if (component != CLAUDE or payload.digest != AUDITED_CLAUDE or digest != AUDITED_CLAUDE
            or os.path.lexists(authority.folder / "archive" / "custody-pending.json")
            or next(private_directory(authority.folder / "sessions").iterdir(), None) is not None):
        raise Refusal("Claude does not match the audited pending recovery conditions.")
    roots = list(private_directory(authority.folder / "writers").iterdir())
    if len(roots) != 1 or not valid_token(roots[0].name):
        raise Refusal("Claude does not have one interrupted guardian invocation.")
    invocation = roots[0].name
    writers = _documents(roots[0])
    if len(writers) != 1:
        raise Refusal("The Claude child already registered or the writer inventory changed.")
    guardian = read(writers[0])
    validate("writer", guardian)
    owner = {name: guardian[name] for name in ("pid", "startedAt")}
    common = {"component": component, "epoch": epoch, "invocation": invocation, "payloadSha256": digest}
    if (guardian != {"version": 1, **common, **owner, "writer": guardian["writer"], "parent": None,
                     "boot": boot, "phase": "active", "contextSha256": None}
            or writers[0].name != guardian["writer"] + ".json" or matches(owner)):
        raise Refusal("Claude lacks the exact exited state-free guardian.")
    if authority.read("taint") != {"version": 1, **common, "boot": boot, "reason": "custody-loss"}:
        raise Refusal("The Claude custody-loss marker is unrelated to this handoff.")

    folder = authority.folder / "handoffs"
    documents = _documents(folder)
    originals = [path for path in documents if not path.name.endswith(".context.json")]
    if len(documents) != 2 or len(originals) != 1:
        raise Refusal("Claude does not have one pending main handoff and context.")
    handoff = read(originals[0])
    validate("handoff", handoff)
    context_file = folder / (handoff["handoff"] + ".context.json")
    raw = read_bytes(context_file)
    context = decode(raw)
    normal_context(context)
    binding = {**common, "role": "main", "entry": payload.descriptor["entry"], "nonce": handoff["nonce"],
               "acceptanceSha256": authority.read("qualification")["acceptanceSha256"]}
    if (originals[0].name != handoff["handoff"] + ".json" or context_file not in documents
            or handoff != {"version": 1, **binding, "handoff": handoff["handoff"], "parent": guardian["writer"],
                           "child": context["writer"], "phase": "pending", "contextSha256": sha256(raw)}
            or context != {"version": 1, "kind": "driver-admission-context", **binding, "boot": boot,
                           "registry": str(authority.registry), "registrySha256": sha256(canonical(authority.identity)),
                           "writer": handoff["child"], "parent": {"writer": guardian["writer"], **owner},
                           "process": context["process"], "handoff": handoff["handoff"]}
            or context["writer"] == guardian["writer"] or matches(context["process"])):
        raise Refusal("Claude lacks a verified pending transfer to an exited, unregistered child.")

    expected = {"version": 1, "kind": "driver-normal-admission", **common, "boot": boot,
                "build": row["build"], "checkpoint": None}
    markers = authority.folder / "normal-admissions"
    if read(markers / (invocation + ".json")) != expected:
        raise Refusal("The interrupted Claude invocation lacks its exact launch marker.")
    for path in _documents(markers):
        if path.name == invocation + ".json":
            continue
        marker = read(path)
        fields(marker, "version kind component epoch invocation payloadSha256 boot build checkpoint")
        if (marker["kind"] != expected["kind"] or marker["component"] != component or marker["epoch"] == epoch
                or not valid_token(marker["invocation"]) or path.name != marker["invocation"] + ".json"
                or marker["checkpoint"] is not None):
            raise Refusal("An additional or unaccounted-for Claude admission remains.")
        _prior_marker(authority, marker)
    return {"component": component, "epoch": epoch, "invocation": invocation, "writer": guardian["writer"],
            "case": "pending-before-child-registration",
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


def recover_guardians(registry: Path, session: str, *, pending_claude: bool = False) -> Object:
    home = Path(getpwuid(os.getuid()).pw_dir)
    if registry != build_registry(home) or not canonical_uuid(session):
        raise Refusal("Guardian recovery requires the canonical stable registry and a session UUID.")
    authorities = [Authority(registry, name) for name in COMPONENTS]
    shared = authorities[0].shared
    kind = "driver-claude-pending-recovery" if pending_claude else "driver-guardian-recovery"
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
            if (not isinstance(recorded, dict) or proof["kind"] != kind
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

        selected = [(authority, lease, row)
                    for authority, lease, row in zip(authorities, leases, before["components"], strict=True)
                    if not pending_claude or authority.component == CLAUDE]
        if current == before and not os.path.lexists(complete):
            rows = [_prove_pending_claude(authority, lease, row, packages[CLAUDE], boot) if pending_claude
                    else _prove(authority, lease, row, boot) for authority, lease, row in selected]
            prepared = {"version": 1, "kind": kind, "session": session, "boot": boot,
                        "providerPayloadSha256": gate.provider.digest, "installed": before, "components": rows}
            private_directory(receipts, create=True)
            _immutable(journal, canonical(prepared), limit=RECEIPT_LIMIT)
            proof = prepared
            publish(shared / "fresh-install.json",
                    {**before, "phase": "staging", "promotionSha256": sha256(canonical(proof))})
            current = fresh_install(registry)
        if proof is None:
            raise Refusal("The closed guardian recovery proof is missing.")
        finished = {"version": 1, "kind": kind + "-complete", "session": session,
                    "proofSha256": sha256(canonical(proof))}
        verify_only = current == before
        if verify_only and read(complete) != finished:
            raise Refusal("The completed guardian recovery receipt changed.")
        staged = {**before, "phase": "staging", "promotionSha256": finished["proofSha256"]}
        if not verify_only and (current != staged or proof["boot"] != boot):
            raise Refusal("The closed guardian recovery fence or Mac boot changed.")
        for (authority, _, install_row), recovered in zip(selected, proof["components"], strict=True):
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
