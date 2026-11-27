"""Attach a confirmed Subscription to an existing exact Browser profile."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
from functools import partial
from pathlib import Path

from arbol_backend.bridge import constant, pairs
from arbol_backend.browser_commands import INSTANCE, PROFILE, REQUEST, SEQOYA_PROFILE, BrowserProfile
from arbol_backend.browser_profiles import existing_profile, needs_rebind
from arbol_backend.model import Refused, identity
from arbol_backend.server import Backend


def profile(value: object) -> BrowserProfile:
    if not isinstance(value, dict) or set(value) != {"profile", "instance", "request"}:
        raise ValueError("An exact Browser profile record is required.")
    name, instance, request = (value[key] for key in ("profile", "instance", "request"))
    if not all(isinstance(field, str) for field in (name, instance, request)):
        raise ValueError("Invalid Browser profile identity.")
    if not PROFILE.fullmatch(name) or not INSTANCE.fullmatch(instance) or not REQUEST.fullmatch(request):
        raise ValueError("Invalid Browser profile identity.")
    return BrowserProfile(name, instance, request)


def fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def request(path: Path) -> tuple[tuple[str, str], BrowserProfile | None, BrowserProfile]:
    path = path.absolute()
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        pinned = os.fstat(stream.fileno())
        if (not stat.S_ISREG(pinned.st_mode) or pinned.st_uid != os.getuid()
                or stat.S_IMODE(pinned.st_mode) != 0o600 or pinned.st_nlink != 1 or pinned.st_size > 4096
                or path.resolve(strict=True) != path):
            raise ValueError("The private adoption request is invalid.")
        raw = stream.read(4097)
        if (fingerprint(os.fstat(stream.fileno())) != fingerprint(pinned)
                or fingerprint(path.lstat()) != fingerprint(pinned) or len(raw) != pinned.st_size):
            raise ValueError("The adoption request changed.")
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict) or type(value.get("format")) is not int:
        raise ValueError("The adoption request has an unknown format.")
    if value["format"] == 1 and set(value) == {"format", "previous", "target"}:
        previous, target = profile(value["previous"]), profile(value["target"])
        if SEQOYA_PROFILE.fullmatch(previous.profile) and existing_profile(target.profile):
            return ("codex", "chatgpt"), previous, target
    if value["format"] == 2 and set(value) == {"format", "driver", "subscription", "target"}:
        provider = (value["driver"], value["subscription"])
        target = profile(value["target"])
        if provider in (("pi", "chatgpt"), ("pi", "minimax")) and existing_profile(target.profile):
            return provider, None, target
    raise ValueError("Select a confirmed Subscription and an existing non-default profile.")


async def adopt(provider: tuple[str, str], previous: BrowserProfile | None, target: BrowserProfile) -> None:
    package = Path(__file__).resolve().parents[1]
    if package.parent != Path.home() / ".local/lib/sylvan-stack/arbol/stable/arbol":
        raise ValueError("Run the adoption from the installed Backend package.")
    backend = Backend(identity(package, {}))
    try:
        profiles, browser = backend.browser.profiles, backend.browser.browser
        if previous is None:
            async with backend.database.browser_authority():
                account = await backend.accounts.browser_slot(*provider)
                if account.get("family") != provider[1] or account.get("state") != "signed_in":
                    raise needs_rebind()
                captured = await backend.accounts.driver_identity.capture(*provider)
                confirm = partial(backend.accounts.driver_identity.expect, captured)
                binding = await profiles.attach_existing(captured.proof, target, browser, confirm)
            print(json.dumps({"profile": binding.profile, "state": binding.state, "origin": binding.origin}))
            return
        async with backend.database.browser_authority():
            await backend.accounts.browser_slot(*provider)
            saved = await profiles.saved_binding(*provider)
            if saved is None:
                raise needs_rebind()
            before, proof = saved
            if proof is None:
                raise needs_rebind()
            captured = await backend.accounts.driver_identity.capture_expected(proof)
            verify = partial(backend.accounts.driver_identity.expect, captured)
            async with profiles.identities.transaction() as (session, installation):
                selected = await profiles.identities.current(session, installation, *provider)
                if selected is None or before.incarnation != selected.incarnation:
                    raise needs_rebind()
            binding = await profiles.adopt_existing(selected, previous, target, browser, verify)
        print(json.dumps({"profile": binding.profile, "state": binding.state, "origin": binding.origin}))
    finally:
        await backend.accounts.close()
        await backend.database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    try:
        asyncio.run(adopt(*request(args.request)))
    except Refused as error:
        print(json.dumps({"status": "refused", "code": error.code}))
        return 1
    except (OSError, ValueError):
        print(json.dumps({"status": "refused", "code": "invalid_input"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
