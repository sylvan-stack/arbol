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

import fcntl
import os
import re
import selectors
import signal
import stat
import struct
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import CodeType
from typing import Literal
from unittest.mock import patch

from driver_identity_qualification import (
    Baseline,
    CompletedLaunch,
    FixtureAuthority,
    H1Schedule,
    H1View,
    TerminalView,
    WholeCheckController,
    Workspace,
    require,
)

import arbol_builds.driver_admission as provider_admission
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
    FileImage,
    HelperSpanCollector,
    Object,
    ObservationFailed,
    OwnedChild,
    TerminalSpanCollector,
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


def _fixed_sleep_image() -> Object:
    """Bounded fixed root-owned OS image; never an owned-fixture read or dispatch."""
    path = Path("/bin/sleep")
    require(os.uname().sysname == "Darwin" and path.resolve(strict=True) == path
            and path.parent.resolve(strict=True) == path.parent,
            "Fixed supported physical OS executable is unavailable.")
    end, limit = time.monotonic() + 2, 16 * 1024 * 1024
    file_keys = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size", "st_mtime_ns")
    parent_keys = ("st_dev", "st_ino", "st_mode", "st_uid", "st_mtime_ns")
    with ExitStack() as owned:
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        owned.callback(os.close, parent_fd)
        parent = os.fstat(parent_fd)
        require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == 0 and not parent.st_mode & 0o022,
                "Unsafe fixed root-owned OS executable directory.")
        fd = os.open("sleep", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent_fd)
        owned.callback(os.close, fd)
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1
                and not before.st_mode & 0o022 and bool(before.st_mode & 0o111)
                and 0 < before.st_size <= limit, "Unsafe fixed root-owned OS executable image.")
        raw = bytearray()
        for _ in range(limit // 65536 + 2):
            require(time.monotonic() < end, "Fixed OS executable observation exceeded its bound.")
            part = os.read(fd, min(65536, limit + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
            require(len(raw) <= limit, "Fixed OS executable image exceeds its bound.")
        else:
            raise ObservationFailed("Fixed OS executable read-count bound exceeded.")
        after, named = os.fstat(fd), os.stat("sleep", dir_fd=parent_fd, follow_symlinks=False)
        parent_after, parent_named = os.fstat(parent_fd), path.parent.lstat()
        require(len(raw) == before.st_size and time.monotonic() < end
                and all(getattr(before, key) == getattr(after, key) == getattr(named, key) for key in file_keys)
                and all(getattr(parent, key) == getattr(parent_after, key) == getattr(parent_named, key) for key in parent_keys),
                "Fixed OS executable or parent changed during original-fd/named/hash observation.")
        return {"path": str(path), "device": before.st_dev, "inode": before.st_ino, "uid": 0,
                "mode": stat.S_IMODE(before.st_mode), "nlink": 1, "size": before.st_size,
                "mtimeNs": before.st_mtime_ns, "sha256": digest(bytes(raw)),
                "parent": {"path": str(path.parent), "device": parent.st_dev, "inode": parent.st_ino,
                           "uid": 0, "mode": stat.S_IMODE(parent.st_mode), "mtimeNs": parent.st_mtime_ns}}


def provider_stale_owner_refuses(controller: WholeCheckController, baseline: Baseline, *,
                                  component: str, provider_source_sha256: str) -> Object:
    """Distinct NEGATIVE inspect-result fault at the real shared signal boundary.

    Two real harmless owned processes remain alive during the observation. Only
    one fresh inspect return value is replaced by a labelled wrong-birth row;
    there is no kernel PID-reuse claim or forged durable custody/context. This
    calls the real class boundary directly, not a claimed public-route run.
    The ordinary public supervise-to-SignalBridge coupling is source-bound.
    This prospective body has no gate registration or execution permission.
    """
    controller.workspace.verify(controller.evidence)
    controller.scope.recheck()
    require(component in baseline.scopes and component != "arbol"
            and controller.scope == baseline.scopes[component]
            and valid_hash(provider_source_sha256)
            and threading.enumerate() == [threading.current_thread()],
            "Stale-owner boundary needs the original actual tuple and sole observer thread.")
    provider = controller.scope.gate.provider
    source_path = provider.root / "src/arbol_builds/driver_process.py"
    source = read_image(source_path, limit=1024 * 1024, private=False)
    require(source.sha256 == provider_source_sha256 and provider_process.__file__ is not None
            and vars(provider_process)["os"] is os
            and Path(provider_process.__file__).resolve(strict=True) == source_path.resolve(strict=True)
            and all(Path(method.__code__.co_filename).resolve(strict=True) == source_path.resolve(strict=True)
                    for method in (provider_process.SignalBridge.__init__, provider_process.SignalBridge._forward,
                                   provider_process.SignalBridge.prepared, provider_process.supervise)),
            "Actual provider class/public call path differs from the admitted sealed source.")
    executable = Path("/bin/sleep")
    tool = _fixed_sleep_image()
    info = executable.lstat()
    require(executable.resolve(strict=True) == executable and stat.S_ISREG(info.st_mode)
            and info.st_uid == 0 and not info.st_mode & 0o022 and bool(info.st_mode & 0o111)
            and info.st_nlink == 1, "Fixed harmless process program is unavailable.")
    end = time.monotonic() + 20  # One shared observation AND owned-cleanup budget.
    authority = Authority(controller.workspace.registry, component)
    children: dict[str, subprocess.Popen[bytes]] = {}
    owners: dict[str, ExactProcess] = {}
    cleanup: dict[str, Object] = {}
    attempts: list[Object] = []
    terminal: provider_process.Terminal | None = None
    original: BaseException | None = None
    observation: Object = {"kind": "abr38-provider-stale-owner-negative-read-boundary",
        "component": component, "providerSource": source.evidence(), "harmlessProgram": tool,
        "publicRouteExecuted": False, "kernelPidReuseObserved": False, "signalAttempts": attempts}

    def remaining() -> float:
        value = end - time.monotonic()
        require(value > 0, "Stale-owner observation/owned cleanup exceeded its shared bound.")
        return value

    def forbidden_signal(*arguments: object) -> None:
        attempts.append({"arguments": list(arguments)})
        raise ObservationFailed("Stale-owner signal boundary attempted a forbidden signal.")

    try:
        # No subject admission, helper ticket, inherited grant, pipe, native
        # process or provider context is attached to these two fixed children.
        for name in ("owned-target", "unrelated-owned-survivor"):
            remaining()
            require(_fixed_sleep_image() == tool,
                    "Fixed harmless program changed before spawn.")
            remaining()
            process = subprocess.Popen([str(executable), "60"], env=without_authority({}),
                cwd=controller.workspace.registry, close_fds=True, start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            children[name] = process  # Retain actual Popen before fallible identity inspection.
            owner = ExactProcess.read(process_identity(process.pid))
            owners[name] = owner
            require(owner.live(parent=os.getpid()), "Owned harmless process birth/parent is unavailable.")
        target = children["owned-target"]
        target_owner = owners["owned-target"]
        actual = provider_process.inspect(target.pid)
        require(actual is not None and actual.owner == target_owner.object()
                and actual.parent == os.getpid() and actual.group == target.pid,
                "Real harmless target lacks its independently observed kernel birth/group/parent.")
        assert actual is not None
        birth = datetime.fromisoformat(target_owner.started_at.replace("Z", "+00:00"))
        wrong_birth = (birth + timedelta(microseconds=1)).astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        require(provider_process.valid_start(wrong_birth) and wrong_birth != target_owner.started_at,
                "Labelled negative read-boundary birth is not distinct/canonical.")
        changed = provider_process.Process({"pid": target.pid, "startedAt": wrong_birth}, actual.parent, actual.group)
        # A genuine Terminal is retained but never prepared/claimed, and no
        # handlers are installed. The real stale-owner branch returns BEFORE
        # using it; no controlling-terminal/process-group state is changed.
        terminal = provider_process.Terminal()
        bridge = provider_process.SignalBridge(terminal)
        bridge.child, bridge.owner = target, target_owner.object()
        with authority.mutex(seconds=remaining()):
            before = _raw_authority_image(authority)
        observation.update({"actualTarget": {"owner": actual.owner, "parent": actual.parent, "group": actual.group},
            "fault": {"label": "wrong-birth-inspect-result-only", "owner": changed.owner,
                      "parent": changed.parent, "group": changed.group},
            "participants": {name: owner.object() for name, owner in owners.items()}, "metadataBefore": before})
        with (patch.object(provider_process, "inspect", return_value=changed) as reader,
              patch.object(os, "kill", side_effect=forbidden_signal) as kill,
              patch.object(os, "killpg", side_effect=forbidden_signal) as killpg):
            bridge._forward(signal.SIGTERM)
            reader.assert_called_once_with(target.pid)
            kill.assert_not_called()
            killpg.assert_not_called()
        # Fresh REAL observations occur only AFTER restoring inspect and both
        # signal APIs. A mocked read can never prove an actual survivor.
        require(not attempts and all(owner.live(parent=os.getpid()) for owner in owners.values())
                and all(process.poll() is None for process in children.values()),
                "Real owned/unrelated process did not survive the refusal observation.")
        with authority.mutex(seconds=remaining()):
            after = _raw_authority_image(authority)
        require(after == before and bridge.owner == target_owner.object() and bridge.pending == set(),
                "Negative stale-owner read changed actual metadata or retained boundary ownership.")
        observation["metadataAfter"] = after
        observation["realSurvivorsAfterRestoringFault"] = {name: owner.object() for name, owner in owners.items()}
        remaining()
    except BaseException as error:
        original = error
    finally:
        # Independently attempt every owned target, then every actual Popen
        # wait. No group kill, SIGKILL, reused/unverified PID or second timeout.
        for name, process in children.items():
            record: Object = {"pid": process.pid, "termAttempted": False, "waited": False, "errors": []}
            cleanup[name] = record
            try:
                if process.poll() is None:
                    cleanup_owner = owners.get(name)
                    require(cleanup_owner is not None and cleanup_owner.live(parent=os.getpid()),
                            "Owned cleanup identity unavailable; leave it explicitly unresolved.")
                    assert cleanup_owner is not None
                    record["termAttempted"] = True
                    signal_verified(cleanup_owner, signal.SIGTERM)
            except BaseException as error:
                record["errors"].append(type(error).__name__)
        for name, process in children.items():
            record = cleanup[name]
            try:
                record["returncode"] = process.wait(timeout=max(0, end - time.monotonic()))
                record["waited"] = True
            except BaseException as error:
                record["errors"].append(type(error).__name__)
            record["unresolved"] = not record["waited"] or bool(record["errors"])
        if terminal is not None:
            try:
                terminal.close()  # Only its own unclaimed data description.
            except BaseException as error:
                observation["terminalCloseError"] = type(error).__name__
                if original is None:
                    original = error
                else:
                    original.add_note("Unclaimed terminal close: " + type(error).__name__)
        observation["ownedCleanup"] = cleanup
        observation["budgetExpired"] = time.monotonic() >= end
        if any(row["unresolved"] for row in cleanup.values()) or observation["budgetExpired"]:
            if original is None:
                original = ObservationFailed("Owned stale-owner observation cleanup is unresolved or expired.")
            original.add_note("Actual owned cleanup: " + repr(cleanup))
        observation["failed"] = original is not None
        try:
            controller.evidence.write("provider-stale-owner-refusal.json", observation, limit=16 * 1024 * 1024)
        except BaseException as error:
            if original is None:
                original = error
            else:
                original.add_note("Private stale-owner observation unavailable: " + type(error).__name__)
    if original is not None:
        raise original
    return observation


def _raw_authority_image(authority: Authority) -> Object:
    """Caller holds the real mutex; bounded raw fixture observation, no State API.

    Capture ALL names, including contexts, markers, sessions and lock files. The
    root inode and every retained directory/file inode belong to the oracle.
    This is not a refreshed production custody model or a terminal inference.
    """
    root = physical_owned(authority.folder, directory=True)
    inventory = tree_inventory(authority.folder)
    require(len(inventory) <= 4096, "Raw authority inventory exceeds its finite bound.")
    entries: list[Object] = []
    total = 0
    for row in inventory:
        item = dict(row)
        if row["type"] == "file":
            image = read_image(authority.folder / row["path"], limit=1024 * 1024)
            require(image.sha256 == row["sha256"] and image.device == row["device"]
                    and image.inode == row["inode"] and image.mode == row["mode"],
                    "Raw metadata changed during serialized capture.")
            total += len(image.raw)
            require(total <= 4 * 1024 * 1024, "Raw authority bytes exceed their finite bound.")
            item["rawHex"] = image.raw.hex()
        entries.append(item)
    require(tree_inventory(authority.folder) == inventory,
            "Authority inventory changed during serialized raw capture.")
    current = physical_owned(authority.folder, directory=True)
    require((root.st_dev, root.st_ino) == (current.st_dev, current.st_ino),
            "Authority root changed during raw capture.")
    return {"root": {"path": str(authority.folder), "device": root.st_dev,
                     "inode": root.st_ino, "mode": root.st_mode & 0o777}, "entries": entries}


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
            actual_owner = process_identity(os.getpid())
            require(guardian.owner == actual_owner and guardian.boot == provider_process.boot_uuid()
                    and guardian.payload == scope.producer(COMPONENT),
                    "Original Guardian is not the independently observed caller/boot/tuple.")
            expected_writer: Object = {"version": 1, "invocation": guardian.invocation, "writer": guardian.writer,
                "parent": None, "component": COMPONENT, "epoch": guardian.epoch,
                "payloadSha256": scope.producer(COMPONENT).digest, "boot": provider_process.boot_uuid(),
                **actual_owner, "phase": "active", "contextSha256": None}
            # Independent literal expectation, not Guardian._bootstrap_writer().
            original_path = subject.authority.folder / "writers" / guardian.invocation / (guardian.writer + ".json")
            require(document(read_image(original_path).raw) == expected_writer,
                    "Original bootstrap writer differs from actual independent process/tuple bindings.")
            metadata_before = _raw_authority_image(subject.authority)
            writer_files = [row["path"] for row in metadata_before["entries"]
                            if row["type"] == "file" and row["path"].startswith("writers/")]
            require(writer_files == [original_path.relative_to(subject.authority.folder).as_posix()]
                    and not any(row["path"].startswith("handoffs/") for row in metadata_before["entries"])
                    and not os.path.lexists(subject.authority.folder / "taint.json"),
                    "Late attempt needs the sole original bootstrap writer and no prior transfer/taint.")
            subject.evidence.write("late-gate-metadata-before.json", metadata_before)
        refused = False
        try:
            guardian.spawn_gate("unit", prepared=forbidden_start)
        except Refusal:
            refused = True
        with subject.authority.mutex():
            metadata_after = _raw_authority_image(subject.authority)
            # Preserve failed raw observations BEFORE asserting equality. No
            # writer, handoff/context, marker, lock, session or archive change is
            # authorized by this refused transfer; only taint.json may appear.
            subject.evidence.write("late-gate-metadata-after.json", metadata_after)
            require(refused and not prepared and child.process is None and guardian.handoff is None,
                    "A late new runner registered/spawned instead of refusing before execution.")
            require(guardian.lease < 0 and guardian.build_use < 0 and subject.snapshot() == before,
                    "Failed transfer retained owned descriptions or accessed State.")
            expected_taint: Object = {"version": 1, "component": COMPONENT, "epoch": guardian.epoch,
                "boot": expected_writer["boot"], "reason": "custody-loss", "invocation": guardian.invocation,
                "payloadSha256": scope.producer(COMPONENT).digest}
            taint = subject.authority.read("taint")
            taint_entries = [row for row in metadata_after["entries"] if row["path"] == "taint.json"]
            require(len(taint_entries) == 1 and taint_entries[0]["type"] == "file"
                    and document(bytes.fromhex(taint_entries[0]["rawHex"])) == expected_taint
                    and taint == expected_taint, "Aborted transfer lost its exact durable original obligation.")
            retained_after = {"root": metadata_after["root"], "entries": [row for row in metadata_after["entries"]
                                                                                 if row["path"] != "taint.json"]}
            require(retained_after == metadata_before,
                    "Refused late spawn mutated original raw metadata, marker, control, lock or custody inventory.")
            require(document(read_image(original_path).raw) == expected_writer,
                    "Refused late transfer changed the original active bootstrap writer.")
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
                "expectedOriginalWriter": expected_writer, "metadataBefore": metadata_before,
                "metadataAfter": metadata_after, "taint": taint, "activeSuiteH1DeathProved": False},
                limit=32 * 1024 * 1024)
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


# This source supersedes only the active-H1 gap in the historical CURRENT8
# comment above. The terminal interval is the separate af1/controller allocation;
# a successful precontinue observation below is NEVER a complete unit check.
_H1_SELECTORS = {"arbol-codex-driver": "chatgpt", "arbol-claude-driver": "anthropic-2",
                 "arbol-pi-driver": "zai-2", "arbol-mimo-driver": "xiaomi"}


@dataclass(frozen=True)
class H1ProgramPins:
    """Static reviewed body pins from the REAL candidate payload/source cohort.

    No path/module/selector is supplied: these three source entries are fixed.
    Later gate wiring must bind the actual independently admitted final bodies,
    not assume an older source hash qualifies a changed package.
    """

    support: str
    actor: str
    local_case: str

    def verify(self, controller: WholeCheckController, component: str) -> Object:
        controller.scope.recheck()  # Real M/D/runtime before any fixture read.
        payload = controller.scope.producer(component)
        case_path = ("tests/test_subscription_identity.py" if component == "arbol-mimo-driver"
                     else "tests/top/test_top_subscription_identity.py")
        observations: Object = {}
        for name, expected in (("tests/identity_support.py", self.support),
                               ("tests/identity_actor.py", self.actor), (case_path, self.local_case)):
            require(valid_hash(expected), "Missing admitted fixed H1 source hash.")
            image = read_image(payload.root / name, limit=1024 * 1024, private=False)
            require(image.sha256 == expected, "Fixed packaged H1 body differs from its admitted source pin.")
            observations[name] = image.evidence()
        require("tests/identity_actor.py" in payload.descriptor["helpers"], "Actor is not an actual D helper.")
        provider = controller.scope.gate.provider
        shared: Object = {}
        for module, name in ((provider_process, "src/arbol_builds/driver_process.py"),
                             (sys.modules[Authority.__module__], "src/arbol_builds/driver_admission.py")):
            location = module.__file__
            require(location is not None, "Actual shared production module has no physical source origin.")
            assert location is not None
            actual = read_image(Path(location).resolve(strict=True), limit=1024 * 1024, private=False)
            packaged = read_image(provider.root / name, limit=1024 * 1024, private=False)
            require(actual.sha256 == packaged.sha256, "Observer's actual guard/process body differs from sealed provider.")
            shared[name] = {"actualImported": actual.evidence(), "sealedProvider": packaged.evidence()}
        return {"source": payload.descriptor["source"], "payloadSha256": payload.digest,
                "runtime": payload.descriptor["interpreter"], "fixedBodies": observations,
                "actualGuardAndProcessSourceCoupling": shared, "providerPayloadSha256": provider.digest}


def _h1_canonical(raw: bytes, *, limit: int) -> Object:
    value = document(raw, limit=limit)
    require(canonical(value) == raw, "H1 observer evidence is not canonical JSONLF.")
    return value


def _h1_raw_ex(authority: Authority, expected: Object) -> bool:
    """Actual original-inode EX|NB; True means blocked by some real SH.

    No metadata guard, creation, duplicate SH, foreign unlock or inherited FD.
    A successful own EX is released only by closing this fresh description.
    Holder attribution is a SEPARATE obligation before the caller uses True.
    """
    fd = authority.open_lock("admission.lock")  # create=False, actual private schema.
    try:
        held, named = os.fstat(fd), (authority.folder / "admission.lock").lstat()
        require(stat.S_ISREG(held.st_mode) and held.st_uid == named.st_uid == os.getuid()
                and stat.S_IMODE(held.st_mode) == stat.S_IMODE(named.st_mode) == 0o600
                and held.st_nlink == named.st_nlink == 1
                and {"device": held.st_dev, "inode": held.st_ino} == expected
                and (held.st_dev, held.st_ino) == (named.st_dev, named.st_ino), "Original H1 lock changed.")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            blocked = True
        else:
            blocked = False
        again = (authority.folder / "admission.lock").lstat()
        require((held.st_dev, held.st_ino) == (again.st_dev, again.st_ino), "Lock replaced during raw EX probe.")
        return blocked
    finally:
        os.close(fd)


@dataclass(frozen=True)
class H1SystemPs:
    """Pinned fixed OS process-state observer, never a caller-selected executable."""

    identity: tuple[int, int, int, int, int]
    sha256: str

    @classmethod
    def capture(cls) -> H1SystemPs:
        require(sys.platform == "darwin", "H1 kernel STOP oracle requires actual Darwin.")
        path = Path("/bin/ps")
        require(path.resolve(strict=True) == path, "Fixed system ps is not physical.")
        parent = path.parent.lstat()
        require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == 0 and not parent.st_mode & 0o022,
                "Fixed system ps directory is writable or not OS-owned.")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and before.st_nlink == 1
                    and not before.st_mode & 0o022 and bool(before.st_mode & 0o111)
                    and 0 < before.st_size <= 32 * 1024 * 1024, "Fixed system ps is unsafe/oversized.")
            raw = bytearray()
            while len(raw) <= 32 * 1024 * 1024:
                part = os.read(fd, min(65536, 32 * 1024 * 1024 + 1 - len(raw)))
                if not part:
                    break
                raw.extend(part)
            after, named = os.fstat(fd), path.lstat()
            def key(item: os.stat_result) -> tuple[int, int, int, int, int]:
                return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_mode)
            require(len(raw) == before.st_size and key(before) == key(after) == key(named),
                    "Fixed system ps changed while pinned.")
            return cls(key(before), digest(bytes(raw)))
        finally:
            os.close(fd)

    def stopped(self, owner: ExactProcess, *, deadline: float) -> Object:
        require(self.capture() == self and owner.live(), "STOP observer/program/process identity changed.")
        end = min(deadline, time.monotonic() + 2)
        require(end > time.monotonic(), "No remaining actual STOP observation budget.")
        process = subprocess.Popen(["/bin/ps", "-p", str(owner.pid), "-o", "stat="],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        observer: ExactProcess | None = None
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        original: BaseException | None = None
        cleanup: list[str] = []
        try:
            # A fast system observer may already have exited; never signal an
            # unverified birth merely because this Popen once had that PID.
            if process.poll() is None:
                observer = ExactProcess.read(process_identity(process.pid))
                require(observer.live(parent=os.getpid()), "Actual ps direct-child birth unavailable.")
            with selectors.DefaultSelector() as selector:
                for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                    require(stream is not None, "Actual ps pipe missing.")
                    assert stream is not None
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                while selector.get_map():
                    remaining = end - time.monotonic()
                    require(remaining > 0, "Actual STOP observation exceeded two seconds.")
                    for key, _ in selector.select(min(.02, remaining)):
                        name = key.data
                        raw = os.read(key.fd, 4097 - len(buffers[name]))
                        if not raw:
                            selector.unregister(key.fileobj)
                        else:
                            buffers[name].extend(raw)
                            require(len(buffers[name]) <= 4096, "Actual ps output exceeds 4096 bytes.")
            status = process.wait(timeout=max(.001, end - time.monotonic()))
            require(time.monotonic() <= end and status == 0 and not buffers["stderr"] and owner.live()
                    and self.capture() == self, "STOP query failed or target/system program changed.")
            raw = bytes(buffers["stdout"])
            match = re.fullmatch(rb"[ \t]*([A-Za-z+<>NWs]+)[ \t]*\n", raw)
            require(match is not None and match[1].startswith(b"T"),
                    "Exact same-birth H1 is not actually kernel STOPPED.")
            return {"target": owner.object(), "argv": ["/bin/ps", "-p", str(owner.pid), "-o", "stat="],
                    "stdoutHex": raw.hex(), "stderrHex": bytes(buffers["stderr"]).hex(), "returncode": status,
                    "systemPsSha256": self.sha256, "systemPsIdentity": list(self.identity), "actualOwnedWait": True}
        except BaseException as error:
            original = error
            error.add_note("Actual failed ps bytes: " + repr({name: bytes(raw).hex() for name, raw in buffers.items()}))
            raise
        finally:
            if process.poll() is None:
                try:
                    if observer is not None and observer.live(parent=os.getpid()):
                        signal_verified(observer, signal.SIGTERM)
                    else:
                        cleanup.append("ps-ownership-unverified:no-signal")
                except BaseException as error:
                    cleanup.append("ps-stop:" + type(error).__name__)
                try:
                    process.wait(timeout=max(.001, end - time.monotonic()))
                except BaseException as error:
                    cleanup.append("ps-wait:" + type(error).__name__)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except BaseException as error:
                        cleanup.append("ps-pipe:" + type(error).__name__)
            if cleanup:
                note = "Actual STOP observer cleanup unresolved: " + repr(cleanup)
                if original is None:
                    raise ObservationFailed(note)
                original.add_note(note)


@dataclass(frozen=True)
class H1ShortOrigins:
    """Actual readiness origins plus hash-bound local result/receipt observations."""

    paths: tuple[Path, ...]
    identities: tuple[tuple[int, int, int, int], ...]
    receipts: tuple[tuple[Path, str], ...]

    @classmethod
    def capture(cls, view: H1View) -> H1ShortOrigins:
        root, component = view.root, view.component
        local = _h1_canonical(view.images["local-results.json"].raw, limit=1024 * 1024)
        row = local["rows"][-1]
        result_hash = row["resultSha256"]
        require(valid_hash(result_hash) and row["id"] == local["h1CaseId"], "Missing fixed H1 preconditions result.")
        receipts: list[tuple[Path, str]] = []
        if component == "arbol-codex-driver":
            path = root / "h1-preconditions.json"
            raw = read_image(path, limit=65536).raw
            require(digest(raw) == result_hash, "Codex readiness origins not bound to actual H1 result.")
            result = _h1_canonical(raw, limit=65536)
            require(result["kind"] == "abr38-H1-local-preconditions" and result["case"] == view.case
                    and result["helperContextSha256"] == view.helper_context_sha256
                    and result["actorReadySha256"] == view.images["actor-ready.json"].sha256,
                    "Codex directory origins belong to another actual capture/context.")
            records = result["shortLockDirectories"]
            receipts.append((path, digest(raw)))
        else:
            path = (root / ("result-" + result_hash + ".json") if component == "arbol-pi-driver"
                    else root / "local-evidence" / f"{len(local['rows']) - 1:04d}.result")
            result_raw = read_image(path, limit=65536).raw
            require(digest(result_raw) == result_hash, "Actual local H1 result bytes differ from full report.")
            result = _h1_canonical(result_raw, limit=65536)
            receipt_path = root / "short-lock-directories.json"
            directory_raw = read_image(receipt_path, limit=65536).raw
            directory_result = _h1_canonical(directory_raw, limit=65536)
            exact_fields(directory_result, ("version", "directories"))
            require(type(directory_result["version"]) is int and directory_result["version"] == 1,
                    "Wrong exact readiness directory receipt.")
            if component == "arbol-pi-driver":
                require(result["directoryEvidenceSha256"] == digest(directory_raw)
                        and result["contextSha256"] == view.helper_context_sha256
                        and result["actorReadySha256"] == view.images["actor-ready.json"].sha256,
                        "Pi origins/result are not bound to the actual capture-return.")
            else:
                # Claude/Mimo fixed admitted source writes this exclusive receipt
                # immediately after real capture-ready; their H1 result binds the
                # same actor/context/ACK. Do not invent a field in their wire.
                require(result["contextSha256"] == view.helper_context_sha256
                        and result["actorReadySha256"] == view.images["actor-ready.json"].sha256,
                        "Actual Claude/Mimo H1 result belongs to another capture.")
            records = directory_result["directories"]
            receipts.extend(((path, digest(result_raw)), (receipt_path, digest(directory_raw))))
        require(isinstance(records, list) and len(records) == 3, "All THREE original readiness directories are required.")
        expected = (root / "state", root / "state/subscriptions", root / "state/subscriptions" / _H1_SELECTORS[component])
        identities: list[tuple[int, int, int, int]] = []
        for path, record in zip(expected, records, strict=True):
            require(isinstance(record, dict), "Invalid physical readiness directory row.")
            if component == "arbol-codex-driver":
                exact_fields(record, ("relative", "device", "inode", "uid", "mode"))
                require(record["relative"] == path.relative_to(root).as_posix(), "A report selected another directory.")
            else:
                require(record["path"] == str(path), "A report selected another directory.")
                exact_fields(record, ("path", "device", "inode") if component == "arbol-pi-driver"
                             else ("path", "device", "inode", "uid", "mode"))
            info = physical_owned(path, directory=True)
            require(type(record["device"]) is int and type(record["inode"]) is int
                    and (info.st_dev, info.st_ino) == (record["device"], record["inode"]),
                    "Actual short-lock parent differs from ORIGINAL readiness origin.")
            if component != "arbol-pi-driver":
                require(record["uid"] == info.st_uid and record["mode"] == stat.S_IMODE(info.st_mode),
                        "Original readiness ownership/mode differs.")
            identities.append((info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)))
        observation = cls(expected, tuple(identities), tuple(receipts))
        observation.recheck()
        return observation

    def recheck(self) -> None:
        for path, identity in zip(self.paths, self.identities, strict=True):
            info = physical_owned(path, directory=True)
            require((info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)) == identity,
                    "Original readiness physical parent was replaced/re-owned.")
        for path, expected in self.receipts:
            require(read_image(path, limit=65536).sha256 == expected, "Immutable readiness receipt changed.")

    def absent_lock(self) -> Object:
        self.recheck()
        parent = self.paths[-1]
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            require((info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)) == self.identities[-1],
                    "Short-lock observation descriptor is not the retained parent.")
            try:
                os.stat("lock", dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ObservationFailed("Actual ephemeral Subscription lock still exists after stopped capture-return.")
            self.recheck()
            return {"parent": str(parent), "original": list(self.identities[-1]), "exactLockName": "lock",
                    "actualErrno": "ENOENT", "lockCreatedOpenedOrReclaimed": False,
                    "receipts": [{"path": str(path), "sha256": value} for path, value in self.receipts]}
        finally:
            os.close(fd)


class H1SpanObservation:
    """One verified no-SH external observer; no CLI, authority or gate result."""

    def __init__(self, controller: WholeCheckController, baseline: Baseline, collector: HelperSpanCollector,
                 *, component: str, case: str, schedule: H1Schedule, ready_raw: bytes) -> None:
        # Ready starts ONE <=60-second span, including failed EOF capture and
        # all cleanup; the original full-unit budget cannot leak through here.
        # Preserve the collector's existing twenty-second cleanup reserve and
        # retain the separate five-second effect boundary below.
        ready_at = collector.ready_observed_at
        collector.end = min(collector.end, ready_at + 60)
        collector.deadline = min(collector.deadline, collector.end - 20)
        # bind retains this instance across EVERY subsequent fallible
        # source/ready/origin/ps/evidence operation below.
        self.controller, self.baseline, self.collector = controller, baseline, collector
        self.component, self.case, self.schedule, self.ready_raw = component, case, schedule, ready_raw
        self.view: H1View | None = None
        self.ps: H1SystemPs | None = None
        self.origins: H1ShortOrigins | None = None
        self.may_be_stopped = False
        self.cont_attempted = False
        self.closed = False
        self.observations: Object = {"component": component, "case": case, "completeCheckClaimed": False}
        self.cleanup_record: Object | None = None
        self.sources: Object = {}
        self.end = min(collector.deadline, ready_at + 5)
        self.authority = Authority(controller.workspace.registry, component)

    @classmethod
    def bind(cls, controller: WholeCheckController, baseline: Baseline, collector: HelperSpanCollector,
             *, component: str, case: str, schedule: H1Schedule, ready_raw: bytes,
             programs: H1ProgramPins) -> H1SpanObservation:
        require(component in _H1_SELECTORS, "Wrong fixed H1 family.")
        span = cls(controller, baseline, collector, component=component, case=case,
                   schedule=schedule, ready_raw=ready_raw)
        try:
            span.sources = programs.verify(controller, component)
            # Assignment is BEFORE subsequent fallible ps/origin/evidence work.
            span.view = controller.verify_h1_ready(component, baseline=baseline, child=collector.child,
                case=case, schedule=schedule, ready_raw=ready_raw)
            span.ps = H1SystemPs.capture()
            span.origins = H1ShortOrigins.capture(span.view)
            span.observations["packagedSource"] = span.sources
            return span
        except BaseException as error:
            span.cleanup(error)
            raise

    def _remaining(self) -> float:
        remaining = self.end - time.monotonic()
        require(remaining > 0, "H1 observer exceeded its fixed five-second ready boundary.")
        return remaining

    def _fresh_active(self) -> H1View:
        self._remaining()
        assert self.view is not None
        current = self.controller.verify_h1_ready(self.component, baseline=self.baseline, child=self.collector.child,
            case=self.case, schedule=self.schedule, ready_raw=self.ready_raw)
        require(current == self.view, "Actual H1 report/process/custody changed before STOP/death.")
        assert self.origins is not None
        self.origins.recheck()
        return current

    def _continue(self) -> None:
        if self.may_be_stopped:
            assert self.view is not None
            self.cont_attempted = True
            # Orphan adoption after Suite death is legitimate; SAME retained
            # PID/birth, not its former parent's liveness, authorizes this CONT.
            signal_verified(self.view.helper, signal.SIGCONT)
            self.may_be_stopped = False

    def _stop_and_observe(self) -> None:
        view = self._fresh_active()
        assert self.ps is not None and self.origins is not None
        # This flag is set BEFORE syscall: an exception/cancel after delivery
        # cannot suppress unconditional fresh-identity CONT in cleanup.
        self.may_be_stopped = True
        signal_verified(view.helper, signal.SIGSTOP)
        self.observations["actualStop"] = self.ps.stopped(view.helper, deadline=self.end)
        self.observations["shortLockReleased"] = self.origins.absent_lock()
        self._remaining()
        with self.authority.mutex(seconds=self._remaining()):
            self.observations["beforeAuthority"] = _raw_authority_image(self.authority)
            self.observations["beforeState"] = tree_inventory(view.root / "state")

    def positive_precontinue(self) -> Object:
        """Called by the full positive coordinator BEFORE its normal H1 continue.

        This returns only provisional STOP/release evidence. The caller still
        owes real helper/whole Suite/provider/terminal phases and EVERY original
        deferred assertion. No local unit success is produced by this method.
        """
        try:
            self._stop_and_observe()
            assert self.view is not None
            self.observations["bothActiveRawExBlocked"] = _h1_raw_ex(self.authority, self.view.admission_lock)
            require(self.observations["bothActiveRawExBlocked"], "Active Suite/H1 have no independently held real SH.")
            self._continue()
            self._fresh_active()
            with self.authority.mutex(seconds=self._remaining()):
                require(_raw_authority_image(self.authority) == self.observations["beforeAuthority"]
                        and tree_inventory(self.view.root / "state") == self.observations["beforeState"],
                        "Positive STOP/CONT changed original metadata or Subscription state.")
            self.observations["positiveContinueStillPending"] = True
            self.controller.evidence.write("h1-positive-stop-precontinue.json", self.observations, limit=32 * 1024 * 1024)
            return dict(self.observations)
        except BaseException as error:
            self.cleanup(error)
            raise
        finally:
            if self.may_be_stopped:
                original = sys.exception()
                try:
                    self._continue()
                except BaseException as error:
                    if original is None:
                        self.cleanup(error)
                        raise
                    original.add_note("Unconditional H1 CONT failed: " + type(error).__name__)

    def death(self) -> Object:
        """Deliberately failed disposable subject; NEVER a full gate pass."""
        try:
            self._stop_and_observe()
            view = self._fresh_active()
            assert self.ps is not None and self.origins is not None
            # Still ACTIVE Suite and same stopped H1 are bound independently.
            self.ps.stopped(view.helper, deadline=self.end)
            with self.authority.mutex(seconds=self._remaining()):
                require(normal_control(self.authority, epoch=view.suite_context["epoch"],
                                       candidate=self.controller.scope)["epoch"] == view.suite_context["epoch"],
                        "Actual control changed before intended Suite death.")
                actual_writer = read(writer_path(self.authority, view.suite_context["invocation"],
                                                 view.suite_context["writer"]))
                originals = [row for row in view.custody["writers"]
                             if row["writer"] == view.suite_context["writer"]]
                require(len(originals) == 1 and actual_writer == originals[0] and actual_writer["phase"] == "active"
                        and view.helper.live(parent=view.suite.pid)
                        and self.collector.child.owner.live(parent=os.getpid()),
                        "Suite/helper/provider no longer match the actual active death boundary.")
                signal_verified(view.suite, signal.SIGKILL)  # ONLY the intended exact Suite death.
            while view.suite.live():
                time.sleep(min(.01, self._remaining()))
            # c2e: real owned-provider reap, NOT root-terminal/EOF sampling,
            # closes all provider SH descriptions before sole-H1 attribution.
            code = self.collector.child.wait_owned(seconds=self._remaining())
            require(self.collector.child.reaped and not view.suite.live(), "Actual provider/Suite closure unavailable.")
            self.observations["actualProviderReap"] = {"process": self.collector.child.owner.object(),
                "returncode": code, "reaped": self.collector.child.reaped, "observerReapedSuiteOrH1": False}
            self.observations["sameH1StillStopped"] = self.ps.stopped(view.helper, deadline=self.end)
            self.origins.recheck()
            with self.authority.mutex(seconds=self._remaining()):
                current = _raw_authority_image(self.authority)
                require(current == self.observations["beforeAuthority"],
                        "Suite death changed original metadata before guarded unknown publication.")
                require(tree_inventory(view.root / "state") == self.observations["beforeState"],
                        "STOP/death modified original State.")
                require(_h1_raw_ex(self.authority, view.admission_lock), "Stopped independently admitted H1 lost its OWN SH.")
            self.observations["soleStoppedH1RawExBlocked"] = True
            self._continue()  # Real queued parent-socket EOF remains failure.
            # The normal collector retains actual failed bytes/reaps only its
            # provider. No helper/Suite waitpid or synthetic terminal is added.
            captured = self.collector.capture_ended_failure()
            self.observations["actualFailedProviderCapture"] = {"returncode": captured.returncode,
                "stdoutHex": captured.stdout.hex(), "stderrHex": captured.stderr.hex()}
            # Give the ACTUAL queued parent-socket EOF/error path its bounded
            # chance to execute. A helper SIGTERM fallback is cleanup only and
            # cannot be reported as an observed ordinary EOF disposition.
            eof_end = min(self.collector.end - 1, time.monotonic() + 5)
            while view.helper.live() and time.monotonic() < eof_end:
                time.sleep(min(.02, max(0, eof_end - time.monotonic())))
            require(not view.helper.live(), "Real parent-EOF helper cleanup not observed; retain unavailable obligation.")
            self.observations["helperKernelGoneAfterCONTWithoutObserverTERM"] = True
            self.observations["actualParentSocketEOFQueuedBySuiteDeath"] = True
            self.observations["actorReportedEOFReadDirectly"] = False
            self.observations["observerSignalledHelperTERMBeforeEOFCleanup"] = False
            failure = ObservationFailed("Intentional active Suite loss retains unknown custody.")
            self.cleanup(failure)
            require(self.cleanup_record is not None, "Missing actual failed-subject cleanup observation.")
            assert self.cleanup_record is not None
            require(not self.cleanup_record["errors"] and not self.cleanup_record["possiblyStoppedH1"]
                    and all(value is False for value in self.cleanup_record["sameBirthLive"].values())
                    and self.collector.child.reaped, "Failed-subject cleanup remains unavailable/unresolved.")
            with self.authority.mutex(seconds=max(.001, min(2, self.collector.end - time.monotonic()))):
                custody = reconcile(self.authority, persist_unknown=False, candidate=self.controller.scope)
                require(custody.unknown and self.authority.read("control")["epoch"] == view.suite_context["epoch"],
                        "Real active loss was silently treated as resolved or rotated.")
                taint_before_guard = os.path.lexists(self.authority.folder / "taint.json")
                try:
                    normal_control(self.authority, candidate=self.controller.scope)
                except Refusal:
                    pass
                else:
                    raise ObservationFailed("Normal admission accepted the actual unresolved subject.")
                # Codex real abandon can already have published its own taint.
                # Claude/Pi/Mimo intentionally leave ACTIVE records and exit;
                # the ACTUAL normal guard then persists reconcile's generic
                # unknown-custody taint (new token, payload=None). Never invent
                # a helper-abandon call or demand its nonexistent taint/terminal.
                taint = self.authority.read("taint")
                require(taint["component"] == self.component and taint["reason"] == "custody-loss"
                        and taint["epoch"] == view.helper_context["epoch"]
                        and taint["boot"] == view.helper_context["boot"] and valid_token(taint["invocation"])
                        and taint["payloadSha256"] in (None, view.helper_context["payloadSha256"]),
                        "Actual normal guard lost the original epoch/boot/component custody binding.")
                if taint["payloadSha256"] is not None:
                    require(taint["invocation"] == view.helper_context["invocation"],
                            "Actual own-context taint belongs to another invocation.")
                self.observations["taintExistedBeforeActualNormalGuard"] = taint_before_guard
                after_metadata = _raw_authority_image(self.authority)
                retained = {"root": after_metadata["root"], "entries": [row for row in after_metadata["entries"]
                                                                             if row["path"] != "taint.json"]}
                require(retained == self.observations["beforeAuthority"],
                        "Actual loss changed original writer/handoff/context/marker/control bytes beyond taint.")
                self.observations["afterAuthority"] = after_metadata
                self.observations["unknownCustody"] = {"unknown": custody.unknown, "active": custody.active,
                    "pending": custody.pending, "taint": self.authority.read("taint"),
                    "writers": list(custody.writers), "handoffs": list(custody.handoffs)}
            require(not _h1_raw_ex(self.authority, view.admission_lock),
                    "Kernel-gone participants left another unexplained SH holder; no closure proof.")
            self.observations["freshRawExAvailableWithCustodyStillUnknown"] = True
            self.observations["afterState"] = tree_inventory(view.root / "state")
            require(self.observations["afterState"] == self.observations["beforeState"],
                    "Failure cleanup changed original captured Subscription state.")
            self.observations["requiresRealClosedRecovery"] = True
            self.controller.evidence.write("h1-actual-active-loss.json", self.observations, limit=32 * 1024 * 1024)
            return dict(self.observations)
        except BaseException as error:
            self.cleanup(error)
            raise
        finally:
            if self.may_be_stopped:
                original = sys.exception()
                try:
                    self._continue()
                except BaseException as error:
                    if original is None:
                        self.cleanup(error)
                        raise
                    original.add_note("Unconditional H1 CONT failed: " + type(error).__name__)

    def cleanup(self, original: BaseException) -> None:
        if self.closed:
            if self.cleanup_record is not None:
                original.add_note("Retained H1 cleanup: " + repr(self.cleanup_record))
            return
        self.closed = True
        end = min(self.collector.end, time.monotonic() + 20)
        self.collector.end = end  # No second collector cleanup budget on unwind.
        errors: list[str] = []
        if self.view is not None and self.may_be_stopped:
            try:
                self._continue()  # EVERY exit, before any wait/evidence call.
            except BaseException as error:
                errors.append("same-birth-CONT:" + type(error).__name__)
        targets = {} if self.view is None else {"suite": self.view.suite, "helper": self.view.helper}
        states: dict[str, bool | None] = {}
        for name, owner in targets.items():
            try:
                states[name] = owner.live()
                if states[name]:
                    signal_verified(owner, signal.SIGTERM)
            except BaseException as error:
                states[name] = None
                errors.append(name + "-verified-cancel:" + type(error).__name__)
        stdin = self.collector.child.process.stdin
        if stdin is not None:
            try:
                stdin.close()  # FAILURE EOF, never successful continue.
            except BaseException as error:
                errors.append("failure-input:" + type(error).__name__)
        try:
            self.collector.child.request_stop()
        except BaseException as error:
            errors.append("provider-stop:" + type(error).__name__)
        iterations = 0
        while time.monotonic() < end - .05 and iterations < 400:
            iterations += 1
            for name, owner in targets.items():
                try:
                    states[name] = owner.live()
                except BaseException as error:
                    states[name] = None
                    errors.append(name + "-observation:" + type(error).__name__)
            if self.collector.child.reaped and all(value is False for value in states.values()):
                break
            if not self.collector.child.reaped:
                try:
                    self.collector.child.wait_owned(seconds=min(.05, max(.001, end - time.monotonic())))
                except subprocess.TimeoutExpired:
                    pass
                except BaseException as error:
                    errors.append("provider-wait:" + type(error).__name__)
                    break  # Endpoint/wait cleanup below still runs independently.
            else:
                try:
                    time.sleep(min(.02, max(0, end - time.monotonic())))
                except BaseException as error:
                    errors.append("participant-wait:" + type(error).__name__)
                    break
        try:
            owned = self.collector.abort()  # Same deadline, independent endpoint attempts.
        except BaseException as error:
            errors.append("provider-endpoints:" + type(error).__name__)
            owned = {"providerReaped": self.collector.child.reaped, "unresolved": True}
        self.cleanup_record = {"verified": {name: owner.object() for name, owner in targets.items()},
            "sameBirthLive": states, "possiblyStoppedH1": self.may_be_stopped, "contAttempted": self.cont_attempted,
            "providerCleanup": owned, "errors": errors, "iterations": iterations, "observerReapedDescendant": False,
            "custodyResolvedOrTerminalClaimed": False}
        original.add_note("H1 bounded cleanup: " + repr(self.cleanup_record))
        try:
            self.controller.evidence.write("h1-span-failure-cleanup.json", self.cleanup_record)
        except BaseException as error:
            original.add_note("H1 cleanup evidence unavailable: " + type(error).__name__)


def h1_active_loss_subject(controller: WholeCheckController, baseline: Baseline, *, component: str, case: str,
                           schedule: H1Schedule, programs: H1ProgramPins, environment: Mapping[str, str],
                           seconds: float) -> Object:
    """Fixed complete-unit launch in a fresh disposable subject, never a filter.

    Each family gets a distinct registry/fixture; no taint-copy/reset/rebind.
    The outer full check separately consumes the successful full positive domain.
    """
    require(component in _H1_SELECTORS and not controller.reaped and not controller.finished_external,
            "H1 active-loss subject cannot reuse a completed or partly observed check.")
    controller.workspace.verify(controller.evidence)
    programs.verify(controller, component)
    schedule.verify(controller.scope.producer(component))
    child = OwnedChild(controller.fixed_argv(component, controller.scope.producer(component).build, "build-unit"),
                       environment=without_authority(dict(environment)), cwd=controller.workspace.registry)
    collector: HelperSpanCollector | None = None
    span: H1SpanObservation | None = None
    try:
        collector = HelperSpanCollector(child, case=case, seconds=seconds)
        with collector:
            ready_raw = collector.ready()
            # bind itself retains verified identities through every fallible
            # source/origin setup path and performs bounded failure cleanup.
            span = H1SpanObservation.bind(controller, baseline, collector, component=component, case=case,
                                          schedule=schedule, ready_raw=ready_raw, programs=programs)
            return span.death()
    except BaseException as subject_error:
        if span is not None and getattr(span, "view", None) is not None:
            span.cleanup(subject_error)
        elif collector is not None:
            try:
                collector.abort()
            except BaseException as error:
                subject_error.add_note("H1 provider setup cleanup: " + type(error).__name__)
        else:
            try:
                child.request_stop()
            except BaseException as error:
                subject_error.add_note("H1 setup provider stop: " + type(error).__name__)
            try:
                child.wait_owned(seconds=20)
            except BaseException as error:
                subject_error.add_note("H1 setup provider wait: " + type(error).__name__)
            for stream in (child.process.stdin, child.process.stdout, child.process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except BaseException as error:
                        subject_error.add_note("H1 setup pipe: " + type(error).__name__)
        raise
    finally:
        if collector is not None:
            outer_error = sys.exception()
            try:
                controller.evidence.write("h1-loss-raw-capture.json", collector.raw_observation(), limit=4 * 1024 * 1024)
            except BaseException as error:
                if outer_error is None:
                    raise
                outer_error.add_note("H1 raw output evidence unavailable: " + type(error).__name__)


class TerminalSpanObservation:
    """Fixed four-family positive oracles for the full combined controller.

    These methods supply no gate by themselves. Complete body/source admission
    must bind the real full-runner adapter, actual helper-owner waits/ACK and
    quiet sole-owning finish before use. No thread, selector or control message
    is introduced. The existing collector owns unconditional BOTH-target CONT
    and bounded real cleanup even when any observation here raises.
    """

    def __init__(self, *, component: str, case: str, programs: H1ProgramPins) -> None:
        require(component in _H1_SELECTORS and re.fullmatch(r"[0-9a-f]{32}", case, re.ASCII) is not None,
                "Invalid fixed positive terminal subject.")
        self.component, self.case, self.programs = component, case, programs
        self.h1: H1SpanObservation | None = None
        self.ps: H1SystemPs | None = None
        self.original: H1View | None = None
        self.images: dict[str, FileImage] = {}
        self.interval_seen = False
        self.completed = False
        self.record: Object = {"component": component, "case": case, "completeCheckClaimed": False}

    def precontinue(self, controller: WholeCheckController, baseline: Baseline,
                    collector: TerminalSpanCollector, view: H1View, schedule: H1Schedule,
                    ready_raw: bytes) -> None:
        require(self.original is None and not self.interval_seen and not self.completed
                and view.component == self.component and view.case == self.case
                and without_authority(dict(os.environ)) == dict(os.environ),
                "Positive external observer is repeated, foreign or carries admission authority.")
        self.original = view
        span = H1SpanObservation.bind(controller, baseline, collector, component=self.component,
            case=self.case, schedule=schedule, ready_raw=ready_raw, programs=self.programs)
        self.h1 = span
        require(span.view == view, "Positive precontinue observer verified another H1 subject.")
        # This owns the genuine H1 STOP/ENOENT/raw-EX/CONT observation; it does
        # NOT send the Suite continue or claim H1/local/full-check completion.
        self.record["h1Precontinue"] = span.positive_precontinue()
        self.ps = span.ps
        require(self.ps is not None, "Fixed OS process observer is unavailable.")

    def _image(self, view: TerminalView, name: str, *, limit: int = 65536) -> FileImage:
        view.h1.recheck_files()
        image = read_image(view.h1.root / name, limit=limit)
        require((view.h1.root / name).lstat().st_nlink == 1, "Linked positive helper receipt.")
        if name in self.images:
            require(image == self.images[name], "Actual helper/completion receipt changed.")
        self.images[name] = image
        return image

    def _provider_progress(self, controller: WholeCheckController, view: TerminalView) -> Object:
        """Bind actual mirrored-STOP/wait branch to Guardian's real prior close.

        A terminal provider row alone is NEVER used as proof of its SH close.
        The owned provider is independently observed STOPPED by the caller;
        this exact public supervise branch is reached only after spawn_gate
        returns through Guardian._spawn's real own-close and finalizers.
        """
        provider = controller.scope.gate.provider
        path = provider.root / "src/arbol_builds/driver_process.py"
        image = read_image(path, limit=1024 * 1024, private=False)
        require(image.sha256 == view.sources["sources"]["src/arbol_builds/driver_process.py"]["sha256"]
                and provider_process.__file__ is not None
                and Path(provider_process.__file__).resolve(strict=True) == path.resolve(strict=True),
                "Actual public supervisor source differs from the pinned provider.")
        compiled = compile(image.raw, str(path), "exec", dont_inherit=True, optimize=sys.flags.optimize)
        codes: dict[str, list[CodeType]] = {}

        def collect(code: CodeType) -> None:
            codes.setdefault(code.co_qualname, []).append(code)
            for value in code.co_consts:
                if isinstance(value, CodeType):
                    collect(value)

        collect(compiled)  # Compilation only, never executes a packaged body.
        methods = (provider_process.Guardian.spawn_gate, provider_process.Guardian._spawn,
                   provider_process.Guardian._close_owned, provider_process.SignalBridge.stopped,
                   provider_process.SignalBridge._forward, provider_process.supervise)
        for method in methods:
            require(Path(method.__code__.co_filename).resolve(strict=True) == path.resolve(strict=True)
                    and codes.get(method.__qualname__) == [method.__code__],
                    "Actual close/STOP/continue/wait code object differs from packaged source.")
        return {"source": image.evidence(), "actualCodeObjects": [method.__qualname__ for method in methods],
                "closeSite": view.intent["closeSite"], "provider": view.intent["provider"],
                "suite": view.intent["suite"], "providerRootAloneUsedAsCloseProof": False}

    def _helpers(self, controller: WholeCheckController, view: TerminalView) -> None:
        """Exact ACK/result receipts plus actual complete metadata/source binding.

        Source-pinned producer witnesses own real direct-child waits and joined
        APIs; no observer attempts to reap those nonchildren or treats a flag,
        terminal record, file hash or kernel absence alone as that wait.
        """
        authority = Authority(controller.workspace.registry, self.component)
        provisional = _h1_canonical(view.h1.images["local-results.json"].raw, limit=1024 * 1024)
        require(len(provisional["rows"]) == len(view.settled["rows"]), "Whole local result inventory changed.")
        for before, after in zip(provisional["rows"], view.settled["rows"], strict=True):
            require(before["id"] == after["id"], "Whole local result order changed.")
            if before["id"] != provisional["h1CaseId"]:
                require(before["resultSha256"] == after["resultSha256"],
                        "Original completed ordinary result was replaced at terminal settlement.")
            else:
                require(before["resultSha256"] != after["resultSha256"],
                        "Provisional H1 preconditions cannot substitute for its real positive result.")
        h1_index: int | None = None
        for index, row in enumerate(view.settled["helpers"]):
            prefix = f"terminal-helper-{index:04d}."
            context_raw = view.images[prefix + "context"].raw
            context = document(context_raw, limit=65536)
            accepted_raw = read_bytes(authority.folder / "handoffs" / (context["handoff"] + ".json"))
            accepted = document(accepted_raw)
            ack_raw = view.images[prefix + "ack"].raw
            ack = _h1_canonical(ack_raw, limit=65536)
            if self.component == "arbol-codex-driver":
                expected_ack: Object = {"version": 1, "kind": "abr38-terminal-helper-actual-ack",
                    "handoff": accepted, "contextSha256": digest(context_raw), "process": context["process"],
                    "ackPath": "synchronous-acknowledge-returned-before-ticket-close"}
            elif self.component == "arbol-pi-driver":
                expected_ack = {"version": 1, "kind": "abr38-pi-owned-helper-ack", **context["process"],
                    "contextSha256": digest(context_raw), "handoffSha256": digest(accepted_raw)}
            else:
                expected_ack = {"version": 1, "kind": "abr38-actual-helper-ack", "pid": context["process"]["pid"],
                    "contextSha256": digest(context_raw), "handoffSha256": digest(accepted_raw)}
            require(type(ack.get("version")) is int and ack == expected_ack,
                    "Actual source-bound terminal helper ACK receipt differs.")
            if context["handoff"] == view.h1.helper_context["handoff"]:
                require(h1_index is None and context == view.h1.helper_context and row["waitStatus"] == 0,
                        "Positive H1 receipt is duplicate/foreign or has failed actual wait status.")
                h1_index = index
        require(h1_index is not None, "Actual positive H1 helper is absent from the complete settlement.")
        assert h1_index is not None
        row = view.settled["helpers"][h1_index]
        prefix = f"terminal-helper-{h1_index:04d}."
        actor_raw = view.images[prefix + "result"].raw
        result = _h1_canonical(actor_raw, limit=4096)
        require(type(result.get("version")) is int and result == {"version": 1, "kind": "actor-result",
            "case": self.case, "action": "lease-hold", "outcome": "completed"},
            "Real positive H1 result is not its actual completed local observation.")
        if self.component == "arbol-pi-driver":
            stdout_name, stderr_name = "helper.stdout", "helper.stderr"
        else:
            stdout_name, stderr_name = "actor.stdout", "actor.stderr"
        require(self._image(view, stdout_name).raw == actor_raw and self._image(view, stderr_name).raw == b"",
                "Actual H1 output/result or stderr differs from its genuine successful capture.")
        if self.component == "arbol-codex-driver":
            completion_raw = self._image(view, "helper-completion.json").raw
            expected_completion: Object = {"version": 1, "kind": "abr38-H1-actual-completion", "case": self.case,
                "process": view.h1.helper.object(), "waitStatus": 0, "actorResultSha256": digest(actor_raw),
                "contextSha256": view.h1.helper_context_sha256,
                "terminalRecordSha256": row["terminalRecordSha256"],
                "ackPath": "synchronous-acknowledge-returned-before-ticket-close"}
        elif self.component == "arbol-pi-driver":
            completion_raw = self._image(view, "helper-completion.json").raw
            original_ack = self._image(view, "helper-ack.json").raw
            handoff_raw = read_bytes(authority.folder / "handoffs" / (view.h1.helper_context["handoff"] + ".json"))
            require(_h1_canonical(original_ack, limit=4096) == {"version": 1, "kind": "abr38-pi-direct-helper-ack",
                **view.h1.helper.object(), "contextSha256": view.h1.helper_context_sha256,
                "handoffSha256": digest(handoff_raw)}, "Original Pi H1 synchronous ACK receipt differs.")
            expected_completion = {"version": 1, "kind": "abr38-pi-helper-completion", "case": self.case,
                "contextSha256": view.h1.helper_context_sha256, "handoffSha256": digest(handoff_raw),
                **view.h1.helper.object(), "returncode": 0, "actorResultSha256": digest(actor_raw),
                "stderrSha256": digest(b""), "terminalRecordSha256": row["terminalRecordSha256"],
                "ackEvidenceSha256": digest(original_ack)}
        else:
            completion_raw = self._image(view, "helper-settlement.json").raw
            original_ack = self._image(view, "helper-ack.json").raw
            require(original_ack == view.images[prefix + "ack"].raw
                    and self._image(view, "helper-terminal.json").raw == view.images[prefix + "terminal"].raw,
                    "Original actual H1 ACK/terminal receipt changed before whole finish.")
            expected_completion = {"version": 1, "kind": "abr38-direct-helper-settlement",
                **view.h1.helper.object(), "returncode": 0, "stdoutSha256": digest(actor_raw),
                "stderrSha256": digest(b""), "contextSha256": view.h1.helper_context_sha256,
                "terminalSha256": row["terminalRecordSha256"], "ackSha256": digest(original_ack)}
        completion = _h1_canonical(completion_raw, limit=65536)
        require(type(completion.get("version")) is int and completion == expected_completion,
                "Original actual owner wait/result/ACK/terminal completion differs.")
        self.record["h1ActualCompletion"] = {"sha256": digest(completion_raw), "value": completion}

    def interval(self, controller: WholeCheckController, baseline: Baseline,
                 collector: TerminalSpanCollector, view: TerminalView) -> None:
        require(self.original == view.h1 and self.h1 is not None and self.ps is not None
                and not self.interval_seen and not self.completed,
                "Independent terminal interval is repeated, unbound or out of order.")
        end = collector.terminal_interval_ends_at
        assert self.ps is not None
        provider = collector.child.owner
        # BOTH retained kernel targets, with a Suite bracket. No provider STOP
        # is sent by this observer; public supervision mirrors real Suite STOP.
        require(provider.live(parent=os.getpid()) and view.h1.suite.live(parent=provider.pid),
                "Actual terminal targets lost retained birth/parent bindings.")
        self.record["suiteStopped"] = self.ps.stopped(view.h1.suite, deadline=end)
        self.record["providerStopped"] = self.ps.stopped(provider, deadline=end)
        self.record["suiteStoppedAgain"] = self.ps.stopped(view.h1.suite, deadline=end)
        self.record["sourceBoundProviderProgress"] = self._provider_progress(controller, view)
        remaining = end - time.monotonic()
        require(remaining > 0, "Terminal interval expired before independent short mutex.")
        authority = Authority(controller.workspace.registry, self.component)
        with authority.mutex(seconds=remaining):
            require(time.monotonic() < end, "Terminal mutex was unavailable within the original interval.")
            custody = reconcile(authority, persist_unknown=False, candidate=controller.scope)
            require(custody.resolved and custody.active == custody.pending == 0
                    and all(row["phase"] == "terminal" for row in custody.writers),
                    "Actual terminal graph has active/pending/unknown obligations.")
            suite = read(writer_path(authority, view.h1.suite_context["invocation"], view.h1.suite_context["writer"]))
            require(suite == {"version": 1, "invocation": view.h1.suite_context["invocation"],
                "writer": view.h1.suite_context["writer"], "parent": view.h1.suite_context["parent"]["writer"],
                "component": self.component, "epoch": baseline.epochs[self.component],
                "payloadSha256": controller.scope.producer(self.component).digest, "boot": baseline.boot,
                **view.h1.suite.object(), "phase": "terminal", "contextSha256": view.h1.suite_context_sha256},
                "Actual Suite has not genuinely published terminal under its original context.")
            for writer in custody.writers:
                if writer["writer"] not in (suite["writer"], suite["parent"]):
                    require(not ExactProcess.read({key: writer[key] for key in ("pid", "startedAt")}).live(),
                            "Another actual writer could hold SH at the sole-Suite interval.")
            self._helpers(controller, view)
            before = _raw_authority_image(authority)
            blocked = _h1_raw_ex(authority, view.h1.admission_lock)
            require(blocked, "Actual original-inode EX did not block at the sole-Suite own-close boundary.")
            require(_raw_authority_image(authority) == before and time.monotonic() < end,
                    "Raw interval probe changed metadata or exceeded its five-second boundary.")
            self.record["soleSuiteOriginalShBlockedEx"] = blocked
            self.record["terminalMetadata"] = before
        view.recheck_files()
        self.interval_seen = True
        # Return with BOTH still stopped; controller performs real dual CONT.
        require(time.monotonic() < end, "Independent terminal interval completed too late.")

    def finished(self, controller: WholeCheckController, baseline: Baseline,
                 collector: TerminalSpanCollector, view: TerminalView, captured: Captured) -> None:
        require(self.interval_seen and not self.completed and self.original == view.h1
                and collector.child.reaped and captured.owner == collector.child.owner
                and captured.returncode == 0 and not view.h1.suite.live() and not view.h1.helper.live(),
                "Actual positive Suite/helper/provider close/zero-exit/reaps did not complete.")
        view.recheck_files()
        for name, image in self.images.items():
            require(read_image(view.h1.root / name, limit=max(1, len(image.raw))) == image,
                    "Completed H1 owner evidence changed after actual whole close.")
        # The real public provider source maps its actual Suite waitpid exit to
        # the observed provider return. This is not an observer descendant reap.
        self.record["sourceBoundProviderWait"] = self._provider_progress(controller, view)
        controller.verify_terminal_closure(self.component, baseline=baseline, view=view)
        self.record["realWholeClosure"] = {"provider": captured.owner.object(), "returncode": captured.returncode,
            "providerActuallyReaped": collector.child.reaped, "suiteKernelGone": True, "helperKernelGone": True,
            "observerReapedDescendant": False, "allOriginalDeferredAssertionsStillRequired": True}
        controller.evidence.write("terminal-independent-positive.json", self.record, limit=16 * 1024 * 1024)
        self.completed = True


_MIMO_MAIN_COMPONENT = "arbol-mimo-driver"
_MIMO_STUBBORN = "trap '' TERM; printf stubborn-start; sleep 60"
_MIMO_ADMISSION_PROBE = ("subscriptions", "identity", "xiaomi")
_MIMO_RECIPE_SOURCE = ("tests/native/support.py", "tests/native/test_public_lifecycle.py")
_MIMO_PRODUCTION_SOURCE = ("src/arbol_mimo_driver/standin.py", "src/arbol_mimo_driver/runtime.py",
    "src/arbol_mimo_driver/ownership.py", "src/arbol_mimo_driver/adapters/watcher.py",
    "src/arbol_mimo_driver/runs.py", "src/arbol_mimo_driver/admission.py", "bin/identity-helper.py",
    "bin/entry.py", "src/arbol_mimo_driver/cli.py", "src/arbol_mimo_driver/native_server.py",
    "src/arbol_mimo_driver/events.py", "src/arbol_mimo_driver/output.py",
    "src/arbol_mimo_driver/adapters/process_table.py", "src/arbol_mimo_driver/native_cleanup.py",
    "src/arbol_mimo_driver/operation.py", "src/arbol_mimo_driver/native_cli.py")

def _mimo_explicit_native_image(path: Path, expected_sha256: str) -> Object:
    """Hash ONLY the explicitly supplied uninstalled native input, streaming.

    The finite512MiB bound matches existing qualify_binary. No installed-native
    fallback, native invocation or descriptor inheritance is introduced.
    """
    import hashlib

    require(valid_hash(expected_sha256) and path.is_absolute() and path.resolve(strict=True) == path,
            "Invalid exact explicit native candidate/hash.")
    physical_owned(path.parent, directory=True, private=False)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
                and before.st_mode & 0o111 != 0 and 0 < before.st_size <= 512 * 1024 * 1024,
                "Explicit uninstalled native input is not the bounded owned executable.")
        hashed, total = hashlib.sha256(), 0
        while total <= 512 * 1024 * 1024:
            block = os.read(fd, min(65536, 512 * 1024 * 1024 + 1 - total))
            if not block:
                break
            total += len(block)
            hashed.update(block)
        after, named = os.fstat(fd), path.lstat()
        keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode", "st_nlink")
        require(total == before.st_size and all(getattr(before, key) == getattr(after, key) == getattr(named, key) for key in keys)
                and hashed.hexdigest() == expected_sha256, "Exact explicit native input changed during observation.")
        return {"path": str(path), "device": before.st_dev, "inode": before.st_ino,
                "mode": stat.S_IMODE(before.st_mode), "size": total, "sha256": hashed.hexdigest(), "links": 1}
    finally:
        os.close(fd)



@dataclass(frozen=True)
class MimoOfflineInput:
    """Explicit separately approved native fixture input, NEVER installed fallback."""

    candidate: Path
    candidate_sha256: str
    source_sha256: Mapping[str, str]

    def verify(self, controller: WholeCheckController) -> Object:
        controller.scope.recheck()  # Full actual M/D before fixture/State reads.
        payload = controller.scope.producer(_MIMO_MAIN_COMPONENT)
        require(set(self.source_sha256) == set((*_MIMO_RECIPE_SOURCE, *_MIMO_PRODUCTION_SOURCE))
                and valid_hash(self.candidate_sha256), "Missing exact admitted offline fixture source/native pins.")
        images: Object = {}
        for name in (*_MIMO_RECIPE_SOURCE, *_MIMO_PRODUCTION_SOURCE):
            expected = self.source_sha256[name]
            require(valid_hash(expected), "Invalid source-owned fixture body hash.")
            image = read_image(payload.root / name, limit=4 * 1024 * 1024, private=False)
            require(image.sha256 == expected, "Offline fixture/production source differs from its admitted pin.")
            images[name] = image.evidence()
        require("bin/identity-helper.py" in payload.descriptor["helpers"]
                and self.candidate.is_absolute() and self.candidate.resolve(strict=True) == self.candidate,
                "Native candidate/helper input is not the exact explicit physical input.")
        native_image = _mimo_explicit_native_image(self.candidate, self.candidate_sha256)
        return {"nativeCandidate": native_image, "fixedSources": images,
                "producerSource": payload.descriptor["source"], "payloadSha256": payload.digest,
                "syntheticOnly": True, "genuineProfileOrModelUsabilityClaimed": False}


@dataclass(frozen=True)
class MimoMainRecipe:
    """Arbol-owned exact DATA counterpart of Mimo's fixed MainWatcherRecipe.

    No sibling import/exec; the actual fixed public candidate owns preparation.
    Future47 reuses the Mimo-native DATA type in its own verified runtime.
    """

    home: Path
    case: str
    native: MimoOfflineInput
    tuple_pins_sha256: str

    @property
    def tool(self) -> Path:
        return self.home / "tool"

    @property
    def work(self) -> Path:
        return self.home / "project"

    @property
    def state(self) -> Path:
        return self.tool / "state"

    @property
    def request(self) -> Path:
        return self.tool / "main-watcher-request.json"

    @property
    def run_id(self) -> str:
        return "abr38-main-" + self.case

    def options(self) -> Object:
        return {"text": "ready", "calls": [{"name": "bash", "arguments": {"command": _MIMO_STUBBORN,
            "description": "Owned offline MAIN/Watcher across-begin fixture"}}]}

    def request_value(self) -> Object:
        return {"runId": self.run_id, "subscriptionId": "xiaomi", "tools": "all", "history": [],
            "workingDirectory": str(self.work), "input": {"role": "user", "text": "abr38-main-watcher"}}

    def tails(self) -> tuple[list[str], list[str], list[str]]:
        prefix = ["--state-dir", str(self.state), "dev", "stand-in", str(self.tool), "--"]
        return ([*prefix, "install"], [*prefix, "driver", "subscriptions", "sign-in", "xiaomi"],
                [*prefix, "driver", "run", "--control", "--subscription", "xiaomi", "--request", str(self.request)])

    def receipt(self) -> Object:
        require(re.fullmatch(r"[0-9a-f]{32}", self.case, re.ASCII) is not None
                and valid_hash(self.tuple_pins_sha256), "Invalid fixed private case/tuple pins.")
        physical_owned(self.home, directory=True)
        install, attach, run = self.tails()
        return {"version": 1, "kind": "abr38-mimo-main-watcher-recipe", "case": self.case,
            "home": str(self.home), "tool": str(self.tool), "work": str(self.work), "state": str(self.state),
            "request": str(self.request), "runId": self.run_id, "subscription": "xiaomi",
            "candidate": str(self.native.candidate), "candidateSha256": self.native.candidate_sha256,
            "tuplePinsSha256": self.tuple_pins_sha256, "syntheticOnly": True, "scenario": "native text",
            "options": self.options(), "requestValue": self.request_value(),
            "installTail": install, "attachTail": attach, "runTail": run}


class MimoMainStream:
    """One data-only bounded drainer for an OWNED public provider's two pipes.

    The reader never signals, admits metadata, reads State or invokes callbacks.
    It keeps output draining during real begin/binding work. Caller owns control
    stdin and joins this thread before any successful external-phase result.
    """

    def __init__(self, child: OwnedChild, *, run_id: str | None, end: float) -> None:
        self.child, self.run_id, self.end = child, run_id, end
        self.condition = threading.Condition()
        self.stopping = threading.Event()
        self.raw = {"stdout": bytearray(), "stderr": bytearray()}
        self.eof: set[str] = set()
        self.records: list[Object] = []
        self.errors: list[str] = []
        self.partial = bytearray()
        self.finished = False
        self.started = False
        self.thread = threading.Thread(target=self._read, name="abr38-mimo-public-output", daemon=False)

    def start(self) -> None:
        require(not self.started and self.child.owner.pid == self.child.process.pid,
                "Public data drainer lacks its retained actual owned Popen identity.")
        self.started = True
        self.thread.start()

    def _read(self) -> None:
        parse_failed = False

        def failed(error: BaseException) -> None:
            with self.condition:
                if len(self.errors) < 64:
                    self.errors.append(type(error).__name__ + ":" + str(error)[:512])
                self.condition.notify_all()

        try:
            with selectors.DefaultSelector() as selector:
                for name, pipe in (("stdout", self.child.process.stdout), ("stderr", self.child.process.stderr)):
                    try:
                        require(pipe is not None, "Actual public provider output pipe is absent.")
                        assert pipe is not None
                        os.set_blocking(pipe.fileno(), False)
                        selector.register(pipe, selectors.EVENT_READ, name)
                    except BaseException as error:
                        failed(error)
                while selector.get_map() and not self.stopping.is_set():
                    require(time.monotonic() < self.end, "Public output exceeded its original sixty-second span.")
                    for key, events in selector.select(min(.025, max(0, self.end - time.monotonic()))):
                        if not events & selectors.EVENT_READ:
                            continue
                        name = key.data
                        try:
                            data = os.read(key.fd, 65536)
                        except BlockingIOError:
                            continue
                        except BaseException as error:
                            failed(error)
                            selector.unregister(key.fileobj)
                            continue
                        with self.condition:
                            if not data:
                                selector.unregister(key.fileobj)
                                self.eof.add(name)  # Actual read(0), never close/exit inference.
                                if name == "stdout" and self.partial:
                                    failed(ObservationFailed("Truncated actual public JSONLF output."))
                            else:
                                room = max(0, 4 * 1024 * 1024 - len(self.raw[name]))
                                self.raw[name].extend(data[:room])
                                if len(data) > room:
                                    failed(ObservationFailed("Actual output overflow; bounded failed prefix retained."))
                                if name == "stdout" and self.run_id is not None and not parse_failed:
                                    try:
                                        self.partial.extend(data)
                                        while b"\n" in self.partial:
                                            line, _, tail = self.partial.partition(b"\n")
                                            self.partial = bytearray(tail)
                                            require(not self.finished and 0 < len(line) <= 1024 * 1024
                                                    and len(self.records) < 4096, "Extra/oversized actual public frame.")
                                            record = document(bytes(line), limit=1024 * 1024)
                                            require(record.get("runId") == self.run_id and isinstance(record.get("type"), str)
                                                    and type(record.get("seq")) is int
                                                    and record["seq"] == len(self.records) + 1,
                                                    "Public frame belongs to another run or lost its real sequence.")
                                            self.records.append(record)
                                            self.finished = record["type"] == "finished"
                                        require(len(self.partial) <= 1024 * 1024, "Public partial frame exceeded its bound.")
                                    except BaseException as error:
                                        failed(error)
                                        parse_failed = True  # Continue draining real failed bytes on BOTH pipes.
                                        self.partial.clear()
                            self.condition.notify_all()
        except BaseException as error:
            failed(error)
        finally:
            with self.condition:
                self.condition.notify_all()

    def stubborn_start(self, *, end: float) -> Object:
        with self.condition:
            while True:
                require(not self.errors, "Actual data reader failed: " + repr(self.errors))
                for record in self.records:
                    if record["type"] == "tool_output_delta" and "stubborn-start" in str(record.get("text", "")):
                        require(time.monotonic() <= end, "Real stubborn-start exceeded startup budget.")
                        return dict(record)
                require(time.monotonic() < min(end, self.end) and self.thread.is_alive()
                        and "stdout" not in self.eof, "Actual stubborn-start was not observed before bounded EOF/exit.")
                self.condition.wait(min(.025, max(0, min(end, self.end) - time.monotonic())))

    def snapshot(self) -> Object:
        with self.condition:
            return {"provider": self.child.owner.object(), "stdoutHex": bytes(self.raw["stdout"]).hex(),
                "stderrHex": bytes(self.raw["stderr"]).hex(), "actualEof": sorted(self.eof),
                "records": list(self.records), "errors": list(self.errors), "readerAlive": self.thread.is_alive(),
                "providerActuallyReaped": self.child.reaped, "custodyOrGatePassClaimed": False}

    def join(self, *, end: float, failure: bool) -> None:
        if not self.started:
            return
        deadline = min(end, self.end)
        self.thread.join(timeout=max(0, deadline - (.05 if failure else 0) - time.monotonic()))
        if failure and self.thread.is_alive():
            self.stopping.set()  # Stop data work only after attempting pending-byte drain.
            self.thread.join(timeout=max(0, deadline - time.monotonic()))
        require(not self.thread.is_alive(), "Owned data reader did not join within original span.")
        if not failure:
            require(not self.errors and self.eof == {"stdout", "stderr"} and not self.partial,
                    "Public output did not genuinely drain to complete EOF.")


def _mimo_finite_data_call(child: OwnedChild, *, end: float) -> Captured:
    """Exact public install/attach/begin/refusal call; NEVER the controlled Run.

    Actual failed bytes survive pre-selector/IO/timeout failures. All attempts
    share this one deadline; only the caller-owned provider is stopped/reaped.
    This deliberately never sends successful EOF, even for preparation calls.
    """
    stream: MimoMainStream | None = None
    original: BaseException | None = None
    failures: list[str] = []
    try:
        require(time.monotonic() + 1 < end, "No remaining fixed-call budget/cleanup reserve.")
        stream = MimoMainStream(child, run_id=None, end=end)
        stream.start()
        status = child.wait_owned(seconds=max(.001, end - 1 - time.monotonic()))
        stream.join(end=end, failure=False)
        captured = stream.snapshot()
        return Captured(status, bytes.fromhex(captured["stdoutHex"]), bytes.fromhex(captured["stderrHex"]), child.owner)
    except BaseException as error:
        original = error
        try:
            child.request_stop()
        except BaseException as cleanup:
            failures.append("owned-stop:" + type(cleanup).__name__)
        try:
            child.wait_owned(seconds=max(.001, end - time.monotonic()))
        except BaseException as cleanup:
            failures.append("owned-wait:" + type(cleanup).__name__)
        if stream is not None:
            try:
                stream.join(end=end, failure=True)
            except BaseException as cleanup:
                failures.append("data-join:" + type(cleanup).__name__)
            error.add_note("Actual failed public bytes: " + repr(stream.snapshot()))
        error.add_note("Fixed public call cleanup: " + repr(failures))
        raise
    finally:
        for pipe in (child.process.stdin, child.process.stdout, child.process.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except BaseException as cleanup:
                    failures.append("pipe-close:" + type(cleanup).__name__)
        if failures:
            if original is not None:
                original.add_note("Fixed-call endpoint failures: " + repr(failures))
            else:
                failure = ObservationFailed("Fixed-call actual endpoints unresolved: " + repr(failures))
                if stream is not None:
                    failure.add_note("Actual fixed-call bytes: " + repr(stream.snapshot()))
                raise failure


def _mimo_original_group_members(pgid: int, *, end: float) -> list[Object]:
    """Read ONLY an original ledger PGID with the fixed Darwin OS ABI.

    No signals or permission follows, even if the number has been reused. A
    nonempty/reused/inaccessible/full inventory is failure, never cleanup proof.
    Fresh PID/birth inspection is independently joined to each enumerated PID.
    """
    import ctypes
    import errno

    require(sys.platform == "darwin" and type(pgid) is int and 0 < pgid <= 2**31 - 1
            and pgid != os.getpgrp() and time.monotonic() < end, "Unsafe/unavailable original native group observation.")
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    library.proc_listpgrppids.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    library.proc_listpgrppids.restype = ctypes.c_int
    capacity = 64
    while capacity <= 131072:
        require(time.monotonic() < end, "Original group observation exceeded its shared deadline.")
        values = (ctypes.c_int * capacity)()
        ctypes.set_errno(0)
        count = library.proc_listpgrppids(pgid, values, ctypes.sizeof(values))
        require(type(count) is int and count >= 0
                and (count > 0 or ctypes.get_errno() in (0, errno.ESRCH)), "Cannot independently enumerate the original group.")
        if count >= capacity:
            capacity *= 2
            continue
        members: list[Object] = []
        for pid in values[:count]:
            require(type(pid) is int and pid > 0 and time.monotonic() < end,
                    "Invalid/unbounded original group member observation.")
            current = provider_process.inspect(pid)
            if current is not None and current.group == pgid:
                members.append({"process": current.owner, "parent": current.parent, "group": current.group})
        return members
    raise ObservationFailed("Native group inventory exceeds the fixed OS observation bound.")


@dataclass(frozen=True)
class MimoMainView:
    main: ExactProcess
    watcher: ExactProcess
    main_context: Object
    watcher_context: Object
    main_context_sha256: str
    watcher_context_sha256: str
    main_writer: Object
    watcher_writer: Object
    custody: Object
    ledger: Object
    run_record: Object
    admission_lock: Object
    before_metadata: Object


class MimoMainSubject:
    """One healthy disposable subject with REAL offline public preparation.

    Ordinary JSONLF stop and verified-main SIGTERM use distinct fresh subjects
    and share the same active-boundary and settlement observations.
    No preparation or runtime operation occurs on construction/import.
    """

    def __init__(self, controller: WholeCheckController, baseline: Baseline, *, case: str,
                 native: MimoOfflineInput, full_run_end: float, environment: Mapping[str, str]) -> None:
        require(controller.scope == baseline.scopes[_MIMO_MAIN_COMPONENT]
                and not controller.reaped and not controller.finished_external
                and re.fullmatch(r"[0-9a-f]{32}", case, re.ASCII) is not None
                and time.monotonic() < full_run_end <= time.monotonic() + 7200,
                "MAIN/Watcher requires a fresh exact independently owned subject and original gate budget.")
        controller.workspace.verify(controller.evidence)
        controller.scope.recheck()
        self.controller, self.baseline, self.case, self.native = controller, baseline, case, native
        self.full_end = full_run_end
        self.source = native.verify(controller)
        pins = [controller.scope.gate.provider, *controller.scope.producers]
        require(len(pins) == 5 and len({item.component for item in pins}) == 5, "Missing real five-tuple cohort.")
        tuples_raw = canonical({"version": 1, "kind": "abr38-mimo-main-actual-tuples", "tuples": [
            {"component": item.component, "build": item.build, "source": item.descriptor["source"],
             "payloadSha256": item.digest} for item in pins]})
        controller.evidence.write_bytes("mimo-main-tuples.json", tuples_raw)
        self.recipe = MimoMainRecipe(controller.workspace.fixture_root / ("mimo-main-" + case), case,
                                     native, digest(tuples_raw))
        self.authority = Authority(controller.workspace.registry, _MIMO_MAIN_COMPONENT)
        self.original_control: Object | None = None
        self.preparation: list[Object] = []
        self.prepared = False
        self.child: OwnedChild | None = None
        self.stream: MimoMainStream | None = None
        self.view: MimoMainView | None = None
        self.run_end = 0.0
        self.boundary_end = 0.0
        self.session = str(uuid.uuid4())  # Genuine new operator session, NOT a boot UUID.
        self.begun = False
        self.stop_sent = False
        self.stop_observed_at = 0.0
        self.closed = False
        allowed = ("PATH", "USER", "LOGNAME", "LANG", "TMPDIR", "TERM")
        self.environment = {key: environment[key] for key in allowed if key in environment}
        self.environment.update(HOME=str(self.recipe.home), SHELL="/bin/bash",
                                ARBOL_MIMO_TEST_CANDIDATE=str(native.candidate))
        self.environment.setdefault("PATH", "/usr/bin:/bin")
        self.record: Object = {"component": _MIMO_MAIN_COMPONENT, "case": case, "source": self.source,
            "syntheticOnly": True, "genuineModelOrAccountProof": False, "preparedInvocations": self.preparation,
            "publicDrainWhileActiveInvoked": False, "completeCheckClaimed": False}

    def _argv(self, tail: list[str]) -> list[str]:
        self.controller.scope.recheck()
        return self.controller.fixed_argv(_MIMO_MAIN_COMPONENT,
            self.controller.scope.producer(_MIMO_MAIN_COMPONENT).build, "driver", tail)

    def _data(self, path: Path, raw: bytes) -> None:
        require(path.parent in (self.recipe.home, self.recipe.tool) and len(raw) <= 1024 * 1024,
                "Only fixed private fixture DATA basenames may be published.")
        physical_owned(path.parent, directory=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            pending = memoryview(raw)
            while pending:
                count = os.write(fd, pending)
                require(count > 0, "Private fixture DATA write failed.")
                pending = pending[count:]
            os.fsync(fd)
            held, named = os.fstat(fd), path.lstat()
            require(held.st_nlink == named.st_nlink == 1 and (held.st_dev, held.st_ino) == (named.st_dev, named.st_ino),
                    "Private fixture DATA inode/link changed.")
        finally:
            os.close(fd)
        sync_directory(path.parent)

    def _prep_call(self, tail: list[str], *, name: str, end: float) -> Object:
        require(time.monotonic() + 1 < end, "Original native preparation budget exhausted.")
        child = OwnedChild(self._argv(tail), environment=without_authority(self.environment), cwd=self.recipe.home)
        try:
            captured = _mimo_finite_data_call(child, end=end)
        except BaseException as error:
            item: Object = {"name": name, "argv": child.process.args, "provider": child.owner.object(),
                "providerActuallyReaped": child.reaped, "returncode": child.process.returncode,
                "failureType": type(error).__name__, "actualFailedBytesAndCleanup": list(getattr(error, "__notes__", ())),
                "custodyOrGatePassClaimed": False}
            self.preparation.append(item)
            try:
                self.controller.evidence.write("mimo-prep-" + name + "-failed.json", item, limit=32 * 1024 * 1024)
            except BaseException as evidence_error:
                error.add_note("Preparation evidence unavailable: " + type(evidence_error).__name__)
            raise
        item = {"name": name, "argv": child.process.args, "provider": child.owner.object(),
            "returncode": captured.returncode, "providerActuallyReaped": child.reaped,
            "stdoutHex": captured.stdout.hex(), "stderrHex": captured.stderr.hex()}
        self.preparation.append(item)
        self.controller.evidence.write("mimo-prep-" + name + "-output.json", item, limit=32 * 1024 * 1024)
        require(child.reaped and captured.returncode == 0 and not captured.stderr,
                "Actual public native preparation refused; preserve original failed subject.")
        self.controller.reaped.append(child)
        result = document(captured.stdout, limit=1024 * 1024)
        self.controller.require_finished_graph(_MIMO_MAIN_COMPONENT)
        with self.authority.mutex():
            control = normal_control(self.authority, candidate=self.controller.scope)
            require(self.original_control is not None and control == self.original_control,
                    "Public preparation changed healthy control/epoch.")
            image = _raw_authority_image(self.authority)
        item["actualControl"], item["actualMetadata"] = control, image
        self.controller.evidence.write("mimo-prep-" + name + ".json", item, limit=32 * 1024 * 1024)
        return result

    def prepare(self) -> Object:
        require(not self.prepared and self.child is None and not os.path.lexists(self.recipe.home),
                "No preparation resume, existing profile, copied history or reused fixture.")
        self.controller.require_finished_graph(_MIMO_MAIN_COMPONENT)
        with self.authority.mutex():
            control = normal_control(self.authority, candidate=self.controller.scope)
            require(control["epoch"] == self.baseline.epochs[_MIMO_MAIN_COMPONENT]
                    and not os.path.lexists(self.authority.folder / "taint.json")
                    and not os.path.lexists(self.authority.folder / "maintenance.json"),
                    "Offline native preparation requires the original healthy fixture baseline.")
            self.original_control = control
            self.record["beforePreparationMetadata"] = _raw_authority_image(self.authority)
        physical_owned(self.controller.workspace.fixture_root, directory=True)
        self.recipe.home.mkdir(mode=0o700)
        self.recipe.tool.mkdir(mode=0o700)
        self.recipe.work.mkdir(mode=0o700)
        sync_directory(self.controller.workspace.fixture_root)
        self._data(self.recipe.home / ".main-watcher-recipe.json", canonical(self.recipe.receipt()))
        install, attach, _ = self.recipe.tails()
        prepared = self._prep_call(install, name="install", end=min(self.full_end, time.monotonic() + 20))
        require(prepared.get("installed") is True and prepared.get("qualified") is False
                and prepared.get("nativeHome") == str(self.recipe.tool / "native-profile/home")
                and prepared.get("nativeVersion") in ("0.1.16", "0.1.16-arbol4")
                and isinstance(prepared.get("helperPath"), str), "Actual offline install did not produce the fixed fixture.")
        helper_path = prepared["helperPath"]
        require(helper_path and all(Path(value).is_absolute() and Path(value).resolve(strict=True) == Path(value)
                                   for value in helper_path.split(os.pathsep)), "Actual native helper paths are not physical.")
        self.environment["PATH"] = helper_path + os.pathsep + self.environment["PATH"]
        self._data(self.recipe.tool / "scenario", b"native text\n")
        self._data(self.recipe.tool / "options.json", canonical(self.recipe.options()))
        self._data(self.recipe.request, canonical(self.recipe.request_value()))
        self._prep_call(attach, name="attach", end=min(self.full_end, time.monotonic() + 30))
        self.record["normalAdmissionProbe"] = self._normal_admission_probe()
        self.record["providerAdmissionSource"] = self._provider_sources()
        self.native.verify(self.controller)
        manifest = document(read_image(self.recipe.tool / "fixture-manifest.json", limit=65536).raw, limit=65536)
        require(manifest.get("syntheticIdentity") is True and manifest.get("model") == "arbol-mimo-fixture"
                and manifest.get("home") == str(self.recipe.tool / "native-profile/home")
                and manifest.get("binary") == str(self.native.candidate),
                "Actual stand-in manifest escaped the explicitly synthetic candidate/home.")
        with self.authority.mutex():
            require(normal_control(self.authority, candidate=self.controller.scope) == self.original_control,
                    "Preparation lost original healthy control/epoch.")
            self.record["preparedMetadataBeforeimage"] = _raw_authority_image(self.authority)
        self.record["recipe"] = self.recipe.receipt()
        self.record["fixtureManifest"] = manifest
        self.record["preparedStateInventory"] = tree_inventory(self.recipe.state)
        self.record["preparedLifetime"] = self._lifetime(self.recipe.state)
        self.record["ownedDirectoryOrigins"] = self._directory_origins()
        self.controller.evidence.write("mimo-main-preparation.json", self.record, limit=32 * 1024 * 1024)
        self.prepared = True
        return self.recipe.receipt()

    def _normal_admission_probe(self) -> Object:
        end = min(self.full_end, time.monotonic() + 20)
        state = self.recipe.home / "normal-probe-state"
        require(not os.path.lexists(state), "Normal admission probe State must be genuinely absent.")
        proof = self._prep_call(["--state-dir", str(state), *_MIMO_ADMISSION_PROBE], name="normal-admission", end=end)
        provider = self.controller.reaped[-1]
        observed = self._lifetime(state)
        require(type(proof.get("version")) is int
                and proof == {"version": 1, "driver": "mimo", "subscription": "xiaomi", **observed["lifetime"]},
                "Ordinary admission did not return the independently observed new Xiaomi lifetime.")
        payload = self.controller.scope.producer(_MIMO_MAIN_COMPONENT)
        with self.authority.mutex(seconds=max(.001, end - time.monotonic())):
            custody = reconcile(self.authority, persist_unknown=False, candidate=self.controller.scope)
            roots = [row for row in custody.writers if row["parent"] is None
                     and {key: row[key] for key in ("pid", "startedAt")} == provider.owner.object()]
            require(custody.resolved and provider.reaped and len(roots) == 1 and roots[0]["phase"] == "terminal",
                    "The reaped normal probe does not own a unique terminal root in the actual custody graph.")
            mains = [row for row in custody.handoffs if row["invocation"] == roots[0]["invocation"]
                     and row["parent"] == roots[0]["writer"] and row["role"] == "main"]
            require(len(mains) == 1, "Normal probe lacks its own accepted MAIN transfer.")
            context, context_hash = self._public_context(mains[0], roots[0], role="main", entry=payload.descriptor["entry"])
            main = ExactProcess.read(context["process"])
            writer = read(writer_path(self.authority, context["invocation"], context["writer"]))
            require(writer["phase"] == "terminal" and writer["contextSha256"] == context_hash
                    and {key: writer[key] for key in ("pid", "startedAt")} == main.object() and not main.live(),
                    "The normal probe's own MAIN did not close under its accepted context.")
        require(time.monotonic() <= end, "Normal admission probe exceeded its preparation budget.")
        return {"argv": provider.process.args, "stateAbsentBefore": True, "state": str(state),
                "publicProof": proof, "independentState": observed, "providerActuallyReaped": provider.reaped,
                "terminalRoot": roots[0], "acceptedMainHandoff": mains[0], "terminalMain": writer}

    def _directory_origins(self) -> Object:
        origins: Object = {}
        for label, path in (("home", self.recipe.home), ("tool", self.recipe.tool), ("work", self.recipe.work),
                            ("state", self.recipe.state), ("subscriptions", self.recipe.state / "subscriptions"),
                            ("xiaomi", self.recipe.state / "subscriptions/xiaomi"),
                            ("nativeHome", self.recipe.tool / "native-profile/home")):
            image = physical_owned(path, directory=True)
            origins[label] = {"path": str(path), "device": image.st_dev, "inode": image.st_ino,
                              "mode": stat.S_IMODE(image.st_mode)}
        return origins

    def _lifetime(self, state: Path) -> Object:
        root = read_image(state / "identity.json")
        sidecar = read_image(state / "subscriptions/xiaomi/identity.json")
        root_value, witness = document(root.raw), document(sidecar.raw)
        require(type(root_value.get("version")) is int and root_value["version"] == 1
                and type(witness.get("version")) is int and witness["version"] == 1
                and witness.get("state") == "active"
                and valid_token(root_value.get("generation")) and valid_token(witness.get("witness"))
                and read_image(state / "format").raw == b"2\n", "State did not establish genuine format-2 proof.")
        return {"rootImage": root.evidence(), "sidecarImage": sidecar.evidence(),
                "lifetime": {"generation": root_value["generation"], "witness": witness["witness"]}}

    def _public_context(self, row: Object, parent: Object, *, role: str, entry: str) -> tuple[Object, str]:
        require(valid_token(row["handoff"]), "Invalid actual handoff token.")
        raw = read_bytes(self.authority.folder / "handoffs" / (row["handoff"] + ".context.json"))
        context = document(raw)
        normal_context(context)
        payload = self.controller.scope.producer(_MIMO_MAIN_COMPONENT)
        require(self.original_control is not None, "No original healthy epoch was retained.")
        assert self.original_control is not None
        require(context["role"] == role and context["entry"] == entry
                and context["invocation"] == parent["invocation"]
                and context["registry"] == str(self.controller.workspace.registry)
                and context["registrySha256"] == self.controller.scope.registry_sha256
                and context["component"] == _MIMO_MAIN_COMPONENT and context["epoch"] == self.original_control["epoch"]
                and context["boot"] == self.baseline.boot and context["payloadSha256"] == payload.digest
                and context["acceptanceSha256"] == self.controller.scope.acceptance_sha256
                and context["parent"] == {"writer": parent["writer"],
                                          **{key: parent[key] for key in ("pid", "startedAt")}},
                "Actual MAIN/Watcher context lost source/tuple/epoch/boot/entry/parent binding.")
        expected = {"version": 1, "handoff": context["handoff"], "component": _MIMO_MAIN_COMPONENT,
            "invocation": context["invocation"], "parent": parent["writer"], "child": context["writer"],
            "epoch": context["epoch"], "payloadSha256": payload.digest, "phase": "accepted", "nonce": context["nonce"],
            "contextSha256": digest(raw), "role": role, "entry": entry,
            "acceptanceSha256": self.controller.scope.acceptance_sha256, "challenge": row["challenge"]}
        require(row == expected and valid_token(row["challenge"]), "Actual accepted ACK/ready/go/started handoff differs.")
        return context, digest(raw)

    def verify_active(self, *, draining: bool) -> MimoMainView:
        require(self.child is not None and self.stream is not None and self.prepared and self.original_control is not None,
                "No actual public MAIN is available for active binding.")
        assert self.child is not None and self.stream is not None and self.original_control is not None
        self.controller.scope.recheck()
        payload = self.controller.scope.producer(_MIMO_MAIN_COMPONENT)
        with self.authority.mutex(seconds=max(.001, self.boundary_end - time.monotonic())):
            control = self.authority.read("control")
            expected_control = {**self.original_control, "phase": "draining", "session": self.session} if draining else self.original_control
            require(control == expected_control and not os.path.lexists(self.authority.folder / "taint.json"),
                    "Actual current control is not the exact intended healthy/draining beforeimage.")
            custody = reconcile(self.authority, persist_unknown=False, candidate=self.controller.scope)
            require(not custody.unknown and custody.active == 2 and custody.pending == 0,
                    "Actual live subject is not exactly MAIN plus persistent metadata Watcher.")
            roots = [row for row in custody.writers if row["parent"] is None
                     and {key: row[key] for key in ("pid", "startedAt")} == self.child.owner.object()]
            require(len(roots) == 1 and roots[0]["phase"] == "terminal", "Owned actual provider root/transfer differs.")
            mains = [row for row in custody.handoffs if row["parent"] == roots[0]["writer"]
                     and row["invocation"] == roots[0]["invocation"] and row["role"] == "main"]
            require(len(mains) == 1, "Actual public MAIN transfer is ambiguous.")
            main_context, main_hash = self._public_context(mains[0], roots[0], role="main", entry=payload.descriptor["entry"])
            main_writer = read(writer_path(self.authority, main_context["invocation"], main_context["writer"]))
            helpers = [row for row in custody.handoffs if row["parent"] == main_context["writer"]
                       and row["invocation"] == main_context["invocation"] and row["entry"] == "bin/identity-helper.py"]
            # bind_endpoint has already finished and is NOT the live Watcher.
            active_helpers = []
            for row in helpers:
                writer = read(writer_path(self.authority, row["invocation"], row["child"]))
                if writer["phase"] == "active":
                    active_helpers.append((row, writer))
            require(len(active_helpers) == 1, "Persistent actual metadata Watcher is missing/ambiguous.")
            watcher_row, watcher_writer = active_helpers[0]
            watcher_context, watcher_hash = self._public_context(watcher_row, main_writer, role="helper", entry="bin/identity-helper.py")
            main, watcher = ExactProcess.read(main_context["process"]), ExactProcess.read(watcher_context["process"])
            require(main_writer == {"version": 1, "invocation": main_context["invocation"], "writer": main_context["writer"],
                "parent": roots[0]["writer"], "component": _MIMO_MAIN_COMPONENT, "epoch": main_context["epoch"],
                "payloadSha256": payload.digest, "boot": self.baseline.boot, **main.object(), "phase": "active",
                "contextSha256": main_hash} and watcher_writer == {"version": 1, "invocation": watcher_context["invocation"],
                "writer": watcher_context["writer"], "parent": main_context["writer"], "component": _MIMO_MAIN_COMPONENT,
                "epoch": watcher_context["epoch"], "payloadSha256": payload.digest, "boot": self.baseline.boot,
                **watcher.object(), "phase": "active", "contextSha256": watcher_hash}, "Actual active writer rows differ.")
            require(self.child.owner.live(parent=os.getpid()) and main.live(parent=self.child.owner.pid)
                    and watcher.live(parent=main.pid), "Real provider/MAIN/Watcher birth/direct-parent binding changed.")
            ledger = document(read_image(self.recipe.state / "tmp" / self.recipe.run_id / "ledger.json", limit=1024 * 1024).raw,
                              limit=1024 * 1024)
            run = document(read_image(self.recipe.state / "runs" / (self.recipe.run_id + ".json"), limit=65536).raw, limit=65536)
            require(run["runId"] == ledger["runId"] == self.recipe.run_id and run["owner"] == ledger["owner"] == main.object()
                    and run["epoch"] == ledger["nonce"] and run["subscriptionId"] == ledger["subscriptionId"] == "xiaomi"
                    and run["lifetime"] == ledger["lifetime"] == self.record["preparedLifetime"]["lifetime"]
                    and ledger["resources"]["watcher"]["owner"] == watcher.object()
                    and ledger["resources"]["watcher"]["state"] == "admitted", "Real Run/ledger does not bind persistent Watcher/lifetime.")
            for row in custody.writers:
                if row["writer"] not in (roots[0]["writer"], main_context["writer"], watcher_context["writer"]):
                    require(row["phase"] == "terminal" and not ExactProcess.read(
                        {key: row[key] for key in ("pid", "startedAt")}).live(), "Another metadata helper remains active/unjoined.")
            image = _raw_authority_image(self.authority)
            return MimoMainView(main, watcher, main_context, watcher_context, main_hash, watcher_hash, main_writer, watcher_writer,
                {"writers": list(custody.writers), "handoffs": list(custody.handoffs)}, ledger, run,
                self.baseline.locks[_MIMO_MAIN_COMPONENT]["admission"], image)

    def start_and_begin(self) -> MimoMainView:
        require(self.prepared and self.child is None and not self.begun, "No run/resume/subset start is allowed.")
        require(self.native.verify(self.controller) == self.source, "Actual source/native preparation pins changed before Run.")
        self.run_end = min(self.full_end, time.monotonic() + 60)
        _, _, tail = self.recipe.tails()
        self.child = OwnedChild(self._argv(tail), environment=without_authority(self.environment), cwd=self.recipe.home)
        try:
            self.stream = MimoMainStream(self.child, run_id=self.recipe.run_id, end=self.run_end)
            self.stream.start()
            started = self.stream.stubborn_start(end=min(self.run_end - 40, time.monotonic() + 20))
            self.boundary_end = min(self.run_end - 35, time.monotonic() + 5)
            self.view = self.verify_active(draining=False)  # Retain VERIFIED targets before fallible writes/effects.
            self.record["actualStubbornStart"] = started
            self.record["activeBeforeBegin"] = self.view.before_metadata
            argv = [*self.controller.scope.gate.provider.prefix, "driver-state", "begin", "--registry-dir",
                    str(self.controller.workspace.registry), "--component", _MIMO_MAIN_COMPONENT, "--session", self.session]
            begin = OwnedChild(argv, environment=without_authority(self.environment), cwd=self.controller.workspace.registry)
            result = _mimo_finite_data_call(begin, end=self.boundary_end)
            self.controller.reaped.append(begin)
            self.record["actualBegin"] = {"argv": argv, "provider": begin.owner.object(), "reaped": begin.reaped,
                "stdoutHex": result.stdout.hex(), "stderrHex": result.stderr.hex(), "session": self.session}
            self.controller.evidence.write("mimo-main-begin-output.json", self.record["actualBegin"], limit=32 * 1024 * 1024)
            require(begin.reaped and result.returncode == 0 and document(result.stdout).get("phase") == "draining",
                    "Actual public begin did not close new admission.")
            current = self.verify_active(draining=True)
            require(current.main == self.view.main and current.watcher == self.view.watcher
                    and current.main_writer == self.view.main_writer and current.watcher_writer == self.view.watcher_writer,
                    "Real begin changed active accepted writer/epoch bindings.")
            with self.authority.mutex(seconds=max(.001, self.boundary_end - time.monotonic())):
                require(_h1_raw_ex(self.authority, current.admission_lock), "Actual drain EX precondition was available while both writers lived.")
            require(time.monotonic() <= self.boundary_end, "Real startup/bind/begin exceeded its five-second boundary.")
            # Only the public begin's real control transition is allowed here.
            # No normal marker/writer/handoff/context is deleted or relabelled.
            def without_control(image: Object) -> Object:
                return {"root": image["root"], "entries": [row for row in image["entries"] if row["path"] != "control.json"]}
            require(without_control(current.before_metadata) == without_control(self.view.before_metadata),
                    "Public begin changed metadata beyond its genuine control/session transition.")
            self.record["activeAfterBegin"] = current.before_metadata
            self.record["rawDrainExPreconditionBlockedWhileBothActive"] = True
            self.record["rawExHolderAttributedSolelyToWatcher"] = False
            self.view = current
            self.begun = True
            self.refuse_new_after_begin()
            return current
        except BaseException as error:
            self.abort(error)
            raise

    def refuse_new_after_begin(self) -> None:
        """A distinct fixed public launch must refuse before ANY new State read.

        It uses the remaining ORIGINAL five-second begin-boundary budget. No
        metadata-only refusal or absent child attribute substitutes for the raw
        complete before/after writer/handoff/context/marker inventory.
        """
        require(self.begun and self.view is not None and self.child is not None
                and self.original_control is not None and not self.stop_sent,
                "Closed-admission observation requires the verified live pair.")
        assert self.view is not None and self.child is not None and self.original_control is not None
        state = self.recipe.home / "refused-state"
        require(not os.path.lexists(state), "Refusal State must be genuinely absent.")
        expected_control = {**self.original_control, "phase": "draining", "session": self.session}
        with self.authority.mutex(seconds=max(.001, self.boundary_end - time.monotonic())):
            require(self.authority.read("control") == expected_control,
                    "Genuine begin control changed before fresh-launch refusal.")
            before = _raw_authority_image(self.authority)
            phase_check = self._observe_draining_control()
            require(self.authority.read("control") == expected_control and _raw_authority_image(self.authority) == before,
                    "The independent control check changed the draining authority.")
        argv = self._argv(["--state-dir", str(state), *_MIMO_ADMISSION_PROBE])
        normal = self.record["normalAdmissionProbe"]
        require(normal["argv"] == [*argv[:-4], normal["state"], *argv[-3:]] and normal["state"] != str(state),
                "Draining and normal admission probes differ beyond their private State sibling.")
        probe = OwnedChild(argv, environment=without_authority(self.environment), cwd=self.recipe.home)
        captured = _mimo_finite_data_call(probe, end=self.boundary_end)
        self.controller.reaped.append(probe)
        # Persist real bytes before any assertion on the public refusal result.
        self.controller.evidence.write("mimo-main-new-refusal-output.json", {
            "argv": probe.process.args, "provider": probe.owner.object(), "providerActuallyReaped": probe.reaped,
            "returncode": captured.returncode, "stdoutHex": captured.stdout.hex(), "stderrHex": captured.stderr.hex()},
            limit=32 * 1024 * 1024)
        expected_refusal = canonical({"error": {"code": "builds_failed",
            "message": "Driver maintenance refused; preserve closed recovery authority."}})
        require(probe.reaped and captured.returncode == 1 and captured.stdout == expected_refusal
                and not captured.stderr and not os.path.lexists(state),
                "Fresh public Driver did not return the provider refusal before reaching State.")
        self.controller.scope.recheck()
        with self.authority.mutex(seconds=max(.001, self.boundary_end - time.monotonic())):
            after = _raw_authority_image(self.authority)
            require(after == before, "Refused launch changed actual control/writers/handoffs/contexts/markers.")
            require(self.view.main.live(parent=self.child.owner.pid) and self.view.watcher.live(parent=self.view.main.pid),
                    "Original admitted MAIN/Watcher pair did not remain live across fresh-launch refusal.")
        require(time.monotonic() <= self.boundary_end, "Fresh refusal exceeded the original five-second boundary.")
        self.record["closedAdmissionRefusal"] = {"before": before, "after": after,
            "stateAbsentBeforeAndAfter": True, "providerActuallyReaped": probe.reaped,
            "publicRefusalOnly": True, "independentSourceBoundCheck": phase_check,
            "metadataOrTerminalSynthesized": False}

    def _observe_draining_control(self) -> Object:
        """Check the real phase gate under the caller's short mutex."""
        try:
            normal_control(self.authority, candidate=self.controller.scope)
        except Refusal as error:
            trace = error.__traceback__
            check = trace.tb_next if trace is not None else None
            refusal = check.tb_next if check is not None else None
            phase_line = self.record["providerAdmissionSource"]["driver_admission.py"]["normalControlPhaseRefusalLine"]
            if (check is None or check.tb_frame.f_code is not normal_control.__code__
                    or check.tb_lineno != phase_line
                    or refusal is None or refusal.tb_frame.f_code is not provider_admission.refuse.__code__
                    or refusal.tb_next is not None):
                raise ObservationFailed("Draining control did not refuse directly at the admitted phase check.") from error
            return {"function": normal_control.__qualname__, "line": check.tb_lineno, "directRefusal": True}
        raise ObservationFailed("The pinned control check admitted new work while draining.")

    def ordinary_stop(self) -> None:
        require(self.begun and self.record.get("closedAdmissionRefusal") is not None
                and not self.stop_sent and self.child is not None and self.view is not None,
                "Ordinary stop requires the already verified actual begin boundary.")
        assert self.child is not None and self.view is not None
        pipe = self.child.process.stdin
        require(pipe is not None and not pipe.closed and self.view.main.live(parent=self.child.owner.pid)
                and self.view.watcher.live(parent=self.view.main.pid), "Actual control/MAIN/Watcher changed before stop.")
        assert pipe is not None
        os.set_blocking(pipe.fileno(), False)
        raw = memoryview(canonical({"type": "stop"}))
        end = min(self.run_end - 15, time.monotonic() + 5)
        with selectors.DefaultSelector() as selector:
            selector.register(pipe, selectors.EVENT_WRITE)
            while raw:
                require(time.monotonic() < end, "Existing ordinary JSONLF stop could not be delivered within the original budget.")
                if selector.select(min(.025, max(0, end - time.monotonic()))):
                    try:
                        count = os.write(pipe.fileno(), raw)
                    except BlockingIOError:
                        continue
                    require(count > 0, "Actual ordinary stop pipe closed early.")
                    raw = raw[count:]
        self.stop_sent = True
        self.stop_observed_at = time.monotonic()
        self.record["ordinaryJsonLfStopSentAfterBegin"] = True
        # KEEP stdin OPEN. No successful EOF trigger or communicate/collect.

    def verified_main_stop(self) -> None:
        require(self.begun and self.record.get("closedAdmissionRefusal") is not None
                and not self.stop_sent and self.view is not None and self.child is not None
                and self.stream is not None and self.original_control is not None,
                "Verified-main cancellation requires the admitted pair across real begin.")
        assert self.view is not None and self.child is not None and self.stream is not None
        assert self.original_control is not None
        view = self.view
        provider = self.child
        stdin = provider.process.stdin
        require(stdin is not None and not stdin.closed
                and set(threading.enumerate()) == {threading.current_thread(), self.stream.thread},
                "Cancellation needs an open input pipe and the sole data reader.")
        end = min(self.run_end - 15, time.monotonic() + 5)
        sent_key = (view.main.pid, view.main.started_at)
        real_kill = os.kill
        context_hash = view.main_context_sha256
        changed_hash = ("1" if context_hash.startswith("0") else "0") + context_hash[1:]
        observation: Object = {"main": view.main.object(), "watcher": view.watcher.object(),
                               "inputKeptOpen": True, "publicDrainInvoked": False, "signals": []}
        self.record["verifiedMainCancellation"] = observation

        def no_signal(*arguments: object) -> None:
            observation["signals"].append(list(arguments))
            raise ObservationFailed("A non-target or duplicate signal was attempted.")

        def changed_reread(authority: Authority, invocation: str, writer: str) -> Object:
            actual = provider_admission.read_writer(authority, invocation, writer)
            require(authority is self.authority and actual == view.main_writer
                    and invocation == view.main_context["invocation"] and writer == view.main_context["writer"],
                    "The reread fault reached a writer other than the verified active MAIN.")
            observation["changedReread"] = {"real": actual, "substitutedContextSha256": changed_hash}
            return {**actual, "contextSha256": changed_hash}

        def signal_main(pid: int, number: int) -> None:
            require(time.monotonic() < end and pid == view.main.pid and number == signal.SIGTERM
                    and not observation["signals"] and view.main.live(parent=provider.owner.pid)
                    and view.watcher.live(parent=view.main.pid),
                    "The actual signal is outside the fresh verified MAIN boundary.")
            real_kill(pid, number)
            self.stop_observed_at = time.monotonic()
            self.stop_sent = True
            observation["signals"].append([pid, int(number)])

        with self.authority.mutex(seconds=max(.001, end - time.monotonic())):
            require(self.authority.read("control") == {**self.original_control, "phase": "draining", "session": self.session},
                    "The genuine draining session changed before cancellation.")
            custody = reconcile(self.authority, persist_unknown=False, candidate=self.controller.scope)
            require(not custody.unknown and custody.active == 2 and custody.pending == 0
                    and list(custody.writers) == view.custody["writers"] and list(custody.handoffs) == view.custody["handoffs"]
                    and view.main.live(parent=provider.owner.pid) and view.watcher.live(parent=view.main.pid),
                    "The active pair differs from the independently verified custody graph.")
            before = _raw_authority_image(self.authority)
            require(before == view.before_metadata, "The original verified writer, control or marker bytes changed.")
            with (patch.object(provider_process, "read_writer", side_effect=changed_reread) as reread,
                  patch.object(os, "kill", side_effect=no_signal),
                  patch.object(os, "killpg", side_effect=no_signal)):
                fresh: set[tuple[int, str]] = set()
                try:
                    provider_process.request_cancellation(self.authority, custody, fresh)
                except Refusal:
                    reread.assert_called_once_with(self.authority, view.main_context["invocation"], view.main_context["writer"])
                else:
                    raise ObservationFailed("Cancellation accepted a mismatching fresh context hash.")
                require("changedReread" in observation and not fresh and not observation["signals"]
                        and _raw_authority_image(self.authority) == before,
                        "The labelled reread fault changed real custody or attempted a signal.")
            with (patch.object(os, "kill", side_effect=no_signal),
                  patch.object(os, "killpg", side_effect=no_signal)):
                sent = {sent_key}
                provider_process.request_cancellation(self.authority, custody, sent)
                require(sent == {sent_key} and not observation["signals"]
                        and _raw_authority_image(self.authority) == before,
                        "An already-signalled owner changed custody or received a duplicate signal.")
            observation["priorSignalSuppressed"] = True
            observation["negativeAuthoritySha256"] = digest(canonical(before))
            with (patch.object(os, "kill", side_effect=signal_main),
                  patch.object(os, "killpg", side_effect=no_signal)):
                pending: set[tuple[int, str]] = set()
                provider_process.request_cancellation(self.authority, custody, pending)
            require(self.stop_sent and pending == {sent_key}
                    and observation["signals"] == [[view.main.pid, int(signal.SIGTERM)]],
                    "The verified MAIN did not receive exactly one real SIGTERM.")
        require(time.monotonic() <= end and stdin is not None and not stdin.closed,
                "Verified-main cancellation exceeded its budget or changed the open stdin boundary.")

    def _source_coupling(self) -> Object:
        """Exact packaged paths; static call-path proof has explicit limits.

        No Mimo body is imported/executed by this observer. Actual context/D/M
        binds its fixed public entry; source checks describe why real own-run
        retirement implies verify_cleanup proof, not normal shutdown success.
        """
        import ast

        require(self.native.verify(self.controller) == self.source, "Exact native/source pins changed during the subject.")
        producer = self.controller.scope.producer(_MIMO_MAIN_COMPONENT)
        selected = {
            "src/arbol_mimo_driver/runtime.py": ("Terminal.latch", "Run.cleanup", "Run.execute"),
            "src/arbol_mimo_driver/runs.py": ("Runs.verify_cleanup", "Runs.verified_proof", "Runs.retire", "Runs.release_owned"),
            "src/arbol_mimo_driver/ownership.py": ("Ownership.shutdown", "Ownership.bind_endpoint"),
            "src/arbol_mimo_driver/native_server.py": ("NativeServer.close",),
            "src/arbol_mimo_driver/adapters/watcher.py": ("WatcherClient.finish", "WatcherClient.__init__"),
            "src/arbol_mimo_driver/admission.py": ("Admission.finish", "HelperHandoff.require_terminal"),
            "src/arbol_mimo_driver/operation.py": ("Operation.__init__", "Operation.__exit__"),
        }
        paths: Object = {}
        for name, expected in selected.items():
            image = read_image(producer.root / name, limit=4 * 1024 * 1024, private=False)
            require(image.sha256 == self.native.source_sha256[name], "Packaged cancellation/verification source differs.")
            parsed = ast.parse(image.raw, filename=str(image.path))
            lines = image.raw.splitlines(keepends=True)
            functions: Object = {}
            for owner in parsed.body:
                if isinstance(owner, ast.ClassDef):
                    for node in owner.body:
                        qualified = owner.name + "." + node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else ""
                        if qualified in expected:
                            assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno is not None
                            functions[qualified] = {"firstLine": node.lineno, "lastLine": node.end_lineno,
                                "bodySha256": digest(b"".join(lines[node.lineno - 1:node.end_lineno]))}
            require(set(functions) == set(expected), "Missing source-defined cancellation/cleanup proof body.")
            paths[name] = {"image": image.evidence(), "staticBodies": functions}
        provider_paths = self._provider_sources()
        require(provider_paths == self.record["providerAdmissionSource"], "Pinned provider source changed after preparation.")
        return {"producer": paths, "provider": provider_paths,
            "reportConsumption": "SOURCE-COUPLED Runtime.cleanup -> Runs.verify_cleanup -> genuine terminal/clean proof -> retire/release_owned",
            "normalOwnershipShutdownReturnedProven": False, "rawObservationsReceiptRetained": False,
            "watcherMainOwnedWaitAndRequireTerminal": "STATIC call-path retention ONLY; invocation/success not established by cancelled subject",
            "complementaryCompletedPredicateOwner": "ABR-38 step47; incomplete here"}

    def _provider_sources(self) -> Object:
        import arbol_builds.driver_state as provider_state

        provider = self.controller.scope.gate.provider
        require(vars(provider_state)["Guardian"] is provider_process.Guardian
                and vars(provider_process)["normal_control"] is normal_control
                and vars(provider_process)["read_writer"] is provider_admission.read_writer
                and vars(provider_process)["os"] is os
                and normal_control is provider_admission.normal_control,
                "The loaded candidate route does not use the observed control check.")
        actual = (provider_process.supervise, provider_process.Guardian._close_owned,
                  provider_process.Guardian.admit, provider_process.inspect, provider_state.launch_candidate,
                  provider_process.request_cancellation, provider_process.matches,
                  provider_state.begin, provider_state.drain, normal_control, provider_admission.read_writer,
                  provider_admission.refuse, Authority.lease)
        provider_paths: Object = {}
        bound_functions = 0
        for short in ("driver_process.py", "driver_state.py", "driver_admission.py"):
            path = provider.root / "src/arbol_builds" / short
            image = read_image(path, limit=1024 * 1024, private=False)
            compiled = compile(image.raw, str(path), "exec", dont_inherit=True, optimize=sys.flags.optimize)
            codes: dict[str, list[CodeType]] = {}

            def collect(code: CodeType, target: dict[str, list[CodeType]] = codes) -> None:
                target.setdefault(code.co_qualname, []).append(code)
                for value in code.co_consts:
                    if isinstance(value, CodeType):
                        collect(value)

            collect(compiled)  # Compilation ONLY; no packaged execution.
            names = []
            for method in actual:
                if Path(method.__code__.co_filename).name == short:
                    require(Path(method.__code__.co_filename).resolve(strict=True) == path.resolve(strict=True)
                            and codes.get(method.__qualname__) == [method.__code__],
                            "Actual provider wait/EX/process code is not its pinned packaged source.")
                    names.append(method.__qualname__)
            require(bool(names), "Unbound actual provider source path.")
            provider_paths[short] = {"image": image.evidence(), "actualCodeObjects": names}
            bound_functions += len(names)
            if short == "driver_admission.py":
                lines = image.raw.splitlines()
                start = normal_control.__code__.co_firstlineno - 1
                # The phase guard precedes deployment, taint and custody checks.
                guard = b'    if control["phase"] != "normal" or (epoch is not None and control["epoch"] != epoch):'
                guard_index = lines.index(guard, start, start + 8)
                require(lines[guard_index + 1] == b"        refuse()", "Pinned phase guard no longer calls direct refusal.")
                provider_paths[short]["normalControlPhaseRefusalLine"] = guard_index + 2
        require(bound_functions == len(actual), "An admission or settlement function lacks pinned provider source.")
        return provider_paths

    def _resource_closure(self, *, end: float) -> Object:
        require(self.view is not None and time.monotonic() < end, "No retained original resources/deadline.")
        assert self.view is not None
        resources = self.view.ledger.get("resources")
        require(isinstance(resources, dict) and 0 < len(resources) <= 1024 and "watcher" in resources,
                "Original resource inventory is missing or outside its finite bound.")
        assert isinstance(resources, dict)
        observed: Object = {}
        for name, row in resources.items():
            require(isinstance(name, str) and isinstance(row, dict) and type(row.get("pgid")) is int,
                    "Original native resource has no exact bounded owner/group record.")
            owner = ExactProcess.read(row["owner"])
            require(not owner.live(), "An original attributable resource remains alive, including outside its old group.")
            members = _mimo_original_group_members(row["pgid"], end=end)
            require(not members, "Original native resource group is nonempty/reused/unresolved; never signal it.")
            observed[name] = {"original": row, "originalOwnerKernelGone": True,
                              "freshOriginalGroupMembers": members, "observerSentResourceSignal": False}
        # Do not sample a vanished scratch and fabricate an empty final ledger.
        # Late resource protection is additionally source-coupled to actual
        # verify_cleanup's complete final inventory before genuine retirement.
        return {"retainedOriginalResources": observed,
                "completeFinalInventory": "SOURCE-COUPLED verify_cleanup; no sampled-empty inventory claim"}

    def settle_after_cancellation(self) -> Object:
        require(self.begun and self.stop_sent and self.view is not None and self.child is not None
                and self.stream is not None and self.original_control is not None and not self.closed,
                "No genuine cancellation subject is available for settlement.")
        assert self.view is not None and self.child is not None and self.stream is not None and self.original_control is not None
        settle_end = min(self.run_end - 15, self.stop_observed_at + 20)
        require(time.monotonic() + .5 < settle_end, "No original cancellation settlement/reader reserve remains.")
        status = self.child.wait_owned(seconds=max(.001, settle_end - .5 - time.monotonic()))
        self.stream.join(end=settle_end, failure=False)
        output = self.stream.snapshot()
        # Actual bytes survive any following validation, source, State or IO error.
        self.controller.evidence.write("mimo-main-actual-cancelled-output.json", output, limit=32 * 1024 * 1024)
        records = output["records"]
        require(self.child.reaped and status == 2 and not output["stderrHex"] and records
                and sum(row["type"] == "finished" for row in records) == 1
                and records[-1]["type"] == "finished" and records[-1].get("outcome") == "cancelled"
                and "error" not in records[-1]
                and not any(row["type"] == "notice" and row.get("code") == "cleanup_unresolved" for row in records),
                "Actual stop did not produce its exact cancelled, proof-backed closure result.")
        starts: dict[str, Object] = {}
        finishes: dict[str, Object] = {}
        stubborn_call = self.record["actualStubbornStart"].get("callId")
        for row in records:
            if row["type"] in ("tool_started", "tool_finished"):
                call = row.get("callId")
                require(isinstance(call, str) and bool(call) and len(call) <= 4096, "Invalid actual tool correlation.")
                target = starts if row["type"] == "tool_started" else finishes
                require(call not in target, "Duplicate actual tool start/finish.")
                if target is finishes:
                    require(call in starts, "Actual tool finished before its start.")
                target[call] = row
        require(bool(starts) and set(starts) == set(finishes) and stubborn_call in starts,
                "Original held tool lacks balanced actual interruption/output completion.")
        require(time.monotonic() <= settle_end, "Cancellation settlement exceeded its original twenty seconds.")
        require(not self.view.main.live() and not self.view.watcher.live(),
                "Actual MAIN/Watcher remain live; no terminal-from-provider-exit inference.")
        self.controller.reaped.append(self.child)
        observed_end = min(self.full_end, self.run_end, time.monotonic() + 15)
        sources = self._source_coupling()
        resources = self._resource_closure(end=observed_end)
        require(self._directory_origins() == self.record["ownedDirectoryOrigins"]
                and self._lifetime(self.recipe.state) == self.record["preparedLifetime"],
                "Original private roots/proof changed during the cancelled subject.")
        # Read ORIGINAL State only: no fresh registry, copy, normal API recovery
        # call, source helper execution or report-polled race is introduced.
        state_inventory = tree_inventory(self.recipe.state)
        require(not os.path.lexists(self.recipe.state / "runs" / (self.recipe.run_id + ".json"))
                and not os.path.lexists(self.recipe.state / "tmp" / self.recipe.run_id)
                and not any(row["path"].startswith("runs/") and row["type"] == "file" for row in state_inventory)
                and not any(row["path"].startswith("tmp/.retired-") for row in state_inventory),
                "Actual original run/scratch remains unresolved; never relabel or erase it.")
        with self.authority.mutex(seconds=max(.001, observed_end - time.monotonic())):
            expected_control = {**self.original_control, "phase": "draining", "session": self.session}
            require(self.authority.read("control") == expected_control
                    and not os.path.lexists(self.authority.folder / "taint.json")
                    and not os.path.lexists(self.authority.folder / "maintenance.json"),
                    "Real cancellation changed the intended closed session or left unknown authority.")
            custody = reconcile(self.authority, persist_unknown=False, candidate=self.controller.scope)
            require(custody.resolved and custody.active == custody.pending == 0
                    and all(row["phase"] == "terminal" for row in custody.writers),
                    "Whole original custody graph is not genuinely terminal/resolved.")
            final_handoffs = {row["handoff"]: row for row in custody.handoffs}
            original_handoffs = {row["handoff"]: row for row in self.view.custody["handoffs"]}
            require(all(final_handoffs.get(key) == value for key, value in original_handoffs.items()),
                    "An original accepted transfer was removed or changed after begin.")
            final_writers = {(row["invocation"], row["writer"]): row for row in custody.writers}
            original_writers = {(row["invocation"], row["writer"]): row for row in self.view.custody["writers"]}
            require(all(final_writers.get(key) == {**value, "phase": "terminal"}
                        for key, value in original_writers.items()),
                    "Original writer history changed beyond genuine terminal publication.")
            changed_paths = {"writers/" + row["invocation"] + "/" + row["writer"] + ".json"
                             for row in self.view.custody["writers"]}
            expected_new_writers: set[tuple[str, str]] = set()
            cleanup_helpers: list[Object] = []
            for key in sorted(set(final_handoffs) - set(original_handoffs)):
                handoff = final_handoffs[key]
                require(handoff["role"] == "helper" and handoff["entry"] == "bin/identity-helper.py"
                        and handoff["invocation"] == self.view.main_context["invocation"]
                        and handoff["parent"] == self.view.main_context["writer"],
                        "A new root/MAIN/foreign helper appeared after genuine begin.")
                context, context_hash = self._public_context(handoff, self.view.main_writer,
                    role="helper", entry="bin/identity-helper.py")
                process = ExactProcess.read(context["process"])
                writer_key = (context["invocation"], context["writer"])
                require(writer_key not in original_writers and writer_key not in expected_new_writers,
                        "A cleanup helper reused original writer/transfer authority.")
                expected_new_writers.add(writer_key)
                expected_writer: Object = {"version": 1, "invocation": context["invocation"], "writer": context["writer"],
                    "parent": self.view.main_context["writer"], "component": _MIMO_MAIN_COMPONENT,
                    "epoch": context["epoch"], "payloadSha256": self.controller.scope.producer(_MIMO_MAIN_COMPONENT).digest,
                    "boot": self.baseline.boot, **process.object(), "phase": "terminal", "contextSha256": context_hash}
                require(final_writers.get(writer_key) == expected_writer and not process.live(),
                        "A legitimate cleanup helper did not genuinely close under its exact accepted context.")
                members = _mimo_original_group_members(process.pid, end=observed_end)
                require(not members, "An original source-bound cleanup helper group remains live/reused.")
                cleanup_helpers.append({"handoff": handoff, "context": context, "contextSha256": context_hash,
                    "writer": expected_writer, "kernelGone": True, "freshOriginalHelperPidGroupMembers": members,
                    "groupOrigin": "SOURCE-COUPLED Watcher/endpoint Popen(start_new_session=True)",
                    "observerReapedHelper": False, "helperOwnedWaitProvenByCancelledOutput": False})
                changed_paths.update(("writers/" + context["invocation"] + "/" + context["writer"] + ".json",
                                      "handoffs/" + key + ".json", "handoffs/" + key + ".context.json"))
            require(set(final_writers) - set(original_writers) == expected_new_writers,
                    "An unaccounted writer appeared beyond genuine cleanup helper transfers.")
            for context, old_row in ((self.view.main_context, self.view.main_writer),
                                     (self.view.watcher_context, self.view.watcher_writer)):
                require(read(writer_path(self.authority, context["invocation"], context["writer"])) == {**old_row, "phase": "terminal"},
                        "Actual original MAIN/Watcher did not genuinely finish under its accepted context.")
                raw = read_bytes(self.authority.folder / "handoffs" / (context["handoff"] + ".context.json"))
                require(document(raw) == context, "Original public context bytes/bindings changed at closure.")
            for row in custody.writers:
                require(not ExactProcess.read({key: row[key] for key in ("pid", "startedAt")}).live(),
                        "Another terminal-labelled metadata process remains alive/unjoined.")
            before = _raw_authority_image(self.authority)
            def preserved(image: Object) -> Object:
                return {"root": image["root"], "entries": [row for row in image["entries"] if row["path"] not in changed_paths]}
            require(preserved(before) == preserved(self.view.before_metadata),
                    "Cancellation changed controls/markers/contexts/archives beyond accounted genuine helper custody.")
            require(not _h1_raw_ex(self.authority, self.view.admission_lock),
                    "Genuine original-inode EX is still blocked after complete closure.")
            after = _raw_authority_image(self.authority)
            require(after == before, "Actual raw EX observation changed custody/control/marker history.")
        require(time.monotonic() <= observed_end, "Original sixty-second span exhausted before independent closure.")
        self.record.update({"actualCancelledOutput": output, "staticAndSourceCoupledEvidence": sources,
            "independentOriginalResources": resources, "actualStateInventory": state_inventory,
            "wholeTerminalCustody": {"writers": list(custody.writers), "handoffs": list(custody.handoffs)},
            "legitimateCleanupHelpers": cleanup_helpers,
            "actualClosedAuthority": after, "originalAdmissionExAvailable": True,
            "providerActuallyReaped": self.child.reaped, "mainAndWatcherKernelGone": True,
            "mainWait": "SOURCE-COUPLED actual public provider supervise/wait result; observer did not reap descendant",
            "rawObservationsReceiptRetained": False, "normalOwnershipShutdownReturnedProven": False,
            "observerReapedDescendant": False, "externalMaintenancePerformed": False,
            "genuineBegunSessionRemainsClosed": self.session, "completeCheckClaimed": False})
        for pipe in (self.child.process.stdin, self.child.process.stdout, self.child.process.stderr):
            if pipe is not None:
                pipe.close()
        self.controller.evidence.write("mimo-main-across-begin-cancelled.json", self.record, limit=32 * 1024 * 1024)
        self.closed = True
        return dict(self.record)

    def abort(self, original: BaseException) -> None:
        if self.closed:
            return
        self.closed = True
        end = min(self.full_end, self.run_end if self.run_end else self.full_end, time.monotonic() + 15)
        errors: list[str] = []
        child = self.child
        if child is not None:
            # Failure EOF only AFTER original failure, never a successful trigger.
            if child.process.stdin is not None:
                try:
                    child.process.stdin.close()
                except BaseException as error:
                    errors.append("failure-stdin:" + type(error).__name__)
            if self.view is not None:
                try:
                    if self.view.main.live():
                        signal_verified(self.view.main, signal.SIGTERM)
                except BaseException as error:
                    errors.append("verified-main-cancel:" + type(error).__name__)
            try:
                child.request_stop()
            except BaseException as error:
                errors.append("owned-provider-stop:" + type(error).__name__)
            try:
                child.wait_owned(seconds=max(.001, end - .25 - time.monotonic()))
            except BaseException as error:
                errors.append("owned-provider-wait:" + type(error).__name__)
        if self.stream is not None:
            try:
                self.stream.join(end=end, failure=True)
            except BaseException as error:
                errors.append("data-reader-join:" + type(error).__name__)
        if child is not None:
            for pipe in (child.process.stdin, child.process.stdout, child.process.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except BaseException as error:
                        errors.append("owned-pipe:" + type(error).__name__)
        cleanup: Object = {"errors": errors, "subjectBeforeFailure": self.record,
            "providerActuallyReaped": child is not None and child.reaped,
            "main": None if self.view is None else self.view.main.object(),
            "watcher": None if self.view is None else self.view.watcher.object(),
            "observerSignalledHelperOrGroup": False, "observerReapedDescendant": False,
            "custodyOrTerminalClaimed": False, "stream": None if self.stream is None else self.stream.snapshot()}
        original.add_note("Mimo actual subject cleanup: " + repr(cleanup))
        try:
            self.controller.evidence.write("mimo-main-failed-cleanup.json", cleanup, limit=32 * 1024 * 1024)
        except BaseException as error:
            original.add_note("Private failed-subject evidence unavailable: " + type(error).__name__)


def main_watcher_across_begin(controller: WholeCheckController, baseline: Baseline, *, case: str,
                             native: MimoOfflineInput, full_run_end: float, environment: Mapping[str, str]) -> Object:
    """Prospective fixed offline subject13.1; not registered/wired/executed here."""
    subject = MimoMainSubject(controller, baseline, case=case, native=native,
                              full_run_end=full_run_end, environment=environment)
    try:
        subject.prepare()
        subject.start_and_begin()
        subject.ordinary_stop()
        return subject.settle_after_cancellation()
    except BaseException as error:
        subject.abort(error)
        raise


def verified_main_cancellation_across_begin(controller: WholeCheckController, baseline: Baseline, *, case: str,
                                            native: MimoOfflineInput, full_run_end: float,
                                            environment: Mapping[str, str]) -> Object:
    """Prospective provider-triggered cancellation on a fresh offline subject."""
    subject = MimoMainSubject(controller, baseline, case=case, native=native,
                              full_run_end=full_run_end, environment=environment)
    try:
        subject.prepare()
        subject.start_and_begin()
        subject.verified_main_stop()
        return subject.settle_after_cancellation()
    except BaseException as error:
        subject.abort(error)
        raise
