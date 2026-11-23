"""Prospective ABR-38 external maintenance cases for disposable Build registries."""

from __future__ import annotations

import fcntl
import os
import re
import selectors
import signal
import stat
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from driver_identity_qualification import ArchiveImage, ArchiveWitness, Baseline, WholeCheckController, require

from arbol_builds.driver_admission import (
    COMPONENTS,
    Authority,
    publish_bytes,
    reconcile,
    valid_token,
    validate,
    without_authority,
)
from arbol_builds.driver_payload import request_binding
from top.driver_state_support import (
    Captured,
    FileImage,
    Object,
    OwnedChild,
    canonical,
    digest,
    directory_identity,
    document,
    physical_owned,
    read_image,
    signal_verified,
    sync_directory,
    tree_inventory,
)
from top.test_top_driver_state_admission import H1SpanCompletion, TerminalCloseClosure, TerminalSpanObservation

Operation = Literal["upgrade", "identity-reset", "restore", "identity-recover"]
Fault = Literal["no-fd", "wrong-inode", "separate-description", "receipt", "state", "operation",
                "context-copy", "epoch", "attempt", "payload"]
Mode = Literal["observe", "before-spawn", "before-ack", "cached", "unsafe-source-parent", "retirement"] | Fault
_OPERATIONS = {"upgrade", "identity-reset", "restore", "identity-recover"}
_CONTEXT_FAULTS = {"epoch", "attempt", "payload"}
_ROOT_METADATA = {"format", "identity.json", "identity-maintenance.json", "identity-upgrade.json"}
_SUBSCRIPTION_METADATA = re.compile(r"subscriptions/[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}/identity(?:-pending)?\.json\Z", re.ASCII)
_MANIFEST_LIMIT = 32 * 1024 * 1024
_PROVIDER_REFUSAL = {"error": {"code": "builds_failed",
                              "message": "Driver maintenance refused; preserve closed recovery authority."}}

# Run the exact sealed entry in its bundled -ISB interpreter. The fixed
# observer is outside the installed payload. It intercepts only the real
# administrative Popen boundary and the pre-stdout ACK boundary. Report on
# stderr and wait for a one-byte permit on inherited stdio, with no extra
# control fd passed to the producer. All production validation stays live.
_OBSERVER = """\
import json
import os
import sys

entry, mode, replacement, retirement_program, *arguments = sys.argv[1:]
if arguments[:2] != ['driver-state', 'execute']:
    raise SystemExit(96)
sys.argv[:] = [entry, *arguments]
sys.modules['__main__'].__file__ = entry
fd_key = 'ARBOL_DRIVER_MAINTENANCE_FD'
context_key = 'ARBOL_DRIVER_MAINTENANCE_CONTEXT'
normal_keys = ('ARBOL_DRIVER_ADMISSION_FD', 'ARBOL_DRIVER_ADMISSION_CONTEXT')
state = {}

def frame(value, wait=False):
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\\n').encode()
    if len(raw) > 4096 or os.write(2, raw) != len(raw):
        os._exit(97)
    if wait and os.read(0, 1) != b'+':
        os._exit(98)

class ObservedProcesses:
    def __init__(self, module):
        self.module = module

    def __getattr__(self, key):
        return getattr(self.module, key)

    def Popen(self, argv, **options):
        environment = options['env']
        fd = int(environment[fd_key])
        context = environment[context_key]
        info = os.fstat(fd)
        inherited = list(options['pass_fds'])
        original = list(argv)
        if inherited != [fd] or fd < 3 or not os.get_inheritable(fd):
            os._exit(99)
        frame({'phase': 'spawn', 'argv': original, 'context': context,
               'fd': fd, 'device': info.st_dev, 'inode': info.st_ino,
               'mode': info.st_mode & 0o7777, 'uid': info.st_uid,
               'normalAuthorityCleared': not any(key in environment for key in normal_keys),
               'closedOtherDescriptors': options['close_fds'] is True}, wait=True)
        altered = None
        try:
            if mode == 'no-fd':
                options['pass_fds'] = ()
            if mode in ('wrong-inode', 'separate-description'):
                altered = os.open(replacement, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
                environment[fd_key] = str(altered)
                options['pass_fds'] = (altered,)
            if mode == 'context-copy':
                environment[context_key] = replacement
            if mode in ('receipt', 'state'):
                name = '--maintenance' if mode == 'receipt' else '--state-dir'
                argv = list(argv)
                argv[argv.index(name) + 1] = replacement
            if mode == 'operation':
                argv = list(argv)
                argv[argv.index('state') + 1] = 'identity-reset'
                index = argv.index('--from-format')
                del argv[index:index + 2]
            if mode == 'retirement':
                argv = [*argv[:2], '-c', retirement_program, replacement, *argv[2:]]
            # Context-field faults are applied and independently observed by
            # the outer controller while this process waits at the barrier.
            child = self.module.Popen(argv, **options)
            state['child'] = child
            passed = None if altered is None else os.fstat(altered)
            frame({'phase': 'child', 'argv': list(argv),
                   'context': environment[context_key], 'passFds': list(options['pass_fds']),
                   'pid': child.pid,
                   'substituteInode': None if passed is None else [passed.st_dev, passed.st_ino]})
            return child
        finally:
            if altered is not None:
                os.close(altered)

def observe(frame_object, event, value):
    name = frame_object.f_code.co_name
    module = frame_object.f_globals.get('__name__')
    if module == 'arbol_builds.driver_process' and name == 'run_administrative':
        namespace = frame_object.f_globals
        if event == 'call':
            if mode == 'cached':
                os._exit(101)
            state['module'] = namespace['subprocess']
            namespace['subprocess'] = ObservedProcesses(state['module'])
        if event == 'return':
            namespace['subprocess'] = state.pop('module')
            child = state.get('child')
            if child is not None:
                stdout = None if value is None else value.stdout.hex()
                frame({'phase': 'child-return', 'pid': child.pid,
                       'reapedExit': child.returncode, 'acceptedStdoutHex': stdout},
                      wait=mode == 'before-ack')
    if (mode == 'before-ack' and module == 'arbol_builds.launcher' and name == 'write_all'
            and event == 'call' and frame_object.f_back.f_code.co_name == 'provider_entry'
            and frame_object.f_back.f_globals.get('__name__') == 'arbol_builds.driver_state'):
        local = frame_object.f_locals
        if local['fd'] != 1 or 'error' in json.loads(local['data']):
            os._exit(100)
        frame({'phase': 'before-ack', 'ackHex': local['data'].hex()}, wait=True)

sys.setprofile(observe)
with open(entry, 'rb') as packaged:
    source = compile(packaged.read(), entry, 'exec')
exec(source, vars(sys.modules['__main__']))
"""

_RETIREMENT_OBSERVER = """\
import json
import os
import sys

configuration, entry, *arguments = sys.argv[1:]
sys.argv[:] = [entry, *arguments]
sys.modules['__main__'].__file__ = entry
with open(configuration, 'rb') as data:
    config = json.load(data)
root = os.path.dirname(os.path.dirname(entry))
journal = config['journal']

def inspect_removal(event, args):
    if event != 'os.remove':
        return
    name, descriptor = os.fsdecode(args[0]), args[1]
    if name != journal:
        if name != 'identity-pending.json' or descriptor < 0:
            return
        named, held = os.lstat(os.path.dirname(journal)), os.fstat(descriptor)
        if (named.st_dev, named.st_ino) != (held.st_dev, held.st_ino):
            return
    frame = sys._getframe(1)
    sites = []
    while frame is not None and len(sites) < 32:
        source = frame.f_code.co_filename
        if source.startswith(root + os.sep):
            sites.append([source[len(root) + 1:], frame.f_code.co_name, frame.f_lineno])
        frame = frame.f_back
    def raw(path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as stream:
            content = stream.read(4097)
        if not 0 < len(content) <= 4096:
            raise RuntimeError('Unexpected journal observation size.')
        return content.hex()
    evidence = {'pid': os.getpid(), 'parentPid': os.getppid(), 'sites': sites,
                'journal': raw(journal), 'sidecar': raw(config['sidecar'])}
    descriptor = os.open(config['evidence'], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write((json.dumps(evidence, sort_keys=True, separators=(',', ':')) + '\\n').encode())
        output.flush()
        os.fsync(output.fileno())

sys.addaudithook(inspect_removal)
with open(entry, 'rb') as packaged:
    source = compile(packaged.read(), entry, 'exec')
exec(source, vars(sys.modules['__main__']))
"""


def _write_new(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


@dataclass(frozen=True)
class Execute:
    """Exact private inputs. Reuse the same instance for a same-attempt retry."""

    state: Path
    backup: Path
    operation: Operation
    source: Path | None = None
    subscription: str | None = None

    def arguments(self, build: str) -> dict[str, str]:
        require(self.operation in _OPERATIONS and (self.source is not None) == (self.operation == "restore")
                and (self.subscription is not None) == (self.operation == "identity-recover"),
                "Wrong arguments for the fixed administrative operation.")
        arguments = {"build": build, "state-dir": str(self.state), "operation": self.operation,
                     "backup": str(self.backup)}
        if self.source is not None:
            arguments["source"] = str(self.source)
        if self.subscription is not None:
            arguments["subscription"] = self.subscription
        return arguments

    def child_argv(self, prefix: list[str], receipt: Path) -> list[str]:
        common = [*prefix, "--state-dir", str(self.state), "state"]
        authority = ["--confirm-quiescent", "--maintenance", str(receipt)]
        if self.operation == "restore":
            return [*common, "restore", "--source", str(self.source), "--backup", str(self.backup), *authority]
        operation: list[str] = [self.operation]
        if self.operation == "upgrade":
            operation.extend(("--from-format", "1"))
        if self.operation == "identity-recover":
            operation.extend(("--subscription", str(self.subscription), "--retire"))
        return [*common, *operation, *authority, "--backup", str(self.backup)]

    def verify(self, controller: WholeCheckController) -> None:
        for path in (self.state, self.backup, self.source):
            if path is not None:
                require(path.is_relative_to(controller.workspace.fixture_root)
                        and path != controller.workspace.fixture_root, "Target escaped the private fixture.")
                physical_owned(path, directory=True)


def _snapshot(path: Path) -> Object:
    return {"root": directory_identity(path), "entries": tree_inventory(path)}


class _Boundary:
    """Only the verified direct provider can be signalled or waited here."""

    def __init__(self, child: OwnedChild, controller: WholeCheckController) -> None:
        self.child = child
        self.controller = controller
        self.until = time.monotonic() + 120

    def frame(self, phase: str) -> Object:
        stream = self.child.process.stderr
        assert stream is not None
        raw = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(stream, selectors.EVENT_READ)
            while len(raw) < 4096 and not raw.endswith(b"\n"):
                remaining = self.until - time.monotonic()
                require(remaining > 0 and bool(selector.select(remaining)), "Provider observation timed out.")
                byte = os.read(stream.fileno(), 1)
                require(bool(byte), "Provider closed before the observed boundary.")
                raw.extend(byte)
        value = document(bytes(raw))
        self.controller.evidence.write_bytes(f"boundary-{self.child.owner.pid}-{phase}.json", bytes(raw))
        require(value.get("phase") == phase, "Unexpected provider observation boundary.")
        return value

    def proceed(self) -> None:
        stream = self.child.process.stdin
        assert stream is not None
        require(os.write(stream.fileno(), b"+") == 1, "Provider observation permit was not delivered.")

    def collect(self) -> Captured:
        return self.controller._collect_owned(self.child, max(.001, self.until - time.monotonic()))

    def kill(self) -> Captured:
        require(self.child.owner.live(parent=os.getpid()), "Verified supervisor identity changed.")
        signal_verified(self.child.owner, signal.SIGKILL)
        result = self.collect()
        require(result.returncode == -signal.SIGKILL and self.child.reaped and not result.stdout and not result.stderr,
                "The owned supervisor did not die at the observed silent boundary.")
        return result

    def close(self) -> None:
        if not self.child.reaped:
            try:
                # EOF lets the fixed pre-spawn/pre-ACK barrier fail closed.
                # If a real child was launched, the supervisor's normal
                # cancellation path owns its wait. Do not kill its group.
                if self.child.process.stdin is not None:
                    self.child.process.stdin.close()
                self.child.request_stop()
                self.child.wait_owned(seconds=20)
                if self.child not in self.controller.reaped:
                    self.controller.reaped.append(self.child)
            finally:
                for stream in (self.child.process.stdout, self.child.process.stderr):
                    if stream is not None:
                        stream.close()


@dataclass(frozen=True)
class ExternalMaintenance:
    """WholeCheckController invokes the fixed case only after the full runner."""

    case_id: str
    component: str
    run: Callable[[WholeCheckController], None]

    def observe(self, controller: WholeCheckController) -> None:
        controller.require_finished_graph(self.component)
        self.run(controller)
        controller.require_finished_graph(self.component)


_CLAUDE_CREATE_WINDOWS = ("C1-prepared-durable", "C2-record-durable", "C3-sidecar-durable",
                          "C4-committed-durable", "C5-clear-durable")


@dataclass(frozen=True)
class ClaudeCreateSubject:
    """Original immutable evidence, captured before any external operation."""

    window: str
    command: str
    case: str
    root: Path
    root_identity: Object
    physical: Object
    owner: FileImage
    checkpoint: FileImage
    settlement: FileImage
    actor_result: FileImage
    ack: FileImage
    root_proof: FileImage
    guard: FileImage
    record: FileImage | None
    generation: str
    witness: str


def claude_create_subjects(controller: WholeCheckController, baseline: Baseline,
                           observer: TerminalSpanObservation) -> tuple[ClaudeCreateSubject, ...]:
    """Bind all ten genuine source-owned subjects before maintenance changes any."""
    component = "arbol-claude-driver"
    require(observer.component == component, "Create evidence belongs to another component.")
    H1SpanCompletion(observer, controller, baseline, component, observer.case).observe(controller)
    TerminalCloseClosure(observer, controller, baseline, component, observer.case).observe(controller)
    view = observer.terminal_view
    assert view is not None
    suite = view.h1.suite_context
    helpers = view.settled["helpers"]
    require(isinstance(helpers, list) and len(helpers) == 12,
            "The ten create actors, broker and final H1 actor have not all settled.")
    require(tuple(row["waitStatus"] for row in helpers) == (0, 1) * 5 + (0, 0),
            "The actual Claude helper wait order differs from the fixed schedule.")
    subjects: list[ClaudeCreateSubject] = []
    for index, (window, command) in enumerate((w, c) for w in _CLAUDE_CREATE_WINDOWS
                                               for c in ("continue", "abort-io")):
        prefix = f"terminal-helper-{index:04d}."
        context = document(view.images[prefix + "context"].raw)
        actor_raw = view.images[prefix + "result"].raw
        actor = document(actor_raw)
        case = actor.get("case")
        require(isinstance(case, str) and re.fullmatch(r"[0-9a-f]{32}", case, re.ASCII) is not None
                and case != observer.case and case not in {item.case for item in subjects}
                and context["invocation"] == suite["invocation"]
                and context["parent"] == {"writer": suite["writer"], **suite["process"]}
                and context["entry"] == "tests/identity_actor.py" and context["role"] == "helper"
                and actor == {"version": 1, "kind": "actor-result", "case": case, "action": "create-stop",
                              "outcome": "completed" if command == "continue" else "injected-failure"}
                and helpers[index]["waitStatus"] == (0 if command == "continue" else 1),
                "Original actor, ordered result or actual wait differs.")
        controller.workspace.verify(controller.evidence)
        root = controller.workspace.fixture_root / component / "create-publication" / suite["invocation"] / case
        for directory in (controller.workspace.registry.parent, controller.workspace.fixture_root,
                          controller.workspace.fixture_root / component,
                          controller.workspace.fixture_root / component / "create-publication", root.parent):
            physical_owned(directory, directory=True)
        root_identity = directory_identity(root)
        state, subscription = root / "state", root / "state" / "subscriptions" / "anthropic-2"
        physical_owned(state, directory=True)
        physical_owned(subscription, directory=True)
        owner = read_image(root / ".fixture-owner.json")
        require(document(owner.raw) == {"version": 1, "case": case, "component": component,
                "invocation": suite["invocation"], "parentWriter": suite["writer"],
                "payloadSha256": controller.scope.producer(component).digest}, "Original fixture owner differs.")
        checkpoint, settlement = (read_image(root / name) for name in
                                  ("create-checkpoint.json", "create-settlement.json"))
        actor_result, ack = read_image(root / "create-actor-result.json"), read_image(root / "helper-ack.json")
        require(actor_result.raw == actor_raw and ack.raw == view.images[prefix + "ack"].raw,
                "Original actor result or actual synchronous ACK changed.")
        before, after = document(checkpoint.raw), document(settlement.raw)
        require(before.get("window") == after.get("window") == window
                and before.get("command") == after.get("command") == command,
                "Original checkpoint and settlement identify another case.")
        position = index // 2 + 1
        journal, record, sidecar = (before.get(key) for key in ("journal", "record", "sidecar"))
        require((journal is not None) == (position <= 4) and (record is not None) == (position >= 2)
                and (sidecar is not None) == (position >= 3), "Original checkpoint window differs.")
        if journal is not None:
            require(isinstance(journal, dict) and journal.get("operation") == "create"
                    and journal.get("phase") == ("committed" if position == 4 else "prepared"),
                    "Original create journal is malformed.")
        witness = journal.get("witness") if isinstance(journal, dict) else (
            sidecar.get("witness") if isinstance(sidecar, dict) else None)
        require(valid_token(witness), "Original create witness is unavailable.")
        require(sidecar is None or sidecar == {"version": 1, "state": "active", "witness": witness},
                "Original checkpoint sidecar differs from the journal witness.")
        if command == "abort-io":
            require(all(after.get(key) == before.get(key) for key in ("journal", "record", "sidecar")),
                    "Actual injected failure did not retain its original checkpoint.")
        else:
            require(after.get("journal") is None and isinstance(after.get("record"), dict)
                    and after.get("sidecar") == {"version": 1, "state": "active", "witness": witness},
                    "Actual continued create did not finish with its original witness.")
        for name, key in (("identity-pending.json", "journal"), ("record.json", "record"),
                          ("identity.json", "sidecar")):
            path = subscription / name
            current = document(read_image(path).raw) if os.path.lexists(path) else None
            require(current == after.get(key), "Saved subject differs from its actual settled checkpoint.")
        proof, guard = read_image(state / "identity.json"), read_image(state / "identity.guard")
        state_identity = directory_identity(state)
        physical = {"case": {key: root_identity[key] for key in ("device", "inode")},
                    "state": {key: state_identity[key] for key in ("device", "inode")},
                    "guard": {"device": guard.device, "inode": guard.inode}}
        require(before.get("physical") == after.get("physical") == physical,
                "Original checkpoint, settlement and intake physical identities differ.")
        generation = document(proof.raw).get("generation")
        require(valid_token(generation) and read_image(state / "format").raw.strip() == b"2",
                "Original format-two generation is unavailable.")
        record_image = read_image(subscription / "record.json") if after.get("record") is not None else None
        assert isinstance(case, str) and isinstance(generation, str) and isinstance(witness, str)
        subjects.append(ClaudeCreateSubject(window, command, case, root, root_identity, physical, owner, checkpoint,
                                             settlement, actor_result, ack, proof, guard, record_image,
                                             generation, witness))
    view.recheck_files()
    controller.require_finished_graph(component)
    return tuple(subjects)


_PI_CREATE_WINDOWS = _CLAUDE_CREATE_WINDOWS


@dataclass(frozen=True)
class PiCreateSubject:
    """Original immutable evidence, captured before any external operation."""

    window: str
    command: str
    case: str
    root: Path
    root_identity: Object
    physical: Object
    owner: FileImage
    checkpoint: FileImage
    settlement: FileImage
    actor_result: FileImage
    ack: FileImage
    root_proof: FileImage
    guard: FileImage
    record: FileImage | None
    generation: str
    witness: str


def pi_create_subjects(controller: WholeCheckController, baseline: Baseline,
                           observer: TerminalSpanObservation) -> tuple[PiCreateSubject, ...]:
    """Bind all ten genuine source-owned subjects before maintenance changes any."""
    component = "arbol-pi-driver"
    require(observer.component == component, "Create evidence belongs to another component.")
    H1SpanCompletion(observer, controller, baseline, component, observer.case).observe(controller)
    TerminalCloseClosure(observer, controller, baseline, component, observer.case).observe(controller)
    view = observer.terminal_view
    assert view is not None
    suite = view.h1.suite_context
    helpers = view.settled["helpers"]
    require(isinstance(helpers, list) and len(helpers) == 11,
            "The ten create actors and final H1 actor have not all settled.")
    subjects: list[PiCreateSubject] = []
    for index, (window, command) in enumerate((w, c) for w in _PI_CREATE_WINDOWS
                                               for c in ("continue", "abort-io")):
        prefix = f"terminal-helper-{index:04d}."
        context = document(view.images[prefix + "context"].raw)
        actor_raw = view.images[prefix + "result"].raw
        actor = document(actor_raw)
        case = actor.get("case")
        require(isinstance(case, str) and re.fullmatch(r"[0-9a-f]{32}", case, re.ASCII) is not None
                and case != observer.case and case not in {item.case for item in subjects}
                and context["invocation"] == suite["invocation"]
                and context["parent"] == {"writer": suite["writer"], **suite["process"]}
                and context["entry"] == "tests/identity_actor.py" and context["role"] == "helper"
                and actor == {"version": 1, "kind": "actor-result", "case": case, "action": "create-stop",
                              "outcome": "completed" if command == "continue" else "injected-failure"}
                and helpers[index]["waitStatus"] == (0 if command == "continue" else 1),
                "Original actor, ordered result or actual wait differs.")
        controller.workspace.verify(controller.evidence)
        root = controller.workspace.fixture_root / component / "create-publication" / suite["invocation"] / case
        for directory in (controller.workspace.registry.parent, controller.workspace.fixture_root,
                          controller.workspace.fixture_root / component,
                          controller.workspace.fixture_root / component / "create-publication", root.parent):
            physical_owned(directory, directory=True)
        root_identity = directory_identity(root)
        state, subscription = root / "state", root / "state" / "subscriptions" / "zai-2"
        physical_owned(state, directory=True)
        physical_owned(subscription, directory=True)
        owner = read_image(root / ".fixture-owner.json")
        require(document(owner.raw) == {"version": 1, "case": case, "component": component,
                "invocation": suite["invocation"], "parentWriter": suite["writer"],
                "payloadSha256": controller.scope.producer(component).digest}, "Original fixture owner differs.")
        checkpoint, settlement = (read_image(root / name) for name in
                                  ("create-checkpoint.json", "create-settlement.json"))
        actor_result, ack = read_image(root / "create-actor-result.json"), read_image(root / "create-helper-ack.json")
        require(actor_result.raw == actor_raw and ack.raw == view.images[prefix + "ack"].raw,
                "Original actor result or actual synchronous ACK changed.")
        before, after = document(checkpoint.raw), document(settlement.raw)
        require(before.get("window") == after.get("window") == window
                and before.get("command") == after.get("command") == command,
                "Original checkpoint and settlement identify another case.")
        position = index // 2 + 1
        journal, record, sidecar = (before.get(key) for key in ("journal", "record", "sidecar"))
        require((journal is not None) == (position <= 4) and (record is not None) == (position >= 2)
                and (sidecar is not None) == (position >= 3), "Original checkpoint window differs.")
        if journal is not None:
            require(isinstance(journal, dict) and journal.get("operation") == "create"
                    and journal.get("phase") == ("committed" if position == 4 else "prepared"),
                    "Original create journal is malformed.")
        witness = journal.get("witness") if isinstance(journal, dict) else (
            sidecar.get("witness") if isinstance(sidecar, dict) else None)
        require(valid_token(witness), "Original create witness is unavailable.")
        require(sidecar is None or sidecar == {"version": 1, "state": "active", "witness": witness},
                "Original checkpoint sidecar differs from the journal witness.")
        if command == "abort-io":
            require(all(after.get(key) == before.get(key) for key in ("journal", "record", "sidecar")),
                    "Actual injected failure did not retain its original checkpoint.")
        else:
            require(after.get("journal") is None and isinstance(after.get("record"), dict)
                    and after.get("sidecar") == {"version": 1, "state": "active", "witness": witness},
                    "Actual continued create did not finish with its original witness.")
        for name, key in (("identity-pending.json", "journal"), ("record.json", "record"),
                          ("identity.json", "sidecar")):
            path = subscription / name
            current = document(read_image(path).raw) if os.path.lexists(path) else None
            require(current == after.get(key), "Saved subject differs from its actual settled checkpoint.")
        proof, guard = read_image(state / "identity.json"), read_image(state / "identity.guard")
        state_identity = directory_identity(state)
        physical = {"case": {key: root_identity[key] for key in ("device", "inode")},
                    "state": {key: state_identity[key] for key in ("device", "inode")},
                    "guard": {"device": guard.device, "inode": guard.inode}}
        require(before.get("physical") == after.get("physical") == physical,
                "Original checkpoint, settlement and intake physical identities differ.")
        generation = document(proof.raw).get("generation")
        require(valid_token(generation) and read_image(state / "format").raw.strip() == b"2",
                "Original format-two generation is unavailable.")
        record_image = read_image(subscription / "record.json") if after.get("record") is not None else None
        assert isinstance(case, str) and isinstance(generation, str) and isinstance(witness, str)
        subjects.append(PiCreateSubject(window, command, case, root, root_identity, physical, owner, checkpoint,
                                             settlement, actor_result, ack, proof, guard, record_image,
                                             generation, witness))
    view.recheck_files()
    controller.require_finished_graph(component)
    return tuple(subjects)


class Maintenance:
    def __init__(self, controller: WholeCheckController, component: str, environment: Mapping[str, str]) -> None:
        require(component in COMPONENTS, "Unknown Driver maintenance subject.")
        self.controller = controller
        self.component = component
        self.environment = without_authority(dict(environment))
        self.authority = Authority(controller.workspace.registry, component)
        self.payload = controller.scope.producer(component)
        self.session = str(uuid.uuid4())
        self.receipt = self.authority.folder / "maintenance.json"
        self.lock = self.authority.folder / "admission.lock"
        required = physical_owned(self.lock, directory=False)
        self.lock_identity = (required.st_dev, required.st_ino)
        self.folder = self.authority.folder / "sessions" / self.session
        self.result = self.folder / "result.json"

    def argv(self, command: str, arguments: Mapping[str, str], *, session: str | None = None) -> list[str]:
        argv = ["driver-state", command, "--registry-dir", str(self.controller.workspace.registry),
                "--component", self.component, "--session", self.session if session is None else session]
        for key, value in sorted(arguments.items()):
            argv.extend(("--" + key, value))
        return argv

    def capture(self, argv: list[str], name: str) -> Captured:
        child = OwnedChild(argv, cwd=self.controller.workspace.registry, environment=self.environment)
        result = self.controller._collect_owned(child, 120)
        self.record(name, child, result)
        return result

    def record(self, name: str, child: OwnedChild, result: Captured) -> None:
        argv = child.process.args
        assert isinstance(argv, list)
        self.controller.evidence.write(name + "-" + self.session + ".json", {
            "argv": argv if argv[2] != "-c" else [*argv[4:7], *argv[8:]],
            "observerSha256": digest(_OBSERVER.encode()) if argv[2] == "-c" else None,
            "retirementObserverSha256": digest(_RETIREMENT_OBSERVER.encode()) if argv[2] == "-c" and argv[5] == "retirement" else None,
            "process": result.owner.object(), "reaped": child.reaped, "exit": result.returncode,
            "stdoutHex": result.stdout.hex(), "stderrHex": result.stderr.hex(),
        })

    def call(self, command: str, arguments: Mapping[str, str]) -> Object:
        return self.controller.maintenance(self.component, command, session=self.session, arguments=arguments,
                                           environment=self.environment)

    def lease(self, *, blocked: bool) -> None:
        fd = os.open(self.lock, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            actual = os.fstat(fd)
            named = physical_owned(self.lock, directory=False)
            require((actual.st_dev, actual.st_ino) == (named.st_dev, named.st_ino) == self.lock_identity,
                    "The original component lease inode changed.")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                require(blocked, "Original component EX is still held.")
            else:
                require(not blocked, "The actual supervisor does not exclude an independent EX.")
        finally:
            os.close(fd)

    def open(self) -> Object:
        self.controller.require_finished_graph(self.component)
        before = self.authority.read("control")
        require(before["phase"] == "normal" and before["session"] is None, "Maintenance requires a normal subject.")
        require(self.call("begin", {}).get("phase") == "draining", "Actual begin did not close normal admission.")
        self.drain()
        closed = self.authority.read("control")
        require(closed == {**before, "phase": "exclusive", "session": self.session},
                "Drain did not retain the original epoch and exact session.")
        return closed

    def drain(self) -> None:
        require(self.call("drain", {}).get("phase") == "exclusive", "Actual drain did not reach exclusive.")
        self.lease(blocked=False)

    def image(self, request: Execute, *, unsafe_parent: Path | None = None) -> Object:
        state = _snapshot(request.state) if unsafe_parent is None else _unsafe_parent_image(request.state, unsafe_parent)
        return {"control": self.authority.read("control"), "receipt": read_image(self.receipt).raw.hex(),
                "authority": _snapshot(self.authority.folder), "state": state,
                "backup": _snapshot(request.backup),
                "source": _snapshot(request.source) if request.source is not None else None}

    def preserve(self, name: str, request: Execute, *, unsafe_parent: Path | None = None) -> Object:
        value = self.image(request, unsafe_parent=unsafe_parent)
        self.controller.evidence.write(name + "-" + self.session + ".json", value)
        return value

    def _verify_spawn(self, request: Execute, frame: Object) -> Path:
        original = physical_owned(self.lock, directory=False)
        require(frame["argv"] == request.child_argv(list(self.payload.prefix), self.receipt)
                and frame["normalAuthorityCleared"] is True and frame["closedOtherDescriptors"] is True
                and (frame["device"], frame["inode"]) == self.lock_identity
                and frame["mode"] == 0o600 and frame["uid"] == original.st_uid,
                "Actual child argv or inherited EX descriptor differs from the exact operation contract.")
        pending = document(read_image(self.folder / "operation.json").raw)
        validate("operation", pending)
        attempt = str(pending["attempt"])
        context_path = self.folder / "contexts" / (attempt + ".json")
        require(frame["context"] == str(context_path), "Child did not get its own immutable context path.")
        raw = read_image(context_path).raw
        context = document(raw)
        validate("context", context)
        receipt = read_image(self.receipt).raw
        control = self.authority.read("control")
        require(document(receipt) == {"version": 1, "kind": "driver-state-maintenance", "component": self.component,
                                      "session": self.session, "epoch": control["epoch"], "phase": "exclusive",
                                      "gateSha256": self.controller.scope.gate.digest},
                "Provider did not use the exact original closed receipt.")
        expected = {"component": self.component, "session": self.session, "epoch": control["epoch"],
                    "gateSha256": self.controller.scope.gate.digest, "payloadSha256": self.payload.digest,
                    "stateDirectory": str(request.state), "operation": request.operation, "receiptSha256": digest(receipt),
                    "registry": str(self.controller.workspace.registry),
                    "acceptanceSha256": self.authority.read("qualification")["acceptanceSha256"]}
        if request.subscription is not None:
            expected["subscription"] = request.subscription
        require(control["phase"] == "exclusive" and control["session"] == self.session
                and all(context[key] == value for key, value in expected.items())
                and pending == {**context, "phase": "pending", "sourceSha256": pending["sourceSha256"],
                                "backupSha256": pending["backupSha256"]},
                "Actual pending operation does not bind the original receipt, tuple and target.")
        request_raw = read_image(context_path.with_name(attempt + ".request.json")).raw
        binding = document(request_raw)
        request_binding(binding, context)
        require(binding["contextSha256"] == digest(raw) and binding["build"] == self.payload.build
                and binding["backup"] == str(request.backup)
                and binding["source"] == (None if request.source is None else str(request.source)),
                "Provider request does not bind the actual context and immutable argument inputs.")
        self.lease(blocked=True)
        self.controller.evidence.write("handoff-" + self.session + "-" + str(uuid.uuid4()) + ".json",
                                       {"contextHex": raw.hex(), "requestHex": request_raw.hex(),
                                        "receiptHex": receipt.hex(), "control": control})
        return context_path

    def _verify_child(self, frame: Object, ended: Object, spawn: Object, mode: Mode, replacement: str) -> None:
        argv = list(spawn["argv"])
        passed = [spawn["fd"]]
        context = spawn["context"]
        if mode == "no-fd":
            passed = []
        if mode in ("wrong-inode", "separate-description"):
            info = physical_owned(Path(replacement), directory=False)
            require(len(frame["passFds"]) == 1 and frame["passFds"] != passed
                    and type(frame["passFds"][0]) is int and frame["passFds"][0] >= 3
                    and frame["substituteInode"] == [info.st_dev, info.st_ino]
                    and ((info.st_dev, info.st_ino) == self.lock_identity) == (mode == "separate-description"),
                    "Actual producer did not inherit the separate fault descriptor.")
            passed = frame["passFds"]
        else:
            require(frame["substituteInode"] is None, "An unrelated descriptor was substituted.")
        if mode == "context-copy":
            context = replacement
        if mode in ("receipt", "state"):
            option = "--maintenance" if mode == "receipt" else "--state-dir"
            argv[argv.index(option) + 1] = replacement
        if mode == "operation":
            argv[argv.index("state") + 1] = "identity-reset"
            index = argv.index("--from-format")
            del argv[index:index + 2]
        if mode == "retirement":
            argv = [*argv[:2], "-c", _RETIREMENT_OBSERVER, replacement, *argv[2:]]
        require(frame["argv"] == argv and frame["passFds"] == passed and frame["context"] == context
                and type(frame["pid"]) is int and frame["pid"] > 0 and ended["pid"] == frame["pid"]
                and type(ended["reapedExit"]) is int,
                "The fixed Popen boundary and the real reaped child disagree.")

    def _fault_input(self, request: Execute, mode: Mode) -> str:
        if mode == "separate-description":
            return str(self.lock)
        if mode not in ("state", "receipt", "context-copy", "wrong-inode", *_CONTEXT_FAULTS):
            return ""
        trap = request.state.parent / ("observation-" + self.session)
        require(trap.is_relative_to(self.controller.workspace.fixture_root) and trap != self.controller.workspace.fixture_root,
                "Fault input escaped the disposable subject.")
        trap.mkdir(mode=0o700)
        if mode == "state":
            return os.fspath(trap)
        path = trap / "input.json"
        if mode == "receipt":
            _write_new(path, read_image(self.receipt).raw)
        if mode == "wrong-inode":
            _write_new(path, b"")
        return str(path)

    def execute_observed(self, request: Execute, mode: Mode, *, unsafe_parent: Path | None = None,
                         retirement: Path | None = None) -> Object:
        request.verify(self.controller)
        self.controller.require_finished_graph(self.component)
        require(mode != "operation" or request.operation == "upgrade", "Operation substitution needs the exact upgrade row.")
        require((unsafe_parent is not None) == (mode == "unsafe-source-parent"), "Unsafe parent observation scope differs.")
        require((retirement is not None) == (mode == "retirement"), "Retirement observation scope differs.")
        self.controller.scope.recheck()
        replacement = self._fault_input(request, mode)
        if retirement is not None:
            require(retirement.is_relative_to(self.controller.workspace.fixture_root) and request.operation == "identity-recover",
                    "Retirement observer escaped its exact recovery fixture.")
            physical_owned(retirement, directory=False)
            replacement = str(retirement)
        provider = self.controller.scope.gate.provider
        interpreter, isolation, entry = provider.prefix
        child = OwnedChild([interpreter, isolation, "-c", _OBSERVER, entry, mode, replacement,
                            _RETIREMENT_OBSERVER if retirement is not None else "",
                            *self.argv("execute", request.arguments(self.payload.build))],
                           cwd=self.controller.workspace.registry, environment=self.environment)
        boundary = _Boundary(child, self.controller)
        try:
            if mode == "cached":
                captured = boundary.collect()
                self.record(mode, child, captured)
                require(captured.returncode == 0 and not captured.stderr
                        and document(captured.stdout) == self._execute_reply(),
                        "Completed-attempt retry called the administrative child or refused.")
                self.lease(blocked=False)
                return self.verify_result(request)
            spawn = boundary.frame("spawn")
            context_path = self._verify_spawn(request, spawn)
            before = self.preserve("pre-child-" + mode, request, unsafe_parent=unsafe_parent)
            if mode == "before-spawn":
                captured = boundary.kill()
                self.record(mode, child, captured)
                require(self.image(request) == before and not os.path.lexists(self.result),
                        "Supervisor death before spawn changed the pending attempt or target.")
                self.lease(blocked=False)
                return document(read_image(context_path).raw)

            original: Path | None = None
            if mode == "context-copy":
                _write_new(Path(replacement), read_image(context_path).raw)
            if mode in _CONTEXT_FAULTS:
                original = Path(replacement)
                context = document(read_image(context_path).raw)
                changed = "payloadSha256" if mode == "payload" else mode
                prior = context[changed]
                context[changed] = ("0" if prior[0] != "0" else "1") + prior[1:]
                os.rename(context_path, original)
                _write_new(context_path, canonical(context))
                sync_directory(original.parent)
                self.controller.evidence.write_bytes("substitution-" + self.session + ".json", read_image(context_path).raw)

            try:
                boundary.proceed()
                launched = boundary.frame("child")
                ended = boundary.frame("child-return")
                self._verify_child(launched, ended, spawn, mode, replacement)
                if mode == "before-ack":
                    require(ended["reapedExit"] == 0 and ended["acceptedStdoutHex"] is not None,
                            "Lost ACK did not follow the genuine reaped administrative child.")
                    marker = read_image(request.state / "identity-maintenance.json")
                    archive = read_image(request.backup / "before" / "manifest.json", limit=_MANIFEST_LIMIT)
                    attempt = document(read_image(context_path).raw)["attempt"]
                    marker_value = document(marker.raw)
                    require(marker_value["attempt"] == attempt and marker_value["phase"] == "complete"
                            and marker_value["backupSha256"] == archive.sha256
                            and os.path.lexists(self.folder / "operation.json") and not os.path.lexists(self.result),
                            "The child did not complete its archive and marker before the provider's result.")
                    self.lease(blocked=True)
                    self.preserve("child-finished-before-provider-settlement", request)
                    boundary.proceed()
                    ack = boundary.frame("before-ack")
                    settled = self.preserve("before-lost-ack", request)
                    require(self._execute_reply() == document(bytes.fromhex(ack["ackHex"])),
                            "The intercepted ACK does not reference the actual durable result.")
                    require(marker == read_image(marker.path) and archive == read_image(archive.path, limit=_MANIFEST_LIMIT),
                            "Provider settlement rewrote the child's completed marker or before archive.")
                    self.lease(blocked=False)
                    captured = boundary.kill()
                    self.record(mode, child, captured)
                    require(self.image(request) == settled, "Lost ACK changed already durable settlement.")
                    result = self.verify_result(request)
                    self._verify_child_output(ended, result)
                    return result
                captured = boundary.collect()
                self.record(mode, child, captured)
            finally:
                if original is not None and child.reaped:
                    # Keep the original inode and retain the exact fault bytes
                    # separately. Never restore authority under a live child.
                    os.rename(context_path, original.with_name("substituted.json"))
                    os.rename(original, context_path)
                    sync_directory(context_path.parent)
                    sync_directory(original.parent)

            self.lease(blocked=False)
            if mode in ("observe", "retirement"):
                require(captured.returncode == 0 and not captured.stderr and ended["reapedExit"] == 0
                        and document(captured.stdout) == self._execute_reply(),
                        "Exact packaged provider/child dispatch did not complete.")
                result = self.verify_result(request)
                self._verify_child_output(ended, result)
                if retirement is not None:
                    config = document(read_image(retirement).raw)
                    frame = document(read_image(Path(config["evidence"])).raw)
                    require(frame["pid"] == launched["pid"] and frame["parentPid"] == captured.owner.pid,
                            "Journal unlink observation does not belong to the actual reaped administrative child.")
                return result
            require(captured.returncode == 1 and not captured.stderr and document(captured.stdout) == _PROVIDER_REFUSAL
                    and ended["reapedExit"] == 1 and ended["acceptedStdoutHex"] is None,
                    "Substituted input was not refused by the actual child and packaged supervisor.")
            require(self.image(request, unsafe_parent=unsafe_parent) == before and not os.path.lexists(self.result),
                    "Rejected child changed the pending attempt, custody, State or before archive.")
            if mode == "state":
                require(not _snapshot(Path(replacement))["entries"], "The rejected substitute State was modified.")
            self.preserve("after-refusal-" + mode, request, unsafe_parent=unsafe_parent)
            return document(read_image(context_path).raw)
        finally:
            boundary.close()

    def _execute_reply(self) -> Object:
        return {"version": 1, "component": self.component, "session": self.session,
                "phase": "exclusive", "result": str(self.result)}

    def _verify_child_output(self, ended: Object, result: Object) -> None:
        output = document(bytes.fromhex(ended["acceptedStdoutHex"]))
        fields = ("component", "session", "epoch", "operation", "attempt", "payloadSha256", "stateDirectorySha256")
        maintenance = {key: result[key] for key in fields}
        if "subscription" in result:
            maintenance["subscription"] = result["subscription"]
        require(output == {"version": 1, "format": 2, "generation": result["generation"], "maintenance": maintenance},
                "Actual child result does not settle its exact immutable context.")

    def verify_result(self, request: Execute) -> Object:
        raw = read_image(self.result).raw
        result = document(raw)
        validate("result", result)
        history = self.folder / "attempts" / result["attempt"]
        context = document(read_image(history / "context.json").raw)
        marker_raw = read_image(request.state / "identity-maintenance.json").raw
        marker = document(marker_raw)
        before = read_image(request.backup / "before" / "manifest.json", limit=1024 * 1024)
        fields = ("component", "session", "epoch", "operation", "attempt", "payloadSha256", "generation")
        require(result["component"] == self.component and result["session"] == self.session
                and result["epoch"] == self.authority.read("control")["epoch"] and result["operation"] == request.operation
                and result["payloadSha256"] == self.payload.digest and result["status"] == "complete" and result["format"] == 2
                and result["stateDirectorySha256"] == digest(os.fsencode(request.state))
                and result.get("subscription") == request.subscription and result["backupSha256"] == before.sha256
                and all(context[key] == result[key] == marker[key] for key in fields)
                and marker["phase"] == "complete" and marker["backupSha256"] == before.sha256
                and document(read_image(request.state / "identity.json").raw)["generation"] == result["generation"]
                and read_image(history / "result.json").raw == raw and read_image(history / "marker.json").raw == marker_raw
                and not os.path.lexists(self.folder / "operation.json"),
                "Durable result, immutable before archive, local marker and exact attempt history disagree.")
        self.controller.evidence.write("result-" + self.session + "-" + str(uuid.uuid4()) + ".json", {
            "resultHex": raw.hex(), "markerHex": marker_raw.hex(), "beforeManifest": before.evidence(),
        })
        return result

    def finish(self, request: Execute, result: Object) -> None:
        new = self.call("finish", {"result": str(self.result)})
        control = self.authority.read("control")
        history = self.folder / "attempts" / result["attempt"]
        journal = document(read_image(history / "finish.json").raw)
        require(new.get("phase") == "normal"
                and control == {"version": 1, "phase": "normal", "session": None, "epoch": journal["nextEpoch"]}
                and control["epoch"] != result["epoch"] and journal["phase"] == "complete"
                and journal["resultSha256"] == read_image(self.result).sha256
                and read_image(history / "finished-marker.json").raw == read_image(history / "marker.json").raw
                and not os.path.lexists(request.state / "identity-maintenance.json"),
                "Finish did not archive the exact marker and reopen at its own fresh epoch.")
        self.lease(blocked=False)

    def refuse_finish(self, request: Execute, *, session: str, result: Path, name: str) -> None:
        self.controller.require_finished_graph(self.component)
        before = self.preserve(name + "-before", request)
        captured = self.capture([*self.controller.scope.gate.provider.prefix,
                                 *self.argv("finish", {"result": str(result)}, session=session)], name)
        require(captured.returncode == 1 and not captured.stderr and document(captured.stdout) == _PROVIDER_REFUSAL
                and before == self.image(request), "Stale/copied result changed closed control or target.")
        self.lease(blocked=False)

    def refuse_replaced_result(self, request: Execute, old: Path) -> None:
        """Substitute old bytes at the exact active pathname, retaining both inodes."""
        self.controller.require_finished_graph(self.component)
        current = self.preserve("before-result-substitution", request)
        saved = request.backup.parent / ("original-result-" + self.session + ".json")
        rejected = saved.with_name("rejected-result-" + self.session + ".json")
        require(not os.path.lexists(saved) and not os.path.lexists(rejected), "Result evidence path already exists.")
        raw = read_image(old).raw
        require(raw != read_image(self.result).raw, "Stale result must be a distinct actual result.")
        os.rename(self.result, saved)
        _write_new(self.result, raw)
        sync_directory(saved.parent)
        # If the invocation cannot be settled, leave both original and
        # substitute available. Never restore a result under a live provider.
        self.refuse_finish(request, session=self.session, result=self.result, name="replaced-result-refusal")
        os.rename(self.result, rejected)
        os.rename(saved, self.result)
        sync_directory(self.result.parent)
        sync_directory(saved.parent)
        require(self.image(request) == current and read_image(rejected).raw == raw,
                "Original active result or captured substituted bytes were lost.")

    def admitted_proof(self, state: Path, subscription: str, *, expectation: str | None = None,
                       expected_error: Literal["in_use", "internal"] | None = None, name: str) -> Object:
        self.controller.require_finished_graph(self.component)
        tail = ["--state-dir", str(state), "subscriptions", "identity", subscription]
        if expectation is not None:
            tail.extend(("--expect", expectation))
        capture = self.capture(self.controller.fixed_argv(self.component, self.payload.build, "driver", tail), name)
        require(capture.returncode == (0 if expected_error is None else 1) and not capture.stderr,
                "Fresh admitted identity operation returned the wrong status.")
        self.controller.require_finished_graph(self.component)
        with self.authority.mutex():
            graph = reconcile(self.authority, persist_unknown=False, candidate=self.controller.scope)
            providers = [row for row in graph.writers if row["parent"] is None and row["phase"] == "terminal"
                         and (row["pid"], row["startedAt"]) == (capture.owner.pid, capture.owner.started_at)]
            require(graph.resolved and len(providers) == 1, "Proof lacks its actual terminal provider.")
            parent = providers[0]
            mains = [row for row in graph.handoffs if row["invocation"] == parent["invocation"]
                     and row["parent"] == parent["writer"] and row["role"] == "main" and row["phase"] == "accepted"
                     and row["entry"] == self.payload.descriptor["entry"]]
            require(len(mains) == 1, "Proof lacks its actual accepted MAIN route.")
        result = document(capture.stdout)
        if expected_error is not None:
            require(set(result) == {"error"} and isinstance(result["error"], dict)
                    and result["error"].get("code") == expected_error, "The admitted proof returned the wrong refusal.")
            return result
        require(result.get("subscription") == subscription and type(result.get("version")) is int
                and result.get("version") == 1 and result.get("driver") == self.component.removeprefix("arbol-").removesuffix("-driver")
                and valid_token(result.get("generation")) and valid_token(result.get("witness")),
                "Fresh proven identity is malformed or belongs to another Subscription.")
        return result

    def claude_create_refusal(self, state: Path, *, absent: bool) -> None:
        """Capture one of the two fixed ordinary routes in the reviewed create walk.

        The caller still owns all before/after state and original-subject checks.
        No caller-supplied command, subscription, error code or success flag is
        accepted by this narrow observation.
        """
        require(self.component == "arbol-claude-driver", "Create refusal belongs to Claude only.")
        self.controller.require_finished_graph(self.component)
        tail = ["--state-dir", str(state), "subscriptions"]
        if absent:
            tail.extend(("identity", "anthropic-2"))
        else:
            tail.extend(("create", "--family", "anthropic", "--id", "anthropic-2",
                         "--label", "ABR-38 duplicate create"))
        capture = self.capture(self.controller.fixed_argv(self.component, self.payload.build, "driver", tail),
                               "create-absence" if absent else "create-settlement")
        require(capture.returncode == 1 and not capture.stderr,
                "The actual ordinary create observation did not refuse cleanly.")
        result = document(capture.stdout)
        require(set(result) == {"error"} and isinstance(result["error"], dict)
                and result["error"].get("code") == ("not_found" if absent else "in_use"),
                "The actual ordinary create refusal differs from the fixed route.")
        self.controller.require_finished_graph(self.component)
        with self.authority.mutex():
            graph = reconcile(self.authority, persist_unknown=False, candidate=self.controller.scope)
            parents = [row for row in graph.writers if row["parent"] is None and row["phase"] == "terminal"
                       and (row["pid"], row["startedAt"]) == (capture.owner.pid, capture.owner.started_at)]
            require(graph.resolved and len(parents) == 1, "The actual refusal provider did not finish.")
            parent = parents[0]
            handoffs = [row for row in graph.handoffs if row["invocation"] == parent["invocation"]
                        and row["parent"] == parent["writer"] and row["role"] == "main"
                        and row["phase"] == "accepted" and row["entry"] == self.payload.descriptor["entry"]]
            require(len(handoffs) == 1 and sum(row["invocation"] == parent["invocation"]
                    and row["writer"] == handoffs[0]["child"] and row["parent"] == parent["writer"]
                    and row["phase"] == "terminal" for row in graph.writers) == 1,
                    "The actual refusal MAIN did not finish through its accepted handoff.")


    def pi_create_refusal(self, state: Path, *, absent: bool) -> None:
        """Capture one of the two fixed ordinary routes in the reviewed create walk.

        The caller still owns all before/after state and original-subject checks.
        No caller-supplied command, subscription, error code or success flag is
        accepted by this narrow observation.
        """
        require(self.component == "arbol-pi-driver", "Create refusal belongs to Pi only.")
        self.controller.require_finished_graph(self.component)
        tail = ["--state-dir", str(state), "subscriptions"]
        if absent:
            tail.extend(("identity", "zai-2"))
        else:
            tail.extend(("create", "--family", "zai", "--id", "zai-2",
                         "--label", "ABR-38 duplicate create"))
        capture = self.capture(self.controller.fixed_argv(self.component, self.payload.build, "driver", tail),
                               "create-absence" if absent else "create-settlement")
        require(capture.returncode == 1 and not capture.stderr,
                "The actual ordinary create observation did not refuse cleanly.")
        result = document(capture.stdout)
        require(set(result) == {"error"} and isinstance(result["error"], dict)
                and result["error"].get("code") == ("not_found" if absent else "in_use"),
                "The actual ordinary create refusal differs from the fixed route.")
        self.controller.require_finished_graph(self.component)
        with self.authority.mutex():
            graph = reconcile(self.authority, persist_unknown=False, candidate=self.controller.scope)
            parents = [row for row in graph.writers if row["parent"] is None and row["phase"] == "terminal"
                       and (row["pid"], row["startedAt"]) == (capture.owner.pid, capture.owner.started_at)]
            require(graph.resolved and len(parents) == 1, "The actual refusal provider did not finish.")
            parent = parents[0]
            handoffs = [row for row in graph.handoffs if row["invocation"] == parent["invocation"]
                        and row["parent"] == parent["writer"] and row["role"] == "main"
                        and row["phase"] == "accepted" and row["entry"] == self.payload.descriptor["entry"]]
            require(len(handoffs) == 1 and sum(row["invocation"] == parent["invocation"]
                    and row["writer"] == handoffs[0]["child"] and row["parent"] == parent["writer"]
                    and row["phase"] == "terminal" for row in graph.writers) == 1,
                    "The actual refusal MAIN did not finish through its accepted handoff.")


def maintenance_child_substitution(subject: Maintenance, request: Execute, fault: Fault) -> None:
    """Use a separate disposable subject for each selected child substitution."""
    subject.open()
    pending = subject.execute_observed(request, fault)
    result = subject.execute_observed(request, "observe")
    require(result["attempt"] == pending["attempt"] and result["generation"] == pending["generation"],
            "The correct live handoff did not resume the same refused attempt.")
    subject.finish(request, result)


def maintenance_exact_dispatch(subject: Maintenance, request: Execute) -> Object:
    """Used for each exact row with its own valid source/state fixture."""
    subject.open()
    result = subject.execute_observed(request, "observe")
    subject.finish(request, result)
    return result


class ClaudeCreateWalk:
    """Shared fixed original-subject capture for the two deferred create cases."""

    def __init__(self, controller: WholeCheckController, baseline: Baseline,
                 observer: TerminalSpanObservation, environment: Mapping[str, str]) -> None:
        self.controller, self.baseline, self.observer = controller, baseline, observer
        self.environment = without_authority(dict(environment))
        self.subjects: tuple[ClaudeCreateSubject, ...] | None = None
        self.custody: dict[str, FileImage] = {}
        self.archive: ArchiveWitness | None = None
        self.archive_root: Path | None = None
        self.sessions: set[str] = set()
        self.attempted: set[str] = set()
        self.finished: set[str] = set()

    def prepare(self) -> tuple[ClaudeCreateSubject, ...]:
        require({"H1-span-completion", "terminal-close-closure"} <= self.controller.finished_external,
                "The controller has not completed its original H1 and terminal duties in order.")
        if self.subjects is None:
            self.subjects = claude_create_subjects(self.controller, self.baseline, self.observer)
            view = self.observer.terminal_view
            assert view is not None
            suite = view.h1.suite_context
            authority = Authority(self.controller.workspace.registry, "arbol-claude-driver")
            contexts = [suite]
            for index, row in enumerate(view.settled["helpers"]):
                if index == 10:
                    # Broker registration context remains at its original private
                    # authority; the bounded report contains only its digest.
                    raw = read_image(authority.folder / "handoffs" / (row["handoff"] + ".context.json")).raw
                    require(digest(raw) == row["contextSha256"], "Broker private context digest changed.")
                    require(document(raw)["entry"] == "bin/metadata-helper.py",
                            "The scheduled broker is not the declared metadata helper.")
                else:
                    raw = view.images[f"terminal-helper-{index:04d}.context"].raw
                contexts.append(document(raw))
            for index, context in enumerate(contexts):
                writer = "writers/" + context["invocation"] + "/" + context["writer"] + ".json"
                handoff = "handoffs/" + context["handoff"] + ".json"
                context_file = "handoffs/" + context["handoff"] + ".context.json"
                for relative in (writer, handoff, context_file):
                    require(relative not in self.custody, "Original create custody has duplicate identities.")
                    self.custody[relative] = read_image(authority.folder / relative)
                if index == 11:
                    require(digest(self.custody[context_file].raw) == view.settled["helpers"][10]["contextSha256"],
                            "Original private broker context differs from the observed digest.")
                else:
                    require(self.custody[context_file].raw == (view.images[f"terminal-helper-{index - 1:04d}.context"].raw
                            if index else canonical(suite)), "Original custody context differs from the observed Suite.")
                if index:
                    require(self.custody[writer].raw == view.images[f"terminal-helper-{index - 1:04d}.terminal"].raw,
                            "Original helper terminal bytes differ from the observed witness.")
            require(len(self.custody) == 39, "Original Suite and all twelve helper records are incomplete.")
        return self.subjects

    def archived(self, subject: Maintenance) -> None:
        """Bind the first actual drain's rename and preserve its exact later image."""
        observed = self.controller.last_administration
        require(observed is not None and observed.command == "drain" and observed.session == subject.session
                and observed.component == subject.component, "The actual subject drain is unavailable.")
        assert observed is not None
        witness = observed.archive_witness
        if self.archive is None:
            require(witness is not None, "The first drain did not preserve the original terminal trees.")
            assert witness is not None
            witness.verify(self.controller.workspace)
            additions = set(witness.after.entries) - set(witness.before.entries)
            roots = {name.split("/", 1)[0] for name in additions if name.startswith("custody-")}
            require(len(roots) == 1, "First drain has no unique actual custody destination.")
            root_name = next(iter(roots))
            for relative, image in self.custody.items():
                tree, _, child = relative.partition("/")
                source = witness.sources[tree].entries.get(child)
                require(source is not None and source.get("type") == "file"
                        and source.get("sha256") == image.sha256 and source.get("device") == image.device
                        and source.get("inode") == image.inode and source.get("mode") == image.mode,
                        "First drain did not archive the exact original source inode and bytes.")
                assert source is not None
                moved = witness.after.entries.get(root_name + "/" + relative)
                require(moved == {**source, "path": root_name + "/" + relative},
                        "Actual archive destination differs from the original custody image.")
            self.archive, self.archive_root = witness, subject.authority.folder / "archive" / root_name
        self.check_custody()

    def check_custody(self) -> None:
        authority = Authority(self.controller.workspace.registry, "arbol-claude-driver")
        base = authority.folder if self.archive is None else self.archive_root
        require(base is not None and len(self.custody) == 39, "Original custody is unavailable.")
        assert base is not None
        if self.archive is not None:
            self.archive.verify(self.controller.workspace)
            current = ArchiveImage.capture(authority.folder / "archive")
            require(current.root == self.archive.after.root
                    and all(current.entries.get(name) == row for name, row in self.archive.after.entries.items()),
                    "The first real archive or its original evidence changed during a later drain.")
        for relative, original in self.custody.items():
            current_image = read_image(base / relative)
            require((current_image.raw, current_image.device, current_image.inode, current_image.mode) ==
                    (original.raw, original.device, original.inode, original.mode),
                    "Original Suite/helper writer, accepted handoff or context changed.")

    def unchanged(self, item: ClaudeCreateSubject) -> None:
        self.controller.workspace.verify(self.controller.evidence)
        view = self.observer.terminal_view
        require(view is not None, "Original terminal observation is unavailable.")
        assert view is not None
        view.recheck_files()
        self.check_custody()
        require(directory_identity(item.root) == item.root_identity
                and {key: directory_identity(item.root / "state")[key] for key in ("device", "inode")}
                == item.physical["state"]
                and read_image(item.root / ".fixture-owner.json") == item.owner
                and read_image(item.root / "create-checkpoint.json") == item.checkpoint
                and read_image(item.root / "create-settlement.json") == item.settlement
                and read_image(item.root / "create-actor-result.json") == item.actor_result
                and read_image(item.root / "helper-ack.json") == item.ack
                and read_image(item.root / "state" / "identity.json") == item.root_proof
                and read_image(item.root / "state" / "identity.guard") == item.guard,
                "Original fixture, root, guard or immutable actor evidence changed.")
        record_path = item.root / "state" / "subscriptions" / "anthropic-2" / "record.json"
        if item.record is None:
            require(not os.path.lexists(record_path), "A record appeared in the absent create subject.")
        else:
            require(read_image(record_path) == item.record, "Original create record changed.")

    def metadata(self, item: ClaudeCreateSubject, *, state: str) -> None:
        target = item.root / "state" / "subscriptions" / "anthropic-2"
        pending, sidecar = target / "identity-pending.json", target / "identity.json"
        require(not os.path.lexists(pending) and document(read_image(sidecar).raw) == {
            "version": 1, "state": state, "witness": item.witness},
            "The original witness did not reach its exact required terminal state.")
        self.unchanged(item)

    def execute(self, item: ClaudeCreateSubject, *, absence: bool) -> None:
        require({"H1-span-completion", "terminal-close-closure"} <= self.controller.finished_external
                and self.subjects is not None and any(item is original for original in self.subjects),
                "Maintenance requires the completed outer duties and the bound original subject.")
        self.unchanged(item)
        subject = Maintenance(self.controller, "arbol-claude-driver", self.environment)
        require(subject.session not in self.sessions, "Two original subjects share a maintenance session.")
        self.sessions.add(subject.session)
        backup = self.controller.workspace.fixture_root / ("claude-create-" + item.case + "-" + subject.session)
        backup.mkdir(mode=0o700)
        sync_directory(backup.parent)
        request = Execute(item.root / "state", backup, "identity-recover" if absence else "upgrade",
                          subscription="anthropic-2" if absence else None)
        # Check all paths before begin; an unaccepted fixture path cannot leave
        # a component draining or be bypassed by a different subject.
        request.verify(self.controller)
        if absence:
            require(item.window == _CLAUDE_CREATE_WINDOWS[0] and item.command == "abort-io"
                    and item.record is None, "Only prepared-absent C1 uses targeted retirement.")
            subject.open()
            self.archived(subject)
            self.unchanged(item)
            operation_before = create_operation_before(item, request, absence=absence)
            result = subject.execute_observed(request, "observe")
            verify_create_operation_before(subject, request, result, operation_before)
            self.unchanged(item)
            require(result["generation"] == item.generation, "Targeted retirement changed root generation.")
            subject.finish(request, result)
            self.metadata(item, state="retired")
            subject.claude_create_refusal(request.state, absent=True)
            self.metadata(item, state="retired")
        else:
            require(item.record is not None, "A present-create walk requires its original record.")
            if item.command == "abort-io" and item.window in _CLAUDE_CREATE_WINDOWS[1:4]:
                subject.claude_create_refusal(request.state, absent=False)
            self.metadata(item, state="active")
            expected = item.generation + "." + item.witness
            before = subject.admitted_proof(request.state, "anthropic-2", expectation=expected,
                                            name="create-before-upgrade")
            require(before["generation"] == item.generation and before["witness"] == item.witness,
                    "Fresh ordinary identity differs from the original create witness.")
            self.metadata(item, state="active")
            subject.open()
            self.archived(subject)
            self.unchanged(item)
            operation_before = create_operation_before(item, request, absence=absence)
            result = subject.execute_observed(request, "observe")
            verify_create_operation_before(subject, request, result, operation_before)
            self.unchanged(item)
            subject.finish(request, result)
            require(result["generation"] == item.generation, "No-op format-two upgrade changed generation.")
            self.metadata(item, state="active")
            after = subject.admitted_proof(request.state, "anthropic-2", expectation=expected,
                                           name="create-after-upgrade")
            require(after == before, "Ordinary restart did not preserve the exact original proof.")
            self.metadata(item, state="active")
        self.controller.require_finished_graph("arbol-claude-driver")


@dataclass(frozen=True)
class ClaudeCreateRecovery:
    walk: ClaudeCreateWalk

    @property
    def case_id(self) -> str:
        return "create-publication-recovery"

    def observe(self, controller: WholeCheckController) -> None:
        require(controller is self.walk.controller and self.case_id not in self.walk.attempted,
                "Create recovery is foreign or repeated.")
        self.walk.attempted.add(self.case_id)
        subjects = self.walk.prepare()
        for item in subjects:
            if (item.window, item.command) != (_CLAUDE_CREATE_WINDOWS[0], "abort-io"):
                self.walk.execute(item, absence=False)
        self.walk.finished.add(self.case_id)


@dataclass(frozen=True)
class ClaudeCreateAbsence:
    walk: ClaudeCreateWalk

    @property
    def case_id(self) -> str:
        return "create-publication-absence"

    def observe(self, controller: WholeCheckController) -> None:
        require(controller is self.walk.controller and self.case_id not in self.walk.attempted,
                "Create absence is foreign or repeated.")
        self.walk.attempted.add(self.case_id)
        subjects = self.walk.prepare()
        absent = [item for item in subjects if (item.window, item.command) ==
                  (_CLAUDE_CREATE_WINDOWS[0], "abort-io")]
        require(len(absent) == 1, "The unique prepared-absent original subject is missing.")
        self.walk.execute(absent[0], absence=True)
        self.walk.finished.add(self.case_id)


class PiCreateWalk:
    """Shared fixed original-subject capture for the two deferred create cases."""

    def __init__(self, controller: WholeCheckController, baseline: Baseline,
                 observer: TerminalSpanObservation, environment: Mapping[str, str]) -> None:
        self.controller, self.baseline, self.observer = controller, baseline, observer
        self.environment = without_authority(dict(environment))
        self.subjects: tuple[PiCreateSubject, ...] | None = None
        self.custody: dict[str, FileImage] = {}
        self.archive: ArchiveWitness | None = None
        self.archive_root: Path | None = None
        self.sessions: set[str] = set()
        self.attempted: set[str] = set()
        self.finished: set[str] = set()

    def prepare(self) -> tuple[PiCreateSubject, ...]:
        require({"H1-span-completion", "terminal-close-closure"} <= self.controller.finished_external,
                "The controller has not completed its original H1 and terminal duties in order.")
        if self.subjects is None:
            self.subjects = pi_create_subjects(self.controller, self.baseline, self.observer)
            view = self.observer.terminal_view
            assert view is not None
            suite = view.h1.suite_context
            authority = Authority(self.controller.workspace.registry, "arbol-pi-driver")
            contexts = [suite] + [document(view.images[f"terminal-helper-{index:04d}.context"].raw)
                                  for index in range(11)]
            for index, context in enumerate(contexts):
                writer = "writers/" + context["invocation"] + "/" + context["writer"] + ".json"
                handoff = "handoffs/" + context["handoff"] + ".json"
                context_file = "handoffs/" + context["handoff"] + ".context.json"
                for relative in (writer, handoff, context_file):
                    require(relative not in self.custody, "Original create custody has duplicate identities.")
                    self.custody[relative] = read_image(authority.folder / relative)
                require(self.custody[context_file].raw == (view.images[f"terminal-helper-{index - 1:04d}.context"].raw
                        if index else canonical(suite)), "Original custody context differs from the observed Suite.")
                if index:
                    require(self.custody[writer].raw == view.images[f"terminal-helper-{index - 1:04d}.terminal"].raw,
                            "Original helper terminal bytes differ from the observed witness.")
            require(len(self.custody) == 36, "Original Suite and all eleven helper records are incomplete.")
        return self.subjects

    def archived(self, subject: Maintenance) -> None:
        """Bind the first actual drain's rename and preserve its exact later image."""
        observed = self.controller.last_administration
        require(observed is not None and observed.command == "drain" and observed.session == subject.session
                and observed.component == subject.component, "The actual subject drain is unavailable.")
        assert observed is not None
        witness = observed.archive_witness
        if self.archive is None:
            require(witness is not None, "The first drain did not preserve the original terminal trees.")
            assert witness is not None
            witness.verify(self.controller.workspace)
            additions = set(witness.after.entries) - set(witness.before.entries)
            roots = {name.split("/", 1)[0] for name in additions if name.startswith("custody-")}
            require(len(roots) == 1, "First drain has no unique actual custody destination.")
            root_name = next(iter(roots))
            for relative, image in self.custody.items():
                tree, _, child = relative.partition("/")
                source = witness.sources[tree].entries.get(child)
                require(source is not None and source.get("type") == "file"
                        and source.get("sha256") == image.sha256 and source.get("device") == image.device
                        and source.get("inode") == image.inode and source.get("mode") == image.mode,
                        "First drain did not archive the exact original source inode and bytes.")
                assert source is not None
                moved = witness.after.entries.get(root_name + "/" + relative)
                require(moved == {**source, "path": root_name + "/" + relative},
                        "Actual archive destination differs from the original custody image.")
            self.archive, self.archive_root = witness, subject.authority.folder / "archive" / root_name
        self.check_custody()

    def check_custody(self) -> None:
        authority = Authority(self.controller.workspace.registry, "arbol-pi-driver")
        base = authority.folder if self.archive is None else self.archive_root
        require(base is not None and len(self.custody) == 36, "Original custody is unavailable.")
        assert base is not None
        if self.archive is not None:
            self.archive.verify(self.controller.workspace)
            current = ArchiveImage.capture(authority.folder / "archive")
            require(current.root == self.archive.after.root
                    and all(current.entries.get(name) == row for name, row in self.archive.after.entries.items()),
                    "The first real archive or its original evidence changed during a later drain.")
        for relative, original in self.custody.items():
            current_image = read_image(base / relative)
            require((current_image.raw, current_image.device, current_image.inode, current_image.mode) ==
                    (original.raw, original.device, original.inode, original.mode),
                    "Original Suite/helper writer, accepted handoff or context changed.")

    def unchanged(self, item: PiCreateSubject) -> None:
        self.controller.workspace.verify(self.controller.evidence)
        view = self.observer.terminal_view
        require(view is not None, "Original terminal observation is unavailable.")
        assert view is not None
        view.recheck_files()
        self.check_custody()
        require(directory_identity(item.root) == item.root_identity
                and {key: directory_identity(item.root / "state")[key] for key in ("device", "inode")}
                == item.physical["state"]
                and read_image(item.root / ".fixture-owner.json") == item.owner
                and read_image(item.root / "create-checkpoint.json") == item.checkpoint
                and read_image(item.root / "create-settlement.json") == item.settlement
                and read_image(item.root / "create-actor-result.json") == item.actor_result
                and read_image(item.root / "create-helper-ack.json") == item.ack
                and read_image(item.root / "state" / "identity.json") == item.root_proof
                and read_image(item.root / "state" / "identity.guard") == item.guard,
                "Original fixture, root, guard or immutable actor evidence changed.")
        record_path = item.root / "state" / "subscriptions" / "zai-2" / "record.json"
        if item.record is None:
            require(not os.path.lexists(record_path), "A record appeared in the absent create subject.")
        else:
            require(read_image(record_path) == item.record, "Original create record changed.")

    def metadata(self, item: PiCreateSubject, *, state: str) -> None:
        target = item.root / "state" / "subscriptions" / "zai-2"
        pending, sidecar = target / "identity-pending.json", target / "identity.json"
        require(not os.path.lexists(pending) and document(read_image(sidecar).raw) == {
            "version": 1, "state": state, "witness": item.witness},
            "The original witness did not reach its exact required terminal state.")
        self.unchanged(item)

    def execute(self, item: PiCreateSubject, *, absence: bool) -> None:
        require({"H1-span-completion", "terminal-close-closure"} <= self.controller.finished_external
                and self.subjects is not None and any(item is original for original in self.subjects),
                "Maintenance requires the completed outer duties and the bound original subject.")
        self.unchanged(item)
        subject = Maintenance(self.controller, "arbol-pi-driver", self.environment)
        require(subject.session not in self.sessions, "Two original subjects share a maintenance session.")
        self.sessions.add(subject.session)
        backup = self.controller.workspace.fixture_root / ("pi-create-" + item.case + "-" + subject.session)
        backup.mkdir(mode=0o700)
        sync_directory(backup.parent)
        request = Execute(item.root / "state", backup, "identity-recover" if absence else "upgrade",
                          subscription="zai-2" if absence else None)
        # Check all paths before begin; an unaccepted fixture path cannot leave
        # a component draining or be bypassed by a different subject.
        request.verify(self.controller)
        if absence:
            require(item.window == _PI_CREATE_WINDOWS[0] and item.command == "abort-io"
                    and item.record is None, "Only prepared-absent C1 uses targeted retirement.")
            subject.open()
            self.archived(subject)
            self.unchanged(item)
            operation_before = create_operation_before(item, request, absence=absence)
            result = subject.execute_observed(request, "observe")
            verify_create_operation_before(subject, request, result, operation_before)
            self.unchanged(item)
            require(result["generation"] == item.generation, "Targeted retirement changed root generation.")
            subject.finish(request, result)
            self.metadata(item, state="retired")
            subject.pi_create_refusal(request.state, absent=True)
            self.metadata(item, state="retired")
        else:
            require(item.record is not None, "A present-create walk requires its original record.")
            if item.command == "abort-io" and item.window in _PI_CREATE_WINDOWS[1:4]:
                subject.pi_create_refusal(request.state, absent=False)
            self.metadata(item, state="active")
            expected = item.generation + "." + item.witness
            before = subject.admitted_proof(request.state, "zai-2", expectation=expected,
                                            name="create-before-upgrade")
            require(before["generation"] == item.generation and before["witness"] == item.witness,
                    "Fresh ordinary identity differs from the original create witness.")
            self.metadata(item, state="active")
            subject.open()
            self.archived(subject)
            self.unchanged(item)
            operation_before = create_operation_before(item, request, absence=absence)
            result = subject.execute_observed(request, "observe")
            verify_create_operation_before(subject, request, result, operation_before)
            self.unchanged(item)
            subject.finish(request, result)
            require(result["generation"] == item.generation, "No-op format-two upgrade changed generation.")
            self.metadata(item, state="active")
            after = subject.admitted_proof(request.state, "zai-2", expectation=expected,
                                           name="create-after-upgrade")
            require(after == before, "Ordinary restart did not preserve the exact original proof.")
            self.metadata(item, state="active")
        self.controller.require_finished_graph("arbol-pi-driver")


@dataclass(frozen=True)
class PiCreateRecovery:
    walk: PiCreateWalk

    @property
    def case_id(self) -> str:
        return "create-publication-recovery"

    def observe(self, controller: WholeCheckController) -> None:
        require(controller is self.walk.controller and self.case_id not in self.walk.attempted,
                "Create recovery is foreign or repeated.")
        self.walk.attempted.add(self.case_id)
        subjects = self.walk.prepare()
        for item in subjects:
            if (item.window, item.command) != (_PI_CREATE_WINDOWS[0], "abort-io"):
                self.walk.execute(item, absence=False)
        self.walk.finished.add(self.case_id)


@dataclass(frozen=True)
class PiCreateAbsence:
    walk: PiCreateWalk

    @property
    def case_id(self) -> str:
        return "create-publication-absence"

    def observe(self, controller: WholeCheckController) -> None:
        require(controller is self.walk.controller and self.case_id not in self.walk.attempted,
                "Create absence is foreign or repeated.")
        self.walk.attempted.add(self.case_id)
        subjects = self.walk.prepare()
        absent = [item for item in subjects if (item.window, item.command) ==
                  (_PI_CREATE_WINDOWS[0], "abort-io")]
        require(len(absent) == 1, "The unique prepared-absent original subject is missing.")
        self.walk.execute(absent[0], absence=True)
        self.walk.finished.add(self.case_id)


def maintenance_four_dispatch_rows(cases: Mapping[Operation, tuple[Maintenance, Execute]]) -> dict[Operation, Object]:
    """The four rows use independently prepared valid targets and genuine child outcomes."""
    require(set(cases) == _OPERATIONS and all(operation == request.operation for operation, (_, request) in cases.items())
            and len({subject.controller.workspace.registry for subject, _ in cases.values()}) == len(_OPERATIONS),
            "A fixed administrative row is missing or shares a mutable registry with another row.")
    return {operation: maintenance_exact_dispatch(subject, request) for operation, (subject, request) in cases.items()}


def interrupted_supervisor_and_old_finish(subject: Maintenance, request: Execute, *, subscription: str,
                                          later_backup: Path) -> Object:
    """Observe actual pending death and a distinct lost ACK of the same attempt."""
    require(request.operation == "upgrade", "Supervisor recovery must resume the original conversion.")
    subject.open()
    pending = subject.execute_observed(request, "before-spawn")
    subject.drain()
    result = subject.execute_observed(request, "before-ack")
    require(result["attempt"] == pending["attempt"] and result["generation"] == pending["generation"],
            "A new attempt replaced the pending attempt after supervisor death.")
    subject.drain()
    settled = subject.preserve("retry-before", request)
    require(subject.execute_observed(request, "cached") == result and subject.image(request) == settled
            and subject.call("execute", request.arguments(subject.payload.build)) == subject._execute_reply()
            and subject.image(request) == settled,
            "The actual lost-ACK replay changed the resolved attempt, generation, archive or target.")

    copy = request.backup.parent / ("copied-result-" + subject.session + ".json")
    _write_new(copy, read_image(subject.result).raw)
    subject.refuse_finish(request, session=subject.session, result=copy, name="copied-result-refusal")
    subject.finish(request, result)
    proof = subject.admitted_proof(request.state, subscription, name="fresh-capture")
    require(proof["generation"] == result["generation"], "Fresh proof is outside the finished generation.")
    same = subject.admitted_proof(request.state, subscription, expectation=proof["generation"] + "." + proof["witness"],
                                  name="restarted-expect")
    require(same == proof, "A freshly admitted restart did not accept the exact current proof.")

    later = Maintenance(subject.controller, subject.component, subject.environment)
    later_request = Execute(request.state, later_backup, "identity-reset")
    later_request.verify(subject.controller)
    later.open()
    later.refuse_finish(later_request, session=subject.session, result=subject.result, name="old-session-refusal")
    later.refuse_finish(later_request, session=later.session, result=subject.result, name="old-path-refusal")
    later_result = later.execute_observed(later_request, "observe")
    require(later_result["generation"] != result["generation"], "A later real reset reused the earlier generation.")
    later.refuse_finish(later_request, session=subject.session, result=subject.result, name="old-result-refusal")
    later.refuse_replaced_result(later_request, subject.result)
    later.finish(later_request, later_result)
    fresh = later.admitted_proof(request.state, subscription, name="after-later-finish")
    require(fresh["generation"] == later_result["generation"], "Later legitimate finish did not open its fresh proof.")
    return {"original": result, "originalProof": proof, "later": later_result, "laterProof": fresh}


def _metadata_name(name: str) -> bool:
    return name in _ROOT_METADATA or _SUBSCRIPTION_METADATA.fullmatch(name) is not None


@dataclass(frozen=True)
class MetadataArchive:
    """Independent raw archive observation, including absent rows and tree shape."""

    raw: bytes
    format: int | None
    files: dict[str, bytes | None]

    @property
    def sha256(self) -> str:
        return digest(self.raw)

    @classmethod
    def read(cls, directory: Path) -> MetadataArchive:
        manifest = read_image(directory / "manifest.json", limit=_MANIFEST_LIMIT)
        value = document(manifest.raw, limit=_MANIFEST_LIMIT)
        require(set(value) == {"version", "kind", "format", "files"}
                and type(value["version"]) is int and value["version"] == 1
                and value["kind"] == "driver-identity-backup" and isinstance(value["files"], list)
                and len(value["files"]) <= 100000 and canonical(value, limit=_MANIFEST_LIMIT) == manifest.raw,
                "Invalid or noncanonical metadata-only archive manifest.")
        files: dict[str, bytes | None] = {}
        expected = {"manifest.json": "file"}
        prior = b""
        size = len(manifest.raw)
        for row in value["files"]:
            require(isinstance(row, dict) and set(row) == {"path", "present", "size", "sha256"}
                    and isinstance(row["path"], str) and _metadata_name(row["path"])
                    and row["path"].encode() > prior and type(row["present"]) is bool,
                    "Unexpected, duplicate or unsafe archive row.")
            name = str(row["path"])
            prior = name.encode()
            declared_size = row["size"]
            require(type(declared_size) is int and 0 <= declared_size <= 4096,
                    "Invalid declared archive input size.")
            require(size + declared_size <= _MANIFEST_LIMIT, "Archive exceeds its total byte bound.")
            if not row["present"]:
                require(declared_size == 0 and row["sha256"] is None, "Absence requires the exact empty row.")
                files[name] = None
                continue
            entry = read_image(directory / name)
            require(len(entry.raw) == declared_size and entry.sha256 == row["sha256"],
                    "Physical archive bytes do not match the manifest.")
            size += len(entry.raw)
            files[name] = entry.raw
            expected[name] = "file"
            for parent in Path(name).parents:
                if parent != Path("."):
                    expected[parent.as_posix()] = "directory"
        actual = {row["path"]: row["type"] for row in tree_inventory(directory)}
        require(actual == expected and _ROOT_METADATA <= set(files),
                "Archive has a missing or forbidden physical entry.")
        raw_format = files["format"]
        number = {b"1": 1, b"2": 2}.get(raw_format.strip()) if raw_format is not None else None
        require((value["format"] is None or type(value["format"]) is int) and value["format"] == number,
                "Archived format marker and manifest disagree.")
        return cls(manifest.raw, number, files)


@dataclass(frozen=True)
class CreateOperationBefore:
    """Raw actual metadata immediately before one fixed create-subject execute."""

    case: str
    operation: Operation
    subscription: str
    values: Mapping[str, bytes | None]


def create_operation_before(item: ClaudeCreateSubject | PiCreateSubject, request: Execute, *,
                            absence: bool) -> CreateOperationBefore:
    subscription = "anthropic-2" if type(item) is ClaudeCreateSubject else "zai-2"
    require(request.state == item.root / "state"
            and request.operation == ("identity-recover" if absence else "upgrade")
            and request.subscription == (subscription if absence else None),
            "Create before-image must use the original fixed subject and operation.")
    prefix = "subscriptions/" + subscription + "/"
    names = ("format", "identity.json", prefix + "identity-pending.json", prefix + "identity.json")
    values: dict[str, bytes | None] = {}
    for name in names:
        path = request.state / name
        values[name] = read_image(path).raw if os.path.lexists(path) else None
    require(values["format"] == b"2\n" and values["identity.json"] == item.root_proof.raw
            and document(item.root_proof.raw).get("generation") == item.generation,
            "Actual preoperation format or original root generation changed.")
    journal, sidecar = values[prefix + "identity-pending.json"], values[prefix + "identity.json"]
    if absence:
        checkpoint = document(item.checkpoint.raw)
        require(item.window == "C1-prepared-durable" and item.command == "abort-io" and item.record is None
                and journal is not None and sidecar is None
                and document(journal) == checkpoint.get("journal")
                and document(journal) == {"version": 1, "operation": "create", "phase": "prepared",
                                          "witness": item.witness},
                "Prepared-absent C1 must preserve its exact original pending witness and absent sidecar.")
    else:
        require(item.record is not None and journal is None and sidecar is not None
                and document(sidecar) == {"version": 1, "state": "active", "witness": item.witness},
                "Present upgrade requires the settled original witness and no pending journal.")
    return CreateOperationBefore(item.case, request.operation, subscription, values)


def verify_create_operation_before(subject: Maintenance, request: Execute, result: Object,
                                   captured: CreateOperationBefore) -> None:
    """Join physical archive bytes to this operation's real result and history before finish."""
    require(captured.operation == request.operation and captured.subscription ==
            (request.subscription if request.operation == "identity-recover" else
             "anthropic-2" if subject.component == "arbol-claude-driver" else "zai-2"),
            "Create archive observation belongs to another operation.")
    before = MetadataArchive.read(request.backup / "before")
    require(before.format == 2 and all(name in before.files and before.files[name] == raw
                                      for name, raw in captured.values.items()),
            "Physical before archive does not contain every exact preoperation byte and absence row.")
    result_image = read_image(subject.result)
    actual = document(result_image.raw)
    history = subject.folder / "attempts" / result["attempt"]
    operation = document(read_image(history / "operation.json").raw)
    marker_image = read_image(request.state / "identity-maintenance.json")
    marker = document(marker_image.raw)
    require(actual == result and result["component"] == subject.component and result["session"] == subject.session
            and result["operation"] == captured.operation and result["backupSha256"] == before.sha256
            and marker["backupSha256"] == before.sha256 and operation["backupSha256"] == before.sha256
            and marker["attempt"] == operation["attempt"] == result["attempt"]
            and read_image(history / "result.json").raw == result_image.raw
            and read_image(history / "marker.json").raw == marker_image.raw,
            "Before archive digest is not bound to the actual result, marker and operation history.")
    subject.controller.evidence.write("create-before-" + subject.session + ".json", {
        "version": 1, "case": captured.case, "component": subject.component, "session": subject.session,
        "attempt": result["attempt"], "operation": captured.operation, "subscription": captured.subscription,
        "beforeManifestSha256": before.sha256,
        "actualMetadataHex": {name: None if raw is None else raw.hex() for name, raw in captured.values.items()},
        "resultSha256": result_image.sha256, "markerSha256": marker_image.sha256,
    })


def _restore_state_metadata(state: Path) -> dict[str, bytes]:
    return {row["path"]: read_image(state / row["path"]).raw for row in tree_inventory(state)
            if row["type"] == "file" and _metadata_name(row["path"])}


def _nonmetadata_state(state: Path) -> Object:
    return {"root": directory_identity(state),
            "entries": [row for row in tree_inventory(state) if not _metadata_name(row["path"])]}


def _restore_archive_order(request: Execute, result: Object, source: MetadataArchive,
                           before: MetadataArchive, marker: Object) -> Object:
    if source.format == 1:
        conversion = MetadataArchive.read(request.backup / "conversion-before")
        live_intent = conversion.files["identity-maintenance.json"]
        require(conversion.format == 1 and conversion.files["format"] == source.files["format"]
                and conversion.files["identity-upgrade.json"] is None and live_intent is not None
                and document(live_intent) == {**marker, "phase": "pending"},
                "Format 1 reconversion did not preserve its restored input and own earlier pending intent.")
        assert live_intent is not None
        return {"sha256": conversion.sha256, "pendingMarkerHex": live_intent.hex()}
    require(not os.path.lexists(request.backup / "conversion-before"),
            "Format 2 restore ran an unnecessary format 1 conversion.")
    original = source.files["identity.json"]
    require(original is not None and document(original)["generation"] != result["generation"]
            and marker["backupSha256"] == before.sha256,
            "Format 2 restore reused its archived generation or changed its before archive.")
    return {}


def metadata_only_restore(subject: Maintenance, request: Execute, *, source_format: Literal[1, 2],
                          subscription: str, native_home: Path, malformed_target: bool = False) -> Object:
    """Observe real restore, lost ACK and reopened proof on one owned fixture.

    The supplied source is a previously captured metadata archive. State already
    has a valid local record and chat, plus an isolated home with byte sentinels.
    In the malformed case, inject fixed bad metadata only after closing it.
    """
    request.verify(subject.controller)
    source_path = request.source
    require(request.operation == "restore" and source_path is not None
            and native_home.is_relative_to(subject.controller.workspace.fixture_root)
            and native_home != subject.controller.workspace.fixture_root
            and not any(native_home.is_relative_to(root) or root.is_relative_to(native_home)
                        for root in (request.state, request.backup)),
            "Restore requires an isolated State, archive and native home.")
    assert source_path is not None
    require(not native_home.is_relative_to(source_path) and not source_path.is_relative_to(native_home),
            "The source archive overlaps native state.")
    source = MetadataArchive.read(source_path)
    require(source.format == source_format and not tree_inventory(request.backup),
            "Wrong source format or a reused restore output.")
    source_tree = _snapshot(source_path)
    previous = subject.admitted_proof(request.state, subscription, name="before-restore-proof")
    state = _nonmetadata_state(request.state)
    native = _snapshot(native_home)
    require(any(row["type"] == "file" and row["path"].endswith("/record.json") for row in state["entries"])
            and any(row["type"] == "file" and "/chats/" in row["path"] for row in state["entries"])
            and any(row["type"] == "file" for row in native["entries"]),
            "Restore fixture is missing record, chat or native/auth evidence.")
    guard_path = request.state / "identity.guard"
    guard = read_image(guard_path)
    fd = os.open(guard_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        held = os.fstat(fd)
        require((held.st_dev, held.st_ino) == (guard.device, guard.inode), "State guard changed before restore.")
        closed = subject.open()
        intact = _restore_state_metadata(request.state)
        if malformed_target:
            failed = {"format": b"bad-format\n", "identity.json": b"{failed-root",
                      "identity-upgrade.json": b"{failed-upgrade", "identity-maintenance.json": b"{failed-maintenance"}
            for name, raw in failed.items():
                publish_bytes(request.state / name, raw)
        original = _restore_state_metadata(request.state)
        subject.controller.evidence.write("restore-original-" + subject.session + ".json", {
            "preRestoreMetadata": {name: raw.hex() for name, raw in original.items()},
            "intactMetadata": {name: raw.hex() for name, raw in intact.items()},
            "malformedTarget": malformed_target, "closed": closed, "protectedState": state, "nativeHome": native,
            "guard": guard.evidence(), "sourceManifestSha256": source.sha256,
        })
        result = subject.execute_observed(request, "before-ack")
        before = MetadataArchive.read(request.backup / "before")
        require(before.sha256 == result["backupSha256"] and (set(original) | set(source.files)) <= set(before.files)
                and all(raw == original.get(name) for name, raw in before.files.items())
                and before.format == (None if malformed_target else 2)
                and result["generation"] != previous["generation"],
                "Restore did not retain raw original metadata and rotate the current proof generation.")
        marker = document(read_image(request.state / "identity-maintenance.json").raw)
        require(marker["sourceSha256"] == source.sha256 and marker["backupSha256"] == before.sha256
                and read_image(request.state / "format").raw == b"2\n"
                and not os.path.lexists(request.state / "identity-upgrade.json"),
                "Restored format and completed marker are not bound to both archives.")
        conversion = _restore_archive_order(request, result, source, before, marker)

        subject.drain()
        before_retry = subject.preserve("before-restore-retry", request)
        require(subject.execute_observed(request, "cached") == result and subject.image(request) == before_retry,
                "Restore retry changed the durable attempt, before image, source, or generation.")
        subject.finish(request, result)
        held = os.fstat(fd)
        require(guard == read_image(guard_path) and (held.st_dev, held.st_ino) == (guard.device, guard.inode)
                and _nonmetadata_state(request.state) == state and _snapshot(native_home) == native
                and _snapshot(source_path) == source_tree and MetadataArchive.read(source_path) == source,
                "Restore changed a live guard, native/auth bytes, chat, record or immutable source.")
    finally:
        os.close(fd)

    stale = previous["generation"] + "." + previous["witness"]
    subject.admitted_proof(request.state, subscription, expectation=stale, expected_error="in_use", name="old-restore-proof-refusal")
    fresh = subject.admitted_proof(request.state, subscription, name="after-restore-proof")
    expected = fresh["generation"] + "." + fresh["witness"]
    require(fresh["generation"] == result["generation"]
            and subject.admitted_proof(request.state, subscription, expectation=expected, name="after-restore-restart") == fresh,
            "Fresh restore proof did not survive restart in the exact new generation.")
    observation = {"result": result, "source": source.sha256, "before": before.sha256, "conversion": conversion,
                   "oldProof": previous, "newProof": fresh, "protectedState": state, "nativeHome": native}
    subject.controller.evidence.write("restore-finished-" + subject.session + ".json", observation)
    return observation


UnsafeParent = Literal["symlink", "nonprivate-directory", "regular-file"]


def _unsafe_parent_image(state: Path, unsafe: Path) -> Object:
    """Capture the exact bad entry without traversing it or ignoring siblings."""
    subscriptions = state / "subscriptions"
    require(unsafe.parent == subscriptions, "Unexpected unsafe path outside the selected Subscription parent.")
    root = directory_identity(state)
    parent = directory_identity(subscriptions)
    entries: dict[str, Object] = {}
    for folder in (state, subscriptions):
        for path in sorted(folder.iterdir()):
            if path in (subscriptions, unsafe):
                continue
            info = path.lstat()
            entries[path.relative_to(state).as_posix()] = (_snapshot(path) if stat.S_ISDIR(info.st_mode)
                                                           else read_image(path).evidence())
    info = unsafe.lstat()
    require(info.st_uid == os.getuid(), "Unsafe test entry is no longer owned by the subject.")
    label = unsafe.relative_to(state).as_posix()
    fault: Object = {"device": info.st_dev, "inode": info.st_ino, "owner": info.st_uid, "mode": info.st_mode}
    if stat.S_ISLNK(info.st_mode):
        fault["link"] = os.readlink(unsafe)
    elif stat.S_ISREG(info.st_mode):
        fault["bytesHex"] = read_image(unsafe).raw.hex()
    else:
        require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o755 and not any(unsafe.iterdir()),
                "Substituted directory changed or is unexpectedly private.")
    return {"root": root, "subscriptions": parent, "safeEntries": entries, "faultPath": label, "fault": fault}


def _source_only_parent(subject: Maintenance, request: Execute, subscription: str) -> tuple[MetadataArchive, Path]:
    request.verify(subject.controller)
    require(subject.component in ("arbol-claude-driver", "arbol-mimo-driver")
            and request.operation == "restore" and request.source is not None
            and _metadata_name(f"subscriptions/{subscription}/identity.json")
            and not tree_inventory(request.backup),
            "Source-only absence needs an isolated Claude or Mimo restore fixture.")
    assert request.source is not None
    parent = request.state / "subscriptions" / subscription
    physical_owned(parent.parent, directory=True)
    require(not os.path.lexists(parent), "Source-only Subscription unexpectedly already exists in the target State.")
    source = MetadataArchive.read(request.source)
    names = {f"subscriptions/{subscription}/{name}" for name in ("identity.json", "identity-pending.json")}
    require(source.format == 2 and names <= set(source.files) and all(source.files[name] is None for name in names),
            "The verified archive must explicitly introduce both absent rows.")
    require(not os.path.lexists(request.source / "subscriptions" / subscription),
            "The source already contains a physical path for its absence rows.")
    return source, parent


def source_only_archive_absence(subject: Maintenance, request: Execute, *, subscription: str) -> Object:
    source, parent = _source_only_parent(subject, request, subscription)
    assert request.source is not None
    before = _nonmetadata_state(request.state)
    exact_source = _snapshot(request.source)
    closed = subject.open()
    result = subject.execute_observed(request, "observe")
    archive_dir = request.backup / "before"
    archive = MetadataArchive.read(archive_dir)
    names = tuple(f"subscriptions/{subscription}/{name}" for name in ("identity.json", "identity-pending.json"))
    require(all(name in archive.files and archive.files[name] is None for name in names)
            and archive.sha256 == result["backupSha256"]
            and not os.path.lexists(archive_dir / "subscriptions" / subscription)
            and not os.path.lexists(parent) and _nonmetadata_state(request.state) == before,
            "Before-image did not record exact union-path absence or restore created a Subscription parent/record.")
    subject.finish(request, result)
    require(not os.path.lexists(parent) and _nonmetadata_state(request.state) == before
            and MetadataArchive.read(archive_dir) == archive and _snapshot(request.source) == exact_source,
            "Finish changed the observed absence, before archive, source, or records.")
    evidence = {"closed": closed, "result": result, "beforeManifestSha256": archive.sha256,
                "sourceManifestSha256": source.sha256, "absentRows": names,
                "beforeManifest": document(archive.raw, limit=_MANIFEST_LIMIT)}
    subject.controller.evidence.write("source-only-absence-" + subject.session + ".json", evidence)
    return evidence


def unsafe_source_only_archive_parent(subject: Maintenance, request: Execute, *, subscription: str,
                                       fault: UnsafeParent) -> None:
    """On a distinct fixture the real child refuses an unsafe existing parent."""
    source, parent = _source_only_parent(subject, request, subscription)
    assert request.source is not None
    exact_source = _snapshot(request.source)
    closed = subject.open()
    decoy: Path | None = None
    if fault == "symlink":
        decoy = subject.controller.workspace.fixture_root / ("parent-decoy-" + subject.session)
        decoy.mkdir(mode=0o700)
        _write_new(decoy / "record.json", b'{"privateFixtureSentinel":true}\n')
        parent.symlink_to(decoy, target_is_directory=True)
    elif fault == "nonprivate-directory":
        parent.mkdir(mode=0o700)
        parent.chmod(0o755)
    else:
        require(fault == "regular-file", "Unexpected source-only parent substitution.")
        _write_new(parent, b"ABR-38 wrong Subscription parent\n")
    sync_directory(parent.parent)
    expected = _unsafe_parent_image(request.state, parent)
    expected_decoy = _snapshot(decoy) if decoy is not None else None
    context = subject.execute_observed(request, "unsafe-source-parent", unsafe_parent=parent)
    require(context["operation"] == "restore" and context["session"] == subject.session
            and subject.authority.read("control") == closed and not tree_inventory(request.backup)
            and not os.path.lexists(subject.result) and _unsafe_parent_image(request.state, parent) == expected
            and (decoy is None or _snapshot(decoy) == expected_decoy)
            and MetadataArchive.read(request.source) == source and _snapshot(request.source) == exact_source,
            "Unsafe existing parent was accepted as absence or refusal modified its protected evidence.")
    subject.controller.evidence.write("unsafe-source-parent-" + subject.session + ".json", {
        "fault": fault, "state": expected, "decoy": expected_decoy, "sourceManifestSha256": source.sha256,
        "context": context, "closed": closed,
    })


def _pending_path(state: Path, subscription: str) -> Path:
    path = f"subscriptions/{subscription}/identity-pending.json"
    require(_SUBSCRIPTION_METADATA.fullmatch(path) is not None, "Invalid recovery fixture Subscription.")
    return state / path


def _remove_journal(path: Path) -> tuple[bytes, str]:
    raw = read_image(path).raw
    value = document(raw)
    require(set(value) == {"version", "operation", "witness", "phase"}
            and type(value["version"]) is int and value["version"] == 1
            and value["operation"] == "remove" and value["phase"] == "prepared"
            and valid_token(value["witness"]), "Expected the owned prepared-remove journal.")
    return raw, str(value["witness"])


def _retirement_source(subject: Maintenance, observation: Object) -> list[Object]:
    component = subject.component.removeprefix("arbol-").replace("-", "_")
    module = "arbol_" + component
    sites = observation["sites"]
    require(isinstance(sites, list) and 0 < len(sites) < 32, "Missing actual sealed retirement stack.")
    expected_site = ("identity.py", "retire_pending") if component == "codex_driver" else ("maintenance.py", "recover")
    matching: list[Object] = []
    for site in sites:
        require(isinstance(site, list) and len(site) == 3 and isinstance(site[0], str)
                and isinstance(site[1], str) and type(site[2]) is int and site[2] > 0,
                "Malformed real retirement stack frame.")
        path = Path(site[0])
        if (path.name, site[1]) != expected_site or path.parent.name != module:
            continue
        require(not path.is_absolute() and ".." not in path.parts, "Retirement site escaped the accepted producer.")
        image = read_image(subject.payload.root / path, limit=_MANIFEST_LIMIT, private=False)
        require(site[2] <= len(image.raw.splitlines()), "Reported retirement frame is outside its immutable source.")
        matching.append({"site": site, "image": image.evidence()})
    require(len(matching) == 1, "Real unlink did not come from the sealed producer's selected recovery site.")
    return matching


def targeted_pending_recovery(subject: Maintenance, request: Execute, *, other_subscription: str,
                              previous_proof: Mapping[str, str]) -> Object:
    """Recover one genuinely prepared local journal and keep the other fenced."""
    request.verify(subject.controller)
    selected = request.subscription
    require(request.operation == "identity-recover" and selected is not None and selected != other_subscription
            and not tree_inventory(request.backup), "Targeted recovery requires two distinct local journal subjects.")
    assert selected is not None
    target = _pending_path(request.state, selected)
    other = _pending_path(request.state, other_subscription)
    selected_raw, old_witness = _remove_journal(target)
    other_raw, other_witness = _remove_journal(other)
    require(old_witness != other_witness and previous_proof["subscription"] == selected
            and previous_proof["witness"] == old_witness, "Prepared journals are not bound to the original lost lifetime.")
    sidecar = target.with_name("identity.json")
    old_sidecar = read_image(sidecar)
    require(document(old_sidecar.raw) == {"version": 1, "state": "active", "witness": old_witness},
            "The selected journal does not own the earlier active sidecar.")
    other_image = read_image(other)
    other_sidecar = read_image(other.with_name("identity.json"))
    require(document(other_sidecar.raw) == {"version": 1, "state": "active", "witness": other_witness},
            "The unrelated journal does not bind its original active sidecar.")
    root = read_image(request.state / "identity.json")
    protected = _nonmetadata_state(request.state)
    require(document(root.raw)["generation"] == previous_proof["generation"],
            "The original selected proof came from another root generation.")

    observation_root = subject.controller.workspace.fixture_root / ("retirement-" + subject.session)
    observation_root.mkdir(mode=0o700)
    config = observation_root / "observer.json"
    observation_path = observation_root / "before-unlink.json"
    _write_new(config, canonical({"journal": str(target), "sidecar": str(sidecar), "evidence": str(observation_path)}))
    closed = subject.open()
    result = subject.execute_observed(request, "retirement", retirement=config)

    before_unlink = document(read_image(observation_path).raw)
    source = _retirement_source(subject, before_unlink)
    retired = canonical({"version": 1, "state": "retired", "witness": old_witness})
    require(before_unlink["journal"] == selected_raw.hex() and before_unlink["sidecar"] == retired.hex()
            and not os.path.lexists(target) and read_image(sidecar).raw == retired
            and read_image(other) == other_image and read_image(other_sidecar.path) == other_sidecar
            and read_image(root.path) == root and result["generation"] == previous_proof["generation"],
            "Actual retirement did not precede unlink or changed the unrelated journal and generation.")
    archive = MetadataArchive.read(request.backup / "before")
    require(archive.sha256 == result["backupSha256"]
            and archive.files[target.relative_to(request.state).as_posix()] == selected_raw
            and archive.files[other.relative_to(request.state).as_posix()] == other_raw
            and _nonmetadata_state(request.state) == protected,
            "Targeted recovery failed to preserve both original journals or changed record/native metadata.")

    subject.finish(request, result)
    require(read_image(other) == other_image and read_image(other_sidecar.path) == other_sidecar
            and _nonmetadata_state(request.state) == protected,
            "Operation-relative finish changed an unrelated journal or record.")
    stale = previous_proof["generation"] + "." + old_witness
    subject.admitted_proof(request.state, selected, expectation=stale, expected_error="in_use", name="retired-proof-refusal")
    fresh = subject.admitted_proof(request.state, selected, name="fresh-recovery-proof")
    expected = fresh["generation"] + "." + fresh["witness"]
    require(fresh["generation"] == result["generation"] and fresh["witness"] != old_witness
            and subject.admitted_proof(request.state, selected, expectation=expected, name="restart-recovery-proof") == fresh,
            "A freshly admitted invocation did not use the newly materialized lifetime.")
    subject.admitted_proof(request.state, other_subscription, expected_error="internal", name="unrelated-pending-refusal")
    require(not os.path.lexists(target) and read_image(other) == other_image and read_image(other_sidecar.path) == other_sidecar,
            "A normally admitted proof consumed or relabelled the unrelated journal.")
    evidence = {"result": result, "archiveSha256": archive.sha256, "closedBefore": closed,
                "beforeUnlink": before_unlink, "sealedSource": source, "oldProof": dict(previous_proof),
                "freshProof": fresh, "preservedOther": other_image.evidence()}
    subject.controller.evidence.write("targeted-recovery-" + subject.session + ".json", evidence)
    return evidence


FinishFault = Literal["unrelated-pending", "malformed-journal", "root-journal"]


def refuse_finish_with_pending(subject: Maintenance, request: Execute, *, affected_subscription: str,
                               fault: FinishFault, observed_journal: bytes) -> None:
    """Inject a bounded fault on a separate subject after its real result."""
    request.verify(subject.controller)
    pending = _pending_path(request.state, affected_subscription)
    physical_owned(pending.parent, directory=True)
    require(not os.path.lexists(pending), "Finish refusal needs a fresh dedicated injected pending path.")
    source = document(observed_journal)
    require(set(source) == {"version", "operation", "witness", "phase"}
            and type(source["version"]) is int and source["version"] == 1 and source["operation"] == "remove"
            and source["phase"] == "prepared" and valid_token(source["witness"]),
            "Finish refusal must use the exact observed prepared-journal shape.")
    if fault == "unrelated-pending":
        require(request.operation in ("upgrade", "identity-reset", "restore"),
                "A genuine successful targeted finish permits unrelated well-formed journals.")
    else:
        require(request.operation == "identity-recover" and affected_subscription != request.subscription,
                "Use targeted recovery to distinguish malformed/root evidence from a well-formed unrelated journal.")
    closed = subject.open()
    result = subject.execute_observed(request, "observe")
    if fault == "root-journal":
        pending = request.state / "identity-upgrade.json"
        raw = canonical({"version": 1, "from": 1, "to": 2, "generation": result["generation"],
                         "backup": str(request.backup), "backupSha256": result["backupSha256"]})
    else:
        raw = observed_journal if fault == "unrelated-pending" else b"{malformed journal"
    require(not os.path.lexists(pending), "Finish refusal would overwrite real pending evidence.")
    _write_new(pending, raw)
    unchanged = read_image(pending)
    subject.refuse_finish(request, session=subject.session, result=subject.result, name="pending-finish-refusal")
    require(subject.authority.read("control") == closed and read_image(pending) == unchanged,
            "Refused finish did not preserve the exact pending journal and original closed control.")

    probe = request.backup.parent / ("closed-state-" + subject.session)
    require(probe.is_relative_to(subject.controller.workspace.fixture_root) and not os.path.lexists(probe),
            "Closed launch probe needs genuinely absent private State.")
    before = subject.preserve("before-closed-proof", request)
    argv = subject.controller.fixed_argv(subject.component, subject.payload.build, "driver",
                                         ["--state-dir", str(probe), "subscriptions", "identity", affected_subscription])
    capture = subject.capture(argv, "pending-closed-proof")
    require(capture.returncode == 1 and not capture.stderr and document(capture.stdout) == _PROVIDER_REFUSAL
            and before == subject.image(request) and not os.path.lexists(probe),
            "The still-closed provider admitted a normal proof or changed the original result.")
