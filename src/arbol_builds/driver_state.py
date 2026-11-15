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
    _exclusive,
    admission_fingerprint,
    archive_boot_custody,
    archive_terminal,
    canonical,
    canonical_uuid,
    custody_loss,
    decode,
    deployment_mutex,
    fields,
    lock_identity,
    normal_control,
    physical,
    private_directory,
    publish,
    publish_bytes,
    read,
    read_bytes,
    reconcile,
    remove,
    sha256,
    token,
    valid_hash,
    valid_token,
    validate,
    without_authority,
)
from .driver_payload import (
    DESCRIPTOR,
    SUBTREE,
    Gate,
    MetadataBackup,
    Payload,
    load,
    metadata_backup,
    metadata_document,
    metadata_marker,
    metadata_upgrade,
    optional_descriptor,
    pin_payloads,
    registered,
    request_binding,
    resolve_provider,
    verify_acceptance,
    verify_gate,
)
from .driver_process import (
    AdministrativeOutput,
    Guardian,
    boot_uuid,
    request_cancellation,
    run_administrative,
    supervise,
)
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
    if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
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
        descriptor = optional_descriptor(folder)
        if descriptor is None:
            continue
        if sha256(descriptor) == producer_digest:
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
            if not _boot_recovery_pending(authority, control):
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
        _recover_boot(request, boot, deadline)
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


def _immutable(path: Path, raw: bytes, *, limit: int = LIMIT) -> None:
    try:
        existing = read_bytes(path, limit=limit)
    except FileNotFoundError:
        publish_bytes(path, raw, limit=limit)
        return
    if existing != raw:
        raise Refusal("Immutable deployment evidence changed.")


def _rollout_folder(registry: Path, session: str, checkpoint: str, *, create: bool = False) -> Path:
    if not canonical_uuid(session) or not valid_token(checkpoint):
        raise Refusal("Invalid deployment identity.")
    folder = registry / ".driver-qualification"
    for name in ("deployments", session, checkpoint):
        folder = private_directory(folder / name, create=create)
    return folder


def _caller_assertion(raw: bytes, gate: Object) -> Object:
    value = decode(raw)
    fields(value, "version callers")
    callers = value["callers"]
    if not isinstance(callers, list):
        raise Refusal("Invalid disabled-caller assertion.")
    routes = {row["launcher"] for row in gate["components"]}
    names: list[str] = []
    for row in callers:
        if (not isinstance(row, dict) or set(row) != {"name", "route", "disabled"}
                or row["disabled"] is not True or row["route"] not in routes
                or not isinstance(row["name"], str) or not row["name"]
                or len(row["name"].encode("utf-8", "strict")) > 128
                or any(ord(character) < 32 or ord(character) == 127 for character in row["name"])):
            raise Refusal("Caller assertions contain only bounded names, registered routes and disabled true.")
        names.append(row["name"])
    if names != sorted(set(names)):
        raise Refusal("Disabled callers must have distinct lexical names.")
    return value


def _qualified_candidates(authorities: list[Authority]) -> list[Payload]:
    """Resolve declarations before staging; full acceptance follows installed hashes."""
    payloads: list[Payload] = []
    for authority in authorities:
        qualification = authority.read("qualification")
        if qualification["component"] != authority.component:
            raise Refusal("Deployment qualification component mismatch.")
        digest = qualification["acceptanceSha256"]
        raw = read_bytes(authority.shared / "acceptances" / (digest + ".json"))
        value = decode(raw)
        if sha256(raw) != digest or not valid_hash(value.get("producerPayloadSha256")):
            raise Refusal("Deployment acceptance digest mismatch.")
        matches: list[Payload] = []
        count = 0
        for folder in (authority.registry / authority.component).iterdir():
            count += 1
            if count > 100000:
                raise Refusal("Deployment registry exceeds its inventory bound.")
            if BUILD_PATTERN.fullmatch(folder.name) is None:
                continue
            descriptor = optional_descriptor(folder)
            if descriptor is None:
                continue
            if sha256(descriptor) == value["producerPayloadSha256"]:
                matches.append(registered(authority.registry, authority.component, folder.name))
        if len(matches) != 1:
            raise Refusal("Exact accepted deployment payload is unavailable.")
        payloads.append(matches[0])
    return payloads


def _rollout_record(path: Path) -> Object | None:
    try:
        value = read(path)
    except FileNotFoundError:
        return None
    validate("deployment", value)
    return value


def _rollout_bindings(authorities: list[Authority], record: Object, *, allow_exclusive: bool = False,
                      recovering: bool = False, reopening: Object | None = None,
                      allow_normal_activity: bool = False) -> list[Object]:
    rows: list[Object] = []
    for authority, expected in zip(authorities, record["components"], strict=True):
        control = authority.read("control")
        closed = (control["session"] == record["session"] and control["epoch"] == expected["epoch"]
                  and control["phase"] in (("draining", "exclusive") if allow_exclusive else ("draining",)))
        normal = False
        if reopening is not None:
            row = next(row for row in reopening["components"] if row["component"] == authority.component)
            normal = control == {"version": 1, "phase": "normal", "session": None, "epoch": row["nextEpoch"]}
        if not closed and not normal:
            raise Refusal("Deployment no longer has its unchanged closed or journaled normal tuple.")
        archived = authority.folder / "boot-archive" / record["checkpoint"] / "normal-admissions"
        if recovering and os.path.lexists(archived):
            active = authority.folder / "normal-admissions"
            if os.path.lexists(active):
                private_directory(active)
                if not allow_normal_activity and next(active.iterdir(), None) is not None:
                    raise Refusal("A new normal admission invalidates the boot checkpoint.")
            admissions_digest = admission_fingerprint(authority, folder=archived)
        elif recovering and allow_normal_activity:
            # A verified completed inventory binds the originally absent marker
            # directory; later normal admissions never reuse its boot authority.
            admissions_digest = sha256(canonical({"version": 1, "markers": []}))
        else:
            admissions_digest = admission_fingerprint(authority)
        rows.append({"component": authority.component, "epoch": expected["epoch"],
                     "controlLock": lock_identity(authority, "control.lock"),
                     "admissionLock": lock_identity(authority, "admission.lock"),
                     "admissionsSha256": admissions_digest})
    return rows


def _verify_rollout(registry: Path, authorities: list[Authority], record: Object, *,
                    reopening: Object | None = None, allow_normal_activity: bool = False) -> tuple[Path, Object]:
    if allow_normal_activity and record["phase"] != "complete":
        raise Refusal("A pending boot/reopen boundary cannot admit normal activity.")
    folder = _rollout_folder(registry, record["session"], record["checkpoint"])
    registry_digest = sha256(canonical(authorities[0].identity))
    if record["registrySha256"] != registry_digest:
        raise Refusal("Deployment registry identity changed.")
    gate_raw, callers_raw = read_bytes(folder / "manifest.json"), read_bytes(folder / "callers.json")
    gate = decode(gate_raw)
    _caller_assertion(callers_raw, gate)
    if any(row["component"] != expected["component"] or row["launcherSha256"] != expected["launcherSha256"]
           for row, expected in zip(record["components"], gate["components"], strict=True)):
        raise Refusal("Deployment component launcher hashes changed.")
    if (sha256(gate_raw) != record["gateSha256"] or sha256(callers_raw) != record["callersSha256"]
            or read_bytes(authorities[0].shared / "gate.json") != gate_raw
            or verify_gate(registry).digest != record["gateSha256"]):
        raise Refusal("Deployment gate/caller hashes changed.")
    checkpoint = read(folder / "checkpoint.json")
    fields(checkpoint, "version kind session checkpoint registrySha256 gateSha256 callersSha256 oldBoot components")
    expected = {"version": 1, "kind": "driver-closed-checkpoint",
                **{key: record[key] for key in ("session", "checkpoint", "registrySha256", "gateSha256", "callersSha256", "oldBoot")}}
    if any(checkpoint.get(key) != value for key, value in expected.items()):
        raise Refusal("Closed checkpoint identity changed.")
    recovery = _recovery_journal(folder, record)
    if checkpoint["components"] != _rollout_bindings(
            authorities, record, allow_exclusive=record["phase"] in ("boot-verified", "maintaining"),
            recovering=recovery is not None, reopening=reopening, allow_normal_activity=allow_normal_activity):
        raise Refusal("Closed authorities, lock inodes or normal admissions changed after checkpoint.")
    return folder, checkpoint


def _before_route(folder: Path, component: str, row: Object) -> tuple[bytes, int] | None:
    if row["beforeSha256"] is None:
        if row["beforeMode"] is not None:
            raise Refusal("Invalid absent launcher before-image.")
        return None
    raw = read_bytes(folder / "before" / (component + ".launcher"), limit=1024 * 1024)
    if sha256(raw) != row["beforeSha256"] or type(row["beforeMode"]) is not int:
        raise Refusal("Launcher before-image changed.")
    return raw, row["beforeMode"]


def _stage_rollout(request: Request, gate: Object, callers_raw: bytes, provider: Payload,
                   authorities: list[Authority], source_bytes: dict[str, bytes], old: Object | None,
                   build_pins: ExitStack) -> Object:
    from .launcher import default_record, read_records
    from .service import driver_route_bytes

    if old is not None and old["phase"] not in ("failed-closed", "complete"):
        raise Refusal("Resume the existing deployment before starting another checkpoint.")
    if old is not None and old["phase"] != "complete" and old["session"] != request.session:
        raise Refusal("A different deployment session owns the closed fence.")
    checkpoint, boot = token(), boot_uuid()
    folder = _rollout_folder(request.registry, request.session, checkpoint, create=True)
    before = private_directory(folder / "before", create=True)
    staged = private_directory(folder / "staged", create=True)
    gate_raw = canonical(gate)
    _immutable(folder / "manifest.json", gate_raw)
    _immutable(folder / "callers.json", callers_raw)
    try:
        old_gate = read_bytes(authorities[0].shared / "gate.json")
    except FileNotFoundError:
        old_gate = None
    if old_gate is not None:
        _immutable(before / "gate.json", old_gate)
    rows: list[Object] = []
    public: list[Object] = []
    for authority, route in zip(authorities, gate["components"], strict=True):
        control = authority.read("control")
        if control["phase"] != "normal" and control["session"] != request.session:
            raise Refusal("A different component maintenance session owns this deployment.")
        old_route = driver_route_bytes(Path(route["launcher"]))
        if old_route is not None:
            _immutable(before / (authority.component + ".launcher"), old_route[0], limit=1024 * 1024)
        selected = default_record(str(request.registry), read_records(str(request.registry), authority.component))
        selection: Object = {"version": 1, "component": authority.component,
                             "build": selected["build"] if selected is not None else None, "recordSha256": None}
        if selected is not None:
            descriptor = open_use_guard(str(request.registry), authority.component, selected["build"])
            build_pins.callback(os.close, descriptor)
            _use_current(authority, selected["build"], descriptor)
            raw = read_bytes(request.registry / authority.component / selected["build"] / "build.json")
            if decode(raw, exact=False) != selected or selected.get("prunedAt"):
                raise Refusal("Selected Build changed before its deployment pin.")
            selection["recordSha256"] = sha256(raw)
            _immutable(before / (authority.component + ".build.json"), raw)
        _immutable(before / (authority.component + ".selection.json"), canonical(selection))
        _immutable(staged / authority.component, source_bytes[authority.component], limit=1024 * 1024)
        rows.append({"component": authority.component, "beforeSha256": sha256(old_route[0]) if old_route else None,
                     "beforeMode": old_route[1] if old_route else None, "selectionSha256": sha256(canonical(selection))})
        public.append({"component": authority.component, "epoch": control["epoch"],
                       "launcherSha256": route["launcherSha256"], "closed": True})
    evidence = {"version": 1, "kind": "driver-rollout", "session": request.session, "checkpoint": checkpoint,
                "providerPayloadSha256": provider.digest, "oldGateSha256": sha256(old_gate) if old_gate else None,
                "components": rows}
    _immutable(folder / "rollout.json", canonical(evidence))
    # The required token identifies this staging attempt. It is not a usable
    # checkpoint until checkpoint.json and awaiting-boot are durably verified.
    record = {"version": 1, "kind": "driver-gate-deployment", "session": request.session,
              "registrySha256": sha256(canonical(authorities[0].identity)), "gateSha256": sha256(gate_raw),
              "callersSha256": sha256(callers_raw), "oldBoot": boot, "newBoot": None,
              "phase": "staged", "components": public, "checkpoint": checkpoint}
    validate("deployment", record)
    # Preserve prior taint bytes before the new unknown pre-gate baseline.
    for authority in authorities:
        try:
            taint = read_bytes(authority.folder / "taint.json")
        except FileNotFoundError:
            taint = None
        if taint is not None:
            _immutable(before / (authority.component + ".taint.json"), taint)
        control = authority.read("control")
        authority.write("control", {**control, "phase": "draining", "session": request.session})
        authority.write("taint", {"version": 1, "component": authority.component, "epoch": control["epoch"],
                                  "boot": boot, "reason": "initial-deployment", "invocation": token(), "payloadSha256": None})
    # Reference publication is guarded by all exact Build SH pins at the caller.
    publish(authorities[0].shared / "deployment.json", record)
    return record


def _rollback_rollout(registry: Path, authorities: list[Authority], record: Object) -> None:
    from .service import driver_route_bytes, publish_driver_route

    folder = _rollout_folder(registry, record["session"], record["checkpoint"])
    if (folder / "checkpoint.json").exists():
        raise Refusal("A durable checkpoint cannot roll back; restage a new closed boundary.")
    evidence = read(folder / "rollout.json")
    fields(evidence, "version kind session checkpoint providerPayloadSha256 oldGateSha256 components")
    if (evidence["kind"] != "driver-rollout" or evidence["session"] != record["session"]
            or evidence["checkpoint"] != record["checkpoint"] or not isinstance(evidence["components"], list)
            or len(evidence["components"]) != len(COMPONENTS)):
        raise Refusal("Invalid rollout before-image evidence.")
    gate = read(folder / "manifest.json")
    for authority, route, row in zip(authorities, gate["components"], evidence["components"], strict=True):
        if row.get("component") != authority.component:
            raise Refusal("Rollout before-image component changed.")
        previous = _before_route(folder, authority.component, row)
        current = driver_route_bytes(Path(route["launcher"]))
        staged = read_bytes(folder / "staged" / authority.component, limit=1024 * 1024)
        if sha256(staged) != route["launcherSha256"]:
            raise Refusal("Staged launcher changed during rollback.")
        if current == (staged, 0o755):
            publish_driver_route(Path(route["launcher"]), current, previous)
        elif current != previous:
            raise Refusal("Changed launcher cannot be overwritten during rollback.")
        # Deployment never edits Build records/default selection. Preserve their
        # exact before-images; never overwrite a concurrent Build's metadata.
        selection = read_bytes(folder / "before" / (authority.component + ".selection.json"))
        if sha256(selection) != row["selectionSha256"]:
            raise Refusal("Build selection evidence changed.")
    gate_path = authorities[0].shared / "gate.json"
    if evidence["oldGateSha256"] is None:
        if gate_path.exists():
            if sha256(read_bytes(gate_path)) != record["gateSha256"]:
                raise Refusal("Changed gate cannot be removed by rollback.")
            remove(gate_path)
    else:
        previous_raw = read_bytes(folder / "before" / "gate.json")
        if sha256(previous_raw) != evidence["oldGateSha256"]:
            raise Refusal("Prior gate evidence changed.")
        current_raw = read_bytes(gate_path)
        if current_raw not in (previous_raw, read_bytes(folder / "manifest.json")):
            raise Refusal("Changed gate cannot be overwritten by rollback.")
        publish_bytes(gate_path, previous_raw)


@handler("deploy")
def deploy(request: Request) -> Object:
    from .service import driver_launcher_source, driver_route_bytes, publish_driver_route

    provider = _provider(request)
    if not Path(__file__).resolve().is_relative_to(provider.root):
        raise Refusal("Deployment requires its exact immutable provider.")
    gate_raw = read_bytes(physical(request.values["manifest"], directory=False))
    gate = decode(gate_raw)
    if gate["providerPayloadSha256"] != provider.digest:
        raise Refusal("Deployment provider changed with its manifest.")
    callers_raw = read_bytes(physical(request.values["callers"], directory=False))
    _caller_assertion(callers_raw, gate)
    sources: dict[str, bytes] = {}
    for row in gate["components"]:
        route = Path(row["launcher"])
        if str(route) != row["launcher"] or route.name != row["component"]:
            raise Refusal("Deployment requires exact canonical component routes.")
        physical(route.parent)
        raw = driver_launcher_source(str(request.registry), row["component"], str(route), provider)
        if sha256(raw) != row["launcherSha256"]:
            raise Refusal("Gate launcher hash differs from publisher-generated bytes.")
        sources[row["component"]] = raw
    with deployment_mutex(request.registry):
        authorities = [Authority(request.registry, component) for component in COMPONENTS]
        # A global independent lock serializes the initial stable inode creation.
        for authority in authorities:
            authority.initialize(request.session, token())
        payloads = _qualified_candidates(authorities)
        with pin_payloads(request.registry, [provider, *payloads]), ExitStack() as stack, ExitStack() as build_pins:
            for authority in authorities:
                stack.enter_context(authority.mutex())
            path = authorities[0].shared / "deployment.json"
            record = _rollout_record(path)
            if record is not None and record["phase"] != "complete" and record["session"] != request.session:
                raise Refusal("A different deployment owns the closed fence.")
            same = (record is not None and record["session"] == request.session
                    and record["gateSha256"] == sha256(gate_raw) and record["callersSha256"] == sha256(callers_raw))
            if record is not None and record["phase"] not in ("failed-closed", "complete") and not same:
                raise Refusal("Changed deployment inputs require a new closed rollout after failure.")
            if same and record is not None and record["phase"] == "complete":
                _verified_complete(request.registry, authorities, payloads, verify_gate(request.registry), record)
                return {"version": 1, "session": request.session, "phase": "complete", "callersMayEnable": True}
            if record is None or record["phase"] in ("failed-closed", "complete"):
                record = _stage_rollout(request, gate, callers_raw, provider, authorities, sources, record, build_pins)
            assert record is not None
            folder = _rollout_folder(request.registry, request.session, record["checkpoint"])
            try:
                if record["phase"] in ("awaiting-boot", "boot-verified", "maintaining"):
                    if record["phase"] == "awaiting-boot":
                        _verify_rollout(request.registry, authorities, record)
                    else:
                        reopening = _reopen_record(folder, record)
                        _verify_rollout(request.registry, authorities, record, reopening=reopening)
                        recovery = _recovery_journal(folder, record)
                        if recovery is None or recovery["phase"] != "complete":
                            raise Refusal("Verified boot phase lacks completed recovery evidence.")
                        for authority in authorities:
                            _verify_boot_archive(authority, record, record["newBoot"])
                    return {"version": 1, "session": request.session, "phase": record["phase"],
                            "checkpoint": record["checkpoint"], "callersMayEnable": False}
                evidence = read(folder / "rollout.json")
                if evidence.get("providerPayloadSha256") != provider.digest:
                    raise Refusal("Staged provider identity changed.")
                _rollout_bindings(authorities, record)
                publish_bytes(authorities[0].shared / "gate.json", gate_raw)
                for authority, route, before in zip(authorities, gate["components"], evidence["components"], strict=True):
                    staged = read_bytes(folder / "staged" / authority.component, limit=1024 * 1024)
                    if staged != sources[authority.component] or sha256(staged) != route["launcherSha256"]:
                        raise Refusal("Staged launcher identity changed.")
                    target = Path(route["launcher"])
                    current = driver_route_bytes(target)
                    desired = (staged, 0o755)
                    if current != desired:
                        previous = _before_route(folder, authority.component, before)
                        if current != previous:
                            raise Refusal("Launcher changed after staging.")
                        publish_driver_route(target, previous, desired)
                if verify_gate(request.registry).digest != record["gateSha256"]:
                    raise Refusal("Installed all-four gate differs from the staged tuple.")
                for authority, payload in zip(authorities, payloads, strict=True):
                    verify_acceptance(authority, payload)
                record = {**record, "phase": "closed-installed"}
                publish(path, record)
                checkpoint_path = folder / "checkpoint.json"
                if not checkpoint_path.exists():
                    if boot_uuid() != record["oldBoot"]:
                        raise Refusal("Kernel changed before the all-four checkpoint; restage closed.")
                    checkpoint = {"version": 1, "kind": "driver-closed-checkpoint",
                                  **{key: record[key] for key in ("session", "checkpoint", "registrySha256", "gateSha256", "callersSha256", "oldBoot")},
                                  "components": _rollout_bindings(authorities, record)}
                    _immutable(checkpoint_path, canonical(checkpoint))
                _verify_rollout(request.registry, authorities, record)
                record = {**record, "phase": "awaiting-boot"}
                publish(path, record)
                return {"version": 1, "session": request.session, "phase": "awaiting-boot",
                        "checkpoint": record["checkpoint"], "callersMayEnable": False}
            except BaseException:
                # The public phase always remains closed. Only a pre-checkpoint
                # failure can restore exact preserved bytes; no caller is enabled.
                publish(path, {**record, "phase": "failed-closed"})
                if not (folder / "checkpoint.json").exists():
                    _rollback_rollout(request.registry, authorities, record)
                raise


def _recovery_journal(folder: Path, record: Object) -> Object | None:
    try:
        value = read(folder / "recovery.json")
    except FileNotFoundError:
        return None
    fields(value, "version kind session checkpoint oldBoot newBoot phase components")
    if (value["kind"] != "driver-boot-recovery" or value["phase"] not in ("prepared", "complete")
            or any(value[key] != record[key] for key in ("session", "checkpoint", "oldBoot"))
            or not canonical_uuid(value["newBoot"]) or value["newBoot"] == value["oldBoot"]
            or (record["newBoot"] is not None and value["newBoot"] != record["newBoot"])
            or not isinstance(value["components"], list) or len(value["components"]) != len(COMPONENTS)):
        raise Refusal("Boot recovery journal identity changed.")
    for component, row in zip(COMPONENTS, value["components"], strict=True):
        if (not isinstance(row, dict) or set(row) != {"component", "phase"}
                or row["component"] != component or row["phase"] not in ("pending", "archived")):
            raise Refusal("Boot recovery journal component changed.")
    if value["phase"] == "complete" and any(row["phase"] != "archived" for row in value["components"]):
        raise Refusal("Incomplete boot recovery cannot claim completion.")
    return value


def _boot_recovery_pending(authority: Authority, control: Object) -> bool:
    """Preserve a verified closed checkpoint before its first recovery journal.

    The caller holds this component mutex; rollout mutation/recovery requires
    all four. This only defers custody interpretation, never proves a new boot
    or grants exclusive admission. Drain retains that verification/archival.
    """
    record = _rollout_record(authority.shared / "deployment.json")
    if record is None or record["phase"] != "awaiting-boot":
        return False
    if control["phase"] != "draining" or control["session"] != record["session"]:
        raise Refusal("Pending boot recovery has a different closed session.")
    authorities = [authority if component == authority.component else Authority(authority.registry, component)
                   for component in COMPONENTS]
    folder, _ = _verify_rollout(authority.registry, authorities, record)
    journal = _recovery_journal(folder, record)
    if record["newBoot"] is not None and journal is None:
        raise Refusal("Published boot recovery has no matching private journal.")
    # A valid awaiting-boot checkpoint protects the old custody/taint even when
    # no drain has yet published recovery.json. Reconciliation against a new
    # boot here would replace that evidence before drain can archive it.
    return True


def _recover_boot(request: Request, current_boot: str, deadline: float) -> None:
    """Production drain-only path: current_boot comes solely from boot_uuid().

    There is no command option, environment override or simulated boot provider.
    This proves only old local process termination on the qualified platform;
    Driver metadata/vendor recovery and continuity checks remain independent.
    """
    if not canonical_uuid(current_boot):
        raise Refusal("Kernel boot identity is unavailable.")
    shared = request.registry / ".driver-qualification"
    observed = _rollout_record(shared / "deployment.json")
    if observed is None or observed["phase"] == "complete":
        return
    if observed["session"] != request.session:
        raise Refusal("A different closed deployment owns boot recovery.")
    if observed["phase"] not in ("awaiting-boot", "boot-verified", "maintaining"):
        raise Refusal("Complete or restage the closed deployment before drain.")
    if current_boot == observed["oldBoot"]:
        raise Refusal("A genuine kernel boot transition after the closed checkpoint is required.")
    with deployment_mutex(request.registry):
        authorities = [Authority(request.registry, component) for component in COMPONENTS]
        payloads = _qualified_candidates(authorities)
        gate = verify_gate(request.registry)
        with pin_payloads(request.registry, [gate.provider, *payloads]), ExitStack() as stack:
            for authority in authorities:
                stack.enter_context(authority.mutex(seconds=max(0, deadline - time.monotonic())))
            record = _rollout_record(shared / "deployment.json")
            if record != observed:
                raise Refusal("Deployment changed during boot recovery.")
            folder = _rollout_folder(request.registry, record["session"], record["checkpoint"])
            journal = _recovery_journal(folder, record)
            if journal is not None and journal["newBoot"] != current_boot:
                publish(shared / "deployment.json", {**record, "phase": "failed-closed"})
                raise Refusal("Kernel changed again during recovery; restage a fresh closed boundary.")
            if record["newBoot"] is not None and journal is None:
                raise Refusal("Published boot recovery has no matching private journal.")
            try:
                _verify_rollout(request.registry, authorities, record)
                for authority, payload in zip(authorities, payloads, strict=True):
                    verify_acceptance(authority, payload)
                if record["phase"] in ("boot-verified", "maintaining"):
                    if (journal is None or journal["phase"] != "complete" or record["newBoot"] != current_boot):
                        raise Refusal("Boot verification lacks its exact completed archive chain.")
                    for authority in authorities:
                        _verify_boot_archive(authority, record, current_boot)
                    return
                # Acquire every independent EX lease before publishing/clearing
                # any old obligation. New-boot holders remain unresolved.
                leases: list[int] = []
                for authority in authorities:
                    descriptor = authority.lease(exclusive=True)
                    stack.callback(os.close, descriptor)
                    leases.append(descriptor)
                if journal is None:
                    journal = {"version": 1, "kind": "driver-boot-recovery",
                               **{key: record[key] for key in ("session", "checkpoint", "oldBoot")},
                               "newBoot": current_boot, "phase": "prepared",
                               "components": [{"component": component, "phase": "pending"} for component in COMPONENTS]}
                    _immutable(folder / "recovery.json", canonical(journal))
                record = {**record, "newBoot": current_boot}
                publish(shared / "deployment.json", record)
                for index, (authority, descriptor) in enumerate(zip(authorities, leases, strict=True)):
                    archive_boot_custody(authority, descriptor, record, current_boot)
                    _verify_boot_archive(authority, record, current_boot)
                    rows = [dict(row) for row in journal["components"]]
                    rows[index]["phase"] = "archived"
                    journal = {**journal, "components": rows}
                    publish(folder / "recovery.json", journal)
                _verify_rollout(request.registry, authorities, record)
                journal = {**journal, "phase": "complete"}
                publish(folder / "recovery.json", journal)
                publish(shared / "deployment.json", {**record, "phase": "boot-verified"})
            except BlockingIOError:
                # Existing independent leases are not failure/termination proof.
                # Preserve the same recoverable checkpoint for a later call.
                raise Refusal("An independent component lease still blocks boot recovery.") from None
            except Exception:
                # A prepared journal can resume a crash. Invalid evidence is
                # never converted into an empty successful receipt.
                raise


def _verify_boot_archive(authority: Authority, record: Object, current_boot: str, *, allow_normal: bool = False) -> None:
    destination = private_directory(authority.folder / "boot-archive" / record["checkpoint"])
    inventory = read(destination / "inventory.json")
    fields(inventory, "version kind component session checkpoint oldBoot newBoot entries")
    complete = read(destination / "complete.json")
    if (inventory["kind"] != "driver-boot-custody" or inventory["component"] != authority.component
            or any(inventory[key] != record[key] for key in ("session", "checkpoint", "oldBoot"))
            or inventory["newBoot"] != current_boot
            or complete != {"version": 1, "kind": "driver-boot-custody-complete",
                            "inventorySha256": sha256(canonical(inventory))}):
        raise Refusal("Completed boot archive identity changed.")
    names = ("writers", "handoffs", "normal-admissions", "archive", "taint.json", "maintenance.json")
    if not isinstance(inventory["entries"], list) or len(inventory["entries"]) != len(names):
        raise Refusal("Boot archive inventory changed.")
    for name, row in zip(names, inventory["entries"], strict=True):
        if (not isinstance(row, dict) or set(row) != {"name", "present", "device", "inode", "sha256"}
                or row["name"] != name or type(row["present"]) is not bool):
            raise Refusal("Boot archive entry changed.")
        target = destination / name
        if row["present"]:
            if (type(row["device"]) is not int or row["device"] < 0
                    or type(row["inode"]) is not int or row["inode"] < 0):
                raise Refusal("Boot archive entry identity is invalid.")
            info = target.lstat()
            if (info.st_dev, info.st_ino) != (row["device"], row["inode"]):
                raise Refusal("Boot archive entry identity changed.")
            if name in names[:4]:
                private_directory(target)
                if row["sha256"] is not None:
                    raise Refusal("Invalid directory archive hash.")
            elif not valid_hash(row["sha256"]) or sha256(read_bytes(target)) != row["sha256"]:
                raise Refusal("Boot archive metadata bytes changed.")
        elif (any(row[key] is not None for key in ("device", "inode", "sha256")) or os.path.lexists(target)):
            raise Refusal("Absent boot archive entry changed.")
    for name in ("writers", "handoffs", "normal-admissions"):
        folder = private_directory(authority.folder / name)
        if not allow_normal and next(folder.iterdir(), None) is not None:
            raise Refusal("Unexpected post-checkpoint writer/admission remains fenced.")
    if os.path.lexists(authority.folder / "taint.json"):
        taint = authority.read("taint")
        if not allow_normal or taint["component"] != authority.component or taint["reason"] != "legacy":
            raise Refusal("A new custody taint cannot be cleared by an old boot checkpoint.")


@dataclass
class Prepared:
    request: Request
    authority: Authority
    payload: Payload
    gate: Gate
    descriptor: int
    folder: Path
    context_path: Path
    context: Object
    binding: Object
    operation: Object
    cached_result: Object | None


def _state_format(directory: Path, *, restore: bool = False) -> int | None:
    try:
        raw = read_bytes(directory / "format")
    except FileNotFoundError:
        if restore:
            return None
        raise Refusal("Maintenance requires existing supported Driver state.") from None
    spelling = raw.strip()
    if re.fullmatch(rb"[1-9][0-9]*", spelling) and spelling not in (b"1", b"2"):
        raise Refusal("Driver state is newer than this maintenance provider.")
    number = {b"1": 1, b"2": 2}.get(spelling)
    if number is None and not restore:
        raise Refusal("Driver state format is malformed.")
    return number


def _root_generation(directory: Path) -> str:
    value = read(directory / "identity.json")
    fields(value, "version generation")
    if not valid_token(value["generation"]):
        raise Refusal("Driver root identity is malformed.")
    return str(value["generation"])


def _separate_metadata_roots(registry: Path, state: Path, backup: Path, source: Path | None) -> None:
    paths = [state, backup, *([source] if source is not None else [])]
    for index, path in enumerate(paths):
        if path.is_relative_to(registry) or registry.is_relative_to(path):
            raise Refusal("Driver state/backup roots must be outside the private registry.")
        for other in paths[:index]:
            if path.is_relative_to(other) or other.is_relative_to(path):
                raise Refusal("Driver state/source/output roots must be disjoint.")


def _session_folder(authority: Authority, session: str) -> Path:
    folder = private_directory(authority.folder / "sessions" / session, create=True)
    for name in ("contexts", "attempts"):
        private_directory(folder / name, create=True)
    return folder


def _context_from_operation(operation: Object) -> Object:
    validate("operation", operation)
    context = {key: value for key, value in operation.items() if key not in ("phase", "sourceSha256", "backupSha256")}
    validate("context", context)
    return context


def _read_optional(path: Path, kind: str) -> Object | None:
    try:
        value = read(path)
    except FileNotFoundError:
        return None
    validate(kind, value)
    return value


def _attempt_history(folder: Path, context: Object, *, operation: Object | None = None,
                     result: Object | None = None) -> Path:
    """Preserve an exact predecessor before replacing any active pointer."""
    attempt = context["attempt"]
    if not valid_token(attempt):
        raise Refusal("Invalid previous maintenance attempt.")
    destination = private_directory(folder / "attempts" / attempt, create=True)
    context_raw = read_bytes(folder / "contexts" / (attempt + ".json"))
    if decode(context_raw) != context:
        raise Refusal("Previous immutable context changed.")
    binding_raw = read_bytes(folder / "contexts" / (attempt + ".request.json"))
    request_binding(decode(binding_raw), context)
    _immutable(destination / "context.json", context_raw)
    _immutable(destination / "request.json", binding_raw)
    if operation is not None:
        if _context_from_operation(operation) != context:
            raise Refusal("Previous operation/context mismatch.")
        _immutable(destination / "operation.json", canonical(operation))
    if result is not None:
        validate("result", result)
        if (any(result[key] != context[key] for key in ("component", "session", "epoch", "attempt", "operation", "payloadSha256", "generation"))
                or result["stateDirectorySha256"] != sha256(context["stateDirectory"].encode("utf-8"))
                or not valid_hash(result["backupSha256"])
                or (context["operation"] == "identity-recover" and result["subscription"] != context["subscription"])
                or (operation is not None and result["backupSha256"] != operation["backupSha256"])):
            raise Refusal("Previous result/context mismatch.")
        _immutable(destination / "result.json", canonical(result))
    return destination


def _make_binding(request: Request, context: Object, payload: Payload, backup: Path, source: Path | None) -> Object:
    value = {"version": 1, "kind": "driver-maintenance-request",
             **{key: context[key] for key in ("component", "session", "epoch", "attempt", "payloadSha256", "acceptanceSha256", "stateDirectory", "operation")},
             "contextSha256": sha256(canonical(context)), "build": payload.build,
             "backup": str(backup), "source": str(source) if source is not None else None}
    if context["operation"] == "identity-recover":
        value["subscription"] = request.values["subscription"]
    request_binding(value, context)
    return value


def _closed_attempt(authority: Authority, request: Request, payload: Payload, gate: Gate,
                    descriptor: int) -> tuple[Object, str]:
    _recheck(authority, payload, gate)
    _exclusive(authority, descriptor)
    control = _control(authority, request.session, closed=True)
    if control["phase"] != "exclusive" or _tainted(authority):
        raise Refusal("Exclusive drained admission is required before execution.")
    custody = reconcile(authority, control=control)
    if not custody.resolved:
        raise Refusal("Unresolved metadata custody remains fenced.")
    deployment = _rollout_record(authority.shared / "deployment.json")
    if deployment is not None and deployment["phase"] != "complete" and (
            deployment["session"] != request.session or deployment["phase"] not in ("boot-verified", "maintaining")):
        raise Refusal("All-four deployment has not verified its closed boot boundary.")
    raw = read_bytes(authority.folder / "maintenance.json")
    receipt = decode(raw)
    validate("maintenance", receipt)
    expected = {"version": 1, "kind": "driver-state-maintenance", "component": request.component,
                "session": request.session, "epoch": control["epoch"], "phase": "exclusive", "gateSha256": gate.digest}
    if receipt != expected:
        raise Refusal("Maintenance receipt does not match current exclusive admission.")
    return control, sha256(raw)


def _predecessor(directory: Path, folder: Path) -> None:
    try:
        marker = metadata_marker(read(directory / "identity-maintenance.json"))
    except FileNotFoundError:
        return
    if marker["phase"] != "complete":
        raise Refusal("Resume the exact pending attempt or explicitly restore verified metadata.")
    history = folder / "attempts" / marker["attempt"]
    previous = read(history / "result.json")
    validate("result", previous)
    operation = read(history / "operation.json")
    context = _context_from_operation(operation)
    if (any(context[key] != marker[key] for key in ("component", "session", "epoch", "operation", "attempt", "payloadSha256", "generation"))
            or operation["sourceSha256"] != marker["sourceSha256"] or operation["backupSha256"] != marker["backupSha256"]):
        raise Refusal("Completed predecessor lacks its exact operation/marker chain.")
    if (any(previous[key] != marker[key] for key in ("component", "session", "epoch", "operation", "attempt", "payloadSha256", "generation", "backupSha256"))
            or previous["stateDirectorySha256"] != sha256(str(directory).encode("utf-8"))):
        raise Refusal("Completed predecessor lacks its exact preserved result.")


def _fresh_generation(request: Request, state: Path, source: MetadataBackup | None) -> str:
    operation = request.values["operation"]
    number = _state_format(state, restore=operation == "restore")
    if operation == "restore":
        assert source is not None
        previous: set[str] = set()
        if source.contents["identity.json"] is not None:
            previous.add(str(metadata_document("identity.json", source.contents["identity.json"])["generation"]))
        try:
            previous.add(_root_generation(state))
        except (OSError, ValueError):
            pass  # The child preserves malformed current metadata before replacement.
        generation = token()
        while generation in previous:
            generation = token()
        return generation
    journal_path = state / "identity-upgrade.json"
    if os.path.lexists(journal_path):
        raise Refusal("Resume the exact original conversion attempt or explicitly restore metadata.")
    if number == 2:
        current = _root_generation(state)
        if operation != "identity-reset":
            return current
        generation = token()
        while generation == current:
            generation = token()
        return generation
    if operation != "upgrade" or number != 1:
        raise Refusal("This maintenance operation requires valid format 2.")
    return token()


@contextmanager
def prepare_execute(request: Request) -> Iterator[Prepared]:
    """No child or state mutation: bind a recoverable attempt under a live EX lease."""
    with _component(request) as (authority, payload, gate):
        if request.values["build"] != payload.build:
            raise Refusal("Execute requires the exact selected qualified Build.")
        state = private_directory(physical(request.values["state-dir"]))
        backup = private_directory(physical(request.values["backup"]))
        source_path = private_directory(physical(request.values["source"])) if "source" in request.values else None
        _separate_metadata_roots(request.registry, state, backup, source_path)
        descriptor = -1
        try:
            with authority.mutex():
                descriptor = authority.lease(exclusive=True)
                control, receipt_digest = _closed_attempt(authority, request, payload, gate, descriptor)
            # The independent EX admission spans bounded metadata verification,
            # immutable reference publication, future child, and acknowledgement.
            source = metadata_backup(source_path, source=True) if source_path is not None else None
            source_digest = source.digest if source is not None else None
            with authority.mutex():
                current, current_receipt = _closed_attempt(authority, request, payload, gate, descriptor)
                if current != control or current_receipt != receipt_digest:
                    raise Refusal("Exclusive admission changed during attempt preparation.")
                folder = _session_folder(authority, request.session)
                pending = _read_optional(folder / "operation.json", "operation")
                result = _read_optional(folder / "result.json", "result")
                old_context: Object | None = None
                old_operation: Object | None = None
                if pending is not None:
                    old_operation = pending
                    old_context = _context_from_operation(pending)
                elif result is not None:
                    old_context = read(folder / "contexts" / (result["attempt"] + ".json"))
                    validate("context", old_context)
                    old_operation = read(folder / "attempts" / result["attempt"] / "operation.json")
                    if _context_from_operation(old_operation) != old_context:
                        raise Refusal("Completed attempt lacks its exact preserved operation.")
                resume = False
                binding: Object
                if old_context is not None:
                    binding = read(folder / "contexts" / (old_context["attempt"] + ".request.json"))
                    request_binding(binding, old_context)
                    same_selector = (old_context["stateDirectory"] == str(state)
                                     and old_context["operation"] == request.values["operation"]
                                     and (old_context["operation"] != "identity-recover"
                                          or old_context["subscription"] == request.values.get("subscription")))
                    incoming = _make_binding(request, old_context, payload, backup, source_path) if same_selector else None
                    same = (binding == incoming and same_selector
                            and old_context["component"] == request.component and old_context["session"] == request.session
                            and old_context["epoch"] == control["epoch"] and old_context["gateSha256"] == gate.digest
                            and old_context["payloadSha256"] == payload.digest and old_context["registry"] == str(request.registry)
                            and old_context["receiptSha256"] == receipt_digest
                            and old_context["acceptanceSha256"] == authority.read("qualification")["acceptanceSha256"])
                    if same:
                        assert old_operation is not None
                        if old_operation["sourceSha256"] != source_digest:
                            raise Refusal("Resumed source manifest changed.")
                        context, operation = old_context, dict(old_operation)
                        resume = True
                    else:
                        if old_context["stateDirectory"] != str(state):
                            raise Refusal("Complete the current target before selecting another state directory.")
                        if pending is not None and request.values["operation"] != "restore":
                            raise Refusal("Only explicit restore may abandon a different pending attempt.")
                        _attempt_history(folder, old_context, operation=old_operation, result=result)
                if not resume:
                    if next(backup.iterdir(), None) is not None:
                        raise Refusal("A fresh maintenance attempt requires an empty private output archive.")
                    if request.values["operation"] != "restore":
                        _predecessor(state, folder)
                    generation = _fresh_generation(request, state, source)
                    context = {"version": 1, "kind": "driver-state-context", "component": request.component,
                               "session": request.session, "epoch": control["epoch"], "gateSha256": gate.digest,
                               "payloadSha256": payload.digest, "stateDirectory": str(state),
                               "operation": request.values["operation"], "attempt": token(), "receiptSha256": receipt_digest,
                               "registry": str(request.registry), "acceptanceSha256": authority.read("qualification")["acceptanceSha256"],
                               "generation": generation}
                    if context["operation"] == "identity-recover":
                        context["subscription"] = request.values["subscription"]
                    validate("context", context)
                    operation = {**context, "phase": "pending", "sourceSha256": source_digest, "backupSha256": None}
                    binding = _make_binding(request, context, payload, backup, source_path)
                else:
                    _state_format(state, restore=context["operation"] == "restore")
                    before = backup / "before" / "manifest.json"
                    if os.path.lexists(before):
                        archive = metadata_backup(backup / "before")
                        if operation["backupSha256"] not in (None, archive.digest):
                            raise Refusal("Resumed immutable before-manifest changed.")
                        operation["backupSha256"] = archive.digest
                    elif operation["backupSha256"] is not None:
                        raise Refusal("Resumed immutable before-manifest is missing.")
                    if context["operation"] == "upgrade" and os.path.lexists(state / "identity-upgrade.json"):
                        journal = metadata_upgrade(read(state / "identity-upgrade.json"))
                        if (journal["generation"] != context["generation"] or journal["backup"] != str(backup)
                                or journal["backupSha256"] != operation["backupSha256"]):
                            raise Refusal("Original conversion journal/generation/archive mismatch.")
                    if context["operation"] == "identity-recover" and (
                            _state_format(state) != 2 or _root_generation(state) != context["generation"]):
                        raise Refusal("Identity recovery root generation changed.")
                validate("operation", operation)
                context_path = folder / "contexts" / (context["attempt"] + ".json")
                # Exact Build pins are already held by _component; they precede
                # this mutex and every new durable context/request/operation ref.
                _immutable(context_path, canonical(context))
                _immutable(folder / "contexts" / (context["attempt"] + ".request.json"), canonical(binding))
                if not resume and result is not None:
                    remove(folder / "result.json")
                    result = None
                if result is None or pending is not None:
                    publish(folder / "operation.json", operation)
                prepared = Prepared(request, authority, payload, gate, descriptor, folder, context_path,
                                    context, binding, operation, result)
            yield prepared
        finally:
            if descriptor >= 0:
                os.close(descriptor)


def supervise_execute(prepared: Prepared) -> AdministrativeOutput:
    """Invoke no child until exact durable context/request/pending tuples recheck."""
    if prepared.cached_result is not None:
        raise Refusal("Validate the durable result instead of replaying a completed child.")

    def check() -> None:
        authority = prepared.authority
        with authority.mutex():
            control, receipt_digest = _closed_attempt(authority, prepared.request, prepared.payload,
                                                      prepared.gate, prepared.descriptor)
            deployment = _rollout_record(authority.shared / "deployment.json")
            if deployment is not None and deployment["registrySha256"] != sha256(canonical(authority.identity)):
                raise Refusal("Administrative registry identity changed.")
            if (control["epoch"] != prepared.context["epoch"] or receipt_digest != prepared.context["receiptSha256"]
                    or read(prepared.context_path) != prepared.context
                    or read(prepared.folder / "contexts" / (prepared.context["attempt"] + ".request.json")) != prepared.binding
                    or read(prepared.folder / "operation.json") != prepared.operation):
                raise Refusal("Administrative attempt changed before spawn.")
            request_binding(prepared.binding, prepared.context)

    return run_administrative(prepared.payload, prepared.context, prepared.binding, prepared.descriptor,
                              prepared.context_path, check)


def _pending_scope(context: Object, *, marker_absent: bool = False) -> None:
    """Read only declared identity metadata, preserving unrelated pending evidence."""
    directory = private_directory(physical(context["stateDirectory"]))
    if _state_format(directory) != 2 or _root_generation(directory) != context["generation"]:
        raise Refusal("Completed maintenance lacks the exact format/root generation.")
    if os.path.lexists(directory / "identity-upgrade.json"):
        raise Refusal("An unresolved root conversion journal remains fenced.")
    if marker_absent and os.path.lexists(directory / "identity-maintenance.json"):
        raise Refusal("A later root maintenance marker cannot consume an earlier result.")
    subscriptions = directory / "subscriptions"
    if not os.path.lexists(subscriptions):
        return
    private_directory(subscriptions)
    count = 0
    for folder in subscriptions.iterdir():
        count += 1
        if count > 100000 or SUBSCRIPTION.fullmatch(folder.name) is None:
            raise Refusal("Unsafe Subscription identity metadata.")
        private_directory(folder)
        for name in ("identity.json", "identity-pending.json"):
            path = folder / name
            try:
                raw = read_bytes(path)
            except FileNotFoundError:
                continue
            metadata_document("subscriptions/" + folder.name + "/" + name, raw)
            if name == "identity-pending.json" and (
                    context["operation"] != "identity-recover" or folder.name == context["subscription"]):
                raise Refusal("An operation-relevant Subscription journal remains fenced.")


def _complete_marker(context: Object, operation: Object, backup_digest: str, raw: bytes) -> Object:
    marker = metadata_marker(decode(raw))
    expected = {"version": 1, **{key: context[key] for key in (
        "component", "session", "epoch", "operation", "attempt", "payloadSha256", "generation")},
        "phase": "complete", "sourceSha256": operation["sourceSha256"], "backupSha256": backup_digest}
    if marker != expected:
        raise Refusal("Local maintenance marker does not settle the exact pending attempt.")
    return marker


def _result_value(context: Object, backup_digest: str) -> Object:
    result = {"version": 1, "kind": "driver-state-result", **{key: context[key] for key in (
        "component", "session", "epoch", "operation", "attempt", "payloadSha256", "generation")},
        "stateDirectorySha256": sha256(context["stateDirectory"].encode("utf-8")),
        "format": 2, "status": "complete", "backupSha256": backup_digest}
    if context["operation"] == "identity-recover":
        result["subscription"] = context["subscription"]
    validate("result", result)
    return result


def _archive_observation(prepared: Prepared) -> str:
    backup = private_directory(physical(prepared.binding["backup"]))
    before = metadata_backup(backup / "before")
    if prepared.operation["backupSha256"] not in (None, before.digest):
        raise Refusal("Before-manifest does not match its immutable attempt.")
    if prepared.context["operation"] == "restore":
        source = metadata_backup(private_directory(physical(prepared.binding["source"])), source=True)
        if source.digest != prepared.operation["sourceSha256"]:
            raise Refusal("Restore source changed before acknowledgement.")
        conversion = backup / "conversion-before"
        if source.manifest["format"] == 1:
            if metadata_backup(conversion).manifest["format"] != 1:
                raise Refusal("Format1 restore lacks its immutable conversion before-image.")
        elif os.path.lexists(conversion):
            raise Refusal("Format2 restore has an unexpected conversion before-image.")
    elif prepared.operation["sourceSha256"] is not None:
        raise Refusal("Unexpected maintenance source binding.")
    if prepared.context["operation"] == "identity-recover":
        name = "subscriptions/" + prepared.context["subscription"] + "/identity-pending.json"
        original = before.contents.get(name)
        if before.manifest["format"] != 2 or original is None:
            raise Refusal("Targeted recovery lacks its immutable original journal.")
        pending = metadata_document(name, original)
        sidecar_name = "subscriptions/" + prepared.context["subscription"] + "/identity.json"
        sidecar = metadata_document(sidecar_name, read_bytes(Path(prepared.context["stateDirectory"]) / sidecar_name))
        if sidecar != {"version": 1, "witness": pending["witness"], "state": "retired"}:
            raise Refusal("Targeted recovery has not durably retired the original witness.")
    return before.digest


def _child_result(output: AdministrativeOutput, context: Object) -> None:
    if output.returncode != 0 or not 0 < len(output.stdout) <= LIMIT:
        raise Refusal("Administrative child did not return one bounded success.")
    value = decode(output.stdout, exact=False)
    fields(value, "version format generation maintenance")
    expected = {"version": 1, "format": 2, "generation": context["generation"],
                "maintenance": {key: context[key] for key in (
                    "component", "session", "epoch", "operation", "attempt", "payloadSha256")}}
    expected["maintenance"]["stateDirectorySha256"] = sha256(context["stateDirectory"].encode("utf-8"))
    if context["operation"] == "identity-recover":
        expected["maintenance"]["subscription"] = context["subscription"]
    if type(value["format"]) is not int or value != expected:
        raise Refusal("Administrative result tuple/generation mismatch.")


def settle_execute(prepared: Prepared, output: AdministrativeOutput | None) -> Object:
    """Ack only exact completed state; write result before retiring pending pointer."""
    if output is not None:
        _child_result(output, prepared.context)
    elif prepared.cached_result is None:
        raise Refusal("Neither child success nor a durable same-attempt result exists.")
    digest = _archive_observation(prepared)
    state = Path(prepared.context["stateDirectory"])
    marker_raw = read_bytes(state / "identity-maintenance.json")
    _complete_marker(prepared.context, prepared.operation, digest, marker_raw)
    _pending_scope(prepared.context)
    result = _result_value(prepared.context, digest)
    if prepared.cached_result is not None and prepared.cached_result != result:
        raise Refusal("Durable result does not match the exact current attempt.")
    authority = prepared.authority
    with authority.mutex():
        control, receipt = _closed_attempt(authority, prepared.request, prepared.payload, prepared.gate, prepared.descriptor)
        if control["epoch"] != prepared.context["epoch"] or receipt != prepared.context["receiptSha256"]:
            raise Refusal("Exclusive admission changed before acknowledgement.")
        if (read(prepared.context_path) != prepared.context
                or read(prepared.folder / "contexts" / (prepared.context["attempt"] + ".request.json")) != prepared.binding):
            raise Refusal("Immutable attempt changed before acknowledgement.")
        active = _read_optional(prepared.folder / "operation.json", "operation")
        if active is not None and active != prepared.operation:
            raise Refusal("A later pending operation cannot consume earlier output.")
        if active is None and prepared.cached_result is None:
            raise Refusal("Pending attempt disappeared before acknowledgement.")
        operation = {**prepared.operation, "backupSha256": digest}
        if active is not None:
            publish(prepared.folder / "operation.json", operation)
        # These observations occur under the same retained EX description; a
        # failed acknowledgement never runs a new rotation or reopens admission.
        if read_bytes(state / "identity-maintenance.json") != marker_raw:
            raise Refusal("Complete marker changed before acknowledgement.")
        _pending_scope(prepared.context)
        destination = _attempt_history(prepared.folder, prepared.context, operation=operation)
        _immutable(destination / "marker.json", marker_raw)
        path = prepared.folder / "result.json"
        previous = _read_optional(path, "result")
        if previous is not None and previous != result:
            raise Refusal("A different result already owns this active pointer.")
        if previous is None:
            publish(path, result)
        _immutable(destination / "result.json", canonical(result))
        if active is not None:
            remove(prepared.folder / "operation.json")
        prepared.operation = operation
        prepared.cached_result = result
        return {"version": 1, "component": prepared.context["component"], "session": prepared.context["session"],
                "phase": "exclusive", "result": str(path)}


@handler("execute")
def execute(request: Request) -> Object:
    with prepare_execute(request) as prepared:
        output = None if prepared.cached_result is not None else supervise_execute(prepared)
        return settle_execute(prepared, output)


def _finish_inputs(request: Request, authority: Authority, payload: Payload, gate: Gate,
                   descriptor: int) -> Prepared:
    folder = private_directory(authority.folder / "sessions" / request.session)
    path = physical(request.values["result"], directory=False)
    if path != folder / "result.json":
        raise Refusal("Finish requires the exact active session result path.")
    result = read(path)
    validate("result", result)
    context_path = folder / "contexts" / (result["attempt"] + ".json")
    context = read(context_path)
    validate("context", context)
    binding = read(folder / "contexts" / (result["attempt"] + ".request.json"))
    request_binding(binding, context)
    history = folder / "attempts" / result["attempt"]
    operation = read(history / "operation.json")
    if (read(history / "context.json") != context or read(history / "request.json") != binding
            or _context_from_operation(operation) != context or not valid_hash(operation["backupSha256"])
            or result != _result_value(context, operation["backupSha256"])
            or context["component"] != request.component or context["session"] != request.session
            or context["registry"] != str(request.registry) or context["gateSha256"] != gate.digest
            or context["payloadSha256"] != payload.digest or binding["build"] != payload.build
            or context["acceptanceSha256"] != authority.read("qualification")["acceptanceSha256"]):
        raise Refusal("Finish result/context/payload does not match the current qualified tuple.")
    if os.path.lexists(folder / "operation.json"):
        raise Refusal("A pending operation must settle before finish.")
    return Prepared(request, authority, payload, gate, descriptor, folder, context_path, context,
                    binding, operation, result)


def _finish_record(prepared: Prepared) -> Object | None:
    if prepared.cached_result is None:
        raise Refusal("Finish requires a durable current result.")
    path = prepared.folder / "attempts" / prepared.context["attempt"] / "finish.json"
    try:
        value = read(path)
    except FileNotFoundError:
        return None
    fields(value, "version kind component session epoch attempt generation resultSha256 contextSha256 requestSha256 markerSha256 nextEpoch phase")
    if (value["kind"] != "driver-maintenance-finish"
            or value["phase"] not in ("prepared", "marker-archived", "ready", "complete")
            or any(value[key] != prepared.context[key] for key in ("component", "session", "epoch", "attempt", "generation"))
            or value["resultSha256"] != sha256(canonical(prepared.cached_result))
            or value["contextSha256"] != sha256(canonical(prepared.context))
            or value["requestSha256"] != sha256(canonical(prepared.binding))
            or not valid_hash(value["markerSha256"]) or not valid_token(value["nextEpoch"])
            or value["nextEpoch"] == value["epoch"]):
        raise Refusal("Finish journal is not the exact current result/archive chain.")
    return value


def _finish_marker(prepared: Prepared, journal: Object | None) -> tuple[bytes, bool]:
    state = private_directory(physical(prepared.context["stateDirectory"]))
    destination = prepared.folder / "attempts" / prepared.context["attempt"]
    acknowledged = read_bytes(destination / "marker.json")
    _complete_marker(prepared.context, prepared.operation, prepared.operation["backupSha256"], acknowledged)
    try:
        raw = read_bytes(state / "identity-maintenance.json")
    except FileNotFoundError:
        if journal is None:
            raise Refusal("Marker removal has no matching durable finish intent.") from None
        raw = read_bytes(destination / "finished-marker.json")
        if raw != acknowledged or sha256(raw) != journal["markerSha256"]:
            raise Refusal("Removed marker lacks its exact finished archive.") from None
        return raw, False
    if raw != acknowledged or (journal is not None and sha256(raw) != journal["markerSha256"]):
        raise Refusal("A later/damaged marker cannot consume this result.")
    return raw, True


def _finish_status(prepared: Prepared, phase: str) -> Object:
    return {"version": 1, "component": prepared.context["component"], "session": prepared.context["session"],
            "phase": phase}


def _normal_finish_retry(prepared: Prepared, control: Object, journal: Object | None) -> Object:
    # A finished retry is read-only: it never fences new normal work or reuses
    # an older result to reopen a later epoch/session.
    if (journal is None or journal["phase"] not in ("ready", "complete")
            or control != {"version": 1, "phase": "normal", "session": None, "epoch": journal["nextEpoch"]}):
        raise Refusal("Old result cannot reopen a later maintenance session.")
    state = private_directory(physical(prepared.context["stateDirectory"]))
    raw = read_bytes(prepared.folder / "attempts" / prepared.context["attempt"] / "finished-marker.json")
    if sha256(raw) != journal["markerSha256"]:
        raise Refusal("Finished marker archive changed.")
    _complete_marker(prepared.context, prepared.operation, prepared.operation["backupSha256"], raw)
    if (_state_format(state) != 2 or _root_generation(state) != prepared.context["generation"]
            or os.path.lexists(state / "identity-maintenance.json") or os.path.lexists(state / "identity-upgrade.json")):
        raise Refusal("Target changed after the exact finished epoch.")
    return _finish_status(prepared, "normal")


def _finish_component(request: Request) -> Object:
    with _component(request) as (authority, payload, gate):
        descriptor = -1
        try:
            with authority.mutex():
                _recheck(authority, payload, gate)
                control = authority.read("control")
                prepared = _finish_inputs(request, authority, payload, gate, descriptor)
                journal = _finish_record(prepared)
                if control["phase"] == "normal":
                    return _normal_finish_retry(prepared, control, journal)
                descriptor = authority.lease(exclusive=True)
                prepared.descriptor = descriptor
                current, receipt = _closed_attempt(authority, request, payload, gate, descriptor)
                deployment = _rollout_record(authority.shared / "deployment.json")
                if (current["epoch"] != prepared.context["epoch"] or receipt != prepared.context["receiptSha256"]
                        or (deployment is not None and deployment["registrySha256"] != sha256(canonical(authority.identity)))
                        or (journal is not None and journal["phase"] == "complete")):
                    raise Refusal("Exclusive finish authority changed or was rolled back.")
                digest = _archive_observation(prepared)
                if digest != prepared.operation["backupSha256"]:
                    raise Refusal("Finish before-manifest changed.")
                marker_raw, present = _finish_marker(prepared, journal)
                if present:
                    _pending_scope(prepared.context)
                else:
                    _pending_scope(prepared.context, marker_absent=True)
                destination = prepared.folder / "attempts" / prepared.context["attempt"]
                if journal is None:
                    assert prepared.cached_result is not None
                    next_epoch = token()
                    while next_epoch == current["epoch"]:
                        next_epoch = token()
                    journal = {"version": 1, "kind": "driver-maintenance-finish",
                               **{key: prepared.context[key] for key in ("component", "session", "epoch", "attempt", "generation")},
                               "resultSha256": sha256(canonical(prepared.cached_result)),
                               "contextSha256": sha256(canonical(prepared.context)), "requestSha256": sha256(canonical(prepared.binding)),
                               "markerSha256": sha256(marker_raw), "nextEpoch": next_epoch, "phase": "prepared"}
                    publish(destination / "finish.json", journal)
                _immutable(destination / "finished-marker.json", marker_raw)
                journal = {**journal, "phase": "marker-archived"}
                publish(destination / "finish.json", journal)
                state = Path(prepared.context["stateDirectory"])
                if present:
                    if read_bytes(state / "identity-maintenance.json") != marker_raw:
                        raise Refusal("Complete marker changed before removal.")
                    remove(state / "identity-maintenance.json")
                _pending_scope(prepared.context, marker_absent=True)
                # A ready intent is durable before normal publication. A crash
                # after publication retries by matching this one nextEpoch only.
                journal = {**journal, "phase": "ready"}
                publish(destination / "finish.json", journal)
                deployment = _rollout_record(authority.shared / "deployment.json")
                if deployment is not None and deployment["phase"] != "complete":
                    return {**_finish_status(prepared, "exclusive"), "deployment": "awaiting-components", "callersMayEnable": False}
                authority.write("control", {"version": 1, "phase": "normal", "session": None, "epoch": journal["nextEpoch"]})
                publish(destination / "finish.json", {**journal, "phase": "complete"})
                return _finish_status(prepared, "normal")
        finally:
            if descriptor >= 0:
                os.close(descriptor)


def _reopen_record(folder: Path, record: Object) -> Object | None:
    try:
        value = read(folder / "reopen.json")
    except FileNotFoundError:
        return None
    fields(value, "version kind session checkpoint registrySha256 gateSha256 callersSha256 phase components")
    if (value["kind"] != "driver-deployment-reopen" or value["phase"] not in ("prepared", "complete")
            or any(value[key] != record[key] for key in ("session", "checkpoint", "registrySha256", "gateSha256", "callersSha256"))
            or not isinstance(value["components"], list) or len(value["components"]) != len(COMPONENTS)):
        raise Refusal("All-four reopen journal identity changed.")
    for expected, row in zip(record["components"], value["components"], strict=True):
        if (not isinstance(row, dict) or set(row) != {
                "component", "epoch", "nextEpoch", "attempt", "resultSha256", "contextSha256", "requestSha256", "finishSha256"}
                or row["component"] != expected["component"] or row["epoch"] != expected["epoch"]
                or not valid_token(row["nextEpoch"]) or row["nextEpoch"] == row["epoch"]
                or not valid_token(row["attempt"])
                or any(not valid_hash(row[key]) for key in ("resultSha256", "contextSha256", "requestSha256", "finishSha256"))):
            raise Refusal("All-four reopen component tuple changed.")
    return value


def _completion_request(registry: Path, session: str, authority: Authority) -> Request:
    path = authority.folder / "sessions" / session / "result.json"
    return Request("finish", registry, {"component": authority.component, "session": session, "result": str(path)})


def _reopen_row(prepared: Prepared, journal: Object) -> Object:
    return {"component": prepared.authority.component, "epoch": journal["epoch"], "nextEpoch": journal["nextEpoch"],
            "attempt": journal["attempt"], "resultSha256": journal["resultSha256"],
            "contextSha256": journal["contextSha256"], "requestSha256": journal["requestSha256"],
            "finishSha256": sha256(canonical({**journal, "phase": "ready"}))}


def _verified_complete(registry: Path, authorities: list[Authority], payloads: list[Payload],
                       gate: Gate, record: Object) -> Object:
    """Caller owns all lexical mutexes; this reports readiness without enabling callers."""
    folder = _rollout_folder(registry, record["session"], record["checkpoint"])
    reopening = _reopen_record(folder, record)
    if record["phase"] != "complete" or reopening is None or reopening["phase"] != "complete":
        raise Refusal("All-four normal completion has no exact durable journal.")
    for authority in authorities:
        _verify_boot_archive(authority, record, record["newBoot"], allow_normal=True)
    _verify_rollout(registry, authorities, record, reopening=reopening, allow_normal_activity=True)
    for authority, payload, row in zip(authorities, payloads, reopening["components"], strict=True):
        normal_control(authority)
        verify_acceptance(authority, payload)
        request = _completion_request(registry, record["session"], authority)
        prepared = _finish_inputs(request, authority, payload, gate, -1)
        journal = _finish_record(prepared)
        if journal is None or _reopen_row(prepared, journal) != row:
            raise Refusal("Completed result no longer matches the all-four reopen journal.")
        _normal_finish_retry(prepared, authority.read("control"), journal)
        _pending_scope(prepared.context, marker_absent=True)
    return {"phase": "normal", "deployment": "complete", "callersMayEnable": True}


def _complete_deployment(request: Request) -> Object | None:
    shared = request.registry / ".driver-qualification"
    observed = _rollout_record(shared / "deployment.json")
    if observed is None or observed["phase"] == "complete":
        return None
    if observed["session"] != request.session or observed["phase"] not in ("boot-verified", "maintaining"):
        raise Refusal("The exact verified deployment must own all-four completion.")
    pending_status = {"phase": "exclusive", "deployment": "awaiting-components", "callersMayEnable": False}
    with deployment_mutex(request.registry):
        authorities = [Authority(request.registry, name) for name in COMPONENTS]
        payloads = _qualified_candidates(authorities)
        gate = verify_gate(request.registry)
        if not Path(__file__).resolve().is_relative_to(gate.provider.root):
            raise Refusal("All-four completion requires the exact immutable provider.")
        with pin_payloads(request.registry, [gate.provider, *payloads]), ExitStack() as stack:
            for authority in authorities:
                stack.enter_context(authority.mutex())
            record = _rollout_record(shared / "deployment.json")
            if record is None:
                raise Refusal("Deployment disappeared before completion.")
            if record != observed:
                if record["phase"] == "complete" and record["session"] == request.session:
                    return _verified_complete(request.registry, authorities, payloads, gate, record)
                raise Refusal("Deployment changed before completion.")
            folder = _rollout_folder(request.registry, record["session"], record["checkpoint"])
            reopening = _reopen_record(folder, record)
            _verify_rollout(request.registry, authorities, record, reopening=reopening)
            for authority in authorities:
                session = authority.folder / "sessions" / request.session
                if not (session / "result.json").exists() or os.path.lexists(session / "operation.json"):
                    if reopening is not None:
                        raise Refusal("A journaled reopen lost its exact active result chain.")
                    return pending_status
            leases: list[int] = []
            try:
                for authority in authorities:
                    descriptor = authority.lease(exclusive=True)
                    stack.callback(os.close, descriptor)
                    leases.append(descriptor)
            except BlockingIOError:
                return pending_status
            rows: list[Object] = []
            prepared_all: list[tuple[Prepared, Object]] = []
            for authority, payload, descriptor in zip(authorities, payloads, leases, strict=True):
                verify_acceptance(authority, payload)
                _exclusive(authority, descriptor)
                prepared = _finish_inputs(_completion_request(request.registry, request.session, authority),
                                          authority, payload, gate, descriptor)
                journal = _finish_record(prepared)
                if journal is None or journal["phase"] not in ("ready", "complete"):
                    if reopening is not None:
                        raise Refusal("A journaled reopen lost a ready component finish.")
                    return pending_status
                control = authority.read("control")
                closed = {"version": 1, "phase": "exclusive", "session": request.session, "epoch": journal["epoch"]}
                normal = {"version": 1, "phase": "normal", "session": None, "epoch": journal["nextEpoch"]}
                if control != closed and (reopening is None or control != normal):
                    raise Refusal("A component is outside its exact closed/desired normal tuple.")
                if journal["phase"] == "complete" and (reopening is None or control != normal):
                    raise Refusal("A completed component finish cannot authorize rolled-back control.")
                if reopening is not None and reopening["phase"] == "complete" and control != normal:
                    raise Refusal("A completed reopen journal cannot authorize rolled-back control.")
                custody = reconcile(authority, control=control)
                if not custody.resolved or _tainted(authority):
                    raise Refusal("All-four completion still has unresolved custody.")
                if _archive_observation(prepared) != prepared.operation["backupSha256"]:
                    raise Refusal("All-four completion before-manifest changed.")
                _raw, present = _finish_marker(prepared, journal)
                if present:
                    raise Refusal("Every component must durably retire its own completed marker first.")
                _pending_scope(prepared.context, marker_absent=True)
                rows.append(_reopen_row(prepared, journal))
                prepared_all.append((prepared, journal))
            desired = {"version": 1, "kind": "driver-deployment-reopen",
                       **{key: record[key] for key in ("session", "checkpoint", "registrySha256", "gateSha256", "callersSha256")},
                       "phase": "prepared", "components": rows}
            if reopening is None:
                _immutable(folder / "reopen.json", canonical(desired))
                reopening = desired
            elif {**reopening, "phase": "prepared"} != desired:
                raise Refusal("Desired normal epochs/results changed during reopen retry.")
            record = {**record, "phase": "maintaining"}
            publish(shared / "deployment.json", record)
            # Global maintaining blocks every launcher even if a crash leaves
            # any subset of these normal controls durably published.
            for prepared, journal in prepared_all:
                prepared.authority.write("control", {"version": 1, "phase": "normal", "session": None,
                                                      "epoch": journal["nextEpoch"]})
                publish(prepared.folder / "attempts" / journal["attempt"] / "finish.json", {**journal, "phase": "complete"})
            for prepared, _journal in prepared_all:
                _pending_scope(prepared.context, marker_absent=True)
                if not reconcile(prepared.authority, control=prepared.authority.read("control")).resolved or _tainted(prepared.authority):
                    raise Refusal("Custody changed before the global complete commit.")
            publish(folder / "reopen.json", {**reopening, "phase": "complete"})
            completed = {**record, "phase": "complete"}
            # Verify the exact desired controls and unchanged gate before this
            # sole global admission commit. No caller command is ever executed.
            _verify_rollout(request.registry, authorities, record, reopening=reopening)
            publish(shared / "deployment.json", completed)
            return _verified_complete(request.registry, authorities, payloads, gate, completed)


@handler("finish")
def finish(request: Request) -> Object:
    result = _finish_component(request)
    completed = _complete_deployment(request)
    return {**result, **completed} if completed is not None else result
