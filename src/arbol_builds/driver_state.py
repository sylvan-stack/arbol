"""Shared registered Driver launch and offline maintenance provider (DRV-6.21).

There is no source-path, copied-launcher or manifest-only admission fallback.
Normal writer admission and exclusive maintenance remain separate protocols.
"""

from __future__ import annotations

import os
import re
import signal
import stat
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from .driver_admission import (
    COMPONENTS,
    LIMIT,
    Authority,
    Custody,
    Object,
    Refusal,
    archive_terminal,
    canonical,
    canonical_uuid,
    custody_loss,
    decode,
    fields,
    normal_control,
    physical,
    private_directory,
    publish,
    publish_bytes,
    read,
    read_bytes,
    reconcile,
    sha256,
    token,
    valid_hash,
    validate,
    without_authority,
)
from .driver_payload import (
    DESCRIPTOR,
    SUBTREE,
    Gate,
    Payload,
    load,
    pin_payloads,
    registered,
    resolve_provider,
    verify_acceptance,
    verify_gate,
)
from .driver_process import Guardian, boot_uuid, request_cancellation, supervise
from .launcher import BUILD_PATTERN, Record, launch, open_use_guard, standard_descriptors, write_all


def _route(authority: Authority, route: str) -> None:
    gate = verify_gate(authority.registry)
    # A direct source import is not this accepted immutable provider.
    if not Path(__file__).resolve().is_relative_to(gate.provider.root):
        raise Refusal("Use the registered immutable Driver launcher/provider.")
    expected = next(row["launcher"] for row in gate.document["components"]
                    if row["component"] == authority.component)
    if physical(os.path.realpath(os.path.abspath(route)), directory=False) != Path(expected):
        raise Refusal("Driver launcher route does not match the installed gate.")


def _use_current(authority: Authority, build: str, descriptor: int) -> None:
    current = os.fstat(descriptor)
    named = (authority.registry / authority.component / ".uses" / build).lstat()
    if (not stat.S_ISREG(current.st_mode) or current.st_uid != os.getuid()
            or stat.S_IMODE(current.st_mode) != 0o600
            or (current.st_dev, current.st_ino) != (named.st_dev, named.st_ino)):
        raise Refusal("Cannot verify the selected Driver Build-use guard.")


def _admission_marker(authority: Authority, control: Object, *, invocation: str,
                      build: str, payload: str | None, boot: str) -> None:
    """Under control mutex, invalidate any closed checkpoint before execution.

    These private records are later checked/archived by the deployment provider;
    no field is added to public control, taint, context or receipt documents.
    """
    checkpoint = None
    deployment = authority.shared / "deployment.json"
    if deployment.exists():
        value = read(deployment)
        validate("deployment", value)
        checkpoint = value["checkpoint"]
    folder = private_directory(authority.folder / "normal-admissions", create=True)
    marker = {"version": 1, "kind": "driver-normal-admission", "component": authority.component,
              "epoch": control["epoch"], "boot": boot, "invocation": invocation, "build": build,
              "payloadSha256": payload, "checkpoint": checkpoint}
    path = folder / (invocation + ".json")
    if path.exists():
        raise Refusal("A normal admission cannot reuse an invocation.")
    publish(path, marker)


def _legacy_taint(authority: Authority, control: Object, *, invocation: str,
                  payload: str | None, boot: str) -> None:
    try:
        prior = read_bytes(authority.folder / "taint.json")
    except FileNotFoundError:
        prior = None
    if prior is not None:
        archive = private_directory(authority.folder / "archive") / ("taint-" + sha256(prior) + ".json")
        if archive.exists() and read_bytes(archive) != prior:
            raise Refusal("An earlier taint archive does not match.")
        if not archive.exists():
            publish_bytes(archive, prior)
    authority.write("taint", {"version": 1, "component": authority.component, "epoch": control["epoch"],
                              "boot": boot, "reason": "legacy", "invocation": invocation,
                              "payloadSha256": payload})


def launch_selected(registry: str, component: str, selected: Record, arguments: list[str],
                    entry: str, use_descriptor: int | None, *, route: str | None = None) -> int:
    if component not in COMPONENTS:
        raise Refusal("Unknown Driver component.")
    authority = Authority(physical(registry), component)
    try:
        _route(authority, route or sys.argv[0])
    except OSError:
        raise Refusal("Registered Driver gate authority is missing or unsafe.") from None
    owned = use_descriptor is None
    descriptor = (open_use_guard(registry, component, selected["build"])
                  if owned else use_descriptor)
    assert descriptor is not None
    try:
        _use_current(authority, selected["build"], descriptor)
        payload: Payload | None = None
        qualified = False
        descriptor_path = authority.registry / component / selected["build"] / SUBTREE / DESCRIPTOR
        try:
            descriptor_path.lstat()
            declared = True
        except FileNotFoundError:
            if descriptor_path.parent.exists():
                raise Refusal("The declared Driver payload is incomplete.") from None
            declared = False
        if declared:
            # A damaged declared format2 payload is a refusal, never legacy fallback.
            payload = registered(authority.registry, component, selected["build"])
            try:
                verify_acceptance(authority, payload)
                qualified = True
            except (OSError, Refusal):
                qualified = False
        if qualified:
            assert payload is not None
            guardian = Guardian.admit(authority, payload)
            try:
                with authority.mutex():
                    control = normal_control(authority, epoch=guardian.epoch)
                    _admission_marker(authority, control, invocation=guardian.invocation,
                                      build=payload.build, payload=payload.digest, boot=guardian.boot)
            except BaseException:
                guardian.abort()
                raise
            return supervise(guardian, arguments)
        boot, invocation = boot_uuid(), token()
        with authority.mutex():
            control = normal_control(authority)
            digest = payload.digest if payload is not None else None
            _admission_marker(authority, control, invocation=invocation,
                              build=selected["build"], payload=digest, boot=boot)
            _legacy_taint(authority, control, invocation=invocation, payload=digest, boot=boot)
            # The short control description closes atomically with exec. The
            # already admitted legacy invocation remains tainted after main exit.
            os.set_inheritable(descriptor, True)
            os.execve(entry, [entry, *arguments], without_authority(os.environ.copy()))
    except (OSError, ValueError, RuntimeError) as error:
        if isinstance(error, Refusal):
            raise
        raise Refusal("Driver launch admission failed; preserve closed recovery authority.") from None
    finally:
        if owned:
            os.close(descriptor)
    return 1


def launch_gated(registry: str, component: str, route: str, arguments: list[str]) -> int:
    """Fixed publisher-generated route; all remaining arguments keep normal -v parsing."""
    def admitted(reg: str, comp: str, record: Record, args: list[str], entry: str, guard: int | None) -> int:
        return launch_selected(reg, comp, record, args, entry, guard, route=route)

    return launch(registry, component, arguments, driver_launch=admitted)


def guarded_publication[T](registry: Path, payloads: list[Payload], authorities: list[Authority],
                           action: Callable[[], T]) -> T:
    """Pin exact Builds before short lexical control locks and durable publication.

    All deployment/operation publishers use this order. The callback is bounded
    trusted registry metadata work: no child, signal, wait or payload deletion.
    """
    names = [authority.component for authority in authorities]
    if len(set(names)) != len(names) or any(authority.registry != registry for authority in authorities):
        raise Refusal("Invalid Driver publication scope.")
    with pin_payloads(registry, payloads), ExitStack() as stack:
        for authority in sorted(authorities, key=lambda value: value.component):
            stack.enter_context(authority.mutex())
        return action()


ADMIN_COMMANDS = frozenset(("deploy", "begin", "drain", "execute", "status", "finish"))
OPERATIONS = frozenset(("upgrade", "identity-reset", "restore", "identity-recover"))
SUBSCRIPTION = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z", re.ASCII)


@dataclass(frozen=True)
class Request:
    command: str
    registry: Path
    values: dict[str, str]

    @property
    def component(self) -> str:
        return self.values["component"]

    @property
    def session(self) -> str:
        return self.values["session"]


# Each reviewed operation leaf installs only its fixed handler. Packaging checks
# the complete table before it can emit a provider capability declaration.
HANDLERS: dict[str, Callable[[Request], Object]] = {}


def handler(name: str) -> Callable[[Callable[[Request], Object]], Callable[[Request], Object]]:
    def register(function: Callable[[Request], Object]) -> Callable[[Request], Object]:
        if name not in ADMIN_COMMANDS or name in HANDLERS:
            raise Refusal("Invalid maintenance dispatch table.")
        HANDLERS[name] = function
        return function
    return register


def parse_request(arguments: list[str], default_registry: str) -> Request:
    """No arbitrary positional argv, implicit flags or operation substitutions."""
    from .cli import options

    if not arguments or arguments[0] not in ADMIN_COMMANDS:
        raise Refusal("Use driver-state deploy, begin, drain, execute, status or finish.")
    name = arguments[0]
    required = {
        "deploy": {"session", "manifest", "callers"},
        "begin": {"component", "session"},
        "drain": {"component", "session"},
        "status": {"component", "session"},
        "execute": {"component", "session", "build", "state-dir", "operation", "backup"},
        "finish": {"component", "session", "result"},
    }[name]
    allowed = required | {"registry-dir"}
    if name == "drain":
        allowed |= {"stop"}
    if name == "execute":
        allowed |= {"source", "subscription"}
    words, parsed = options(arguments[1:], ["--" + key for key in sorted(allowed)], {"--stop"})
    values = {key[2:]: value for key, value in parsed.items()}
    if words or not required <= values.keys() or not canonical_uuid(values["session"]):
        raise Refusal("Invalid maintenance command or session.")
    if name != "deploy" and values["component"] not in COMPONENTS:
        raise Refusal("Unknown Driver component.")
    for key in ("manifest", "callers", "state-dir", "backup", "source", "result"):
        if key in values:
            value = values[key]
            if (not os.path.isabs(value) or os.path.normpath(value) != value or value.startswith("//")
                    or len(value.encode("utf-8", "strict")) > LIMIT or "\0" in value):
                raise Refusal("Maintenance paths must be canonical absolute paths.")
    if name == "execute":
        operation = values["operation"]
        if (operation not in OPERATIONS or BUILD_PATTERN.fullmatch(values["build"]) is None
                or ("source" in values) != (operation == "restore")
                or ("subscription" in values) != (operation == "identity-recover")
                or ("subscription" in values and SUBSCRIPTION.fullmatch(values["subscription"]) is None)):
            raise Refusal("Invalid maintenance operation selector.")
    registry = physical(values.pop("registry-dir", default_registry))
    return Request(name, registry, values)


def _provider(request: Request) -> Payload:
    if request.command != "deploy":
        return verify_gate(request.registry).provider
    # Deployment must bootstrap before new launcher bytes are installed. This
    # resolves only the exact registered provider; deployment separately verifies
    # closed routes, acceptance and checkpoint before any state operation.
    manifest = read(physical(request.values["manifest"], directory=False))
    fields(manifest, "version kind providerPayloadSha256 components")
    rows = manifest["components"]
    if (manifest["kind"] != "driver-gate" or not valid_hash(manifest["providerPayloadSha256"])
            or not isinstance(rows, list) or len(rows) != len(COMPONENTS)):
        raise Refusal("Invalid deployment gate manifest.")
    for component, row in zip(COMPONENTS, rows, strict=True):
        if (not isinstance(row, dict) or set(row) != {"component", "launcher", "launcherSha256"}
                or row["component"] != component or not valid_hash(row["launcherSha256"])
                or not isinstance(row["launcher"], str) or not os.path.isabs(row["launcher"])
                or os.path.normpath(row["launcher"]) != row["launcher"]):
            raise Refusal("Invalid deployment gate routes.")
    return resolve_provider(request.registry, manifest["providerPayloadSha256"])


def command(arguments: list[str], default_registry: str) -> int:
    """Ordinary arbol-builds delegates before handling component authority."""
    try:
        request = parse_request(arguments, default_registry)
        provider = _provider(request)
        with pin_payloads(request.registry, [provider]):
            # Preserve this process's Build pin across exec until the one-shot
            # provider exits, including initial deployment before a gate pin.
            descriptor = open_use_guard(str(request.registry), "arbol", provider.build)
            try:
                _use_provider_guard(request.registry, provider.build, descriptor)
                os.set_inheritable(descriptor, True)
                os.execve(provider.prefix[0], [*provider.prefix, "driver-state", *arguments],
                          without_authority(os.environ.copy()))
            finally:
                os.close(descriptor)
        return 1
    except Exception:
        _maintenance_error()
        return 1


def _use_provider_guard(registry: Path, build: str, descriptor: int) -> None:
    info = os.fstat(descriptor)
    named = (registry / "arbol" / ".uses" / build).lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
            or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
        raise Refusal("Invalid provider Build-use guard.")


def _maintenance_error() -> None:
    write_all(1, canonical({"error": {"code": "builds_failed",
                                    "message": "Driver maintenance refused; preserve closed recovery authority."}}))


def provider_entry(descriptor: Object) -> None:
    """Called only by the sealed immutable script after isolated M/D verification."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    standard_descriptors()
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM})
    try:
        root = Path(__file__).resolve().parents[2]
        provider = load(root, "arbol", descriptor["build"])
        if (provider.descriptor != descriptor or not sys.flags.isolated or not sys.flags.no_site
                or not sys.flags.no_user_site or not sys.flags.safe_path or not sys.dont_write_bytecode
                or Path(sys.executable).resolve() != Path(provider.prefix[0]).resolve()
                or Path(sys.argv[0]).resolve() != Path(provider.prefix[2])):
            raise Refusal("Unverified immutable provider entry.")
        arguments = sys.argv[1:]
        if arguments[:1] == ["--driver-launch"]:
            if len(arguments) < 4 or arguments[2] not in COMPONENTS:
                raise Refusal("Invalid fixed Driver launcher dispatch.")
            registry = physical(arguments[1])
            selected = verify_gate(registry).provider
            if selected.root != provider.root or selected.digest != provider.digest:
                raise Refusal("Driver launcher provider differs from installed gate.")
            with pin_payloads(registry, [provider]):
                result = launch_gated(str(registry), arguments[2], arguments[3], arguments[4:])
            raise SystemExit(result)
        if arguments[:1] != ["driver-state"]:
            raise Refusal("Invalid immutable provider command.")
        from .config import locations
        request = parse_request(arguments[1:], locations().registry)
        selected = _provider(request)
        if selected.root != provider.root or selected.digest != provider.digest:
            raise Refusal("Maintenance provider differs from the exact registered tuple.")
        with pin_payloads(request.registry, [provider]):
            # Future source leaves register their reviewed fixed operations. A
            # partial source tree is never a publishable provider payload.
            function = HANDLERS.get(request.command)
            if function is None:
                raise Refusal("Incomplete maintenance provider payload.")
            raw = canonical(function(request))
            if len(raw) > LIMIT:
                raise Refusal("Maintenance result exceeds its protocol bound.")
            write_all(1, raw)
    except Exception:
        _maintenance_error()
        raise SystemExit(1) from None
    raise SystemExit(0)


@contextmanager
def _component(request: Request) -> Iterator[tuple[Authority, Payload, Gate]]:
    """Exact qualified payload only; source declarations grant no authority."""
    authority = Authority(request.registry, request.component)
    gate = verify_gate(request.registry)
    if not Path(__file__).resolve().is_relative_to(gate.provider.root):
        raise Refusal("Use the verified immutable maintenance provider.")
    qualification = authority.read("qualification")
    if qualification["component"] != request.component:
        raise Refusal("Qualification component mismatch.")
    digest = qualification["acceptanceSha256"]
    raw = read_bytes(authority.shared / "acceptances" / (digest + ".json"))
    acceptance = decode(raw)
    producer_digest = acceptance.get("producerPayloadSha256")
    if sha256(raw) != digest or not valid_hash(producer_digest):
        raise Refusal("Invalid qualification tuple.")
    found: list[Payload] = []
    count = 0
    for folder in (request.registry / request.component).iterdir():
        count += 1
        if count > 100000:
            raise Refusal("Registry exceeds its bounded tuple inventory.")
        if BUILD_PATTERN.fullmatch(folder.name) is None:
            continue
        try:
            raw = read_bytes(folder / SUBTREE / DESCRIPTOR)
        except FileNotFoundError:
            continue
        if sha256(raw) == producer_digest:
            found.append(registered(request.registry, request.component, folder.name))
    if len(found) != 1:
        raise Refusal("The exact accepted Driver payload is unavailable.")
    payload = found[0]
    with pin_payloads(request.registry, [gate.provider, payload]):
        verify_acceptance(authority, payload, digest=digest)
        yield authority, payload, gate


def _recheck(authority: Authority, payload: Payload, gate: Gate) -> None:
    verify_acceptance(authority, payload)
    if verify_gate(authority.registry).digest != gate.digest:
        raise Refusal("Maintenance gate changed during verification.")


def _control(authority: Authority, session: str, *, closed: bool = False) -> Object:
    control = authority.read("control")
    if ((control["phase"] != "normal" and control["session"] != session)
            or (closed and control["phase"] == "normal")):
        raise Refusal("A different or unopened maintenance session owns this component.")
    return control


def _tainted(authority: Authority) -> bool:
    try:
        value = authority.read("taint")
    except FileNotFoundError:
        return False
    if value["component"] != authority.component:
        raise Refusal("Taint component mismatch.")
    return True


def _status(request: Request, authority: Authority, control: Object, custody: Custody | None = None) -> Object:
    # Status never publishes taint, closes admission, signals or touches state.
    if custody is None:
        custody = reconcile(authority, control=control, persist_unknown=False)
    return {"version": 1, "component": request.component, "session": request.session,
            "phase": control["phase"], "custody": {"active": custody.active, "pending": custody.pending,
                                                     "unknown": custody.unknown, "tainted": _tainted(authority)}}


@handler("begin")
def begin(request: Request) -> Object:
    with _component(request) as (authority, payload, gate):
        with authority.mutex():
            _recheck(authority, payload, gate)
            control = _control(authority, request.session)
            if control["phase"] == "normal":
                control = {**control, "phase": "draining", "session": request.session}
                authority.write("control", control)
            # Closing happens before custody inspection. Unknown obligations
            # retain their taint and same epoch; begin never cancels work.
            archive_pending = os.path.lexists(authority.folder / "archive" / "custody-pending.json")
            reconcile(authority, control=control, persist_unknown=not archive_pending)
            _tainted(authority)
            return {"version": 1, "component": request.component, "session": request.session,
                    "phase": control["phase"]}


@handler("status")
def status(request: Request) -> Object:
    with _component(request) as (authority, payload, gate):
        with authority.mutex():
            _recheck(authority, payload, gate)
            return _status(request, authority, _control(authority, request.session))


def _draining(authority: Authority, control: Object) -> Object:
    if control["phase"] != "draining":
        control = {**control, "phase": "draining"}
        authority.write("control", control)
    return control


def _receipt(request: Request, authority: Authority, control: Object, gate: Gate) -> Object:
    receipt = {"version": 1, "kind": "driver-state-maintenance", "component": request.component,
               "session": request.session, "epoch": control["epoch"], "phase": "exclusive",
               "gateSha256": gate.digest}
    path = authority.folder / "maintenance.json"
    try:
        previous = read_bytes(path)
    except FileNotFoundError:
        previous = None
    raw = canonical(receipt)
    if previous is not None and previous != raw:
        validate("maintenance", decode(previous))
        archive = authority.folder / "archive" / ("maintenance-" + sha256(previous) + ".json")
        if archive.exists() and read_bytes(archive) != previous:
            raise Refusal("Maintenance receipt archive changed.")
        if not archive.exists():
            publish_bytes(archive, previous)
    authority.write("control", {**control, "phase": "exclusive"})
    if previous != raw:
        authority.write("maintenance", receipt)
    return {"version": 1, "component": request.component, "session": request.session,
            "phase": "exclusive", "receipt": str(path)}


@handler("drain")
def drain(request: Request) -> Object:
    # This bounds all explicit mutex/poll waits in this call. Inventory and
    # identity verification remain bounded metadata work, not a process scan.
    deadline = time.monotonic() + 20
    sent: set[tuple[int, str]] = set()
    with _component(request) as (authority, payload, gate):
        boot = boot_uuid()
        while True:
            lease = -1
            with authority.mutex(seconds=max(0, deadline - time.monotonic())):
                control = _control(authority, request.session, closed=True)
                if sha256(read_bytes(authority.shared / "gate.json")) != gate.digest:
                    raise Refusal("Maintenance gate changed during drain.")
                try:
                    lease = authority.lease(exclusive=True)
                except BlockingIOError:
                    pass
                try:
                    # Resume a previously verified terminal archive before
                    # interpreting absent active directories. No taint is cleared.
                    if lease >= 0 and os.path.lexists(authority.folder / "archive" / "custody-pending.json"):
                        archive_terminal(authority, lease)
                    custody = reconcile(authority, control=control, boot=boot)
                    if lease >= 0 and not custody.resolved and not custody.unknown:
                        # A registered live writer without any independent SH
                        # lease is custody loss, never evidence of quiescence.
                        custody_loss(authority, invocation=token(), epoch=control["epoch"], boot=boot,
                                     payload_sha256=None)
                        custody = Custody(custody.writers, custody.handoffs, custody.active, custody.pending, True)
                    tainted = _tainted(authority)
                    if lease >= 0 and custody.resolved and not tainted:
                        _recheck(authority, payload, gate)
                        current = _control(authority, request.session, closed=True)
                        if current != control:
                            raise Refusal("Maintenance control changed during drain.")
                        # The acquired EX description excludes every writer;
                        # recheck the exact graph before archival/receipt.
                        custody = reconcile(authority, control=current, boot=boot)
                        if not custody.resolved or _tainted(authority):
                            raise Refusal("Custody remains unresolved under exclusive admission.")
                        if custody.writers or custody.handoffs:
                            archive_terminal(authority, lease)
                        return _receipt(request, authority, current, gate)
                    control = _draining(authority, control)
                    if "stop" in request.values and not custody.unknown and time.monotonic() < deadline:
                        request_cancellation(authority, custody, sent)
                    if custody.unknown or tainted or time.monotonic() >= deadline:
                        return _status(request, authority, control, custody)
                finally:
                    if lease >= 0:
                        # Close only this independent one-shot description.
                        # Durable exclusive/draining state stays closed.
                        os.close(lease)
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.05, remaining))
