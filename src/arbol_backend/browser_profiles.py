"""Installation-owned reservations for dedicated Seqoya Browser profiles."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from .accounts import Accounts
from .browser_commands import (
    INSTANCE,
    PROFILE,
    REQUEST,
    SEQOYA_PROFILE,
    BrowserCommands,
    BrowserProfile,
    UnsupportedBoundOpen,
)
from .database import Database, Session
from .model import Refused
from .subscription_identity import DRIVER, SubscriptionIdentities, SubscriptionIdentity, SubscriptionProof, canonical


def needs_rebind() -> Refused:
    return Refused("needs_rebind", "The exact Subscription Browser profile could not be established.")


def profile_id(installation: str, driver: str, incarnation: str, request: str) -> str:
    fields = (canonical(installation), driver, canonical(incarnation), request)
    if DRIVER.fullmatch(driver) is None or REQUEST.fullmatch(request) is None:
        raise needs_rebind()
    digest = hashlib.sha256()
    for field in fields:
        data = field.encode("utf-8")
        digest.update(len(data).to_bytes(4, "big"))
        digest.update(data)
    return "seqoya-" + digest.hexdigest()[:32]


def existing_profile(profile: str) -> bool:
    return profile != "default" and PROFILE.fullmatch(profile) is not None and SEQOYA_PROFILE.fullmatch(profile) is None


@dataclass(frozen=True)
class ProfileBinding:
    installation: str
    driver: str
    incarnation: str
    request: str
    profile: str
    instance: str | None
    state: str
    origin: str = "generated"

    @property
    def owner(self) -> tuple[str, str, str]:
        return self.installation, self.driver, self.incarnation


class BrowserProfiles:
    def __init__(self, database: Database) -> None:
        self.identities = SubscriptionIdentities(database)

    async def require_identity(self, session: Session, installation: str, selected: SubscriptionIdentity) -> None:
        if installation != selected.installation or selected.state != "active":
            raise needs_rebind()
        current = await self.identities.current(session, installation, selected.driver, selected.native_id)
        if current != selected:
            raise needs_rebind()

    @staticmethod
    async def current(session: Session, selected: SubscriptionIdentity) -> ProfileBinding | None:
        owner = (selected.installation, selected.driver, selected.incarnation)
        rows = await session.execute(
            "SELECT creation_request,profile,profile_instance,state,"
            "COALESCE(to_jsonb(binding)->>'profile_origin','generated') FROM public.seqoya_browser_bindings AS binding "
            "WHERE installation=%s AND driver=%s AND subscription_incarnation=%s AND state<>'retired' FOR UPDATE", owner)
        if not rows:
            return None
        if len(rows) != 1:
            raise needs_rebind()
        request, profile, instance, state, origin = rows[0]
        if (not isinstance(request, str) or REQUEST.fullmatch(request) is None or not isinstance(profile, str)
                or state not in ("preparing", "active", "needs_rebind")
                or (instance is not None and (not isinstance(instance, str) or INSTANCE.fullmatch(instance) is None))
                or (state == "active" and instance is None) or (state == "preparing" and instance is not None)):
            raise needs_rebind()
        if origin == "generated":
            if profile != profile_id(*owner, request):
                raise needs_rebind()
        elif origin == "existing":
            if not existing_profile(profile) or state == "preparing" or instance is None:
                raise needs_rebind()
        else:
            raise needs_rebind()
        return ProfileBinding(*owner, request, profile, instance, state, origin)

    async def reserve(self, selected: SubscriptionIdentity) -> ProfileBinding:
        """Commit a single preparing record before a caller asks Browser to create it."""
        async with self.identities.transaction() as (session, installation):
            await self.require_identity(session, installation, selected)
            current = await self.current(session, selected)
            if current is not None:
                if current.state == "needs_rebind":
                    raise needs_rebind()
                return current
            request = "create_" + secrets.token_urlsafe(16)
            owner = (installation, selected.driver, selected.incarnation)
            profile = profile_id(*owner, request)
            await session.execute(
                "INSERT INTO public.seqoya_browser_bindings "
                "(installation,driver,subscription_incarnation,creation_request,profile,state) "
                "VALUES (%s,%s,%s,%s,%s,'preparing')", (*owner, request, profile))
            return ProfileBinding(*owner, request, profile, None, "preparing")

    async def adopt_existing(self, selected: SubscriptionIdentity, previous: BrowserProfile,
                             target: BrowserProfile, browser: BrowserCommands,
                             verify: Callable[[], Awaitable[None]]) -> ProfileBinding:
        """Retire the exact dedicated association and select the owner's existing profile."""
        if (not existing_profile(target.profile) or target == previous
                or (await browser.list(target.profile)).get(target.profile) != target):
            raise needs_rebind()
        await verify()
        async with self.identities.transaction() as (session, installation):
            await self.require_identity(session, installation, selected)
            current = await self.current(session, selected)
            owner = (installation, selected.driver, selected.incarnation)
            adopted = ProfileBinding(*owner, target.request, target.profile, target.instance, "active", "existing")
            if current == adopted:
                return adopted
            if current != ProfileBinding(*owner, previous.request, previous.profile, previous.instance, "active"):
                raise needs_rebind()
            await session.execute(
                "UPDATE public.seqoya_browser_bindings SET state='retired' "
                "WHERE installation=%s AND driver=%s AND subscription_incarnation=%s AND creation_request=%s",
                (*owner, previous.request))
            await session.execute(
                "INSERT INTO public.seqoya_browser_bindings "
                "(installation,driver,subscription_incarnation,creation_request,profile,profile_instance,state,profile_origin) "
                "VALUES (%s,%s,%s,%s,%s,%s,'active','existing')",
                (*owner, target.request, target.profile, target.instance))
            await verify()
            return adopted

    async def mark_needs_rebind(self, selected: SubscriptionIdentity, expected: ProfileBinding) -> None:
        async with self.identities.transaction() as (session, installation):
            await self.require_identity(session, installation, selected)
            if await self.current(session, selected) == expected:
                await session.execute(
                    "UPDATE public.seqoya_browser_bindings SET state='needs_rebind' "
                    "WHERE installation=%s AND driver=%s AND subscription_incarnation=%s AND creation_request=%s",
                    (*expected.owner, expected.request))

    async def activate(self, selected: SubscriptionIdentity, expected: ProfileBinding,
                       observed: BrowserProfile) -> ProfileBinding:
        if expected.state != "preparing" or (observed.profile, observed.request) != (expected.profile, expected.request):
            raise needs_rebind()
        activated = replace(expected, instance=observed.instance, state="active")
        async with self.identities.transaction() as (session, installation):
            await self.require_identity(session, installation, selected)
            current = await self.current(session, selected)
            if current == activated:
                return activated
            if current != expected:
                raise needs_rebind()
            await session.execute(
                "UPDATE public.seqoya_browser_bindings SET state='active',profile_instance=%s "
                "WHERE installation=%s AND driver=%s AND subscription_incarnation=%s AND creation_request=%s",
                (observed.instance, *expected.owner, expected.request))
        return activated

    async def require_binding(self, selected: SubscriptionIdentity, binding: ProfileBinding) -> None:
        async with self.identities.transaction() as (session, installation):
            await self.require_identity(session, installation, selected)
            if binding.state != "active" or await self.current(session, selected) != binding:
                raise needs_rebind()

    async def verify(self, selected: SubscriptionIdentity, binding: ProfileBinding, browser: BrowserCommands) -> ProfileBinding:
        observed = (await browser.list(binding.profile)).get(binding.profile)
        if observed is None or (observed.request, observed.instance) != (binding.request, binding.instance):
            await self.mark_needs_rebind(selected, binding)
            raise needs_rebind()
        await self.require_binding(selected, binding)
        return binding

    async def lookup(self, selected: SubscriptionIdentity) -> ProfileBinding | None:
        async with self.identities.transaction() as (session, installation):
            await self.require_identity(session, installation, selected)
            return await self.current(session, selected)

    async def active(self, selected: SubscriptionIdentity, browser: BrowserCommands) -> ProfileBinding:
        """Read an established exact binding without creating or opening a profile."""
        binding = await self.lookup(selected)
        if binding is None or binding.state != "active":
            raise needs_rebind()
        return await self.verify(selected, binding, browser)

    async def reconcile(self, selected: SubscriptionIdentity, browser: BrowserCommands) -> ProfileBinding:
        binding = await self.reserve(selected)
        if binding.state == "active":
            return await self.verify(selected, binding, browser)
        observed = (await browser.list(binding.profile)).get(binding.profile)
        if observed is not None and observed.request != binding.request:
            await self.mark_needs_rebind(selected, binding)
            raise needs_rebind()
        # Creating again with the same request recovers crashes, including a
        # response lost before the preparing row learned its real instance.
        created = await browser.create(binding.profile, binding.request)
        if observed is not None and observed != created:
            await self.mark_needs_rebind(selected, binding)
            raise needs_rebind()
        return await self.activate(selected, binding, created)

    async def saved_binding(self, driver: str, subscription: str) -> tuple[ProfileBinding, SubscriptionProof | None] | None:
        """Read the same binding and its expected lifetime in one transaction."""
        async with self.identities.transaction() as (session, installation):
            selected = await self.identities.current(session, installation, driver, subscription)
            if selected is None or selected.state != "active":
                return None
            binding = await self.current(session, selected)
            if binding is None or binding.state != "active":
                return None
            row = await self.identities.proof_row(session, selected)
            proof = None
            if row is not None:
                version, generation, witness = row
                try:
                    proof = SubscriptionProof(version, driver, subscription, generation, witness)
                except Refused:
                    pass  # Legacy or invalid proof goes through the normal observation.
            return binding, proof

    async def open(self, accounts: Accounts, browser: BrowserCommands, driver: str, subscription: str, url: str) -> None:
        async with self.identities.database.browser_authority():
            await self.open_bound(accounts, browser, driver, subscription, url)

    async def open_bound(self, accounts: Accounts, browser: BrowserCommands,
                         driver: str, subscription: str, url: str) -> None:
        saved = await self.saved_binding(driver, subscription)
        prepared, expected_proof = saved if saved is not None else (None, None)
        approval = asyncio.Event()
        pending = None
        if prepared is not None and prepared.instance is not None:
            pending = asyncio.create_task(browser.open(
                prepared.profile, prepared.instance, url, creation_request=prepared.request, approval=approval,
            ))
        try:
            async with accounts.browser_identity_request(
                driver, subscription, confirm_before_lookup=False, expected_proof=expected_proof,
            ) as (selected, verify_proof, matched_expected):
                binding = await self.lookup(selected)
                if binding is None or binding.state != "active":
                    await verify_proof()
                    binding = await self.reconcile(selected, browser)
                await self.require_binding(selected, binding)
                if not matched_expected or binding != prepared:
                    await verify_proof()
                if binding.instance is None:
                    raise needs_rebind()
                try:
                    opened = False
                    if pending is not None and binding == prepared:
                        approval.set()
                        try:
                            await pending
                            opened = True
                        except UnsupportedBoundOpen:
                            pass  # Signed predecessors support the ordinary verified open.
                    if not opened:
                        if pending is not None and not pending.done():
                            pending.cancel()
                            await asyncio.gather(pending, return_exceptions=True)
                        try:
                            await browser.open(binding.profile, binding.instance, url, creation_request=binding.request)
                        except UnsupportedBoundOpen:
                            await self.verify(selected, binding, browser)
                            await verify_proof()
                            await browser.open(binding.profile, binding.instance, url)
                except Refused as error:
                    # A transient command refusal leaves the active binding intact.
                    if error.code != "needs_rebind":
                        await self.verify(selected, binding, browser)
                    raise
                await self.require_binding(selected, binding)
        finally:
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
