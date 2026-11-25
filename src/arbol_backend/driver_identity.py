"""Use the normal installed Driver admission path for local lifetime proof."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass

from arbol_builds.driver_admission import (
    Authority,
    canonical,
    fresh_install,
    normal_control,
    private_directory,
    sha256,
)
from arbol_builds.driver_payload import registered, verify_acceptance, verify_gate
from arbol_builds.service import driver_route_bytes
from arbol_installation.paths import build_registry, installation_root

from .bridge import constant, finite, pairs
from .model import Identity, Refused
from .subscription_identity import PROOF_DRIVERS, SubscriptionProof, target

MAX_PROOF_BYTES = 4096
PROOF_SECONDS = 20.0


def unavailable() -> Refused:
    return Refused("needs_rebind", "The qualified Driver could not prove the selected Subscription lifetime.")


@dataclass(frozen=True)
class DriverSelection:
    command: tuple[str, ...]
    gate: str
    provider: str
    payload: str
    acceptance: str
    epoch: str
    state: tuple[int, int]


@dataclass(frozen=True)
class CapturedProof:
    proof: SubscriptionProof
    selection: DriverSelection


def selection(identity: Identity, driver: str) -> DriverSelection:
    if driver not in PROOF_DRIVERS:
        raise unavailable()
    component = f"arbol-{driver}-driver"
    registry = build_registry(identity.home).resolve(strict=True)
    authority = Authority(registry, component)
    gate = verify_gate(registry)
    installed = fresh_install(registry)
    if (installed is None or installed["phase"] != "complete" or installed["gateSha256"] != gate.digest
            or installed["registrySha256"] != sha256(canonical(authority.identity))):
        raise unavailable()
    route = identity.home / "Applications/Arbol/bin" / component
    state = installation_root(identity.home) / "driver-state" / installed["session"] / driver
    row = next((item for item in installed["components"] if item["component"] == component), None)
    gate_row = next((item for item in gate.document["components"] if item["component"] == component), None)
    if row is None or gate_row is None:
        raise unavailable()
    path_identity = private_directory(state).lstat()
    measured_state = {"device": path_identity.st_dev, "inode": path_identity.st_ino}
    launcher = driver_route_bytes(route)
    if (row["launcher"] != str(route) or gate_row["launcher"] != str(route)
            or row["stateDirectory"] != str(state) or row["stateDirectoryIdentity"] != measured_state
            or launcher is None or sha256(launcher[0]) != row["launcherSha256"]
            or row["launcherSha256"] != gate_row["launcherSha256"]):
        raise unavailable()
    payload = registered(registry, component, row["build"])
    digest = authority.read("qualification")["acceptanceSha256"]
    accepted = verify_acceptance(authority, payload, digest=digest)
    if accepted["status"] != "qualified" or payload.digest != row["payloadSha256"]:
        raise unavailable()
    with authority.mutex(seconds=1):
        control = normal_control(authority)
    command = (*gate.provider.prefix, "--driver-launch-fresh", str(registry), component, str(route), str(state),
               "-v", payload.build)
    return DriverSelection(command, gate.digest, gate.provider.digest, payload.digest, digest, control["epoch"],
                           (path_identity.st_dev, path_identity.st_ino))


def decode_proof(data: bytes, driver: str, native_id: str) -> SubscriptionProof:
    value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant, parse_float=finite)
    if (not isinstance(value, dict) or value.get("driver") != driver or value.get("subscription") != native_id
            or type(value.get("version")) is not int or not isinstance(value.get("generation"), str)
            or not isinstance(value.get("witness"), str)):
        raise unavailable()
    return SubscriptionProof(value["version"], driver, native_id, value["generation"], value["witness"])


class DriverIdentity:
    def __init__(self, identity: Identity) -> None:
        self.identity = identity

    async def capture(self, driver: str, native_id: str) -> CapturedProof:
        return await self.request(driver, native_id, None)

    async def expect(self, captured: CapturedProof) -> None:
        await self.request(captured.proof.driver, captured.proof.native_id, captured)

    async def request(self, driver: str, native_id: str, expected: CapturedProof | None) -> CapturedProof:
        target(driver, native_id)
        try:
            async with asyncio.timeout(PROOF_SECONDS):
                selected = await asyncio.to_thread(selection, self.identity, driver)
                arguments = ["subscriptions", "identity", native_id]
                if expected is not None:
                    if selected != expected.selection:
                        raise unavailable()
                    arguments.extend(("--expect", f"{expected.proof.generation}.{expected.proof.witness}"))
                data = await self.execute(selected.command, arguments)
                proof = decode_proof(data, driver, native_id)
                if (expected is not None and proof != expected.proof
                        or await asyncio.to_thread(selection, self.identity, driver) != selected):
                    raise unavailable()
                return CapturedProof(proof, selected)
        except (OSError, TimeoutError, ValueError, RuntimeError) as error:
            raise unavailable() from error

    async def execute(self, command: tuple[str, ...], arguments: list[str]) -> bytes:
        child = await asyncio.create_subprocess_exec(
            *command, *arguments, cwd=self.identity.folder,
            env={"HOME": str(self.identity.home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True, limit=MAX_PROOF_BYTES,
        )
        assert child.stdout is not None
        try:
            try:
                await child.stdout.readexactly(MAX_PROOF_BYTES + 1)
            except asyncio.IncompleteReadError as end:
                if await child.wait() == 0:
                    return end.partial
            raise unavailable()
        finally:
            if child.returncode is None:
                with suppress(ProcessLookupError):
                    child.terminate()
