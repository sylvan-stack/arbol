"""Prospective ABR-38 external maintenance cases for disposable Build registries."""

from __future__ import annotations

import fcntl
import os
import selectors
import signal
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from driver_identity_qualification import WholeCheckController, require

from arbol_builds.driver_admission import COMPONENTS, Authority, reconcile, valid_token, validate, without_authority
from arbol_builds.driver_payload import request_binding
from top.driver_state_support import (
    Captured,
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

Operation = Literal["upgrade", "identity-reset", "restore", "identity-recover"]
Fault = Literal["no-fd", "wrong-inode", "separate-description", "receipt", "state", "operation",
                "context-copy", "epoch", "attempt", "payload"]
Mode = Literal["observe", "before-spawn", "before-ack", "cached"] | Fault
_OPERATIONS = {"upgrade", "identity-reset", "restore", "identity-recover"}
_CONTEXT_FAULTS = {"epoch", "attempt", "payload"}
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

entry, mode, replacement, *arguments = sys.argv[1:]
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
                       'reapedExit': child.returncode, 'acceptedStdoutHex': stdout})
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
            "argv": argv if argv[2] != "-c" else argv[4:],
            "observerSha256": digest(_OBSERVER.encode()) if argv[2] == "-c" else None,
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

    def image(self, request: Execute) -> Object:
        return {"control": self.authority.read("control"), "receipt": read_image(self.receipt).raw.hex(),
                "authority": _snapshot(self.authority.folder), "state": _snapshot(request.state),
                "backup": _snapshot(request.backup),
                "source": _snapshot(request.source) if request.source is not None else None}

    def preserve(self, name: str, request: Execute) -> Object:
        value = self.image(request)
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

    def execute_observed(self, request: Execute, mode: Mode) -> Object:
        request.verify(self.controller)
        self.controller.require_finished_graph(self.component)
        require(mode != "operation" or request.operation == "upgrade", "Operation substitution needs the exact upgrade row.")
        self.controller.scope.recheck()
        replacement = self._fault_input(request, mode)
        provider = self.controller.scope.gate.provider
        interpreter, isolation, entry = provider.prefix
        child = OwnedChild([interpreter, isolation, "-c", _OBSERVER, entry, mode, replacement,
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
            before = self.preserve("pre-child-" + mode, request)
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
                    ack = boundary.frame("before-ack")
                    require(ended["reapedExit"] == 0 and ended["acceptedStdoutHex"] is not None,
                            "Lost ACK did not follow the genuine reaped administrative child.")
                    settled = self.preserve("before-lost-ack", request)
                    require(self._execute_reply() == document(bytes.fromhex(ack["ackHex"])),
                            "The intercepted ACK does not reference the actual durable result.")
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
            if mode == "observe":
                require(captured.returncode == 0 and not captured.stderr and ended["reapedExit"] == 0
                        and document(captured.stdout) == self._execute_reply(),
                        "Exact packaged provider/child dispatch did not complete.")
                result = self.verify_result(request)
                self._verify_child_output(ended, result)
                return result
            require(captured.returncode == 1 and not captured.stderr and document(captured.stdout) == _PROVIDER_REFUSAL
                    and ended["reapedExit"] == 1 and ended["acceptedStdoutHex"] is None,
                    "Substituted input was not refused by the actual child and packaged supervisor.")
            require(self.image(request) == before and not os.path.lexists(self.result),
                    "Rejected child changed the pending attempt, custody, State or before archive.")
            if mode == "state":
                require(not _snapshot(Path(replacement))["entries"], "The rejected substitute State was modified.")
            self.preserve("after-refusal-" + mode, request)
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
                       name: str) -> Object:
        self.controller.require_finished_graph(self.component)
        tail = ["--state-dir", str(state), "subscriptions", "identity", subscription]
        if expectation is not None:
            tail.extend(("--expect", expectation))
        capture = self.capture(self.controller.fixed_argv(self.component, self.payload.build, "driver", tail), name)
        require(capture.returncode == 0 and not capture.stderr, "Fresh admitted identity operation failed.")
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
        require(result.get("subscription") == subscription and type(result.get("version")) is int
                and result.get("version") == 1 and result.get("driver") == self.component.removeprefix("arbol-").removesuffix("-driver")
                and valid_token(result.get("generation")) and valid_token(result.get("witness")),
                "Fresh proven identity is malformed or belongs to another Subscription.")
        return result


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
