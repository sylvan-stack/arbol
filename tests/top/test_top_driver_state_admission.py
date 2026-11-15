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
            keys(value, "version type handoff nonce contextSha256 challenge")
            check(type(value["version"]) is int and value["version"] == 1
                  and value["type"] == {"G-ready-return": "ready", "G-go-return": "go", "G-started-return": "started"}[window]
                  and value["handoff"] == context["handoff"] and value["nonce"] == context["nonce"]
                  and context_token(value["challenge"]), "Actual peer/send frame is not the exact finite boundary.")
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
                actual_handoff = read(authority.folder / "handoffs" / (context["handoff"] + ".json"))
                check(actual_handoff["phase"] == ("pending" if window == "G-ready-return" else "accepted")
                      and (window == "G-ready-return" or actual_handoff["challenge"] == value["challenge"]),
                      "Actual durable pending/accepted challenge boundary differs.")
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
import selectors
import signal
import struct
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from unittest.mock import patch

from driver_identity_qualification import Baseline, CompletedLaunch, FixtureAuthority, Workspace, require

import arbol_builds.driver_process as provider_process
from arbol_builds.driver_admission import (
    Authority,
    Refusal,
    canonical,
    normal_context,
    normal_control,
    publish,
    read,
    read_bytes,
    reconcile,
    sha256,
    token,
    valid_hash,
    valid_token,
    validate,
    without_authority,
    writer_path,
)
from arbol_builds.driver_process import Frames, Guardian, process_identity
from top.driver_state_support import (
    Captured,
    EvidenceRecorder,
    ExactProcess,
    Object,
    ObservationFailed,
    OwnedChild,
    digest,
    document,
    exact_fields,
    physical_owned,
    read_image,
    signal_verified,
    sync_directory,
    tree_inventory,
)

COMPONENT = "arbol-codex-driver"
ContextFault = Literal["context-hash", "registry", "epoch", "own-parent", "entry", "payload", "acceptance", "nonce"]
GoFault = Literal["nonce", "challenge", "context-hash", "replay"]
CancellationWindow = Literal["offer", "ready", "go", "started"]
_NEGATIVE_SERIALIZATION = threading.Lock()


def _collect_real(child: OwnedChild, *, seconds: float, cleanup_seconds: float = 20) -> Captured:
    try:
        return child.collect(seconds=seconds)
    except BaseException as original:
        try:
            child.request_stop()
        except BaseException as error:
            original.add_note("Owned stop unavailable: " + type(error).__name__)
        try:
            child.wait_owned(seconds=cleanup_seconds)
        except BaseException as error:
            # Preserve unresolved owned custody and the ORIGINAL capture error;
            # a stop/identity/close failure cannot suppress the actual wait.
            original.add_note("Owned wait unavailable: " + type(error).__name__)
        raise


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
        captured = _collect_real(begin, seconds=30)
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


ClassWindow = Literal["G-ready-return", "G-go-return", "G-started-return"]


@dataclass(frozen=True)
class FrozenCaller:
    root: Path
    commit: str
    tree: str
    entry_sha256: str

    @property
    def entry(self) -> Path:
        return self.root / "tests/top/test_top_driver_state_admission.py"

    def verify(self, subject: AdmissionSubject) -> Object:
        """Read OWN real Git facts; never create/edit a checkout or clean flag."""
        physical_owned(self.root, directory=True)
        def git(*arguments: str) -> str:
            result = subprocess.run(["/usr/bin/git", "--no-optional-locks", "-C", str(self.root), *arguments],
                                    env=without_authority(dict(subject.environment)), capture_output=True, timeout=5, check=False)
            require(result.returncode == 0 and len(result.stdout) <= 65536 and len(result.stderr) <= 4096,
                    "Cannot establish actual frozen Git input facts.")
            return result.stdout.decode("utf-8", "strict").rstrip("\n")
        require(git("rev-parse", "--show-toplevel") == str(self.root) and git("rev-parse", "HEAD") == self.commit
                and git("rev-parse", "HEAD^{tree}") == self.tree
                and git("status", "--porcelain=v1") == "", "Frozen caller source is not its own clean exact Git input.")
        provider = subject.baseline.images["arbol"].pin
        require(self.commit == provider.commit and self.tree == provider.tree,
                "This final tuple must use its own exact committed caller source, not an auxiliary source pass.")
        image = read_image(self.entry, limit=1024 * 1024, private=False)
        require(image.sha256 == self.entry_sha256, "Fixed frozen caller entry bytes differ.")
        return {"repository": str(self.root), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                "commit": self.commit, "tree": self.tree, "porcelain": "", "entrySha256": image.sha256}


@dataclass(frozen=True)
class PublicCoupling:
    """Actual sealed candidate-entry observation plus preserved route source facts.

    This is not an ordinary working-launcher execution. That distinct observation
    belongs to final working-cohort coupling below, avoiding a fake working B.
    """

    provider_payload: str
    producer_payload: str
    guardian_sha256: str
    provider_entry_sha256: str
    gate_sha256: str
    route_sha256: str
    context_sha256: str
    invocation: str
    handoff: str
    observation: Path
    observation_sha256: str

    def verify(self, subject: AdmissionSubject) -> None:
        scope = subject.baseline.scopes[COMPONENT]
        provider, producer = scope.gate.provider, scope.producer(COMPONENT)
        image = read_image(self.observation, limit=1024 * 1024)
        require(image.sha256 == self.observation_sha256 and document(image.raw, limit=1024 * 1024)["kind"]
                == "abr38-actual-sealed-candidate-coupling", "Actual public coupling observation changed.")
        require(provider.digest == self.provider_payload and producer.digest == self.producer_payload
                and scope.gate.digest == self.gate_sha256
                and read_image(provider.root / "src/arbol_builds/driver_process.py", private=False).sha256 == self.guardian_sha256
                and read_image(provider.root / provider.descriptor["entry"], private=False).sha256 == self.provider_entry_sha256
                and read_image(subject.workspace.bin / COMPONENT, private=False).sha256 == self.route_sha256,
                "Class caller and actual sealed provider/route no longer bind the same packaged implementation.")
        # The genuine healthy rebind has archived the original terminal trees,
        # preserving raw public context/entries. Do not copy a record to active.
        matches_context: list[Path] = []
        for group in (subject.authority.folder / "archive").iterdir():
            if group.is_dir() and group.name.startswith("custody-"):
                path = group / "handoffs" / (self.handoff + ".context.json")
                if os.path.lexists(path):
                    matches_context.append(path)
        require(len(matches_context) == 1 and digest(read_bytes(matches_context[0])) == self.context_sha256,
                "Actual original public context is not uniquely preserved in its real archive.")


def prepare_sealed_candidate_coupling(subject: AdmissionSubject) -> tuple[AdmissionSubject, PublicCoupling]:
    """Execute the real sealed candidate entry, then honestly archive/rebind healthy.

    Actual creation/maintenance of the fixture is prospective body work, not an
    initializer invocation authorized during source authoring. No Build record is
    copied/promoted and the preparation cannot qualify a later changed tuple.
    """
    subject.verify_unused()
    scope = subject.baseline.scopes[COMPONENT]
    state = subject.workspace.fixture_root / "public-coupling-state"
    require(not os.path.lexists(state), "Public coupling State is not fresh.")
    argv = [*scope.gate.provider.prefix, "--qualification-launch", str(subject.workspace.registry), COMPONENT,
            scope.producer(COMPONENT).build, "driver", "--", "--state-dir", str(state),
            "subscriptions", "identity", "chatgpt"]
    public = OwnedChild(argv, environment=without_authority(dict(subject.environment)), cwd=subject.workspace.registry)
    captured = _collect_real(public, seconds=40)
    require(captured.returncode == 0 and public.reaped, "Actual sealed public candidate entry did not complete.")
    proof = document(captured.stdout)
    root = document(read_bytes(state / "identity.json"))
    sidecar = document(read_bytes(state / "subscriptions/chatgpt/identity.json"))
    require("error" not in proof and proof["generation"] == root["generation"] and proof["witness"] == sidecar["witness"],
            "Public identity output is not its independently persisted actual local proof.")
    with subject.authority.mutex():
        custody = reconcile(subject.authority, persist_unknown=False, candidate=scope)
        roots = [row for row in custody.writers if row["parent"] is None
                 and {key: row[key] for key in ("pid", "startedAt")} == captured.owner.object()]
        require(custody.resolved and custody.active == custody.pending == 0 and len(roots) == 1
                and all(row["phase"] == "terminal" for row in custody.writers), "Public actual custody did not finish.")
        invocation = roots[0]["invocation"]
        handoffs = [row for row in custody.handoffs if row["invocation"] == invocation and row["role"] == "main"]
        require(len(handoffs) == 1 and handoffs[0]["phase"] == "accepted"
                and handoffs[0]["entry"] == scope.producer(COMPONENT).descriptor["entry"], "Public actual child entry differs.")
        handoff = handoffs[0]
        context_raw = read_bytes(subject.authority.folder / "handoffs" / (handoff["handoff"] + ".context.json"))
        context = document(context_raw)
        normal_context(context)
        require(digest(context_raw) == handoff["contextSha256"]
                and context["parent"] == {"writer": roots[0]["writer"], **captured.owner.object()}
                and context["registry"] == str(subject.workspace.registry), "Actual public context/process coupling differs.")
        marker_path = subject.authority.folder / "normal-admissions" / (invocation + ".json")
        marker_hash = digest(read_bytes(marker_path))
        descriptor = subject.authority.lease(exclusive=True)
        os.close(descriptor)
    provider = scope.gate.provider
    guardian_hash = read_image(provider.root / "src/arbol_builds/driver_process.py", private=False).sha256
    entry_hash = read_image(provider.root / provider.descriptor["entry"], private=False).sha256
    route_hash = read_image(subject.workspace.bin / COMPONENT, private=False).sha256
    name = "public-coupling.json"
    observed_hash = subject.evidence.write(name, {"version": 1, "kind": "abr38-actual-sealed-candidate-coupling",
            "scope": str(subject.workspace.registry), "actualArgv": argv, "provider": captured.owner.object(),
            "returncode": captured.returncode, "reaped": public.reaped, "stdout": proof, "context": context,
            "contextSha256": digest(context_raw), "providerPayloadSha256": provider.digest,
            "producerPayloadSha256": scope.producer(COMPONENT).digest, "providerEntrySha256": entry_hash,
            "guardianSha256": guardian_hash, "routeSourceSha256": route_hash, "gateSha256": scope.gate.digest,
            "ordinaryRenderedRouteExecuted": False})
    launch = CompletedLaunch(COMPONENT, invocation, marker_hash, name, captured.owner)
    previous_state = tree_inventory(state)
    # A genuinely new transaction recorder first retains verified original
    # workspace lineage, then the actual immutable public launch witness.
    transaction = EvidenceRecorder(subject.evidence.root.parent, "coupling-authority-" + uuid.uuid4().hex)
    authority = FixtureAuthority(subject.workspace, transaction)
    transaction.write(name, document(read_bytes(subject.evidence.root / name, limit=1024 * 1024), limit=1024 * 1024))
    baseline = authority.apply([subject.baseline.images[component].pin for component in subject.baseline.images],
                               old=subject.baseline, completed=[launch])
    require(tree_inventory(state) == previous_state, "Healthy registry rebind altered the actual public State.")
    renewed = AdmissionSubject(subject.workspace, baseline, subject.evidence, subject.environment)
    coupling = PublicCoupling(provider.digest, scope.producer(COMPONENT).digest, guardian_hash, entry_hash,
                              scope.gate.digest, route_hash, digest(context_raw), invocation, handoff["handoff"],
                              subject.evidence.root / name, observed_hash)
    renewed.verify_unused()
    coupling.verify(renewed)
    return renewed, coupling


class CallerPipe:
    """Owned fixed caller Popen and independently bounded stdio control observer."""

    def __init__(self, subject: AdmissionSubject, frozen: FrozenCaller, window: ClassWindow) -> None:
        subject.verify_unused()
        require(window in ("G-ready-return", "G-go-return", "G-started-return"), "Unknown fixed class window.")
        source = frozen.verify(subject)
        self.subject, self.window = subject, window
        self.case = uuid.uuid4().hex
        parent = subject.workspace.registry.parent
        require(not os.path.lexists(parent / "guardian-class-subject.json"), "Subject preparation cannot be reused.")
        (parent / "guardian-class-output").mkdir(mode=0o700)
        data: Object = {"version": 1, "kind": "abr38-guardian-class-subject", "case": self.case,
                       "cwd": {"path": str(parent), "device": parent.stat().st_dev, "inode": parent.stat().st_ino},
                       "registry": subject.workspace.registry_identity,
                       "fixtureRoot": subject.workspace.fixture_root_identity,
                       "outputRoot": {"path": str(parent / "guardian-class-output"),
                                      "device": (parent / "guardian-class-output").stat().st_dev,
                                      "inode": (parent / "guardian-class-output").stat().st_ino},
                       "source": source, "tuples": [{"component": image.pin.component, "build": image.pin.build,
                            "sourceCommit": image.pin.commit, "sourceTree": image.pin.tree,
                            "payloadSha256": image.payload.digest,
                            "manifestSha256": image.payload.descriptor["payloadManifestSha256"]}
                            for image in subject.baseline.images.values()],
                       "build": subject.baseline.images[COMPONENT].pin.build,
                       "acceptanceSha256": subject.baseline.scopes[COMPONENT].acceptance_sha256,
                       "boot": subject.baseline.boot}
        raw = canonical(data)
        require(len(raw) <= 16384, "Fixed subject document exceeds its finite bound.")
        descriptor = os.open(parent / "guardian-class-subject.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            count = os.write(descriptor, raw)
            require(count == len(raw), "Incomplete subject preparation publication.")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        sync_directory(parent)
        provider = subject.baseline.scopes[COMPONENT].gate.provider
        self.argv = [str(provider.root / provider.descriptor["interpreter"]), "-ISB", str(frozen.entry)]
        self.channels = selectors.DefaultSelector()
        try:
            self.process = subprocess.Popen(self.argv, cwd=parent, env=without_authority(dict(subject.environment)),
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
        except BaseException:
            self.channels.close()
            raise
        observed_owner: ExactProcess | None = None
        try:
            self.owner = ExactProcess.read(process_identity(self.process.pid))
            observed_owner = self.owner
            require(self.owner.live(parent=os.getpid()), "Actual fixed caller birth/parent is unverified.")
            # Work cannot consume the reserved cleanup budget. The complete
            # caller case remains bounded60sec, including20sec failure cleanup.
            self.case_end = time.monotonic() + 60
            self.deadline = self.case_end - 20
            self.buffer = bytearray()
            self.raw_stdout = bytearray()
            self.diagnostics = bytearray()
            self.reaped = False
            assert self.process.stdout is not None and self.process.stderr is not None and self.process.stdin is not None
            for name_channel, pipe in (("control", self.process.stdout), ("diagnostic", self.process.stderr)):
                os.set_blocking(pipe.fileno(), False)
                self.channels.register(pipe, selectors.EVENT_READ, name_channel)
            os.set_blocking(self.process.stdin.fileno(), False)
            self.send({"version": 1, "kind": "guardian-class-case", "case": self.case,
                       "window": window, "subjectSha256": digest(raw)})
        except BaseException as original:
            try:
                if observed_owner is not None and observed_owner.live(parent=os.getpid()):
                    signal_verified(observed_owner, signal.SIGTERM)
            except BaseException as error:
                original.add_note("Owned caller constructor stop unavailable: " + type(error).__name__)
            try:
                self.close()
            except BaseException as error:
                original.add_note("Owned caller constructor endpoints unavailable: " + type(error).__name__)
            try:
                self.process.wait(timeout=25)
            except BaseException as error:
                original.add_note("Owned caller constructor wait unavailable: " + type(error).__name__)
            raise

    def output_bounds(self) -> None:
        require(time.monotonic() < self.deadline, "Complete caller case exceeded60 seconds.")
        for name in ("public.stdout", "public.stderr"):
            path = self.subject.workspace.registry.parent / "guardian-class-output" / name
            if os.path.lexists(path):
                read_image(path, limit=1024 * 1024)

    def send(self, value: Object) -> None:
        assert self.process.stdin is not None
        raw = canonical(value)
        require(len(raw) <= 16384, "Oversized observer control message.")
        limit = min(self.deadline, time.monotonic() + 5)
        view = memoryview(raw)
        with selectors.DefaultSelector() as writer:
            writer.register(self.process.stdin, selectors.EVENT_WRITE)
            while view:
                self.output_bounds()
                require(time.monotonic() < limit, "Owned caller control input backpressure timed out.")
                if writer.select(.05):
                    count = os.write(self.process.stdin.fileno(), view)
                    require(count > 0, "Owned caller control closed.")
                    view = view[count:]

    def pump(self, seconds: float) -> None:
        self.output_bounds()
        for key, _ in self.channels.select(seconds):
            raw = os.read(key.fd, 32769)
            if not raw:
                self.channels.unregister(key.fileobj)
            elif key.data == "diagnostic":
                self.diagnostics.extend(raw)
                require(len(self.diagnostics) <= 4096, "Caller diagnostics exceeded4KiB.")
            else:
                self.raw_stdout.extend(raw)
                self.buffer.extend(raw)
                require(len(self.raw_stdout) <= 32768 and len(self.buffer) <= 32768,
                        "Unexpected/oversized caller control output.")

    def frame(self) -> Object:
        limit = min(self.deadline, time.monotonic() + 20)
        while b"\n" not in self.buffer:
            require(time.monotonic() < limit and bool(self.channels.get_map()), "No complete real caller boundary frame.")
            self.pump(.05)
        raw, _, remainder = self.buffer.partition(b"\n")
        self.buffer[:] = remainder
        require(len(raw) + 1 <= 16384, "Oversized real caller frame.")
        return document(bytes(raw) + b"\n", limit=16384)

    def wait(self, *, seconds: float = 25) -> int:
        limit = min(self.deadline, time.monotonic() + seconds)
        while self.process.poll() is None or self.channels.get_map():
            require(time.monotonic() < limit, "Owned caller wait/reap exceeded its finite bound.")
            self.pump(.05)
        result = self.process.wait(timeout=1)
        self.reaped = True
        require(not self.buffer, "Extra/truncated caller control frame after actual exit.")
        return result

    def close(self) -> None:
        errors: list[str] = []
        try:
            self.channels.close()
        except BaseException as error:
            errors.append(type(error).__name__)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except BaseException as error:
                    errors.append(type(error).__name__)
        require(not errors, "Owned caller endpoint closure failed: " + ",".join(errors))


def _cleanup_verified_window(caller: CallerPipe, child: ExactProcess | None) -> Object:
    """Cleanup is branch-independent; only the fully verified record can signal.

    An orphan can be adopted after its original parent dies. SAME birth remains
    mandatory, but the dead parent's old current-parent relation is not demanded.
    A kernel disappearance is never a foreign-child reap or terminal record.
    """
    errors: list[str] = []
    caller_joined = caller.reaped
    child_disposition = "no-verified-target"
    deadline = min(caller.case_end, time.monotonic() + 20)
    try:
        try:
            if caller.process.poll() is None:
                if caller.owner.live(parent=os.getpid()):
                    signal_verified(caller.owner, signal.SIGTERM)
                else:
                    errors.append("caller-live-ownership-unverified")
        except BaseException as error:
            errors.append("caller-stop:" + type(error).__name__)
        try:
            # Actual Popen handle owns this wait even if IO capture/deadline
            # validation already failed. It does NOT reap any descendant.
            caller.process.wait(timeout=max(.001, min(5, deadline - time.monotonic())))
            caller.reaped = caller_joined = True
        except BaseException as error:
            errors.append("caller-wait:" + type(error).__name__)
    finally:
        try:
            if child is not None:
                child_disposition = "not-same-live-birth"
                for number in (signal.SIGCONT, signal.SIGTERM):
                    try:
                        if child.live():
                            signal_verified(child, number)
                    except BaseException as error:
                        errors.append("verified-child-signal:" + type(error).__name__)
                try:
                    while child.live() and time.monotonic() < deadline:
                        time.sleep(.01)
                    if child.live():
                        child_disposition = "verified-child-remains-live"
                        errors.append(child_disposition)
                    # Absence/reuse is only a kernel observation. The original
                    # metadata can remain unresolved and is never rewritten.
                except BaseException as error:
                    child_disposition = "kernel-observation-unavailable"
                    errors.append("verified-child-observe:" + type(error).__name__)
        finally:
            try:
                caller.close()
            except BaseException as error:
                errors.append("owned-endpoints:" + type(error).__name__)
    return {"callerReaped": caller_joined, "verifiedChild": None if child is None else child.object(),
            "childKernelObservation": child_disposition, "observerReapedChild": False, "errors": errors}


def guardian_class_window(subject: AdmissionSubject, frozen: FrozenCaller, *, window: ClassWindow, kill: bool) -> None:
    """Actual fixed caller death or separate real positive control, never a fake ACK."""
    subject, coupling = prepare_sealed_candidate_coupling(subject)
    caller = CallerPipe(subject, frozen, window)
    verified_child: ExactProcess | None = None
    try:
        ready, boundary = caller.frame(), caller.frame()
        observed_at = time.monotonic()
        exact_fields(ready, ("version", "kind", "case", "window", "invocation", "writer", "epoch", "handoff",
                             "contextSha256", "caller", "child"))
        exact_fields(boundary, ("version", "kind", "case", "window", "contextSha256", "handoff", "caller", "child"))
        require(type(ready["version"]) is int and ready["version"] == 1
                and type(boundary["version"]) is int and boundary["version"] == 1
                and all(valid_token(ready[key]) for key in ("invocation", "writer", "epoch", "handoff"))
                and valid_hash(ready["contextSha256"])
                and ready["kind"] == "guardian-class-ready" and boundary["kind"] == "guardian-class-boundary"
                and boundary == {key: ready[key] for key in boundary if key != "kind"}
                    | {"kind": "guardian-class-boundary"}
                and ready["case"] == caller.case and ready["window"] == window
                and ready["caller"] == caller.owner.object() and caller.owner.live(parent=os.getpid()),
                "Caller boundary frame does not bind the actual independently owned Popen.")
        # Parsing validates shape only. A frame claim is never a signal target,
        # including in finally when a later ownership/binding check rejects it.
        claimed_child = ExactProcess.read(ready["child"])
        require(claimed_child.live(parent=caller.owner.pid), "Caller frame child is not its exact real direct child.")
        authority = subject.authority
        with authority.mutex():
            raw = read_bytes(authority.folder / "handoffs" / (ready["handoff"] + ".context.json"))
            context = document(raw)
            normal_context(context)
            root = read(writer_path(authority, ready["invocation"], ready["writer"]))
            handoff = read(authority.folder / "handoffs" / (ready["handoff"] + ".json"))
            child_writer = read(writer_path(authority, ready["invocation"], context["writer"]))
            validate("writer", root)
            validate("writer", child_writer)
            validate("handoff", handoff)
            scope_now = subject.baseline.scopes[COMPONENT]
            require(context["component"] == root["component"] == child_writer["component"] == COMPONENT
                    and context["payloadSha256"] == root["payloadSha256"] == child_writer["payloadSha256"] == scope_now.producer(COMPONENT).digest
                    and context["epoch"] == root["epoch"] == child_writer["epoch"] == subject.baseline.epochs[COMPONENT]
                    and context["boot"] == root["boot"] == child_writer["boot"] == subject.baseline.boot
                    and context["acceptanceSha256"] == handoff["acceptanceSha256"] == scope_now.acceptance_sha256
                    and child_writer["parent"] == root["writer"] and child_writer["contextSha256"] == digest(raw)
                    and {key: child_writer[key] for key in ("pid", "startedAt")} == claimed_child.object()
                    and handoff["role"] == "main" and handoff["entry"] == context["entry"]
                    and handoff["invocation"] == ready["invocation"] and handoff["nonce"] == context["nonce"],
                    "Actual boundary failed independent tuple/epoch/boot/acceptance/writer bindings.")
            require(digest(raw) == ready["contextSha256"] and context["parent"] == {"writer": ready["writer"], **caller.owner.object()}
                    and context["process"] == claimed_child.object() and context["registry"] == str(subject.workspace.registry)
                    and context["entry"] == subject.baseline.scopes[COMPONENT].producer(COMPONENT).descriptor["entry"]
                    and root["phase"] == "active" and root["pid"] == caller.owner.pid and root["startedAt"] == caller.owner.started_at
                    and handoff["phase"] == ("pending" if window == "G-ready-return" else "accepted")
                    and child_writer["phase"] in ("active", "terminal"), "Actual durable boundary differs from the claimed frame.")
        coupling.verify(subject)
        require(claimed_child.live(parent=caller.owner.pid), "Actual owned child changed during complete ownership verification.")
        # Only the independently verified same-birth descendant can ever enter
        # cleanup. Retain this record across legitimate OS adoption after death.
        verified_child = claimed_child
        state = subject.workspace.fixture_root / "guardian-class-state"
        state_before = tree_inventory(state) if os.path.lexists(state) else None
        require(time.monotonic() - observed_at < 5 and caller.owner.live(parent=os.getpid()), "Exact kill/continue validation window expired.")
        if kill:
            signal_verified(caller.owner, signal.SIGKILL)
            code = caller.wait()
            require(code == -signal.SIGKILL and caller.reaped, "No actual SIGKILL/reap of the fixed caller.")
            with authority.mutex():
                custody = reconcile(authority, candidate=subject.baseline.scopes[COMPONENT])
                original_root = read(writer_path(authority, ready["invocation"], ready["writer"]))
                require(custody.unknown and original_root["phase"] == "active", "Actual parent death became fabricated terminal/quiescence.")
                try:
                    normal_control(authority, candidate=subject.baseline.scopes[COMPONENT])
                except Refusal:
                    pass
                else:
                    raise ObservationFailed("Unknown real parent death still admits normal work.")
            # Probe the actual independent lock after parent death. Success means
            # no remaining SH description; it never means terminal/known custody.
            with authority.mutex():
                try:
                    lease = authority.lease(exclusive=True)
                except BlockingIOError:
                    independent_lease = "still-held"
                else:
                    os.close(lease)
                    independent_lease = "released-but-unknown"
            probe_state = subject.workspace.fixture_root / "guardian-refusal-state"
            require(not os.path.lexists(probe_state), "Refusal probe State is not fresh.")
            marker_before = tree_inventory(authority.folder / "normal-admissions")
            with authority.mutex():
                writers_before = {(row["invocation"], row["writer"]) for row in custody.writers}
                handoffs_before = {row["handoff"] for row in custody.handoffs}
            for selector in ("driver", "build-unit"):
                tail = ["--state-dir", str(probe_state), "subscriptions", "identity", "chatgpt"] if selector == "driver" else []
                scope = subject.baseline.scopes[COMPONENT]
                argv = [*scope.gate.provider.prefix, "--qualification-launch", str(subject.workspace.registry), COMPONENT,
                        scope.producer(COMPONENT).build, selector, "--", *tail]
                remaining = min(10, caller.deadline - time.monotonic())
                require(remaining > 0, "No finite caller-case budget left for refusal and owned cleanup.")
                rejected = OwnedChild(argv, environment=without_authority(dict(subject.environment)), cwd=subject.workspace.registry)
                result = _collect_real(rejected, seconds=remaining,
                                       cleanup_seconds=min(20, max(.001, caller.case_end - time.monotonic())))
                require(rejected.reaped and result.returncode != 0 and not os.path.lexists(probe_state),
                        "Real normal/helper route accepted unknown custody or touched unadmitted State.")
                with authority.mutex():
                    current = reconcile(authority, persist_unknown=False, candidate=scope)
                    require(current.unknown and {(row["invocation"], row["writer"]) for row in current.writers} == writers_before
                            and {row["handoff"] for row in current.handoffs} == handoffs_before,
                            "Refusal attempt created a new writer/handoff before admission.")
                require(tree_inventory(authority.folder / "normal-admissions") == marker_before,
                        "Refused normal/helper attempt published a new admission marker.")
        else:
            caller.send({"version": 1, "kind": "guardian-class-control", "case": caller.case, "command": "continue"})
            require(caller.wait() == 0 and caller.reaped, "Actual positive caller/child transfer did not finish.")
            with authority.mutex():
                custody = reconcile(authority, persist_unknown=False, candidate=subject.baseline.scopes[COMPONENT])
                require(custody.resolved and custody.active == custody.pending == 0
                        and all(row["phase"] == "terminal" for row in custody.writers), "Positive transfer did not publish real full terminal custody.")
                lease = authority.lease(exclusive=True)
                os.close(lease)
            independent_lease = "genuinely-finished"
        subject.evidence.write("guardian-class-outcome.json", {"version": 1, "kind": "abr38-guardian-class-window",
            "window": window, "case": caller.case, "actualCallerArgv": caller.argv, "caller": caller.owner.object(),
            "child": verified_child.object(), "actualCallerReturncode": caller.process.returncode, "reaped": caller.reaped,
            "kill": kill, "ready": ready, "boundary": boundary, "independentLease": independent_lease,
            "stateBeforeKillOrContinue": state_before, "stateAfter": tree_inventory(state) if os.path.lexists(state) else None,
            "publicCouplingSha256": coupling.observation_sha256, "publicLateBinaryDeathObserved": False,
            "controlStdoutSha256": digest(bytes(caller.raw_stdout)), "diagnosticsSha256": digest(bytes(caller.diagnostics))},
            limit=32 * 1024 * 1024)
    finally:
        original_failure = sys.exception()
        # BOTH actual-death and failed-positive paths can leave a child after
        # terminating their caller. A SIGTERM is no promise of caller finally.
        cleanup = _cleanup_verified_window(caller, verified_child)
        cleanup["originalFailureType"] = None if original_failure is None else type(original_failure).__name__
        try:
            subject.evidence.write("guardian-class-cleanup.json", cleanup)
        except BaseException as error:
            if original_failure is None:
                raise
            original_failure.add_note("Cleanup evidence failed: " + type(error).__name__)
        if cleanup["errors"]:
            if original_failure is not None:
                original_failure.add_note("Owned cleanup unresolved: " + ",".join(cleanup["errors"]))
            else:
                raise ObservationFailed("Owned cleanup unresolved; preserve subject: " + ",".join(cleanup["errors"]))


def final_working_rendered_route_coupling(subject: AdmissionSubject) -> None:
    """FINAL unchanged working-cohort70 oracle, never an own-unit assertion.

    Its absence cannot be skipped/deferred inside a unit case and called a full
    unit pass. The own-unit case above owes actual sealed candidate entry + exact
    class/runtime/context coupling, with route hashes as SOURCE evidence only.
    This separately allocated qualification function requires actual final
    working records and executes the rendered ordinary route for that same tuple.
    Failed/unpruned auxiliaries can be legitimately named-runnable in production;
    this deliberate working requirement is the final qualification domain only.
    """
    subject.workspace.verify(subject.evidence)
    scope = subject.baseline.scopes[COMPONENT]
    scope.recheck()
    for image in subject.baseline.images.values():
        current = image.pin.verify(subject.workspace.registry)
        require(current.record["status"] == "working", "Final cohort ordinary-route proof awaits each real own full gate.")
    state = subject.workspace.fixture_root / "final-ordinary-route-state"
    require(not os.path.lexists(state), "Final ordinary route needs a fresh named disposable State.")
    before_routes = {component: read_image(subject.workspace.bin / component, private=False).sha256
                     for component in subject.baseline.scopes}
    before_gate = digest(read_bytes(subject.workspace.registry / ".driver-qualification/gate.json"))
    argv = [str(subject.workspace.bin / COMPONENT), "-v", scope.producer(COMPONENT).build,
            "--state-dir", str(state), "subscriptions", "identity", "chatgpt"]
    normal = OwnedChild(argv, environment=without_authority(dict(subject.environment)), cwd=subject.workspace.registry)
    captured = _collect_real(normal, seconds=40)
    require(normal.reaped and captured.returncode == 0, "Actual final rendered ordinary route did not complete.")
    proof = document(captured.stdout)
    require(proof["generation"] == document(read_bytes(state / "identity.json"))["generation"]
            and proof["witness"] == document(read_bytes(state / "subscriptions/chatgpt/identity.json"))["witness"],
            "Final ordinary proof does not bind actual independently persisted identity.")
    with subject.authority.mutex():
        custody = reconcile(subject.authority, persist_unknown=False, candidate=scope)
        roots = [row for row in custody.writers if row["parent"] is None
                 and {key: row[key] for key in ("pid", "startedAt")} == captured.owner.object()]
        require(custody.resolved and custody.active == custody.pending == 0 and len(roots) == 1,
                "Final ordinary caller/context custody is not actually complete.")
        main = [row for row in custody.handoffs if row["invocation"] == roots[0]["invocation"] and row["role"] == "main"]
        require(len(main) == 1 and main[0]["phase"] == "accepted"
                and main[0]["entry"] == scope.producer(COMPONENT).descriptor["entry"], "Final ordinary child is another entry.")
        raw = read_bytes(subject.authority.folder / "handoffs" / (main[0]["handoff"] + ".context.json"))
        context = document(raw)
        normal_context(context)
        require(context["parent"] == {"writer": roots[0]["writer"], **captured.owner.object()}
                and digest(raw) == main[0]["contextSha256"], "Final ordinary process/context coupling differs.")
        descriptor = subject.authority.lease(exclusive=True)
        os.close(descriptor)
    require(before_gate == scope.gate.digest == digest(read_bytes(subject.workspace.registry / ".driver-qualification/gate.json"))
            and before_routes == {component: read_image(subject.workspace.bin / component, private=False).sha256
                                  for component in subject.baseline.scopes}, "Final ordinary proof changed the exact gate/routes.")
    subject.evidence.write("final-ordinary-route.json", {"version": 1, "kind": "abr38-final-working-cohort-ordinary-route",
            "domain": "final-cohort70-only", "actualArgv": argv, "provider": captured.owner.object(), "reaped": normal.reaped,
            "returncode": captured.returncode, "stdout": proof, "context": context, "contextSha256": digest(raw),
            "providerPayloadSha256": scope.gate.provider.digest, "producerPayloadSha256": scope.producer(COMPONENT).digest,
            "guardianSha256": read_image(scope.gate.provider.root / "src/arbol_builds/driver_process.py", private=False).sha256,
            "gateSha256": before_gate, "routeSha256": before_routes[COMPONENT], "ordinaryRenderedRouteExecuted": True})


MAIN_CONTEXT_FAULTS: tuple[ContextFault, ...] = ("context-hash", "registry", "epoch", "own-parent", "entry", "payload", "acceptance", "nonce")
MAIN_GO_FAULTS: tuple[GoFault, ...] = ("nonce", "challenge", "context-hash", "replay")
MAIN_CANCELLATIONS: tuple[CancellationWindow, ...] = ("offer", "ready", "go", "started")
MAIN_CLASS_WINDOWS: tuple[ClassWindow, ...] = ("G-ready-return", "G-go-return", "G-started-return")
MAIN_CASE_IDS = frozenset({*("context-" + fault for fault in MAIN_CONTEXT_FAULTS),
                          *("go-" + fault for fault in MAIN_GO_FAULTS),
                          *("cancel-" + window for window in MAIN_CANCELLATIONS), "begin-admitted-write",
                          *(window + suffix for window in MAIN_CLASS_WINDOWS for suffix in ("-death", "-positive"))})


def complete_main_admission_inventory(subjects: Mapping[str, AdmissionSubject], frozen: FrozenCaller) -> None:
    """Whole static main inventory, with no filter, optional skip or runtime path dispatch.

    The later admitted fixture constructor must supply every independent subject
    through honest registered tuple preparation, preserving all Build histories.
    This API constructs no registry/catalogue records and launders no tainted State.
    Independent helper-after-parent-death remains the separate current8 inventory.
    """
    require(set(subjects) == MAIN_CASE_IDS and len({subject.workspace.registry for subject in subjects.values()}) == len(subjects),
            "Main admission needs every fixed case and genuinely independent subjects.")
    for fault in MAIN_CONTEXT_FAULTS:
        wrong_context_refuses_before_ready(subjects["context-" + fault], fault)
    for fault_go in MAIN_GO_FAULTS:
        wrong_go_or_replay_refuses_before_state(subjects["go-" + fault_go], fault_go)
    for window_cancel in MAIN_CANCELLATIONS:
        cancel_at_real_wire_boundary(subjects["cancel-" + window_cancel], window_cancel)
    begin_vs_independently_admitted_write(subjects["begin-admitted-write"])
    for window_class in MAIN_CLASS_WINDOWS:
        guardian_class_window(subjects[window_class + "-death"], frozen, window=window_class, kill=True)
        guardian_class_window(subjects[window_class + "-positive"], frozen, window=window_class, kill=False)


def late_new_guardian_gate_after_begin_refuses(subject: AdmissionSubject) -> None:
    """A NEW fixed runner transfer cannot start after actual begin closes it.

    This is the shared Guardian new-launch rule. It does not claim that an
    already admitted producer Session cannot finish a preregistered helper while
    draining, or supply the still-unreviewed active-Suite/H1 death latch.
    """
    guardian, child = subject.guardian(), DirectChild()
    before = subject.snapshot()
    session = str(uuid.uuid4())
    scope = subject.baseline.scopes[COMPONENT]
    argv = [*scope.gate.provider.prefix, "driver-state", "begin", "--registry-dir", str(subject.workspace.registry),
            "--component", COMPONENT, "--session", session]
    try:
        begin = OwnedChild(argv, environment=without_authority(dict(subject.environment)), cwd=subject.workspace.registry)
        captured = _collect_real(begin, seconds=30)
        require(begin.reaped and captured.returncode == 0 and document(captured.stdout)["phase"] == "draining",
                "Actual begin did not close normal admission for the late-launch case.")
    except BaseException:
        guardian.abort()
        raise
    prepared = False

    def forbidden_start(process: subprocess.Popen[bytes], identity: Object) -> None:
        nonlocal prepared
        prepared = True
        child.prepared(process, identity)
        raise ObservationFailed("Late new fixed gate reached actual Popen after begin.")

    try:
        with subject.authority.mutex():
            require(subject.authority.read("control") == {"version": 1, "phase": "draining", "session": session,
                                                          "epoch": guardian.epoch}, "Begin changed the original admitted epoch.")
        refused = False
        try:
            guardian.spawn_gate("unit", prepared=forbidden_start)
        except Refusal:
            refused = True
        require(refused and not prepared and child.process is None and guardian.handoff is None,
                "A late new runner registered/spawned instead of refusing before execution.")
        require(guardian.lease < 0 and guardian.build_use < 0 and subject.snapshot() == before,
                "Failed transfer retained owned descriptions or accessed State.")
        with subject.authority.mutex():
            taint = subject.authority.read("taint")
            require(taint["invocation"] == guardian.invocation and taint["epoch"] == guardian.epoch
                    and taint["component"] == COMPONENT, "Actual aborted transfer lost its durable original obligation.")
            try:
                normal_control(subject.authority, candidate=scope)
            except Refusal:
                pass
            else:
                raise ObservationFailed("Closed/tainted late launch became normally usable.")
        subject.evidence.write("late-gate-refusal.json", {"version": 1, "kind": "abr38-late-new-guardian-gate-refusal",
                "actualBeginArgv": argv, "actualBegin": document(captured.stdout), "provider": captured.owner.object(),
                "reaped": begin.reaped, "guardian": guardian.owner, "invocation": guardian.invocation,
                "epoch": guardian.epoch, "preparedChild": prepared, "stateBefore": before, "stateAfter": subject.snapshot(),
                "taint": taint, "activeSuiteH1DeathProved": False})
    finally:
        try:
            child.cleanup()
        finally:
            if guardian.lease >= 0:
                guardian.abort()


# CURRENT8 REMAINS PARTIAL. The accepted whole-inner report has only version,
# kind, component, build, payloadSha256, invocation, writer, contextSha256,
# selected, pendingExternal and inventorySha256. It supplies neither a reviewed
# preterminal Suite latch nor H1 entry/writer/handoff/ACK/PID bindings. Adding
# such fields or an external actor-control endpoint here would invent a schema.
# The real five-argument H1 actor uses its parent-owned socketpair; parent death
# queues EOF, which is failure, not an authorized successful completion. A real
# verified STOP can retain an existing H1 SH across death, but does not establish
# full local inventory completion + STILL ACTIVE Suite ownership by itself.
# Active Suite/H1 loss, exact helper terminal-before-release and remaining
# helper/Watcher/reused-group observations are NOT supplied by the source above.
# Their finite latch/report disposition needs separate specification/changed-Plan
# review before those prospective bodies, then actual47/53 body admission.
