"""Publish one initially empty installed Driver cohort under closed admission."""

from __future__ import annotations

import os
from contextlib import ExitStack
from pathlib import Path
from pwd import getpwuid
from tempfile import mkdtemp

from arbol_installation.paths import build_payload_directory, build_registry, installation_root

from .driver_admission import (
    COMPONENTS,
    Authority,
    Object,
    Refusal,
    canonical,
    canonical_uuid,
    decode,
    deployment_mutex,
    fields,
    fresh_install,
    physical,
    private_directory,
    publish,
    publish_bytes,
    read,
    read_bytes,
    remove,
    sha256,
    sync_directory,
    token,
)
from .driver_payload import Payload, _registered_payload, pin_payloads, verify_acceptance, verify_gate
from .driver_process import boot_uuid
from .launcher import BUILD_PATTERN, valid_record
from .service import driver_launcher_source, driver_route_bytes, publish_driver_route


def _exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _read_optional(path: Path) -> Object | None:
    try:
        return read(path)
    except FileNotFoundError:
        return None


def _immutable(path: Path, raw: bytes) -> None:
    try:
        current = read_bytes(path)
    except FileNotFoundError:
        publish_bytes(path, raw)
        return
    if current != raw:
        raise Refusal("The staged Driver install evidence changed.")


def _directory_identity(directory: Path, *, empty: bool = False) -> Object:
    info = private_directory(directory).lstat()
    if empty and next(directory.iterdir(), None) is not None:
        raise Refusal("A fresh Driver state directory must be empty.")
    return {"device": info.st_dev, "inode": info.st_ino}


def _record(registry: Path, component: str, build: str) -> tuple[bytes, Object]:
    raw = read_bytes(registry / component / build / "build.json")
    value = decode(raw, exact=False)
    if not valid_record(value, component, build):
        raise Refusal(f"The registered {component} Build {build} record is invalid.")
    return raw, value


def _promotion_build(registry: Path, payload: Payload) -> Object:
    value, registered = _registered_payload(registry, payload.component, payload.build)
    raw = canonical(value)
    if (registered != payload or value["status"] != "working" or value.get("packageOnly") is not True
            or value.get("stableCandidate") is not True
            or (payload.component in COMPONENTS and value.get("dataFormat") != 2)):
        raise Refusal(f"Build {payload.component} {payload.build} lacks a successful stable candidate package.")
    return {"component": payload.component, "build": payload.build, "recordSha256": sha256(raw),
            "payloadSha256": payload.digest, "manifestSha256": payload.descriptor["payloadManifestSha256"],
            "source": payload.descriptor["source"], "checks": value["checks"]}


def _verify_retired(registry: Path, component: str, selected: str) -> None:
    for folder in private_directory(registry / component).iterdir():
        if not BUILD_PATTERN.fullmatch(folder.name) or folder.name == selected:
            continue
        _, record = _record(registry, component, folder.name)
        if record["status"] != "withdrawn" or _exists(build_payload_directory(registry, component, folder.name)):
            raise Refusal(f"{component} Build {folder.name} still has a previous installed payload or selection.")


def _prepare(path: Path, state_root: Path, binding: str, names: list[str],
             *, existing: bool) -> Path:
    entry = _read_optional(path)
    if entry is None:
        if existing or _exists(state_root):
            raise Refusal("The new Driver state root was not reserved by this install.")
        staged = Path(mkdtemp(prefix=".fresh-", dir=state_root.parent))
        sync_directory(state_root.parent)
        entry = {"version": 1, "bindingSha256": binding, "directory": str(staged),
                 "identity": _directory_identity(staged)}
        publish(path, entry)
    fields(entry, "version bindingSha256 directory identity")
    if not isinstance(entry["directory"], str):
        raise Refusal("The prepared Driver state path is invalid.")
    staged = Path(entry["directory"])
    if (entry["bindingSha256"] != binding or staged.parent != state_root.parent
            or not staged.name.startswith(".fresh-") or entry["identity"] != _directory_identity(staged)):
        raise Refusal("The reserved Driver state root does not match this install.")
    if not {item.name for item in staged.iterdir()}.issubset(names):
        raise Refusal("The reserved Driver state root contains unexpected entries.")
    return staged


def _verify_state(directory: Path, rows: list[Object], *, empty: bool) -> None:
    private_directory(directory)
    if {item.name for item in directory.iterdir()} != {Path(row["stateDirectory"]).name for row in rows}:
        raise Refusal("The installed Driver state root does not contain the expected cohort.")
    for row in rows:
        if row["stateDirectoryIdentity"] != _directory_identity(
                directory / Path(row["stateDirectory"]).name, empty=empty):
            raise Refusal("A Driver state directory changed after reservation.")


def _verify_gate(registry: Path, provider: Payload, gate_digest: str) -> None:
    gate = verify_gate(registry)
    if gate.digest != gate_digest or gate.provider != provider:
        raise Refusal("The installed Driver gate does not match the staged cohort.")


def _alias(alias: Path, launcher: Path, *, complete: bool) -> None:
    root = physical(alias.parent)
    info = root.lstat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise Refusal("The installed Driver command alias directory is unsafe.")
    if not _exists(alias) and not complete:
        alias.symlink_to(launcher)
        sync_directory(root)
    if not alias.is_symlink() or os.readlink(alias) != str(launcher):
        raise Refusal(f"The Driver command alias does not match its installed launcher: {alias}")


def install_fresh(registry: Path, provider: Payload, producers: dict[str, Payload], session: str,
                  routes: dict[str, Path], state_paths: dict[str, Path]) -> Object:
    """Stage the installed cohort and open it with one durable group commit."""
    home = Path(getpwuid(os.getuid()).pw_dir)
    if registry != build_registry(home) or not canonical_uuid(session):
        raise Refusal("Fresh Driver installation requires the canonical stable registry and a session UUID.")
    if (provider.component != "arbol" or not Path(__file__).resolve().is_relative_to(provider.root)
            or set(producers) != set(COMPONENTS) or set(routes) != set(COMPONENTS)
            or set(state_paths) != set(COMPONENTS)):
        raise Refusal("Fresh Driver installation requires the exact packaged provider and all four Drivers.")
    state_root = installation_root(home) / "driver-state" / session
    route_root = home / "Applications/Arbol/bin"
    names = [name.removeprefix("arbol-").removesuffix("-driver") for name in COMPONENTS]
    for component, name in zip(COMPONENTS, names, strict=True):
        if (producers[component].component != component or routes[component] != route_root / component
                or state_paths[component] != state_root / name):
            raise Refusal(f"{component} requires its canonical launcher and fresh state path.")

    payloads = [provider, *(producers[component] for component in COMPONENTS)]
    with deployment_mutex(registry), pin_payloads(registry, payloads):
        authority = [Authority(registry, component) for component in COMPONENTS]
        shared = authority[0].shared
        journal = shared / "fresh-install.json"
        preparation = shared / "fresh-preparation.json"
        gate_path = shared / "gate.json"
        if _exists(shared / "deployment.json"):
            raise Refusal("The stable registry already has a Driver deployment.")
        previous = fresh_install(registry)
        for component in COMPONENTS:
            _verify_retired(registry, component, producers[component].build)
        if previous is None and (_exists(gate_path) or _exists(shared / "acceptances")
                or any(_exists(item.folder) for item in authority)
                or any(driver_route_bytes(route) is not None for route in routes.values())
                or any(_exists(home / ".local/bin" / name) for name in COMPONENTS)):
            raise Refusal("Fresh install requires retired routes and no existing Driver admission.")

        sources = {
            name: driver_launcher_source(str(registry), name, str(routes[name]), provider,
                                         state_directory=state_paths[name])
            for name in COMPONENTS
        }
        gate_rows = [{"component": name, "launcher": str(routes[name]), "launcherSha256": sha256(sources[name])}
                     for name in COMPONENTS]
        gate_raw = canonical({"version": 1, "kind": "driver-gate", "providerPayloadSha256": provider.digest,
                              "components": gate_rows})
        boot = boot_uuid()
        registry_digest = sha256(canonical(authority[0].identity))
        gate_digest = sha256(gate_raw)
        platform = os.uname()
        if platform.sysname != "Darwin":
            raise Refusal("The installed Driver gate requires macOS.")
        system = {"system": platform.sysname, "release": platform.release, "machine": platform.machine}
        promotion = {"version": 1, "kind": "driver-stable-promotion", "session": session,
                     "registrySha256": registry_digest, "gateSha256": gate_digest, "platform": system,
                     "unitsRequested": False, "stateDirectories": {name: str(path) for name, path in state_paths.items()},
                     "builds": [_promotion_build(registry, payload) for payload in payloads]}
        promotion_raw = canonical(promotion)
        promotion_digest = sha256(promotion_raw)
        binding = {"version": 1, "kind": "driver-fresh-install", "mode": "fresh", "session": session,
                   "boot": boot, "registrySha256": registry_digest, "gateSha256": gate_digest,
                   "promotionSha256": promotion_digest}
        binding_digest = sha256(canonical(binding))
        private_directory(state_root.parent, create=True)
        components: list[Object]
        if previous is None:
            if _exists(state_root):
                raise Refusal("The new Driver state root already exists.")
            prepared = _prepare(preparation, state_root, binding_digest, names, existing=False)
            for name in names:
                private_directory(prepared / name, create=True)
            components = [
                {**row, "build": producers[component].build, "payloadSha256": producers[component].digest,
                 "stateDirectory": str(state_paths[component]),
                 "stateDirectoryIdentity": _directory_identity(prepared / name, empty=True), "epoch": token()}
                for row, component, name in zip(gate_rows, COMPONENTS, names, strict=True)
            ]
            previous = {**binding, "phase": "staging", "components": components}
            publish(journal, previous)
        else:
            # A fully opened installation is already pinned to its original boot evidence.
            if previous.get("phase") == "complete":
                binding["boot"] = previous.get("boot")
            if any(previous[key] != value for key, value in binding.items()):
                raise Refusal("Fresh Driver installation was started with different inputs.")
            components = previous["components"]
            for row, gate_row in zip(components, gate_rows, strict=True):
                name = gate_row["component"]
                if (any(row[key] != value for key, value in gate_row.items())
                        or row["build"] != producers[name].build or row["payloadSha256"] != producers[name].digest
                        or row["stateDirectory"] != str(state_paths[name])):
                    raise Refusal("The staged Driver route, state path or Build changed.")

        complete = previous["phase"] == "complete"
        if not _exists(state_root):
            if complete:
                raise Refusal("The completed Driver state root disappeared.")
            prepared = _prepare(preparation, state_root, binding_digest, names, existing=True)
            _verify_state(prepared, components, empty=True)
            # Both paths share the owner-only parent, serialized by the deployment mutex.
            if _exists(state_root):
                raise Refusal("A different Driver state root appeared before publication.")
            prepared.rename(state_root)
            sync_directory(state_root.parent)
        _verify_state(state_root, components, empty=not complete)
        if _exists(preparation):
            if complete:
                raise Refusal("Unexpected preparation alongside the completed Driver install.")
            remove(preparation)

        promotions = shared / "promotions"
        acceptances = shared / "acceptances"
        if not complete:
            private_directory(promotions, create=True)
            private_directory(acceptances, create=True)
        promotion_path = promotions / (promotion_digest + ".json")
        if complete:
            if read_bytes(promotion_path) != promotion_raw:
                raise Refusal("The installed Driver promotion record changed.")
        else:
            _immutable(promotion_path, promotion_raw)
            for item, row in zip(authority, components, strict=True):
                item.initialize(session, row["epoch"])

        with ExitStack() as locks:
            for item in authority:
                locks.enter_context(item.mutex())
            if not complete:
                for item in authority:
                    locks.callback(os.close, item.lease(exclusive=True))
                for name in COMPONENTS:
                    desired = (sources[name], 0o755)
                    current = driver_route_bytes(routes[name])
                    if current is None:
                        publish_driver_route(routes[name], None, desired)
                    elif current != desired:
                        raise Refusal("An installed Driver route differs from this fresh install.")
                _immutable(gate_path, gate_raw)
            _verify_gate(registry, provider, gate_digest)
            for name in COMPONENTS:
                _alias(home / ".local/bin" / name, routes[name], complete=complete)
            for item, row in zip(authority, components, strict=True):
                component = item.component
                payload = producers[component]
                acceptance = {
                    "version": 1, "kind": "driver-qualification", "status": "qualified", "scope": str(registry),
                    "contract": "DRV-browser-identity-1", "providerPayloadSha256": provider.digest,
                    "producerPayloadSha256": payload.digest, "gateSha256": gate_digest, "platform": system,
                    "evidenceSha256": promotion_digest,
                }
                raw = canonical(acceptance)
                digest = sha256(raw)
                control = item.read("control")
                normal = {"version": 1, "phase": "normal", "session": None, "epoch": row["epoch"]}
                draining = {**normal, "phase": "draining", "session": session}
                if not complete:
                    if (control not in (draining, normal) or _exists(item.folder / "taint.json")
                            or _exists(item.folder / "maintenance.json")
                            or any(next(private_directory(item.folder / name).iterdir(), None) is not None
                                   for name in ("writers", "handoffs", "sessions", "archive"))):
                        raise Refusal("Closed Driver admission contains other authority or custody.")
                    _immutable(acceptances / (digest + ".json"), raw)
                    selection = {"version": 1, "component": component, "acceptanceSha256": digest}
                    chosen = _read_optional(item.folder / "qualification.json")
                    if chosen is None:
                        item.write("qualification", selection)
                    elif chosen != selection:
                        raise Refusal("Another Driver acceptance is already selected.")
                elif control != normal:
                    raise Refusal("The completed Driver admission changed.")
                if verify_acceptance(item, payload, digest=digest) != acceptance:
                    raise Refusal("The installed Driver acceptance does not match the staged Build.")
                if not complete and control != normal:
                    item.write("control", normal)
            if not complete:
                _verify_state(state_root, components, empty=True)
                previous = {**previous, "phase": "complete"}
                publish(journal, previous)
        return previous
