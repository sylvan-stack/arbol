"""Prospective real admission cases and one fixed external caller; no execution on import.

The later admitted outer check supplies a genuinely new registered subject per
case.  This is not a path/selector exposed to Driver callers.  Inputs are actual
immutable packages and exclusively owned disposable state, never owner profiles.
The external observer holds no subject Session/SH.  Full-body admission is pending.
"""

from __future__ import annotations


# This fixed standalone branch precedes EVERY testing/application import. Library
# mode below remains a prospective case module, never an arbitrary CLI dispatcher.
def _fixed_guardian_caller() -> int:
    import _frozen_importlib
    import sys

    if _frozen_importlib.FrozenImporter.find_spec("os") is None:
        raise SystemExit("Frozen caller bootstrap unavailable.")
    import os

    def check(value: bool, message: str) -> None:
        if not value:
            raise ValueError(message)

    check(len(sys.argv) == 1 and sys.flags.isolated == 1 and sys.flags.no_site == 1
          and sys.flags.no_user_site == 1 and sys.flags.safe_path and sys.dont_write_bytecode,
          "Fixed caller needs zero arguments and the isolated interpreter flags.")
    check(os.__spec__ is not None and os.__spec__.origin == "frozen"
          and os.path.__spec__ is not None and os.path.__spec__.origin == "frozen", "Caller os must be frozen.")
    provider_root = os.path.abspath(sys.executable)
    for _ in range(4):
        provider_root = os.path.dirname(provider_root)
    check(os.path.realpath(provider_root, strict=True) == provider_root, "Provider root is not physical.")

    def inside(value: str) -> bool:
        return (isinstance(value, str) and os.path.isabs(value)
                and (os.path.realpath(value) == provider_root
                     or os.path.realpath(value).startswith(provider_root + os.sep)))

    check(bool(sys.path) and all(inside(value) for value in (sys.executable, sys.prefix, sys.base_prefix,
                                         sys.exec_prefix, sys.base_exec_prefix, *sys.path)),
          "Initial interpreter/import prefix escaped the actual provider runtime.")
    check(os.path.realpath(sys.executable, strict=True)
          == os.path.realpath(provider_root + "/runtime/python/bin/python3.14", strict=True),
          "Caller interpreter is not the actual provider interpreter.")
    info = os.lstat(provider_root)
    check(info.st_uid == os.getuid() and info.st_mode & 0o7777 == 0o700, "Provider root is not private.")
    count = 0
    for parent, directories, files in os.walk(provider_root, followlinks=False):
        for name in directories + files:
            count += 1
            check(count <= 100002, "Provider import inventory exceeded its bound.")
            path = os.path.join(parent, name)
            item = os.lstat(path)
            check(item.st_uid == os.getuid(), "Provider import owner differs.")
            kind = item.st_mode & 0o170000
            if kind == 0o120000:
                check(not os.path.isabs(os.readlink(path)) and inside(os.path.realpath(path, strict=True)),
                      "Unsafe provider runtime link before bundled stdlib import.")
            else:
                check(kind in (0o100000, 0o040000), "Unsafe provider runtime object before imports.")

    # The complete bundled tree was physically confined before these bundled
    # standard-library imports; application code remains unavailable until M/D.
    import base64
    import fcntl
    import hashlib
    import json
    import re
    import select
    import signal
    import stat
    import time
    import unicodedata
    from pathlib import Path
    from typing import Any
    from unittest.mock import patch

    def hashed(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    def regular(path: str, limit: int, *, mode: int | None = None) -> bytes:
        check(os.path.realpath(os.path.dirname(path), strict=True) == os.path.dirname(path), "Nonphysical file parent.")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            before = os.fstat(descriptor)
            check(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_size <= limit
                  and (mode is None or stat.S_IMODE(before.st_mode) == mode), "Unsafe fixed caller input file.")
            raw = bytearray()
            while len(raw) <= limit:
                part = os.read(descriptor, min(65536, limit + 1 - len(raw)))
                if not part:
                    break
                raw.extend(part)
            after, named = os.fstat(descriptor), os.lstat(path)
            check(len(raw) <= limit and len(raw) == before.st_size
                  and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_mode)
                  == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode)
                  and (after.st_dev, after.st_ino) == (named.st_dev, named.st_ino), "Fixed caller input changed.")
            return bytes(raw)
        finally:
            os.close(descriptor)

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            check(key not in result, "Duplicate caller JSON field.")
            result[key] = value
        return result

    def parsed(raw: bytes) -> dict[str, Any]:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite caller JSON.")))
        check(isinstance(value, dict), "Caller expected one object.")
        return dict(value)

    def keys(value: dict[str, Any], names: str) -> None:
        check(set(value) == set(names.split()), "Unknown or missing fixed caller field.")

    def encoded(value: dict[str, Any]) -> bytes:
        return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                + "\n").encode()

    def relative(name: Any) -> str:
        check(isinstance(name, str) and bool(name) and "\\" not in name and "\0" not in name
              and not name.startswith("/") and all(part not in ("", ".", "..") for part in name.split("/")),
              "Unsafe provider relative name.")
        return str(name)

    manifest_raw = regular(provider_root + "/driver-payload-manifest.json", 32 * 1024 * 1024, mode=0o600)
    descriptor_raw = regular(provider_root + "/driver-capability.json", 4096, mode=0o600)
    manifest, declaration = parsed(manifest_raw), parsed(descriptor_raw)
    keys(manifest, "version kind files")
    keys(declaration, "version kind component build source interpreter entry helpers importRoots payloadManifestSha256 capabilities")
    check(type(manifest["version"]) is int and manifest["version"] == 1
          and manifest["kind"] == "driver-payload-manifest" and isinstance(manifest["files"], list)
          and len(manifest["files"]) <= 100000 and manifest_raw == encoded(manifest), "Invalid canonical provider M.")
    check(type(declaration["version"]) is int and declaration["version"] == 1
          and declaration["component"] == "arbol" and declaration["payloadManifestSha256"] == hashed(manifest_raw)
          and descriptor_raw == encoded(declaration)
          and declaration["interpreter"] == "runtime/python/bin/python3.14", "Invalid canonical provider D.")
    inventory: list[dict[str, Any]] = []
    names: set[str] = set()
    for parent, directories, files in os.walk(provider_root, followlinks=False):
        for name in directories + files:
            path = os.path.join(parent, name)
            local = os.path.relpath(path, provider_root).replace(os.sep, "/")
            if local in ("driver-payload-manifest.json", "driver-capability.json"):
                continue
            check(len(inventory) < 100000 and unicodedata.normalize("NFC", local) not in names,
                  "Ambiguous or excessive provider inventory.")
            names.add(unicodedata.normalize("NFC", local))
            item = os.lstat(path)
            row: dict[str, Any] = {"path": local, "mode": stat.S_IMODE(item.st_mode),
                                   "size": 0, "sha256": None, "target": None}
            if stat.S_ISDIR(item.st_mode):
                row["type"] = "directory"
            elif stat.S_ISREG(item.st_mode):
                raw = regular(path, 1024 * 1024 * 1024)
                row.update(type="file", size=len(raw), sha256=hashed(raw))
            else:
                check(stat.S_ISLNK(item.st_mode), "Unexpected provider object.")
                target = os.readlink(path)
                raw_target = target.encode("utf-8", "strict")
                check(bool(raw_target) and len(raw_target) <= 4096 and not os.path.isabs(target)
                      and inside(os.path.realpath(path, strict=True)), "Unconfined provider link.")
                row.update(type="symlink", size=len(raw_target), sha256=hashed(raw_target), target=target)
            inventory.append(row)
    inventory.sort(key=lambda row: str(row["path"]).encode())
    check(inventory == manifest["files"], "Actual complete provider inventory differs from M.")
    # Reject directory-link traversal cycles before any application import.
    nodes = {"", *(row["path"] for row in inventory if row["type"] == "directory")}
    edges: dict[str, set[str]] = {str(name): set() for name in nodes}
    for row in inventory:
        path = Path(provider_root) / row["path"]
        link_target: str | None = None
        if row["type"] == "directory":
            link_target = row["path"]
        elif row["type"] == "symlink" and path.resolve(strict=True).is_dir():
            link_target = path.resolve(strict=True).relative_to(provider_root).as_posix()
            link_target = "" if link_target == "." else link_target
        if link_target is not None:
            parent = Path(row["path"]).parent.as_posix()
            parent = "" if parent == "." else parent
            check(parent in edges and link_target in edges, "Invalid provider link graph.")
            edges[parent].add(link_target)
    degree = {name: 0 for name in edges}
    for targets in edges.values():
        for target in targets:
            degree[target] += 1
    pending = [name for name, degree_value in degree.items() if degree_value == 0]
    visited = 0
    while pending:
        name = pending.pop()
        visited += 1
        for target in edges[name]:
            degree[target] -= 1
            if degree[target] == 0:
                pending.append(target)
    check(visited == len(nodes), "Provider directory-link cycle.")
    check(isinstance(declaration["importRoots"], list) and bool(declaration["importRoots"]), "Missing provider import roots.")
    roots = [os.path.join(provider_root, relative(name)) for name in declaration["importRoots"]]
    check(all(inside(path) and os.path.isdir(path) for path in roots), "Unconfined provider import root.")
    sys.path[:] = roots
    control: list[int] = []
    child: Any = None
    child_owner: dict[str, Any] | None = None
    guardian: Any = None
    outputs: list[str] = []
    case_deadline = time.monotonic() + 60

    def output_bounds() -> None:
        check(time.monotonic() < case_deadline and all(os.stat(path).st_size <= 1024 * 1024 for path in outputs),
              "Fixed caller deadline/public output bound exceeded.")

    def frame_in(seconds: float) -> dict[str, Any]:
        deadline = min(case_deadline, time.monotonic() + seconds)
        data = bytearray()
        while len(data) <= 16384:
            output_bounds()
            remaining = deadline - time.monotonic()
            check(remaining > 0, "Caller control timed out.")
            if not select.select([control[0]], [], [], min(.05, remaining))[0]:
                continue
            part = os.read(control[0], 1)
            check(bool(part), "Unexpected caller-control EOF; not a death observation.")
            data.extend(part)
            if part == b"\n":
                check(len(data) <= 16384, "Oversized caller frame.")
                return parsed(bytes(data))
        raise ValueError("Oversized caller control frame.")

    def frame_out(value: dict[str, Any]) -> None:
        raw = encoded(value)
        check(len(raw) <= 16384, "Oversized caller output frame.")
        deadline = min(case_deadline, time.monotonic() + 5)
        view = memoryview(raw)
        while view:
            output_bounds()
            check(time.monotonic() < deadline, "Caller output backpressure timed out.")
            if select.select([], [control[1]], [], .05)[1]:
                count = os.write(control[1], view)
                check(count > 0, "Caller output closed.")
                view = view[count:]

    def directory(path: str) -> dict[str, Any]:
        check(os.path.realpath(path, strict=True) == path, "Subject path is not physical.")
        item = os.lstat(path)
        check(stat.S_ISDIR(item.st_mode) and item.st_uid == os.getuid()
              and stat.S_IMODE(item.st_mode) == 0o700, "Subject directory is not exclusively private.")
        return {"path": path, "device": item.st_dev, "inode": item.st_ino}

    def context_token(value: Any) -> bool:
        if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{43}", value, re.ASCII) is None:
            return False
        raw = base64.urlsafe_b64decode(value + "=")
        return len(raw) == 32 and base64.urlsafe_b64encode(raw).decode().rstrip("=") == value

    try:
        for descriptor in (0, 1, 2):
            check(stat.S_ISFIFO(os.fstat(descriptor).st_mode), "Caller control must be independently owned pipes.")
            duplicate = fcntl.fcntl(descriptor, fcntl.F_DUPFD_CLOEXEC, 3)
            check(duplicate >= 3 and not os.get_inheritable(duplicate), "Caller control descriptor not isolated.")
            control.append(duplicate)
        initial = frame_in(10)
        keys(initial, "version kind case window subjectSha256")
        check(type(initial["version"]) is int and initial["version"] == 1 and initial["kind"] == "guardian-class-case"
              and isinstance(initial["case"], str) and re.fullmatch(r"[0-9a-f]{32}", initial["case"], re.ASCII) is not None
              and initial["window"] in ("G-ready-return", "G-go-return", "G-started-return")
              and isinstance(initial["subjectSha256"], str)
              and re.fullmatch(r"[0-9a-f]{64}", initial["subjectSha256"], re.ASCII) is not None,
              "Unsupported closed caller case grammar.")
        check(not select.select([control[0]], [], [], 0)[0], "Extra initial caller frame.")
        cwd = os.path.realpath(os.getcwd(), strict=True)
        subject_raw = regular(cwd + "/guardian-class-subject.json", 16384, mode=0o600)
        check(hashed(subject_raw) == initial["subjectSha256"], "Fixed subject preparation hash differs.")
        subject = parsed(subject_raw)
        keys(subject, "version kind case cwd registry fixtureRoot outputRoot source tuples build acceptanceSha256 boot")
        check(type(subject["version"]) is int and subject["version"] == 1
              and subject["kind"] == "abr38-guardian-class-subject" and subject["case"] == initial["case"]
              and subject["cwd"] == directory(cwd) and subject["registry"] == directory(cwd + "/builds")
              and subject["fixtureRoot"] == directory(cwd + "/fixtures")
              and subject["outputRoot"] == directory(cwd + "/guardian-class-output"),
              "Wrong actual subject preparation identity.")
        check(not os.listdir(cwd + "/guardian-class-output"), "Caller output root is not fresh.")
        own_entry = os.path.realpath(__file__, strict=True)
        frozen_root = os.path.dirname(os.path.dirname(os.path.dirname(own_entry)))
        check(own_entry == frozen_root + "/tests/top/test_top_driver_state_admission.py", "Not the one fixed caller entry.")
        source = subject["source"]
        keys(source, "repository branch commit tree porcelain entrySha256")
        check(source["repository"] == frozen_root and source["porcelain"] == ""
              and isinstance(source["branch"], str) and bool(source["branch"])
              and all(isinstance(source[key], str) and re.fullmatch(r"[0-9a-f]{40}", source[key], re.ASCII)
                      for key in ("commit", "tree"))
              and source["entrySha256"] == hashed(regular(own_entry, 1024 * 1024)),
              "Pinned frozen committed caller input differs.")
        # The no-SH outer observer independently reads/rechecks the actual Git
        # facts before Popen; this caller never fabricates/repairs them or runs a
        # Git/tool/module chosen by control data. Its sole test closure is itself.
        check(isinstance(subject["tuples"], list) and len(subject["tuples"]) == 5,
              "Missing exact prepared tuple group before application import.")
        provider_pins = [row for row in subject["tuples"] if isinstance(row, dict) and row.get("component") == "arbol"]
        check(len(provider_pins) == 1, "Missing original prepared provider pin.")
        provider_pin = provider_pins[0]
        keys(provider_pin, "component build sourceCommit sourceTree payloadSha256 manifestSha256")
        check(provider_pin == {"component": "arbol", "build": declaration["build"],
                              "sourceCommit": declaration["source"]["commit"],
                              "sourceTree": declaration["source"]["tree"], "payloadSha256": hashed(descriptor_raw),
                              "manifestSha256": hashed(manifest_raw)},
              "Provider M/D differs from the independently hash-bound preparation before application import.")
        from arbol_builds.driver_admission import (
            Authority,
            normal_context,
            read,
            read_bytes,
            reconcile,
            without_authority,
        )
        from arbol_builds.driver_payload import _registered_payload, load, pin_payloads, resolve_candidate
        from arbol_builds.driver_process import Frames, Guardian, boot_uuid, matches, process_identity

        actual_provider = load(Path(provider_root), "arbol", declaration["build"])
        module_file = sys.modules[Guardian.__module__].__file__
        check(isinstance(module_file, str), "Actual Guardian has no physical module file.")
        assert isinstance(module_file, str)
        check(actual_provider.digest == hashed(descriptor_raw)
              and str(Path(module_file).resolve()) == provider_root + "/src/arbol_builds/driver_process.py",
              "Caller did not import the exact packaged Guardian.")
        check(subject["boot"] == boot_uuid(), "Actual subject boot differs.")
        registry = Path(cwd) / "builds"
        scope = resolve_candidate(registry, "arbol-codex-driver", subject["build"], subject["acceptanceSha256"])
        check(scope.gate.provider == actual_provider and isinstance(subject["tuples"], list)
              and len(subject["tuples"]) == 5, "Wrong complete actual subject tuple group.")
        payloads = [scope.gate.provider, *scope.producers]
        expected: dict[str, dict[str, Any]] = {}
        for row in subject["tuples"]:
            keys(row, "component build sourceCommit sourceTree payloadSha256 manifestSha256")
            check(row["component"] not in expected, "Duplicate real tuple pin.")
            expected[row["component"]] = row
        check(set(expected) == {payload.component for payload in payloads}, "Missing actual component tuple.")
        for payload in payloads:
            row = expected[payload.component]
            record, current = _registered_payload(registry, payload.component, payload.build)
            check(current == payload and record["source"]["uncommittedChanges"] is False
                  and row == {"component": payload.component, "build": payload.build,
                              "sourceCommit": payload.descriptor["source"]["commit"],
                              "sourceTree": payload.descriptor["source"]["tree"], "payloadSha256": payload.digest,
                              "manifestSha256": payload.descriptor["payloadManifestSha256"]}, "Actual immutable tuple pin differs.")
        state = Path(cwd) / "fixtures/guardian-class-state"
        check(not os.path.lexists(state), "Caller cannot reuse or pre-read an existing State.")
        for name in ("public.stdout", "public.stderr"):
            outputs.append(cwd + "/guardian-class-output/" + name)
        null = os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
        public_fds: list[int] = []
        try:
            for path in outputs:
                public_fds.append(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600))
            for source_fd, destination in ((null, 0), (public_fds[0], 1), (public_fds[1], 2)):
                os.dup2(source_fd, destination)
        finally:
            os.close(null)
            for descriptor in public_fds:
                os.close(descriptor)
        check(all(not os.get_inheritable(descriptor) for descriptor in control), "Control leaked into child inheritance.")
        authority = Authority(registry, "arbol-codex-driver")
        with authority.mutex():
            custody = reconcile(authority, persist_unknown=False, candidate=scope)
            check(custody.resolved and not custody.writers and not custody.handoffs,
                  "Caller subject is not new healthy actual custody.")
        prepared_child: Any = None
        boundary_seen = False

        def prepared(process: Any, identity: dict[str, Any]) -> None:
            nonlocal child, child_owner, prepared_child
            check(prepared_child is None and process.pid == identity["pid"]
                  and matches(identity, parent=os.getpid()), "Actual prepared child identity differs.")
            child, child_owner, prepared_child = process, dict(identity), process

        def boundary(window: str, value: dict[str, Any]) -> None:
            nonlocal boundary_seen
            if window != initial["window"]:
                return
            check(not boundary_seen and child_owner is not None and guardian is not None,
                  "Repeated or unowned caller boundary.")
            boundary_seen = True
            assert child_owner is not None
            context_path = authority.folder / "handoffs" / (guardian.handoff + ".context.json")
            raw = read_bytes(context_path)
            context = parsed(raw)
            normal_context(context)
            actual_caller = process_identity(os.getpid())
            check(context["parent"] == {"writer": guardian.writer, **actual_caller}
                  and context["process"] == child_owner and context["entry"] == scope.producer("arbol-codex-driver").descriptor["entry"]
                  and value["contextSha256"] == hashed(raw) and context["registry"] == str(registry)
                  and all(context_token(context[key]) for key in ("invocation", "writer", "handoff", "nonce")),
                  "Boundary does not bind its real context, child and actual caller.")
            with authority.mutex():
                root = read(authority.folder / "writers" / guardian.invocation / (guardian.writer + ".json"))
                check(root["phase"] == "active" and root["pid"] == actual_caller["pid"]
                      and root["startedAt"] == actual_caller["startedAt"], "Root transfer was already terminal.")
            frame_out({"version": 1, "kind": "guardian-class-ready", "case": initial["case"], "window": window,
                       "invocation": guardian.invocation, "writer": guardian.writer, "epoch": guardian.epoch,
                       "handoff": context["handoff"], "contextSha256": hashed(raw),
                       "caller": actual_caller, "child": child_owner})
            frame_out({"version": 1, "kind": "guardian-class-boundary", "case": initial["case"], "window": window,
                       "contextSha256": hashed(raw), "handoff": context["handoff"],
                       "caller": actual_caller, "child": child_owner})
            # No kill command: a death case is externally observed SIGKILL only.
            continuation = frame_in(10)
            keys(continuation, "version kind case command")
            check(continuation == {"version": 1, "kind": "guardian-class-control", "case": initial["case"],
                                   "command": "continue"} and type(continuation["version"]) is int,
                  "Unsupported caller control command.")
            check(not select.select([control[0]], [], [], 0)[0], "Extra caller continuation frame.")

        original_send, original_receive = Frames.send, Frames.receive

        def actual_send(frames: Frames, value: dict[str, Any]) -> None:
            original_send(frames, value)
            if value["type"] == "go":
                boundary("G-go-return", value)

        def actual_receive(frames: Frames) -> dict[str, Any]:
            value = original_receive(frames)
            if value["type"] == "ready":
                boundary("G-ready-return", value)
            elif value["type"] == "started":
                boundary("G-started-return", value)
            return value

        with pin_payloads(registry, payloads, candidate=scope):
            guardian = Guardian.admit(authority, scope.producer("arbol-codex-driver"), candidate=scope)
            with patch.object(Frames, "send", actual_send), patch.object(Frames, "receive", actual_receive):
                guardian.spawn_main(["--state-dir", str(state), "subscriptions", "identity", "chatgpt"],
                                    environment=without_authority(dict(os.environ)), prepared=prepared)
            check(boundary_seen and guardian.transferred and child is not None, "Positive control did not really transfer.")
            while child.poll() is None:
                output_bounds()
                time.sleep(.01)
            check(child.wait(timeout=1) == 0, "Positive-control actual child failed.")
            output_bounds()
            with authority.mutex():
                custody = reconcile(authority, persist_unknown=False, candidate=scope)
                check(custody.resolved and custody.active == custody.pending == 0
                      and all(row["phase"] == "terminal" for row in custody.writers), "Positive custody did not actually finish.")
                descriptor = authority.lease(exclusive=True)
                os.close(descriptor)
            # Positive control has no third protocol frame; observer reads actual
            # exit/status/custody and separate public files after reaping us.
            return 0
    except BaseException:
        if guardian is not None and not guardian.transferred:
            try:
                guardian.abort()
            except BaseException:
                pass  # Preserve the existing unresolved subject; never repair it.
        if child is not None:
            try:
                if child.poll() is None and child_owner is not None and matches(child_owner):
                    os.kill(child_owner["pid"], signal.SIGCONT)
                    os.kill(child_owner["pid"], signal.SIGTERM)
                child.wait(timeout=20)
            except BaseException:
                pass
        if len(control) == 3:
            os.write(control[2], b"Fixed Guardian caller failed; preserve its subject and raw evidence.\n")
        raise
    finally:
        for descriptor in control:
            os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(_fixed_guardian_caller())

# Imports intentionally follow the standalone exit: the caller never imports
# testing modules or widens the verified provider's declared importRoots.
# ruff: noqa: E402

import os
import signal
import struct
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from unittest.mock import patch

from driver_identity_qualification import Baseline, Workspace, require

import arbol_builds.driver_process as provider_process
from arbol_builds.driver_admission import (
    Authority,
    Refusal,
    canonical,
    normal_control,
    publish,
    read,
    read_bytes,
    reconcile,
    sha256,
    token,
    without_authority,
    writer_path,
)
from arbol_builds.driver_process import Frames, Guardian, process_identity
from top.driver_state_support import (
    EvidenceRecorder,
    ExactProcess,
    Object,
    ObservationFailed,
    OwnedChild,
    digest,
    document,
    physical_owned,
    signal_verified,
    tree_inventory,
)

COMPONENT = "arbol-codex-driver"
ContextFault = Literal["context-hash", "registry", "epoch", "own-parent", "entry", "payload", "acceptance", "nonce"]
GoFault = Literal["nonce", "challenge", "context-hash", "replay"]
CancellationWindow = Literal["offer", "ready", "go", "started"]
_NEGATIVE_SERIALIZATION = threading.Lock()


@dataclass(frozen=True)
class AdmissionSubject:
    """Only a later admitted static fixture constructor can supply these objects."""

    workspace: Workspace
    baseline: Baseline
    evidence: EvidenceRecorder
    environment: Mapping[str, str]

    @property
    def authority(self) -> Authority:
        return Authority(self.workspace.registry, COMPONENT)

    def verify_unused(self) -> None:
        self.workspace.verify(self.evidence)
        self.baseline.scopes[COMPONENT].recheck()
        require(self.baseline.scopes[COMPONENT].registry == self.workspace.registry,
                "Subject is not this real registered candidate scope.")
        # Source identity alone cannot authorize a provider from another package.
        provider = self.baseline.scopes[COMPONENT].gate.provider
        require(Path(provider_process.__file__).resolve().is_relative_to(provider.root),
                "The real parent implementation must come from the exact provider payload.")
        with self.authority.mutex():
            control = normal_control(self.authority, candidate=self.baseline.scopes[COMPONENT])
            custody = reconcile(self.authority, persist_unknown=False, candidate=self.baseline.scopes[COMPONENT])
            require(control["epoch"] == self.baseline.epochs[COMPONENT] and custody.resolved
                    and not custody.writers and not custody.handoffs,
                    "A failure case cannot reuse a used, tainted or unknown subject.")
        require(not os.path.lexists(self.state), "Each actual identity command needs a fresh owned State.")
        physical_owned(self.workspace.fixture_root, directory=True)

    @property
    def state(self) -> Path:
        return self.workspace.fixture_root / "admission-state"

    def argv(self) -> list[str]:
        # This signed-out local proof command does not consult/discover native auth.
        return ["--state-dir", str(self.state), "subscriptions", "identity", "chatgpt"]

    def guardian(self) -> Guardian:
        self.verify_unused()
        scope = self.baseline.scopes[COMPONENT]
        return Guardian.admit(self.authority, scope.producer(COMPONENT), candidate=scope)

    def snapshot(self) -> Object:
        return {"stateAbsent": not os.path.lexists(self.state),
                "fixture": tree_inventory(self.workspace.fixture_root)}

    def closed_observation(self) -> Object:
        """A failed protocol stays unknown/closed; no sampling, drain or reset."""
        with self.authority.mutex():
            custody = reconcile(self.authority, candidate=self.baseline.scopes[COMPONENT])
            require(custody.unknown or os.path.lexists(self.authority.folder / "taint.json"),
                    "Uncertain failed transfer was not retained.")
            try:
                normal_control(self.authority, candidate=self.baseline.scopes[COMPONENT])
            except Refusal:
                pass
            else:
                raise ObservationFailed("A failed transfer still admits ordinary work.")
            return {"unknown": custody.unknown, "active": custody.active, "pending": custody.pending,
                    "control": self.authority.read("control"),
                    "taint": read(self.authority.folder / "taint.json")}


@dataclass
class DirectChild:
    """Actual Guardian child handle, not a PID learned from output/EOF."""

    process: subprocess.Popen[bytes] | None = None
    identity: ExactProcess | None = None
    reaped: bool = False

    def prepared(self, child: subprocess.Popen[bytes], identity: Object) -> None:
        require(self.process is None, "A case cannot replace its independently observed child.")
        owner = ExactProcess.read(identity)
        require(owner.pid == child.pid and owner.live(parent=os.getpid()), "Actual child birth/parent differs.")
        self.process, self.identity = child, owner

    def wait(self) -> int:
        require(self.process is not None and self.identity is not None, "No real spawned child was observed.")
        assert self.process is not None
        result = self.process.wait(timeout=25)
        self.reaped = True
        return result

    def cleanup(self) -> None:
        if self.process is None or self.reaped:
            return
        if self.process.poll() is None:
            assert self.identity is not None
            # An exact owned PID only; no group, terminal inference or guessed kill.
            signal_verified(self.identity, signal.SIGCONT)
            signal_verified(self.identity, signal.SIGTERM)
        self.wait()


@contextmanager
def parent_wire(send: Callable[[Frames, Object], None], receive: Callable[[Frames], Object]) -> Iterator[None]:
    """Instrument the real parent wire, never return synthetic peer success.

    The independent immutable child still performs its own actual parsing,
    descriptor/parent/lease/State admission.  No child code is patched.  The
    original receive is always used by callers.  Exact finite faults below are
    testing triggers, not production algorithms or a generic callable dispatcher.
    """
    require(threading.current_thread() is threading.main_thread()
            and not any(t.is_alive() for t in threading.enumerate() if t is not threading.current_thread()),
            "Wire instrumentation requires an isolated single-threaded external case controller.")
    with _NEGATIVE_SERIALIZATION, patch.object(Frames, "send", send), patch.object(Frames, "receive", receive):
        yield


def wrong_context_refuses_before_ready(subject: AdmissionSubject, fault: ContextFault) -> None:
    """Semantic mutations rebind the offered hash, so a hash mismatch cannot mask them."""
    require(fault in ("context-hash", "registry", "epoch", "own-parent", "entry", "payload", "acceptance", "nonce"),
            "Unknown fixed context fault.")
    guardian = subject.guardian()
    child = DirectChild()
    before = subject.snapshot()
    observed: list[Object] = []
    sent = False
    original_send, original_receive = Frames.send, Frames.receive

    def send(frames: Frames, value: Object) -> None:
        nonlocal sent
        require(value["type"] == "offer" and not sent, "Invalid context-case parent wire phase.")
        sent = True
        assert guardian.handoff is not None
        path = subject.authority.folder / "handoffs" / (guardian.handoff + ".context.json")
        context = read(path)
        changed = dict(context)
        if fault == "context-hash":
            offered = {**value, "contextSha256": "0" * 64}
        else:
            if fault == "registry":
                changed["registry"] = str(subject.workspace.bin)
            elif fault == "epoch":
                changed["epoch"] = token()
            elif fault == "own-parent":
                changed["parent"] = {"writer": context["parent"]["writer"], **process_identity(os.getppid())}
            elif fault == "entry":
                changed["entry"] = "scripts/check_build.py"
            elif fault == "payload":
                changed["payloadSha256"] = "0" * 64
            elif fault == "acceptance":
                changed["acceptanceSha256"] = "0" * 64
            elif fault == "nonce":
                changed["nonce"] = token()
            changed_hash = sha256(canonical(changed))
            with subject.authority.mutex():
                publish(path, changed)
                handoff_path = subject.authority.folder / "handoffs" / (guardian.handoff + ".json")
                pending = read(handoff_path)
                # Rebind the hash, preserving the genuinely minted pending
                # identity. A semantic mismatch cannot be masked by raw hashing.
                pending = {**pending, "contextSha256": changed_hash}
                publish(handoff_path, pending)
            offered = {**value, "contextSha256": changed_hash}
        subject.evidence.write("offered-mutation.json", {"fault": fault, "original": context,
                                                        "offeredContext": changed, "offer": offered})
        original_send(frames, offered)

    def receive(frames: Frames) -> Object:
        value = original_receive(frames)
        observed.append(value)
        # Parent-side original digest checks must not hide erroneous child ready.
        raise ObservationFailed("Child sent a peer frame for an invalid semantic context.")

    refused = False
    try:
        with parent_wire(send, receive):
            try:
                guardian.spawn_main(subject.argv(), environment=without_authority(dict(subject.environment)),
                                    prepared=child.prepared)
            except Refusal:
                refused = True
        require(refused and sent and not observed, "No exact actual child-side refusal was observed.")
        require(child.wait() != 0, "Invalid admission exited successfully.")
        require(subject.snapshot() == before, "Invalid admission reached State before refusing.")
        with subject.authority.mutex():
            own = subject.authority.folder / "writers" / guardian.invocation
            require({p.name for p in own.iterdir()} == {guardian.writer + ".json"},
                    "Invalid context registered a child metadata writer.")
        subject.evidence.write("context-refusal.json", {"fault": fault, "child": child.identity.object()
                               if child.identity is not None else None, "reaped": child.reaped,
                               "before": before, "after": subject.snapshot(), "custody": subject.closed_observation()})
    finally:
        child.cleanup()


def wrong_go_or_replay_refuses_before_state(subject: AdmissionSubject, fault: GoFault) -> None:
    """A real ready and persisted child writer precede the single corrupted go.

    Parent SH is still held here; EX contention alone cannot prove child SH.
    The distinct positive begin case probes EX only after real parent release.
    """
    require(fault in ("nonce", "challenge", "context-hash", "replay"), "Unknown fixed go fault.")
    guardian, child = subject.guardian(), DirectChild()
    before = subject.snapshot()
    ready: Object | None = None
    started: list[Object] = []
    altered = False
    original_send, original_receive = Frames.send, Frames.receive

    def send(frames: Frames, value: Object) -> None:
        nonlocal altered
        if value["type"] == "offer":
            original_send(frames, value)
            return
        require(value["type"] == "go" and ready is not None and not altered, "Wrong go mutation phase.")
        altered = True
        with subject.authority.mutex():
            row = read_writer_actual(subject, guardian)
            require(row["phase"] == "active", "No actual independent child writer preceded go.")
        changed = dict(value)
        if fault == "nonce":
            changed["nonce"] = token()
        elif fault == "challenge":
            changed["challenge"] = token()
        elif fault == "context-hash":
            changed["contextSha256"] = "0" * 64
        if fault == "replay":
            # Both complete originals are queued in one write; no scheduler gap
            # between separate sends can turn a replay test into an ordinary go.
            raw = canonical(value)
            frames._timeout()
            frames.socket.sendall((struct.pack("!I", len(raw)) + raw) * 2)
        else:
            original_send(frames, changed)
        subject.evidence.write("go-mutation.json", {"fault": fault, "ready": ready, "go": changed})

    def receive(frames: Frames) -> Object:
        nonlocal ready
        value = original_receive(frames)
        if ready is None:
            require(value["type"] == "ready", "Actual child did not first send ready.")
            ready = value
        else:
            started.append(value)
        return value

    try:
        refused = False
        with parent_wire(send, receive):
            try:
                guardian.spawn_main(subject.argv(), environment=without_authority(dict(subject.environment)),
                                    prepared=child.prepared)
            except Refusal:
                refused = True
        require(ready is not None and altered, "The intended real ready/go boundary was not reached.")
        require(child.wait() != 0, "Corrupted/replayed go did not fail in the real child.")
        require(refused or fault == "replay", "Wrong go was accepted by the real parent.")
        require(not started or (fault == "replay" and len(started) == 1 and started[0]["type"] == "started"),
                "A bad challenge/nonce/context advanced to started.")
        require(subject.snapshot() == before, "Corrupted/replayed handshake reached State.")
        subject.evidence.write("go-refusal.json", {"fault": fault, "ready": ready, "started": started,
                                                  "parentRefused": refused, "reaped": child.reaped,
                                                  "custody": subject.closed_observation()})
    finally:
        child.cleanup()



def cancel_at_real_wire_boundary(subject: AdmissionSubject, window: CancellationWindow) -> None:
    """Cancel a verified real child at one literal observed transfer boundary.

    This is SIGTERM cancellation, not parent death or a fabricated terminal.
    A started-window scheduling miss fails rather than becoming a later window.
    """
    require(window in ("offer", "ready", "go", "started"), "Unknown finite cancellation window.")
    guardian, child = subject.guardian(), DirectChild()
    before = subject.snapshot()
    original_send, original_receive = Frames.send, Frames.receive
    triggered = False
    peer_frames: list[Object] = []

    def cancel(phase: str) -> None:
        nonlocal triggered
        if phase != window:
            return
        require(not triggered and child.identity is not None and child.process is not None,
                "Cancellation target/window is not the actual prepared child.")
        triggered = True
        assert child.identity is not None and child.process is not None
        # STOP makes the externally witnessed before-State condition stable.
        signal_verified(child.identity, signal.SIGSTOP)
        deadline = time.monotonic() + 10
        while True:
            stopped, status = os.waitpid(child.process.pid, os.WUNTRACED | os.WNOHANG)
            if stopped:
                require(stopped == child.process.pid and os.WIFSTOPPED(status), "Real cancellation child exited before STOP.")
                break
            require(time.monotonic() < deadline, "Cancellation STOP was not acknowledged.")
            time.sleep(.005)
        require(subject.snapshot() == before, "Missed cancellation boundary before actual State access.")
        signal_verified(child.identity, signal.SIGTERM)
        signal_verified(child.identity, signal.SIGCONT)
        subject.evidence.write("cancellation-trigger.json", {"window": window, "process": child.identity.object(),
                                                            "signal": int(signal.SIGTERM), "before": before})

    def send(frames: Frames, value: Object) -> None:
        cancel(str(value["type"]))
        original_send(frames, value)

    def receive(frames: Frames) -> Object:
        value = original_receive(frames)
        peer_frames.append(value)
        cancel(str(value["type"]))
        return value

    try:
        failure: str | None = None
        with parent_wire(send, receive):
            try:
                guardian.spawn_main(subject.argv(), environment=without_authority(dict(subject.environment)),
                                    prepared=child.prepared)
            except (Refusal, OSError) as error:
                failure = type(error).__name__
        require(triggered, "The specified real protocol cancellation boundary was not reached.")
        require(child.wait() != 0 and child.reaped, "Cancellation did not end/reap the actual child.")
        require(subject.snapshot() == before, "Cancelled admission reached State.")
        # An accepted terminal is possible only if genuinely published by the
        # product. No test writes terminal, clears taint or samples away unknown.
        with subject.authority.mutex():
            custody = reconcile(subject.authority, candidate=subject.baseline.scopes[COMPONENT])
            require(custody.unknown or (custody.resolved and all(row["phase"] == "terminal" for row in custody.writers)),
                    "Cancellation lost its pending/active obligation without real completion.")
            if custody.unknown:
                try:
                    normal_control(subject.authority, candidate=subject.baseline.scopes[COMPONENT])
                except Refusal:
                    pass
                else:
                    raise ObservationFailed("Unknown cancelled transfer still admits normal work.")
        subject.evidence.write("cancellation-outcome.json", {"window": window, "peerFrames": peer_frames,
                                "actualParentFailure": failure, "transferred": guardian.transferred,
                                "reaped": child.reaped, "unknown": custody.unknown,
                                "active": custody.active, "pending": custody.pending, "after": subject.snapshot()})
    finally:
        child.cleanup()

def read_writer_actual(subject: AdmissionSubject, guardian: Guardian) -> Object:
    require(guardian.handoff is not None, "No actual pending handoff.")
    assert guardian.handoff is not None
    handoff = read(subject.authority.folder / "handoffs" / (guardian.handoff + ".json"))
    return read(writer_path(subject.authority, guardian.invocation, handoff["child"]))


def begin_vs_independently_admitted_write(subject: AdmissionSubject) -> None:
    """STOP an actual acknowledged child before State, then begin without cancelling it.

    A missed scheduling window fails; no sleep/retry converts it into evidence.
    The later fixed actor lease-hold path can provide a stronger admitted barrier,
    but is not presumed implemented or used by this prospective source.
    """
    guardian, child = subject.guardian(), DirectChild()
    original_send, original_receive = Frames.send, Frames.receive
    session = str(uuid.uuid4())
    saw_started = False

    def receive(frames: Frames) -> Object:
        nonlocal saw_started
        value = original_receive(frames)
        if value["type"] == "started":
            require(not saw_started and child.identity is not None and child.process is not None,
                    "No exact actual started child.")
            saw_started = True
            assert child.identity is not None
            signal_verified(child.identity, signal.SIGSTOP)
            assert child.process is not None
            deadline = time.monotonic() + 10
            while True:
                stopped, status = os.waitpid(child.process.pid, os.WUNTRACED | os.WNOHANG)
                if stopped:
                    require(stopped == child.process.pid and os.WIFSTOPPED(status), "Child did not actually stop.")
                    break
                require(time.monotonic() < deadline, "Exact child STOP acknowledgement timed out.")
                time.sleep(.005)
            require(not os.path.lexists(subject.state), "Missed pre-State window; no race claim.")
        return value

    try:
        with parent_wire(original_send, receive):
            guardian.spawn_main(subject.argv(), environment=without_authority(dict(subject.environment)),
                                prepared=child.prepared)
        require(saw_started and guardian.transferred and guardian.lease < 0 and guardian.build_use < 0,
                "The real independent child was not acknowledged before parent release.")
        with subject.authority.mutex():
            try:
                descriptor = subject.authority.lease(exclusive=True)
            except BlockingIOError:
                pass
            else:
                os.close(descriptor)
                raise ObservationFailed("Parent release also released the child's independent lease.")
        scope = subject.baseline.scopes[COMPONENT]
        argv = [*scope.gate.provider.prefix, "driver-state", "begin", "--registry-dir", str(subject.workspace.registry),
                "--component", COMPONENT, "--session", session]
        begin = OwnedChild(argv, environment=without_authority(dict(subject.environment)), cwd=subject.workspace.registry)
        captured = begin.collect(seconds=30)
        require(captured.returncode == 0 and begin.reaped and document(captured.stdout)["phase"] == "draining",
                "Actual begin did not close normal admission while preserving the accepted child.")
        with subject.authority.mutex():
            require(subject.authority.read("control") == {"version": 1, "phase": "draining", "session": session,
                                                          "epoch": guardian.epoch}, "Begin rotated the admitted epoch.")
        try:
            Guardian.admit(subject.authority, guardian.payload, candidate=scope)
        except Refusal:
            pass
        else:
            raise ObservationFailed("New normal admission succeeded after begin.")
        assert child.identity is not None
        signal_verified(child.identity, signal.SIGCONT)
        require(child.wait() == 0, "Already acknowledged local identity write could not finish while draining.")
        root = document(read_bytes(subject.state / "identity.json"))
        proof = document(read_bytes(subject.state / "subscriptions/chatgpt/identity.json"))
        require(root["generation"] and proof["witness"], "The actual admitted command did not persist identity evidence.")
        with subject.authority.mutex():
            custody = reconcile(subject.authority, persist_unknown=False, candidate=scope)
            require(custody.resolved and custody.active == custody.pending == 0
                    and all(row["phase"] == "terminal" for row in custody.writers), "Admitted write did not really finish.")
            descriptor = subject.authority.lease(exclusive=True)
            os.close(descriptor)
        subject.evidence.write("begin-admitted-write.json", {"child": child.identity.object(), "reaped": child.reaped,
                                "begin": document(captured.stdout), "generation": root["generation"],
                                "proofSha256": digest(canonical(proof)), "state": tree_inventory(subject.state)})
    finally:
        child.cleanup()


# Historical partial4824481 had no supported late parent-death caller. Published
# DRV6e1 now permits the separate fixed caller above; its outer case/oracle bodies
# and complete independent admission remain current7.2/47/53 work. No runtime
# evidence or completion follows from authoring this prospective source.
