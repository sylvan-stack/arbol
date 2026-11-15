"""Prospective ABR-38 cases for the exact isolated Python launch prefixes.

Each case requires an independently prepared registry. Body and integration
review precede execution. This module supplies no discovery or alternate entry.
"""

from __future__ import annotations

import os
import stat
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from driver_identity_qualification import WholeCheckController, require

from arbol_builds.driver_admission import Authority, reconcile, without_authority
from top.driver_state_support import (
    Captured,
    Object,
    OwnedChild,
    canonical,
    directory_identity,
    document,
    physical_owned,
    read_image,
    sync_directory,
    tree_inventory,
)

COMPONENT = "arbol-codex-driver"
MANIFEST = "driver-payload-manifest.json"
DESCRIPTOR = "driver-capability.json"
STD_LIB = "runtime/python/lib/python3.14"
NATIVE_DEPENDENCY = "_ctypes.cpython-314-darwin.so"
IMPORT_PROBE = """import json, sys, _ctypes
print(json.dumps({
    "interpreter": sys.executable,
    "stdlib": json.__spec__.origin,
    "native": _ctypes.__spec__.origin,
    "isolated": bool(sys.flags.isolated and sys.flags.no_site and sys.flags.no_user_site
                     and sys.flags.safe_path and sys.dont_write_bytecode),
}))
"""
BOOTSTRAP_REFUSAL = {"error": {"code": "launch_failed", "message": "Isolated provider bootstrap refused."}}
PROVIDER_REFUSAL = {"error": {"code": "builds_failed",
                             "message": "Driver maintenance refused; preserve closed recovery authority."}}
Mutation = Literal["manifest", "descriptor", "dependency", "mode", "external-link", "gate", "acceptance"]


def _write_new(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
    with path.open("xb") as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


@dataclass(frozen=True)
class ImportTraps:
    """Startup inputs and externally observed import markers."""

    root: Path
    identity: Object
    environment: Mapping[str, str]
    cwd: Path
    sentinels: tuple[Path, ...]
    sources: tuple[tuple[Path, Object], ...]
    link_source: Path

    @classmethod
    def create(cls, controller: WholeCheckController) -> ImportTraps:
        root = controller.workspace.fixture_root / "import-observer"
        root.mkdir(mode=0o700)
        home = root / "home"
        cwd = root / "cwd"
        empty_bin = root / "bin"
        home.mkdir(mode=0o700)
        cwd.mkdir(mode=0o700)
        empty_bin.mkdir(mode=0o700)
        python_home, python_path, user_base = (root / name for name in ("python-home", "python-path", "user-base"))
        startup = python_home / "lib/python3.14/encodings"
        startup.mkdir(mode=0o700, parents=True)
        python_path.mkdir(mode=0o700)
        sites = (user_base / "lib/python3.14/site-packages", user_base / "lib/python/site-packages")
        for directory in sites:
            directory.mkdir(mode=0o700, parents=True)
        sentinels: list[Path] = []
        sources: list[tuple[Path, Object]] = []

        def plant(path: Path, name: str, *, pth: bool = False) -> None:
            sentinel = root / (name + ".executed")
            statement = f"open({str(sentinel)!r}, 'xb').close()"
            _write_new(path, (("import builtins; " if pth else "") + statement + "\n").encode())
            sentinels.append(sentinel)
            sources.append((path, read_image(path, private=False).evidence()))

        plant(startup / "__init__.py", "pythonhome")
        plant(python_path / "json.py", "pythonpath")
        plant(python_path / "sitecustomize.py", "sitecustomize")
        plant(cwd / "json.py", "cwd")
        for index, directory in enumerate(sites):
            plant(directory / "usercustomize.py", f"user-site-{index}")
            plant(directory / "observe.pth", f"pth-{index}", pth=True)
        link_source = root / "external-json.py"
        plant(link_source, "external-link")
        sync_directory(controller.workspace.fixture_root)
        scope = {"HOME": str(home), "PATH": str(empty_bin), "LC_ALL": "C",
                 "PYTHONHOME": str(python_home), "PYTHONPATH": str(python_path), "PYTHONUSERBASE": str(user_base)}
        result = cls(root, directory_identity(root), scope, cwd, tuple(sentinels), tuple(sources), link_source)
        result.verify()
        return result

    def verify(self) -> None:
        require(directory_identity(self.root) == self.identity, "Import observation directory changed.")
        require(all(read_image(path, private=False).evidence() == expected for path, expected in self.sources),
                "A planted startup input changed.")
        require(not any(os.path.lexists(path) for path in self.sentinels),
                "A forbidden import or site hook actually executed.")

    def evidence(self) -> Object:
        return {"environment": dict(self.environment), "workingDirectory": str(self.cwd),
                "sources": [expected for _, expected in self.sources],
                "sentinels": [str(path) for path in self.sentinels]}


def _observe(controller: WholeCheckController, traps: ImportTraps, argv: list[str], name: str) -> Captured:
    traps.verify()
    child = OwnedChild(argv, environment=without_authority(dict(traps.environment)), cwd=traps.cwd)
    capture = controller._collect_owned(child, 90)
    controller.evidence.write_bytes(name + "-stdout.bin", capture.stdout)
    controller.evidence.write_bytes(name + "-stderr.bin", capture.stderr)
    controller.evidence.write(name + "-process.json", {
        "argv": argv, "owner": capture.owner.object(), "exit": capture.returncode, "reaped": child.reaped,
    })
    traps.verify()
    require(child.reaped and not capture.owner.live(), "The exact observed invocation has not been reaped.")
    return capture


def _driver_argv(controller: WholeCheckController, state: Path) -> list[str]:
    producer = controller.scope.producer(COMPONENT)
    return controller.fixed_argv(COMPONENT, producer.build, "driver", ("--state-dir", str(state), "info"))


def _bundled_import_origins(controller: WholeCheckController, traps: ImportTraps) -> Object:
    provider = controller.scope.gate.provider
    interpreter, isolation, _ = provider.prefix
    stdlib = provider.root / STD_LIB
    expected_stdlib = stdlib / "json/__init__.py"
    expected_native = stdlib / "lib-dynload" / NATIVE_DEPENDENCY
    capture = _observe(controller, traps, [interpreter, isolation, "-c", IMPORT_PROBE], "bundled-origins")
    require(capture.returncode == 0 and not capture.stderr, "The isolated import control exited unsuccessfully.")
    result = document(capture.stdout)
    require(result == {"interpreter": interpreter, "stdlib": str(expected_stdlib),
                       "native": str(expected_native), "isolated": True} and result.get("isolated") is True,
            "The real import control did not load the pinned bundled files under isolation.")
    return {"observed": result, "stdlib": read_image(expected_stdlib, private=False).evidence(),
            "native": read_image(expected_native, private=False).evidence()}


def _observe_normal(controller: WholeCheckController, traps: ImportTraps, state: Path) -> Object:
    require(not os.path.lexists(state), "The normal control must start with new State.")
    capture = _observe(controller, traps, _driver_argv(controller, state), "normal-import")
    result = document(capture.stdout)
    capability = result.get("capabilities")
    payload = controller.scope.producer(COMPONENT)
    require(capture.returncode == 0 and not capture.stderr and result.get("driver") == "codex"
            and result.get("build") == payload.build and result.get("stateDirectory") == str(state)
            and isinstance(capability, dict) and type(capability.get("subscriptionIdentity")) is int
            and capability["subscriptionIdentity"] == 1,
            "The isolated Driver did not return its ordinary capability and private State result.")
    physical_owned(state, directory=True, private=False)
    controller.require_finished_graph(COMPONENT)
    authority = Authority(controller.workspace.registry, COMPONENT)
    with authority.mutex():
        graph = reconcile(authority, persist_unknown=False, candidate=controller.scope)
        roots = [row for row in graph.writers if row["parent"] is None and row["phase"] == "terminal"
                 and {key: row[key] for key in ("pid", "startedAt")} == capture.owner.object()]
        require(graph.resolved and len(roots) == 1, "The actual normal provider lacks terminal custody.")
        mains = [row for row in graph.handoffs if row["invocation"] == roots[0]["invocation"]
                 and row["parent"] == roots[0]["writer"] and row["role"] == "main"
                 and row["phase"] == "accepted" and row["entry"] == payload.descriptor["entry"]]
        require(len(mains) == 1, "The normal import evidence lacks the actual MAIN transfer.")
    controller.scope.recheck()
    return {"response": result, "provider": capture.owner.object(), "terminalRoot": roots[0], "main": mains[0]}


def isolated_provider_and_normal_imports(controller: WholeCheckController) -> Object:
    controller.workspace.verify(controller.evidence)
    controller.scope.recheck()
    traps = ImportTraps.create(controller)
    imports = _bundled_import_origins(controller, traps)
    witness = _observe_normal(controller, traps, traps.root / "normal-state")
    session = str(uuid.uuid4())
    argv = [*controller.scope.gate.provider.prefix, "driver-state", "status", "--registry-dir",
            str(controller.workspace.registry), "--component", COMPONENT, "--session", session]
    authority = Authority(controller.workspace.registry, COMPONENT)
    before = tree_inventory(authority.folder)
    capture = _observe(controller, traps, argv, "administrative-status")
    status = document(capture.stdout)
    require(capture.returncode == 0 and not capture.stderr
            and status == {"version": 1, "component": COMPONENT, "session": session, "phase": "normal",
                           "custody": {"active": 0, "pending": 0, "unknown": False, "tainted": False}},
            "The isolated provider did not return ordinary read-only status.")
    require(tree_inventory(authority.folder) == before, "Status changed its authority beforeimage.")
    controller.scope.recheck()
    result = {"traps": traps.evidence(), "bundledImportControl": imports, "normal": witness, "status": status,
              "exactProviderEntry": controller.scope.gate.provider.prefix[2],
              "exactNormalEntry": controller.scope.producer(COMPONENT).prefix[2]}
    controller.evidence.write("isolated-imports.json", result)
    return result


def _alter(controller: WholeCheckController, traps: ImportTraps, mutation: Mutation) -> Object:
    scope = controller.scope
    provider = scope.gate.provider.root
    shared = scope.registry / ".driver-qualification"
    if mutation == "manifest":
        path = provider / MANIFEST
    elif mutation == "descriptor":
        path = provider / DESCRIPTOR
    elif mutation == "dependency":
        path = provider / STD_LIB / "lib-dynload" / NATIVE_DEPENDENCY
    elif mutation == "mode":
        path = provider / "src/arbol_builds/driver_state.py"
    elif mutation == "external-link":
        path = provider / STD_LIB / "json/__init__.py"
    elif mutation == "gate":
        path = shared / "gate.json"
    else:
        require(mutation == "acceptance", "Unknown fixed corruption case.")
        selected, _ = scope.acceptance(COMPONENT)
        path = shared / "acceptances" / (selected + ".json")
    require(path.is_relative_to(controller.workspace.registry), "Corruption target escaped the disposable registry.")
    limit = 32 * 1024 * 1024
    image = read_image(path, limit=limit, private=False)
    require(path.resolve(strict=True) == path, "Corruption target is not a physical payload input.")
    if mutation == "mode":
        path.chmod(image.mode ^ stat.S_IXUSR)
    elif mutation == "external-link":
        path.unlink()
        path.symlink_to(traps.link_source)
    else:
        altered = path.with_name(path.name + ".abr38-replacement")
        _write_new(altered, image.raw + b"\n", mode=image.mode)
        altered.replace(path)
    sync_directory(path.parent)
    if mutation == "external-link":
        require(Path(os.readlink(path)) == traps.link_source, "The external test link was not installed.")
        after: Object = {"target": str(traps.link_source), "kind": "symlink"}
    else:
        observed = read_image(path, limit=limit + 1, private=False)
        require(observed != image, "The disposable qualification input did not change.")
        after = observed.evidence()
    return {"before": image.evidence(), "after": after}


def corrupted_import_scope_refuses(controller: WholeCheckController, mutation: Mutation) -> Object:
    """Each invocation consumes its own fresh disposable negative registry."""
    controller.workspace.verify(controller.evidence)
    controller.scope.recheck()
    traps = ImportTraps.create(controller)
    healthy = _observe_normal(controller, traps, traps.root / "normal-state")
    state = traps.root / "refused-state"
    argv = _driver_argv(controller, state)
    authority = Authority(controller.workspace.registry, COMPONENT)
    before = tree_inventory(authority.folder)
    require(not os.path.lexists(state), "Refusal State already exists.")
    changed = _alter(controller, traps, mutation)
    controller.evidence.write("isolated-corruption-input.json", changed)
    # Gate/acceptance checking is already inside the provider. A failure there
    # still prevents producer admission and is separate from bootstrap refusal.
    stage = "provider-preflight" if mutation in ("gate", "acceptance") else "provider-bootstrap"
    expected = PROVIDER_REFUSAL if stage == "provider-preflight" else BOOTSTRAP_REFUSAL
    capture = _observe(controller, traps, argv, "corrupt-import")
    require(capture.returncode == 1 and capture.stdout == canonical(expected) and not capture.stderr,
            "Corrupt disposable input did not refuse at the expected launch boundary.")
    require(not os.path.lexists(state) and tree_inventory(authority.folder) == before,
            "The corrupt invocation reached producer State or changed actual admission custody.")
    result = {"mutation": mutation, "stage": stage, "inputs": changed, "healthy": healthy,
              "traps": traps.evidence(), "producerStateAbsent": True, "admissionBeforeimageKept": True}
    controller.evidence.write("isolated-corruption.json", result)
    return result
