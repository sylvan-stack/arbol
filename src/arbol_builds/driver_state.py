"""Shared registered Driver launch and offline maintenance provider (DRV-6.21).

There is no source-path, copied-launcher or manifest-only admission fallback.
Normal writer admission and exclusive maintenance remain separate protocols.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from .driver_admission import (
    COMPONENTS,
    Authority,
    Object,
    Refusal,
    normal_control,
    physical,
    private_directory,
    publish,
    publish_bytes,
    read,
    read_bytes,
    sha256,
    token,
    validate,
    without_authority,
)
from .driver_payload import DESCRIPTOR, SUBTREE, Payload, registered, verify_acceptance, verify_gate
from .driver_process import Guardian, boot_uuid, supervise
from .launcher import Record, launch, open_use_guard


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
