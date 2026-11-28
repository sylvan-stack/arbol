"""Replace stable Driver packages inside the existing layout-2 installation."""

from __future__ import annotations

import os
import shlex
from contextlib import ExitStack
from pathlib import Path
from pwd import getpwuid

from arbol_installation.paths import build_registry, installation_root

from .driver_admission import (
    COMPONENTS,
    Authority,
    Object,
    Refusal,
    archive_terminal,
    canonical,
    canonical_uuid,
    decode,
    deployment_mutex,
    fields,
    fresh_install,
    private_directory,
    publish,
    read,
    read_bytes,
    reconcile,
    sha256,
    token,
    valid_hash,
)
from .driver_initial_install import _alias, _promotion_build, _verify_state
from .driver_payload import Gate, Payload, pin_payloads, registered, verify_acceptance, verify_gate
from .driver_registration import register_candidates
from .driver_state import _immutable, _use_current
from .launcher import BUILD_PATTERN, open_use_guard
from .service import driver_route_bytes

RECEIPT_LIMIT = 64 * 1024


def _verify_standalone_codex(home: Path, launcher: Path, state: Path) -> None:
    component = "arbol-codex-driver"
    raw = driver_route_bytes(launcher)
    if raw is None:
        raise Refusal("The standalone Codex launcher is missing.")
    header = ("#!/bin/sh\nunset ARBOL_DRIVER_ADMISSION_FD ARBOL_DRIVER_ADMISSION_CONTEXT "
              "ARBOL_DRIVER_MAINTENANCE_FD ARBOL_DRIVER_MAINTENANCE_CONTEXT\n")
    source = raw[0].decode("utf-8")
    shell = shlex.split(source.removeprefix(header))
    if len(shell) != 5 or shell[0] != "exec":
        raise Refusal("The standalone Codex launcher has an unexpected format.")
    executable = Path(shell[1])
    payload = executable.parent.parent
    build = payload.parent.name
    if (not BUILD_PATTERN.fullmatch(build)
            or executable != home / ".local/lib/sylvan-stack" / component / build / "driver-payload/bin" / component
            or source != header + f'exec {shlex.quote(str(executable))} --state-dir {shlex.quote(str(state))} "$@"\n'
            or driver_route_bytes(executable) is None):
        raise Refusal("The standalone Codex launcher differs from its installed package or state directory.")
    manifest = decode(read_bytes(payload / "package-manifest.json", limit=RECEIPT_LIMIT),
                      limit=RECEIPT_LIMIT, exact=False)
    if manifest.get("component") != component or manifest.get("build") != build:
        raise Refusal("The standalone Codex package does not match its launcher.")


def _bound_packages(registry: Path, home: Path, install: Object, gate: Gate, *,
                    allow_standalone_codex: bool = False) -> dict[str, Payload]:
    state_root = installation_root(home) / "driver-state" / install["session"]
    _verify_state(state_root, install["components"], empty=False)
    packages = {"arbol": gate.provider}
    for row, gate_row in zip(install["components"], gate.document["components"], strict=True):
        component = row["component"]
        launcher = home / "Applications/Arbol/bin" / component
        state = state_root / component.removeprefix("arbol-").removesuffix("-driver")
        raw = driver_route_bytes(launcher)
        if (row["launcher"] != str(launcher) or row["stateDirectory"] != str(state)
                or any(row[key] != gate_row[key] for key in ("component", "launcher", "launcherSha256"))
                or raw is None or sha256(raw[0]) != row["launcherSha256"]):
            raise Refusal(f"{component} differs from its recorded launcher or state directory.")
        alias = home / ".local/bin" / component
        alias_target = launcher
        if allow_standalone_codex and component == "arbol-codex-driver":
            standalone = home / "Applications/Arbol Codex Driver/bin" / component
            if alias.is_symlink() and os.readlink(alias) == str(standalone):
                _verify_standalone_codex(home, standalone, state)
                alias_target = standalone
        _alias(alias, alias_target, complete=True)
        payload = registered(registry, component, row["build"])
        if payload.digest != row["payloadSha256"]:
            raise Refusal(f"{component} differs from its recorded installed package.")
        packages[component] = payload
    return packages


def _promotion(registry: Path, install: Object, packages: dict[str, Payload]) -> Object:
    machine = os.uname()
    if machine.sysname != "Darwin":
        raise Refusal("The installed Driver gate requires macOS.")
    return {"version": 1, "kind": "driver-stable-promotion", "session": install["session"],
            "registrySha256": install["registrySha256"], "gateSha256": install["gateSha256"],
            "platform": {"system": machine.sysname, "release": machine.release, "machine": machine.machine},
            "unitsRequested": False,
            "stateDirectories": {row["component"]: row["stateDirectory"] for row in install["components"]},
            "builds": [_promotion_build(registry, packages[name]) for name in ("arbol", *COMPONENTS)]}


def _promotion_path(shared: Path, install: Object) -> Path:
    digest = install["promotionSha256"]
    if not isinstance(digest, str) or not valid_hash(digest):
        raise Refusal("The Driver promotion digest is invalid.")
    return private_directory(shared / "promotions") / (digest + ".json")


def _acceptance(registry: Path, promotion: Object, provider: Payload, payload: Payload) -> Object:
    return {"version": 1, "kind": "driver-qualification", "status": "qualified", "scope": str(registry),
            "contract": "DRV-browser-identity-1", "providerPayloadSha256": provider.digest,
            "producerPayloadSha256": payload.digest, "gateSha256": promotion["gateSha256"],
            "platform": promotion["platform"], "evidenceSha256": sha256(canonical(promotion))}


def _qualification(component: str, acceptance: Object) -> Object:
    return {"version": 1, "component": component, "acceptanceSha256": sha256(canonical(acceptance))}


def _normal(row: Object) -> Object:
    return {"version": 1, "phase": "normal", "session": None, "epoch": row["epoch"]}


def _preflight(authority: Authority, control: Object) -> None:
    if any(os.path.lexists(authority.folder / item) for item in ("taint.json", "maintenance.json")):
            raise Refusal(f"{authority.component} has unresolved custody or maintenance. Replacement cannot proceed.")
    if authority.read("control") != control:
        raise Refusal(f"{authority.component} admission is already under maintenance or its epoch changed.")


def _controls(authorities: list[Authority], install: Object, packages: dict[str, Payload],
              promotion: Object) -> None:
    for authority, row in zip(authorities, install["components"], strict=True):
        payload = packages[authority.component]
        _preflight(authority, _normal(row))
        if verify_acceptance(authority, payload) != _acceptance(authority.registry, promotion, packages["arbol"], payload):
            raise Refusal(f"{authority.component} acceptance differs from the verified selection.")


def _replace_controls(authorities: list[Authority], leases: list[int], session: str, before: Object, after: Object,
                      old_packages: dict[str, Payload], packages: dict[str, Payload],
                      old_promotion: Object, promotion: Object) -> None:
    for authority, lease, old, new in zip(authorities, leases, before["components"], after["components"], strict=True):
        component, registry = authority.component, authority.registry
        old_normal = _normal(old)
        draining = {**old_normal, "phase": "draining", "session": session}
        normal = _normal(new)
        control = authority.read("control")
        if control not in (old_normal, draining, normal):
            raise Refusal(f"{component} no longer has the recorded replacement controls.")
        _preflight(authority, control)
        old_acceptance = _acceptance(registry, old_promotion, old_packages["arbol"], old_packages[component])
        acceptance = _acceptance(registry, promotion, packages["arbol"], packages[component])
        selected = _qualification(component, acceptance)
        current = authority.read("qualification")
        if current != selected and (control == normal or current != _qualification(component, old_acceptance)):
            raise Refusal(f"{component} no longer has the recorded replacement acceptance.")
        if control == normal:
            if any(next(private_directory(authority.folder / item).iterdir(), None) is not None
                   for item in ("writers", "handoffs")):
                raise Refusal(f"{component} has custody in the staged epoch.")
            continue
        if control == old_normal:
            authority.write("control", draining)
        if (os.path.lexists(authority.folder / "archive/custody-pending.json")
                or any(next(private_directory(authority.folder / item).iterdir(), None) is not None
                       for item in ("writers", "handoffs"))):
            archive_terminal(authority, lease)
        _immutable(private_directory(authority.shared / "acceptances") / (selected["acceptanceSha256"] + ".json"),
                   canonical(acceptance))
        if current != selected:
            authority.write("qualification", selected)
        authority.write("control", normal)


def replace_installed(registry: Path, session: str, folders: list[Path]) -> Object:
    home = Path(getpwuid(os.getuid()).pw_dir)
    if registry != build_registry(home) or not canonical_uuid(session):
        raise Refusal("Driver replacement requires the canonical stable registry and a session UUID.")
    authorities = [Authority(registry, name) for name in COMPONENTS]
    shared = authorities[0].shared
    with deployment_mutex(registry):
        current = fresh_install(registry)
        gate = verify_gate(registry)
        if (current is None or current["registrySha256"] != sha256(canonical(authorities[0].identity))
                or current["gateSha256"] != gate.digest or os.path.lexists(shared / "deployment.json")
                or os.path.lexists(shared / "fresh-preparation.json")):
            raise Refusal("Driver replacement requires a verified installation with no other deployment.")
        receipts = shared / "replacements"
        receipt = receipts / (session + ".json")
        before: Object
        after: Object
        previous = None
        if os.path.lexists(receipts):
            private_directory(receipts)
            try:
                previous = read(receipt, limit=RECEIPT_LIMIT)
            except FileNotFoundError:
                pass
        if previous is None:
            if current["phase"] != "complete" or not folders:
                raise Refusal("Provide stable candidates for a new replacement, or resume the recorded UUID.")
            before = current
            for authority, row in zip(authorities, before["components"], strict=True):
                _preflight(authority, _normal(row))
        else:
            fields(previous, "version kind session before after")
            if previous["kind"] != "driver-replacement" or previous["session"] != session or folders:
                raise Refusal("Resume the recorded Driver replacement UUID without candidate arguments.")
            recorded_before, recorded_after = previous["before"], previous["after"]
            if not isinstance(recorded_before, dict) or not isinstance(recorded_after, dict):
                raise Refusal("The Driver replacement receipt is invalid.")
            before, after = recorded_before, recorded_after
            if current == after:
                packages = _bound_packages(registry, home, after, gate)
                promotion = _promotion(registry, after, packages)
                if canonical(promotion) != read_bytes(_promotion_path(shared, after), limit=RECEIPT_LIMIT):
                    raise Refusal("The completed Driver promotion record changed.")
                _controls(authorities, after, packages, promotion)
                return after
            if current not in (before, {**after, "phase": "staging"}):
                raise Refusal("The recorded replacement no longer matches the installed Drivers.")

        old_packages = _bound_packages(registry, home, before, gate)
        old_promotion = _promotion(registry, before, old_packages)
        if canonical(old_promotion) != read_bytes(_promotion_path(shared, before), limit=RECEIPT_LIMIT):
            raise Refusal("The previous Driver promotion record changed.")
        if previous is None:
            updated = register_candidates(folders, registry, installed=old_packages)
            packages = {**old_packages, **updated}
            rows = [{**row, "build": packages[row["component"]].build,
                     "payloadSha256": packages[row["component"]].digest, "epoch": token()}
                    for row in before["components"]]
            promotion = _promotion(registry, before, packages)
            after = {**before, "components": rows, "promotionSha256": sha256(canonical(promotion))}
        else:
            packages = _bound_packages(registry, home, after, gate)
            promotion = _promotion(registry, after, packages)
        raw_promotion = canonical(promotion)
        if sha256(raw_promotion) != after["promotionSha256"]:
            raise Refusal("The Driver replacement promotion changed.")

        try:
            with ExitStack() as locks:
                for authority in authorities:
                    name = authority.component
                    build = old_packages[name].build
                    descriptor = open_use_guard(str(registry), name, build, exclusive=True)
                    locks.callback(os.close, descriptor)
                    _use_current(authority, build, descriptor)
                pins = [gate.provider, *(packages[name] for name in COMPONENTS if packages[name] != old_packages[name])]
                locks.enter_context(pin_payloads(registry, pins))
                for authority in authorities:
                    locks.enter_context(authority.mutex())
                leases: list[int] = []
                for authority in authorities:
                    lease = authority.lease(exclusive=True)
                    locks.callback(os.close, lease)
                    leases.append(lease)
                if current == before:
                    if _bound_packages(registry, home, before, gate) != old_packages:
                        raise Refusal("The original Driver packages changed before closing admission.")
                    _controls(authorities, before, old_packages, old_promotion)
                    for authority in authorities:
                        if not reconcile(authority, persist_unknown=False).resolved:
                            raise Refusal(f"{authority.component} has unresolved Driver custody. Its selection was preserved.")
                    private_directory(receipts, create=True)
                    raw = canonical({"version": 1, "kind": "driver-replacement", "session": session,
                                     "before": before, "after": after})
                    _immutable(receipt, raw, limit=RECEIPT_LIMIT)
                    publish(shared / "fresh-install.json", {**after, "phase": "staging"})
                _immutable(_promotion_path(shared, after), raw_promotion, limit=RECEIPT_LIMIT)
                _replace_controls(authorities, leases, session, before, after, old_packages, packages, old_promotion,
                                  promotion)
                _controls(authorities, after, packages, promotion)
                if _bound_packages(registry, home, after, gate) != packages:
                    raise Refusal("The staged Driver packages changed before publication.")
                publish(shared / "fresh-install.json", after)
        except BlockingIOError:
            raise Refusal("Driver Builds or admission are in use. Let the current work finish and resume replacement.") from None
        return after
