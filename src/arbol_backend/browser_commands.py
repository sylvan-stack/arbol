"""Bounded calls through the installed signed Browser launcher."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from arbol_builds.service import installed_browser_selection

from .bridge import constant, finite, pairs
from .model import Identity, Refused

PROFILE = re.compile(r"[a-z](?:[a-z0-9-]{0,62}[a-z0-9])?\Z")
SEQOYA_PROFILE = re.compile(r"seqoya-[0-9a-f]{32}\Z")
INSTANCE = re.compile(r"prf_[A-Za-z0-9_-]{22}\Z")
REQUEST = re.compile(r"create_[A-Za-z0-9_-]{22}\Z")
HOST = re.compile(r"ins_[A-Za-z0-9_-]{22}\Z")
TAB = re.compile(r"tab_[A-Za-z0-9_-]{22}\Z")
MANAGEMENT_FIELDS = {"format", "id", "instance", "creationRequest", "createdAt"}
MAX_OUTPUT = 1024 * 1024
BROWSER_SECONDS = 65.0


class UnsupportedScopedListing(Exception):
    pass


def unavailable() -> Refused:
    return Refused("browser_unavailable", "The selected signed Browser could not verify this profile operation.")


@dataclass(frozen=True)
class BrowserProfile:
    profile: str
    instance: str
    request: str


def record(value: Any, *, listing: bool = False) -> BrowserProfile:
    fields = MANAGEMENT_FIELDS | {"running"} if listing else MANAGEMENT_FIELDS
    if (not isinstance(value, dict) or value.keys() != fields or type(value["format"]) is not int
            or value["format"] != 2 or not isinstance(value["id"], str) or PROFILE.fullmatch(value["id"]) is None
            or not isinstance(value["instance"], str) or INSTANCE.fullmatch(value["instance"]) is None
            or not isinstance(value["creationRequest"], str) or REQUEST.fullmatch(value["creationRequest"]) is None
            or not isinstance(value["createdAt"], str) or len(value["createdAt"]) > 40
            or "T" not in value["createdAt"] or (listing and type(value["running"]) is not bool)):
        raise unavailable()
    try:
        if datetime.fromisoformat(value["createdAt"]).utcoffset() != timedelta(0):
            raise unavailable()
    except ValueError as error:
        raise unavailable() from error
    return BrowserProfile(value["id"], value["instance"], value["creationRequest"])


class BrowserCommands:
    def __init__(self, identity: Identity) -> None:
        self.identity = identity
        self.launcher = identity.home / "Applications/Arbol Browser/bin/arbol-browser"

    async def list(self, profile: str | None = None) -> dict[str, BrowserProfile]:
        if profile is not None and PROFILE.fullmatch(profile) is None:
            raise unavailable()
        arguments = ("profiles", "list") if profile is None else ("profiles", "list", profile)
        reply = await self.execute(*arguments)
        if reply.keys() != {"profiles"} or not isinstance(reply["profiles"], list) or len(reply["profiles"]) > 4096:
            raise unavailable()
        profiles: dict[str, BrowserProfile] = {}
        for item in reply["profiles"]:
            observed = record(item, listing=True)
            if observed.profile in profiles:
                raise unavailable()
            profiles[observed.profile] = observed
        return profiles

    async def create(self, profile: str, request: str) -> BrowserProfile:
        if SEQOYA_PROFILE.fullmatch(profile) is None or REQUEST.fullmatch(request) is None:
            raise unavailable()
        reply = await self.execute("profiles", "create", profile, "--creation-request", request)
        if reply.keys() != {"profile", "created"} or type(reply["created"]) is not bool:
            raise unavailable()
        created = record(reply["profile"])
        if created.profile != profile or created.request != request:
            raise unavailable()
        return created

    async def open(self, profile: str, instance: str, url: str) -> None:
        if (SEQOYA_PROFILE.fullmatch(profile) is None or INSTANCE.fullmatch(instance) is None
                or len(url) > 8192 or any(ord(c) <= 32 or c in "\\\x7f" for c in url)):
            raise unavailable()
        try:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
                raise unavailable()
        except ValueError as error:
            raise unavailable() from error
        reply = await self.execute("open", "--profile", profile, "--profile-instance", instance, "--url", url)
        required = {"profile", "instance", "process", "alreadyRunning"}
        if (not required <= reply.keys() <= required | {"tab"} or reply["profile"] != profile
                or not isinstance(reply["instance"], str) or HOST.fullmatch(reply["instance"]) is None
                or type(reply["process"]) is not int or not 1 <= reply["process"] <= 9007199254740991
                or type(reply["alreadyRunning"]) is not bool
                or ("tab" in reply and (not isinstance(reply["tab"], str) or TAB.fullmatch(reply["tab"]) is None))):
            raise unavailable()

    async def execute(self, *arguments: str) -> dict[str, Any]:
        if self.identity.fixture:
            raise unavailable()
        try:
            async with asyncio.timeout(BROWSER_SECONDS):
                selected = await asyncio.to_thread(installed_browser_selection, self.identity.home)
                if selected is None:
                    raise unavailable()
                try:
                    data = await self.run(str(selected["build"]), arguments)
                except UnsupportedScopedListing:
                    # Older signed Builds reject the scoped syntax. Keep this
                    # fallback on the same selected Build and within the same budget.
                    data = await self.run(str(selected["build"]), ("profiles", "list"))
                if await asyncio.to_thread(installed_browser_selection, self.identity.home) != selected:
                    raise unavailable()
                value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant, parse_float=finite)
                if not isinstance(value, dict):
                    raise unavailable()
                return value
        except (OSError, ValueError, RuntimeError, TimeoutError) as error:
            raise unavailable() from error

    async def run(self, build: str, arguments: tuple[str, ...]) -> bytes:
        child = await asyncio.create_subprocess_exec(
            str(self.launcher), "-v", build, *arguments, cwd=self.identity.folder,
            env={"HOME": str(self.identity.home), "PATH": "/usr/bin:/bin"},
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True, limit=MAX_OUTPUT,
        )
        assert child.stdout is not None
        try:
            try:
                await child.stdout.readexactly(MAX_OUTPUT + 1)
            except asyncio.IncompleteReadError as end:
                status = await child.wait()
                if status == 0:
                    return end.partial
                if status == 2 and len(arguments) == 3 and arguments[:2] == ("profiles", "list"):
                    failure = json.loads(end.partial.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
                    if isinstance(failure, dict) and isinstance(failure.get("error"), dict) and failure["error"].get("code") == "invalid_input":
                        raise UnsupportedScopedListing() from None
            raise unavailable()
        finally:
            if child.returncode is None:
                with suppress(ProcessLookupError):
                    child.terminate()
