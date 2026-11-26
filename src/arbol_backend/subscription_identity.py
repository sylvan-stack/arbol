"""PostgreSQL-owned Subscription incarnations, never inferred from a catalogue.

The qualified Driver supplies the lifetime proof. The installation database
assigns the application incarnation and binds it to that exact proof.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

from .database import Database, Session
from .model import Refused

DRIVER = re.compile(r"[a-z][a-z0-9-]{0,79}\Z")
PROOF_DRIVERS = frozenset({"claude", "codex", "mimo", "pi"})
PROOF_TOKEN = re.compile(r"[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]\Z")


def canonical(value: str) -> str:
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError) as error:
        raise Refused("invalid_input", "An exact canonical incarnation UUID is required.") from error
    return value


def target(driver: str, native_id: str) -> None:
    if (DRIVER.fullmatch(driver) is None or not native_id or native_id.startswith("-")
            or len(native_id.encode()) > 256 or any(c.isspace() or ord(c) < 32 or 127 <= ord(c) <= 159
                                                     for c in native_id)):
        raise Refused("invalid_input", "An exact Driver and Subscription identifier are required.")


@dataclass(frozen=True)
class SubscriptionIdentity:
    installation: str
    driver: str
    incarnation: str
    native_id: str
    state: str


@dataclass(frozen=True)
class SubscriptionProof:
    version: int
    driver: str
    native_id: str
    generation: str
    witness: str

    def __post_init__(self) -> None:
        target(self.driver, self.native_id)
        if (type(self.version) is not int or self.version != 1 or self.driver not in PROOF_DRIVERS
                or PROOF_TOKEN.fullmatch(self.generation) is None
                or PROOF_TOKEN.fullmatch(self.witness) is None):
            raise Refused("needs_rebind", "The Driver Subscription proof is unavailable.")


class SubscriptionIdentities:
    def __init__(self, database: Database) -> None:
        self.database = database

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[tuple[Session, str]]:
        """One normal writer permit and transaction serialize every lifecycle change.

        Holding the singleton also orders first creation for a slot with no row.
        Closing a failed/cancelled session rolls back before admission is released.
        """
        async with self.database.permit(), self.database.session() as session:
            await session.execute("BEGIN")
            rows = await session.execute("SELECT id::text FROM public.seqoya_installation WHERE singleton FOR UPDATE")
            if len(rows) != 1:
                raise Refused("needs_rebind", "The installation identity is unavailable.")
            yield session, canonical(rows[0][0])
            await session.execute("COMMIT")

    @staticmethod
    async def current(session: Session, installation: str, driver: str,
                      native_id: str) -> SubscriptionIdentity | None:
        rows = await session.execute(
            "SELECT incarnation::text,state FROM public.seqoya_subscriptions "
            "WHERE installation=%s AND driver=%s AND native_id=%s AND state<>'retired' FOR UPDATE",
            (installation, driver, native_id))
        if not rows:
            return None
        if len(rows) != 1:
            raise Refused("needs_rebind", "The Subscription identity is ambiguous.")
        return SubscriptionIdentity(installation, driver, canonical(rows[0][0]), native_id, rows[0][1])

    @staticmethod
    def expected(current: SubscriptionIdentity | None, installation: str,
                 expected_installation: str, expected_incarnation: str | None) -> None:
        canonical(expected_installation)
        if expected_incarnation is not None:
            canonical(expected_incarnation)
        if installation != expected_installation or (
                None if current is None else current.incarnation) != expected_incarnation:
            raise Refused("needs_rebind", "The selected installation or Subscription lifetime changed.")

    async def installation(self) -> str:
        """Read the authority; no lazy initialization or migration on lookup."""
        async with self.database.session(snapshot=True) as session:
            rows = await session.execute("SELECT id::text FROM public.seqoya_installation WHERE singleton")
            if len(rows) != 1:
                raise Refused("needs_rebind", "The installation identity is unavailable.")
            return canonical(rows[0][0])

    async def uncertain(self, driver: str, native_id: str) -> SubscriptionIdentity | None:
        """Persist uncertainty without retiring the Subscription or removing data.

        Missing legacy records return None. Failed catalogues must not invoke
        this method: their failure is neither uncertainty about an established
        lifetime nor an explicit removal. A successful reusable-id lookup still
        cannot prove continuity after recreation/restore/reset.
        """
        target(driver, native_id)
        async with self.transaction() as (session, installation):
            current = await self.current(session, installation, driver, native_id)
            if current is None:
                return None
            await self.mark_uncertain(session, current)
            return SubscriptionIdentity(installation, driver, current.incarnation, native_id, "needs_rebind")

    @staticmethod
    async def mark_uncertain(session: Session, current: SubscriptionIdentity) -> None:
        values = (current.installation, current.driver, current.incarnation)
        await session.execute(
            "UPDATE public.seqoya_subscriptions SET state='needs_rebind' "
            "WHERE installation=%s AND driver=%s AND incarnation=%s", values)
        await session.execute(
            "UPDATE public.seqoya_browser_bindings SET state='needs_rebind' "
            "WHERE installation=%s AND driver=%s AND subscription_incarnation=%s AND state<>'retired'", values)

    @staticmethod
    async def create_lifetime(session: Session, installation: str, driver: str, native_id: str,
                              proof: SubscriptionProof | None) -> SubscriptionIdentity:
        incarnation = str(uuid4())
        await session.execute(
            "INSERT INTO public.seqoya_subscriptions (installation,driver,incarnation,native_id,state) "
            "VALUES (%s,%s,%s,%s,'active')", (installation, driver, incarnation, native_id))
        if proof is not None:
            await session.execute(
                "INSERT INTO public.seqoya_subscription_proofs (installation,driver,incarnation,version,generation,witness) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (installation, driver, incarnation, proof.version, proof.generation, proof.witness))
        return SubscriptionIdentity(installation, driver, incarnation, native_id, "active")

    @staticmethod
    async def proof_row(session: Session, identity: SubscriptionIdentity) -> tuple[int, str, str] | None:
        rows = await session.execute(
            "SELECT version,generation,witness FROM public.seqoya_subscription_proofs "
            "WHERE installation=%s AND driver=%s AND incarnation=%s",
            (identity.installation, identity.driver, identity.incarnation))
        if len(rows) != 1 or len(rows[0]) != 3:
            return None
        version, generation, witness = rows[0]
        return version, generation, witness

    async def observe(self, proof: SubscriptionProof) -> SubscriptionIdentity:
        """Retain a proved active lifetime or establish the first one for this slot."""
        async with self.transaction() as (session, installation):
            current = await self.current(session, installation, proof.driver, proof.native_id)
            if current is None:
                prior = await session.execute(
                    "SELECT 1 FROM public.seqoya_subscriptions WHERE installation=%s AND driver=%s AND native_id=%s LIMIT 1",
                    (installation, proof.driver, proof.native_id))
                if not prior:
                    return await self.create_lifetime(session, installation, proof.driver, proof.native_id, proof)
            elif current.state == "active":
                if await self.proof_row(session, current) == (proof.version, proof.generation, proof.witness):
                    return current
                await self.mark_uncertain(session, current)
        # The uncertainty update must commit before refusing the caller.
        raise Refused("needs_rebind", "Explicit Subscription rebind is required.")

    @staticmethod
    async def retire_rows(session: Session, current: SubscriptionIdentity) -> None:
        values = (current.installation, current.driver, current.incarnation)
        await session.execute(
            "UPDATE public.seqoya_browser_bindings SET state='retired' "
            "WHERE installation=%s AND driver=%s AND subscription_incarnation=%s AND state<>'retired'", values)
        await session.execute(
            "UPDATE public.seqoya_subscriptions SET state='retired',retired_at=statement_timestamp() "
            "WHERE installation=%s AND driver=%s AND incarnation=%s", values)

    async def retire(self, driver: str, native_id: str, *, installation: str, incarnation: str) -> None:
        """Explicit confirmed removal, guarded against a delayed old event.

        Never call for cache eviction, a missing launcher, sign-out or relabel.
        A retired row cannot be reactivated. Repeating exact removal is harmless.
        """
        target(driver, native_id)
        canonical(incarnation)
        async with self.transaction() as (session, authority):
            current = await self.current(session, authority, driver, native_id)
            if current is None:
                canonical(installation)
                if authority != installation:
                    raise Refused("needs_rebind", "The installation identity changed.")
                return
            self.expected(current, authority, installation, incarnation)
            await self.retire_rows(session, current)

    async def rebind(self, driver: str, native_id: str, *, installation: str,
                     previous: str | None, confirmed: bool,
                     proof: SubscriptionProof | None = None) -> SubscriptionIdentity:
        """Explicit replacement only: preserve previous rows and make a fresh UUID.

        Confirmation belongs to the consuming user workflow, never catalogue
        discovery. The caller with a qualified producer verifies the proof
        against that producer before requesting the replacement.
        """
        target(driver, native_id)
        if confirmed is not True:
            raise Refused("needs_rebind", "Explicit Subscription rebind is required.")
        if proof is not None and (proof.driver, proof.native_id) != (driver, native_id):
            raise Refused("needs_rebind", "The Driver Subscription proof describes a different selection.")
        async with self.transaction() as (session, authority):
            current = await self.current(session, authority, driver, native_id)
            self.expected(current, authority, installation, previous)
            if current is not None:
                await self.retire_rows(session, current)
            return await self.create_lifetime(session, authority, driver, native_id, proof)
