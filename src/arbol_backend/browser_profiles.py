"""Installation-owned reservations for dedicated Seqoya Browser profiles."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass

from .database import Database, Session
from .model import Refused
from .subscription_identity import DRIVER, SubscriptionIdentities, SubscriptionIdentity, canonical

REQUEST = re.compile(r"create_[A-Za-z0-9_-]{22}\Z")
INSTANCE = re.compile(r"prf_[A-Za-z0-9_-]{22}\Z")


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


@dataclass(frozen=True)
class ProfileBinding:
    installation: str
    driver: str
    incarnation: str
    request: str
    profile: str
    instance: str | None
    state: str

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
            "SELECT creation_request,profile,profile_instance,state FROM public.seqoya_browser_bindings "
            "WHERE installation=%s AND driver=%s AND subscription_incarnation=%s AND state<>'retired' FOR UPDATE", owner)
        if not rows:
            return None
        if len(rows) != 1:
            raise needs_rebind()
        request, profile, instance, state = rows[0]
        if (not isinstance(request, str) or profile != profile_id(*owner, request)
                or state not in ("preparing", "active", "needs_rebind")
                or (instance is not None and (not isinstance(instance, str) or INSTANCE.fullmatch(instance) is None))
                or (state == "active" and instance is None) or (state == "preparing" and instance is not None)):
            raise needs_rebind()
        return ProfileBinding(*owner, request, profile, instance, state)

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
