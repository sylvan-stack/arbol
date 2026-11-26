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
    read_handoff,
    read_writer,
    reconcile,
    sha256,
    sync_directory,
    valid_hash,
    valid_token,
    validate,
)
from .driver_payload import Payload, pin_payloads, verify_acceptance, verify_gate
from .driver_process import boot_uuid, identity_record, matches
from .driver_replacement import RECEIPT_LIMIT, _bound_packages, _normal, _promotion, _promotion_path
from .driver_state import _immutable, _use_current
from .launcher import open_use_guard

# This sealed launcher publishes a pending handoff before spawning and never writes Driver state.
AUDITED_PROVIDER = "3dc4ae75852506d0943d1b5906e018732c640fd99ff8d04fac3c0fb65279c3f8"
# This sealed Claude entry waits for a durable accepted transfer before entering the CLI.
AUDITED_CLAUDE = "1572a8a2cf8e6fb10894e0ed63adc9a9bcd37f55a38160cf182d13a7ca13ce57"
CLAUDE = "arbol-claude-driver"
AUDITED_MAIN_PRODUCERS = {
    "claude": "fab8a36e022c4caf437cf4b2f39c15c300260bf89502a2ffdae852252c42f0ca",
    "codex": "e582bf34a3705aa75956dfe8e38908cce87570ecca74fee3f899ad5f4ceb94d6",
}
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


def _process(writer: Object) -> Object:
    return identity_record({key: writer[key] for key in ("pid", "startedAt")})


def _main_records(authority: Authority, row: Object, payload: Payload, boot: str) -> tuple[dict[str, Object], dict[str, Object]]:
    """Read the complete current-epoch ledger for the audited main-only recovery."""
    handoffs: dict[str, Object] = {}
    contexts: dict[str, tuple[Object, str]] = {}
    acceptance = authority.read("qualification")["acceptanceSha256"]
    stamps = {"component": authority.component, "epoch": row["epoch"], "payloadSha256": payload.digest}
    for path in _documents(authority.folder / "handoffs"):
        if path.name.endswith(".context.json"):
            raw = read_bytes(path)
            context = decode(raw)
            normal_context(context)
            if path.name != context["handoff"] + ".context.json":
                raise Refusal("A main handoff context has an inconsistent name.")
            contexts[context["handoff"]] = (context, sha256(raw))
        else:
            handoff = read_handoff(authority, path.stem)
            if (handoff["invocation"] in handoffs or handoff["role"] != "main"
                    or handoff["entry"] != payload.descriptor["entry"] or handoff["acceptanceSha256"] != acceptance
                    or any(handoff[key] != value for key, value in stamps.items())):
                raise Refusal("The ledger contains an unaudited or duplicate main handoff.")
            handoffs[handoff["invocation"]] = handoff
    if {item["handoff"] for item in handoffs.values()} != contexts.keys():
        raise Refusal("The main handoff context inventory is incomplete.")

    markers: dict[str, Object] = {}
    interrupted: dict[str, Object] = {}
    roots = list(private_directory(authority.folder / "writers").iterdir())
    if not roots or len(roots) > 100000 or {path.name for path in roots} != handoffs.keys():
        raise Refusal("The writer roots do not match the audited main handoffs.")
    registry_digest = sha256(canonical(authority.identity))
    for path in sorted(roots):
        invocation = path.name
        handoff = handoffs[invocation]
        context, context_digest = contexts[handoff["handoff"]]
        if not valid_token(invocation) or handoff["contextSha256"] != context_digest:
            raise Refusal("The writer invocation or its handoff context changed.")
        writers = {file.stem: read_writer(authority, invocation, file.stem)
                   for file in _documents(path, limit=2)}
        parent, child = writers.get(handoff["parent"]), writers.get(handoff["child"])
        if (parent is None or parent["parent"] is not None or parent["contextSha256"] is not None
                or handoff["parent"] == handoff["child"]
                or writers.keys() - {handoff["parent"], handoff["child"]}
                or any(writer["boot"] != boot or any(writer[key] != value for key, value in stamps.items())
                       for writer in writers.values())):
            raise Refusal("The main handoff does not own its precise writer inventory.")
        parent_identity = _process(parent)
        expected_context = {
            "version": 1, "kind": "driver-admission-context", **stamps, "boot": boot,
            "role": "main", "registry": str(authority.registry), "registrySha256": registry_digest,
            "invocation": invocation, "writer": handoff["child"],
            "parent": {"writer": parent["writer"], **parent_identity}, "process": context["process"],
            "handoff": handoff["handoff"], "nonce": handoff["nonce"], "entry": handoff["entry"],
            "acceptanceSha256": acceptance,
        }
        child_identity = identity_record(context["process"])
        if (context != expected_context or child_identity == parent_identity
                or (child is not None and (child["parent"] != parent["writer"]
                    or child["contextSha256"] != context_digest or _process(child) != child_identity))):
            raise Refusal("The original guardian and child identities do not match the handoff.")

        if handoff["phase"] == "pending":
            # In the audited launcher the durable accepted publication precedes GO.
            # Registration alone cannot start the Driver. Preserve its original active record.
            if parent["phase"] != "active" or (child is not None and child["phase"] != "active"):
                raise Refusal("A pending main handoff contains a terminal writer.")
            case = "pending-before-go"
        else:
            if child is None or child["phase"] != "terminal":
                raise Refusal("An accepted main child lacks a verified terminal record.")
            case = "terminal-child" if parent["phase"] == "active" else None
        if case is not None:
            if matches(parent_identity) or matches(child_identity):
                raise Refusal("An interrupted main handoff still has a live original process.")
            interrupted[invocation] = {"invocation": invocation, "writer": parent["writer"], "case": case}
        markers[invocation + ".json"] = {
            "version": 1, "kind": "driver-normal-admission", **stamps, "boot": boot,
            "invocation": invocation, "build": row["build"], "checkpoint": None,
        }
    return markers, interrupted


def _prove_interrupted_main(authority: Authority, lease: int, row: Object, payload: Payload,
                            boot: str, driver: str) -> Object:
    _exclusive(authority, lease)
    if (authority.component != "arbol-" + driver + "-driver"
            or payload.digest != AUDITED_MAIN_PRODUCERS[driver] or row["payloadSha256"] != payload.digest
            or os.path.lexists(authority.folder / "archive" / "custody-pending.json")
            or next(private_directory(authority.folder / "sessions").iterdir(), None) is not None):
        raise Refusal("The selected Driver is outside the audited main handoff recovery.")
    markers, interrupted = _main_records(authority, row, payload, boot)
    if not interrupted:
        raise Refusal("The selected Driver has no provable interrupted main handoff.")
    taint = authority.read("taint")
    if (taint["reason"] != "custody-loss" or taint["component"] != authority.component
            or taint["epoch"] != row["epoch"] or taint["boot"] != boot):
        raise Refusal("The custody-loss record does not match the installed Driver.")
    if taint["payloadSha256"] is None:
        if taint["invocation"] + ".json" in markers:
            raise Refusal("A generic custody-loss record conflicts with a launch marker.")
    elif taint["payloadSha256"] != payload.digest or taint["invocation"] not in interrupted:
        raise Refusal("The custody-loss record is unrelated to the interrupted main handoffs.")

    for path in _documents(authority.folder / "normal-admissions"):
        marker = read(path)
        expected = markers.pop(path.name, None)
        if expected is not None:
            if marker != expected:
                raise Refusal("A current main admission marker changed.")
            continue
        fields(marker, "version kind component epoch invocation payloadSha256 boot build checkpoint")
        if (marker["kind"] != "driver-normal-admission" or marker["component"] != authority.component
                or marker["epoch"] == row["epoch"] or not valid_token(marker["invocation"])
                or path.name != marker["invocation"] + ".json" or marker["checkpoint"] is not None):
            raise Refusal("An extra main admission marker cannot be explained by retained custody.")
        _prior_marker(authority, marker)
    if markers:
        raise Refusal("The current main admission marker inventory is incomplete.")

    return {"component": authority.component, "epoch": row["epoch"], "case": "interrupted-main",
            "interruptions": list(interrupted.values()),
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


def recover_guardians(registry: Path, session: str, *, pending_claude: bool = False,
                      main_driver: str | None = None, check_only: bool = False) -> Object:
    home = Path(getpwuid(os.getuid()).pw_dir)
    if registry != build_registry(home) or not canonical_uuid(session):
        raise Refusal("Guardian recovery requires the canonical stable registry and a session UUID.")
    if ((main_driver is not None and (pending_claude or main_driver not in AUDITED_MAIN_PRODUCERS))
            or (check_only and main_driver is None)):
        raise Refusal("The requested guardian recovery mode is unavailable.")
    authorities = [Authority(registry, name) for name in COMPONENTS]
    shared = authorities[0].shared
    if main_driver is not None:
        kind = "driver-" + main_driver + "-interrupted-main-recovery"
        target = "arbol-" + main_driver + "-driver"
    else:
        kind = "driver-claude-pending-recovery" if pending_claude else "driver-guardian-recovery"
        target = CLAUDE if pending_claude else None
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
                    if target is None or authority.component == target]
        if check_only and (proof is not None or os.path.lexists(complete)):
            raise Refusal("Use the recorded session to resume the interrupted main handoff recovery.")
        if current == before and not os.path.lexists(complete):
            rows = []
            for authority, lease, row in selected:
                if main_driver is not None:
                    recovered = _prove_interrupted_main(authority, lease, row, packages[authority.component],
                                                       boot, main_driver)
                elif pending_claude:
                    recovered = _prove_pending_claude(authority, lease, row, packages[CLAUDE], boot)
                else:
                    recovered = _prove(authority, lease, row, boot)
                rows.append(recovered)
            if check_only:
                return {"version": 1, "kind": kind + "-checked", "boot": boot,
                        "components": [{"component": row["component"],
                                        "cases": [entry["case"] for entry in row["interruptions"]]} for row in rows]}
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
