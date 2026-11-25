"""Recover custody across a real reboot without reinstalling the Driver cohort."""

from __future__ import annotations

import os
from contextlib import ExitStack
from pathlib import Path
from pwd import getpwuid

from arbol_installation.paths import build_registry

from .driver_admission import (
    COMPONENTS,
    Authority,
    Object,
    Refusal,
    admission_fingerprint,
    archive_boot_custody,
    canonical,
    canonical_uuid,
    decode,
    deployment_mutex,
    fields,
    fresh_install,
    lock_identity,
    private_directory,
    publish,
    read,
    read_bytes,
    reconcile,
    sha256,
    token,
    valid_hash,
    valid_token,
    validate,
)
from .driver_payload import pin_payloads, verify_acceptance, verify_gate
from .driver_process import boot_uuid
from .driver_replacement import RECEIPT_LIMIT, _acceptance, _bound_packages, _normal, _promotion, _promotion_path
from .driver_state import _immutable, _use_current, _verify_boot_archive
from .launcher import open_use_guard


def _optional(path: Path) -> Object | None:
    try:
        return read(path, limit=RECEIPT_LIMIT)
    except FileNotFoundError:
        return None


def _lock_ids(authority: Authority) -> Object:
    return {name: lock_identity(authority, name) for name in ("control.lock", "admission.lock")}


def _checkpoint_row(authority: Authority, row: Object, boot: str) -> Object:
    if authority.read("control") != _normal(row) or os.path.lexists(authority.folder / "maintenance.json"):
        raise Refusal(f"{authority.component} already has a different maintenance operation.")
    try:
        raw = read_bytes(authority.folder / "taint.json")
    except FileNotFoundError:
        if not reconcile(authority, boot=boot, persist_unknown=False).resolved:
            raise Refusal(f"{authority.component} lacks a terminal custody proof.") from None
        taint_digest = None
    else:
        taint = decode(raw)
        validate("taint", taint)
        if (taint["component"] != authority.component or taint["epoch"] != row["epoch"]
                or taint["reason"] != "custody-loss" or taint["boot"] != boot):
            raise Refusal(f"{authority.component} lacks an exact current-boot custody-loss marker.")
        taint_digest = sha256(raw)
    return {"component": authority.component, "locks": _lock_ids(authority),
            "admissionsSha256": admission_fingerprint(authority), "taintSha256": taint_digest}


def _validate_checkpoint(value: Object, session: str) -> Object:
    fields(value, "version kind session oldBoot checkpoint installed components")
    before, rows = value["installed"], value["components"]
    if (value["kind"] != "driver-installed-boot-checkpoint" or value["session"] != session
            or not canonical_uuid(value["oldBoot"]) or not valid_token(value["checkpoint"])
            or not isinstance(before, dict) or before.get("phase") != "complete"
            or not isinstance(rows, list) or len(rows) != len(COMPONENTS)):
        raise Refusal("The installed Driver boot checkpoint is invalid.")
    for component, row in zip(COMPONENTS, rows, strict=True):
        if (not isinstance(row, dict) or set(row) != {"component", "locks", "admissionsSha256", "taintSha256"}
                or row["component"] != component or not valid_hash(row["admissionsSha256"])
                or (row["taintSha256"] is not None and not valid_hash(row["taintSha256"]))):
            raise Refusal("A Driver boot checkpoint row is invalid.")
    return before


def _verify_custody(authority: Authority, checkpoint: Object, row: Object) -> None:
    if (_lock_ids(authority) != row["locks"] or os.path.lexists(authority.folder / "maintenance.json")):
        raise Refusal(f"{authority.component} maintenance or lock identity changed.")
    destination = authority.folder / "boot-archive" / checkpoint["checkpoint"]
    live_markers = authority.folder / "normal-admissions"
    archived_markers = destination / "normal-admissions"
    if os.path.lexists(archived_markers):
        if os.path.lexists(live_markers) and next(private_directory(live_markers).iterdir(), None) is not None:
            raise Refusal(f"{authority.component} admitted new work after the checkpoint.")
        marker_folder = archived_markers
    else:
        marker_folder = live_markers
    if admission_fingerprint(authority, folder=marker_folder) != row["admissionsSha256"]:
        raise Refusal(f"{authority.component} admission evidence changed after the checkpoint.")
    taints = [p for p in (authority.folder / "taint.json", destination / "taint.json") if os.path.lexists(p)]
    expected = row["taintSha256"]
    if expected is None and not taints:
        return
    if len(taints) != 1 or sha256(read_bytes(taints[0])) != expected:
        raise Refusal(f"{authority.component} custody-loss evidence changed after the checkpoint.")


def _resume(authorities: list[Authority], leases: list[int], checkpoint: Object, boot: str) -> None:
    for authority, package, row in zip(authorities, checkpoint["installed"]["components"],
                                       checkpoint["components"], strict=True):
        normal = _normal(package)
        draining = {**normal, "phase": "draining", "session": checkpoint["session"]}
        if authority.read("control") not in (normal, draining):
            raise Refusal(f"{authority.component} no longer belongs to the recorded window.")
        _verify_custody(authority, checkpoint, row)
    for authority, lease, package, row in zip(authorities, leases, checkpoint["installed"]["components"],
                                              checkpoint["components"], strict=True):
        normal = _normal(package)
        authority.write("control", {**normal, "phase": "draining", "session": checkpoint["session"]})
        archive_boot_custody(authority, lease, checkpoint, boot, taint_expected=row["taintSha256"] is not None)
        _verify_boot_archive(authority, checkpoint, boot)
        _verify_custody(authority, checkpoint, row)
        authority.write("control", normal)


def recover_boot(registry: Path, session: str, action: str) -> Object:
    home = Path(getpwuid(os.getuid()).pw_dir)
    if registry != build_registry(home) or not canonical_uuid(session) or action not in ("check", "prepare", "resume"):
        raise Refusal("Installed Driver boot recovery requires the canonical registry and a session UUID.")
    authorities = [Authority(registry, component) for component in COMPONENTS]
    shared = authorities[0].shared
    with deployment_mutex(registry), ExitStack() as locks:
        current = fresh_install(registry)
        gate = verify_gate(registry)
        if (current is None or current["registrySha256"] != sha256(canonical(authorities[0].identity))
                or current["gateSha256"] != gate.digest or os.path.lexists(shared / "deployment.json")
                or os.path.lexists(shared / "fresh-preparation.json")):
            raise Refusal("Boot recovery requires a verified layout-2 installation with no other deployment.")
        folder = shared / "boot-recoveries"
        checkpoint = None
        checkpoint_file = folder / (session + ".json")
        if os.path.lexists(folder):
            private_directory(folder)
            checkpoint = _optional(checkpoint_file)
        boot_file = folder / (session + ".boot.json")
        complete_file = folder / (session + ".complete.json")
        before = current if checkpoint is None else _validate_checkpoint(checkpoint, session)
        closed = {**before, "phase": "staging",
                  "promotionSha256": sha256(canonical(checkpoint))} if checkpoint is not None else None
        if before["phase"] != "complete" or current not in (before, closed):
            raise Refusal("A different Driver installation or maintenance window is active.")
        if action == "resume" and checkpoint is None:
            raise Refusal("No prepared Driver boot checkpoint exists for this session.")

        boot = boot_uuid()
        if not canonical_uuid(boot):
            raise Refusal("The current kernel boot identity is unavailable.")
        if checkpoint is not None and action != "resume" and boot != checkpoint["oldBoot"]:
            raise Refusal("The host has rebooted. Resume the recorded checkpoint.")
        if checkpoint is not None and action == "resume" and boot == checkpoint["oldBoot"]:
            raise Refusal("The recorded kernel boot is still running. Reboot before resuming.")

        packages = _bound_packages(registry, home, before, gate)
        promotion = _promotion(registry, before, packages)
        raw_promotion = canonical(promotion)
        if (sha256(raw_promotion) != before["promotionSha256"]
                or read_bytes(_promotion_path(shared, before), limit=RECEIPT_LIMIT) != raw_promotion):
            raise Refusal("The installed Driver promotion changed.")
        locks.enter_context(pin_payloads(registry, [gate.provider]))
        for authority in authorities:
            package = packages[authority.component]
            try:
                descriptor = open_use_guard(str(registry), authority.component, package.build, exclusive=True)
            except BlockingIOError:
                raise Refusal(f"{authority.component} still has a running user of its installed Build.") from None
            locks.callback(os.close, descriptor)
            _use_current(authority, package.build, descriptor)
        for authority in authorities:
            locks.enter_context(authority.mutex())
        leases = []
        for authority in authorities:
            try:
                lease = authority.lease(exclusive=True)
            except BlockingIOError:
                raise Refusal(f"{authority.component} still has an active admission lease.") from None
            locks.callback(os.close, lease)
            leases.append(lease)
            package = packages[authority.component]
            if verify_acceptance(authority, package) != _acceptance(registry, promotion, gate.provider, package):
                raise Refusal(f"{authority.component} acceptance changed.")
        if _bound_packages(registry, home, before, gate) != packages or fresh_install(registry) != current:
            raise Refusal("The exact Driver installation changed under its guards.")

        install_file = shared / "fresh-install.json"
        if action != "resume":
            rows = [_checkpoint_row(authority, row, boot)
                    for authority, row in zip(authorities, before["components"], strict=True)]
            affected = [row["component"] for row in rows if row["taintSha256"] is not None]
            if not affected or (checkpoint is not None and checkpoint["components"] != rows):
                raise Refusal("The exact custody-loss set and its admission evidence must be stable.")
            if action == "check":
                return {"phase": "ready" if current == before else "prepared", "session": session,
                        "oldBoot": boot, "affected": affected}
            if checkpoint is None:
                private_directory(folder, create=True)
                checkpoint = {"version": 1, "kind": "driver-installed-boot-checkpoint", "session": session,
                              "oldBoot": boot, "checkpoint": token(), "installed": before, "components": rows}
                _immutable(checkpoint_file, canonical(checkpoint), limit=RECEIPT_LIMIT)
            digest = sha256(canonical(checkpoint))
            publish(install_file, {**before, "phase": "staging", "promotionSha256": digest})
            return {"phase": "prepared", "session": session, "oldBoot": boot, "preparedSha256": digest,
                    "affected": affected}

        assert checkpoint is not None
        observed = {"version": 1, "kind": "driver-installed-boot-observed", "session": session,
                    "preparedSha256": sha256(canonical(checkpoint)), "newBoot": boot}
        complete = {**observed, "kind": "driver-installed-boot-complete"}
        if current == before:
            if _optional(boot_file) != observed or _optional(complete_file) != complete:
                raise Refusal("The Driver fence was not durably closed before reboot.")
        else:
            _immutable(boot_file, canonical(observed))
            _resume(authorities, leases, checkpoint, boot)
            _immutable(complete_file, canonical(complete))
            publish(install_file, before)
        return {"phase": "complete", "session": session, "oldBoot": checkpoint["oldBoot"], "newBoot": boot,
                "preparedSha256": observed["preparedSha256"]}
