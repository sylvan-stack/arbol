"""Shared allowlisted Driver reads and bounded independently failed public accounts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import partial
from typing import Any

from .account_data import CODE, Public
from .allowance_start import pending_window, start_window
from .bridge import MAX_LINE, Error, Params, Registry, driver_id, encode
from .database import Database
from .dispatch import Forwarded
from .driver_identity import DriverIdentity
from .metadata import iso
from .migration import message
from .model import Refused
from .process import Programs
from .subscription_identity import SubscriptionIdentities, SubscriptionIdentity
from .validation import Catalogues

TOTAL = 25.0
CAPACITY = 8
ACTIVITY = """
    SELECT count(*),
           sum(CASE WHEN jsonb_typeof(r.usage->'inputTokens') = 'number'
                    AND r.usage->>'inputTokens' ~ '^[0-9]{1,20}$'
                    THEN (r.usage->>'inputTokens')::numeric END)::text,
           sum(CASE WHEN jsonb_typeof(r.usage->'outputTokens') = 'number'
                    AND r.usage->>'outputTokens' ~ '^[0-9]{1,20}$'
                    THEN (r.usage->>'outputTokens')::numeric END)::text,
           max(r.ended_at)
    FROM public.runs r JOIN public.exchanges e ON e.id = r.exchange_id
    WHERE r.kind = 'agent'
      AND r.ended_at BETWEEN statement_timestamp() - interval '30 days' AND statement_timestamp()
      AND e.route->>'driver' = %s
      AND coalesce(r.started->>'subscriptionId', e.route->>'subscription') = %s
"""


class Accounts:
    def __init__(self, programs: Programs, catalogues: Catalogues, registry: Registry,
                 secrets: Callable[[], tuple[str, ...]], *, total: float = TOTAL, capacity: int = CAPACITY,
                 database: Database | None = None) -> None:
        self.programs, self.catalogues, self.secrets = programs, catalogues, secrets
        self.database = database
        self.identities = SubscriptionIdentities(database) if database is not None else None
        self.driver_identity = DriverIdentity(programs.identity)
        self.total, self.capacity = total, asyncio.Semaphore(capacity)
        self.raws: dict[str, asyncio.Task[list[Any] | Error]] = {}
        self.actions: dict[tuple[str, str, str], asyncio.Task[Params | Error]] = {}
        self.closed = False
        catalogues.fetch = self.raw
        registry.method("accounts.list", self.list)
        for operation in ("check", "usage", "models"):
            registry.method("accounts."+operation, partial(self.action, operation), self.target)
        registry.method("accounts.startWindow", self.start_window, self.window_target)
        if database is not None:
            registry.method("accounts.activity", self.activity, self.target)

    def identity_authority(self) -> SubscriptionIdentities:
        if self.identities is None:
            raise Refused("database_unavailable", "Subscription browser binding requires the installation database.")
        return self.identities

    async def browser_slot(self, driver: str, subscription: str) -> None:
        """Validate a current catalogue slot without promoting it to identity.

        A failed list propagates before any identity write. Relabel/sign-out,
        disappearing launchers and catalogue-cache eviction are not removals.
        """
        driver_id(driver, set(self.scan()))
        public = Public(self.secrets())
        subscription = public.id(subscription)
        rows = await self.raw(driver)
        selected = [row for row in rows if public.subscription_slot(row) == subscription]
        if len(selected) != 1:
            raise Refused("needs_rebind", "The current Subscription cannot be established.")
        public.subscription(selected[0])

    @asynccontextmanager
    async def browser_identity_request(
        self, driver: str, subscription: str,
    ) -> AsyncIterator[tuple[SubscriptionIdentity, Callable[[], Awaitable[None]]]]:
        """Verify a fresh proof before admitting the binding and again before returning its result."""
        authority = self.identity_authority()
        await self.browser_slot(driver, subscription)
        async with authority.database.browser_authority():
            captured = await self.driver_identity.capture(driver, subscription)
            selected = await authority.observe(captured.proof)
            verify = partial(self.driver_identity.expect, captured)
            await verify()
            yield selected, verify
            await verify()

    async def browser_identity(self, driver: str, subscription: str) -> SubscriptionIdentity:
        async with self.browser_identity_request(driver, subscription) as (selected, _):
            return selected

    async def rebind_browser_identity(self, driver: str, subscription: str, *, installation: str,
                                      previous: str | None, confirmed: bool) -> SubscriptionIdentity:
        """Replace the exact confirmed selection with a fresh, proved lifetime."""
        authority = self.identity_authority()
        if confirmed is not True:
            raise Refused("needs_rebind", "Explicit Subscription rebind is required.")
        await self.browser_slot(driver, subscription)
        async with authority.database.browser_authority():
            captured = await self.driver_identity.capture(driver, subscription)
            await self.driver_identity.expect(captured)
            selected = await authority.rebind(driver, subscription, installation=installation, previous=previous,
                                              confirmed=confirmed, proof=captured.proof)
            await self.driver_identity.expect(captured)
            return selected

    async def retire_browser_identity(self, driver: str, subscription: str, *, installation: str,
                                      incarnation: str) -> None:
        """Only an explicit confirmed removal signal may retire an exact lifetime.

        Current accounts APIs do not expose a removal command. Keep this seam
        internal until a consuming lifecycle operation supplies that signal.
        """
        authority = self.identity_authority()
        async with authority.database.browser_authority():
            await authority.retire(driver, subscription, installation=installation, incarnation=incarnation)

    def scan(self) -> list[str]:
        drivers = self.programs.find_drivers()
        self.catalogues.launchers = drivers
        for name in self.catalogues.subscriptions.keys()-drivers:
            self.catalogues.subscriptions.pop(name, None)
        return sorted(drivers)

    def refused(self, value: Any) -> None:
        if not isinstance(value, dict) or "error" not in value:
            return
        error = value["error"]
        if not isinstance(error, dict) or not isinstance(error.get("code"), str) or not CODE.fullmatch(error["code"]):
            raise Error("no_answer", source="driver")
        raise Forwarded(error["code"], "driver", message(error.get("message"), secrets=self.secrets(),
            fallback="The Driver refused this account operation."))

    async def raw_outcome(self, driver: str) -> list[Any] | Error:
        try:
            async with asyncio.timeout(self.total), self.capacity:
                value = await self.programs.call("arbol-"+driver+"-driver", ["subscriptions", "list"],
                                                 kind="account", key="accounts-list-"+driver)
            self.refused(value)
            public = Public(self.secrets())
            rows = public.array(value)
            identifiers = [public.id(public.object(row).get("id")) for row in rows]
            if len(set(identifiers)) != len(identifiers):
                raise Error("no_answer", source="driver")
            self.catalogues.subscriptions[driver] = set(identifiers)
            return rows
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.catalogues.subscriptions.pop(driver, None)
            return error if isinstance(error, Error) else Error("no_answer", source="driver")

    def forget(self, driver: str, task: asyncio.Task[list[Any] | Error]) -> None:
        if self.raws.get(driver) is task:
            self.raws.pop(driver, None)

    async def raw(self, driver: str) -> list[Any]:
        if self.closed:
            raise Error("ended", source="driver")
        task = self.raws.get(driver)
        if task is None or task.done():
            task = asyncio.create_task(self.raw_outcome(driver))
            self.raws[driver] = task
            task.add_done_callback(lambda finished: self.forget(driver, finished))
        result = await asyncio.shield(task)
        if isinstance(result, Error):
            raise result
        return result

    async def list(self, params: Params) -> Params:
        """Read the Drivers' saved catalogue without a vendor call or a database connection."""
        if self.closed:
            raise Error("ended", source="driver")
        drivers = self.scan()
        error = Error("no_answer", source="driver").wire()
        rows: list[Params] = [{"driver": name, "error": error} for name in drivers]
        budget = len(encode({"drivers": rows}))
        limit = MAX_LINE-4096
        if budget > limit:
            raise Error("no_answer", source="driver")
        queue = asyncio.Queue[int]()
        for index in range(len(rows)):
            queue.put_nowait(index)
        async def worker() -> None:
            nonlocal budget
            while not queue.empty():
                index = queue.get_nowait()
                driver = drivers[index]
                try:
                    raw = await self.raw(driver)
                    public = Public(self.secrets())
                    entry: Params = {"driver": driver, "subscriptions": [public.subscription(value) for value in raw]}
                except Exception as refused:
                    entry = {"driver": driver, "error": (refused if isinstance(refused, Error) else Error("no_answer", source="driver")).wire()}
                delta = len(encode(entry))-len(encode(rows[index]))
                if budget+delta <= limit:
                    rows[index] = entry
                    budget += delta
        workers = [asyncio.create_task(worker()) for _ in range(min(CAPACITY, len(rows)))]
        try:
            async with asyncio.timeout(self.total):
                await asyncio.gather(*workers)
        except TimeoutError:
            pass
        finally:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        return {"drivers": rows}

    async def target(self, params: Params) -> Params:
        driver = driver_id(params.get("driver"), set(self.scan()))
        try:
            subscription = Public(self.secrets()).id(params.get("subscription"))
        except Error as error:
            raise Error("invalid_input") from error
        return {"driver": driver, "subscription": subscription}

    async def activity(self, params: Params) -> Params:
        """Aggregate the installation's saved agent runs without contacting a Driver or vendor."""
        if self.closed or self.database is None:
            raise Error("ended")
        try:
            async with asyncio.timeout(self.total), self.capacity, self.database.session(snapshot=True) as session:
                (runs, input_tokens, output_tokens, last_run), = await session.execute(
                    ACTIVITY, [params["driver"], params["subscription"]]
                )
        except TimeoutError as error:
            raise Error("timeout") from error
        result: Params = {"runCount": runs}
        if input_tokens is not None:
            result["inputTokens"] = input_tokens
        if output_tokens is not None:
            result["outputTokens"] = output_tokens
        if last_run is not None:
            result["lastRunAt"] = iso(last_run)
        return result

    async def window_target(self, params: Params) -> Params:
        target = await self.target(params)
        try:
            target["createdAt"] = Public(self.secrets()).time(params.get("createdAt"))
        except Error as error:
            raise Error("invalid_input") from error
        return target

    async def window_outcome(self, params: Params) -> Params | Error:
        try:
            if self.closed or self.database is None:
                raise Error("ended")
            async with asyncio.timeout(40), self.database.permit():
                public = Public(self.secrets())
                rows = [public.subscription(row) for row in await self.raw(params["driver"])]
                account = next((row for row in rows if row["id"] == params["subscription"]), None)
                if account is None or account["createdAt"] != params["createdAt"]:
                    raise Error("invalid_input")
                if not pending_window(params["driver"], account):
                    return {"outcome": "skipped"}
                async with self.capacity:
                    await start_window(self.programs, params["driver"], params["subscription"])
                return {"outcome": "started"}
        except asyncio.CancelledError:
            raise
        except Refused as error:
            return error if isinstance(error, Error) else Error(error.code)
        except Exception as error:
            return error if isinstance(error, Error) else Error("no_answer", source="driver")

    async def start_window(self, params: Params) -> Params:
        # Incarnations cannot share a result, and a disconnected caller cannot cancel
        # another window's admitted request or release its permit before cleanup.
        key = ("startWindow:" + params["createdAt"], params["driver"], params["subscription"])
        task = self.actions.get(key)
        if task is None or task.done():
            task = asyncio.create_task(self.window_outcome(params))
            self.actions[key] = task
            task.add_done_callback(lambda done: self.forget_action(key, done))
        result = await asyncio.shield(task)
        if isinstance(result, Error):
            raise result
        return result

    async def action_outcome(self, key: tuple[str, str, str]) -> Params | Error:
        operation, driver, subscription = key
        try:
            async with asyncio.timeout(self.total), self.capacity:
                value = await self.programs.call("arbol-"+driver+"-driver", ["subscriptions", operation, subscription],
                    kind="account", key="accounts-action-"+json.dumps(key, separators=(",", ":")))
            self.refused(value)
            public = Public(self.secrets())
            if operation == "check":
                result = public.subscription(value)
                if result["id"] != subscription:
                    raise Error("no_answer", source="driver")
                return result
            return public.usage(value) if operation == "usage" else public.models(value)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            return error if isinstance(error, Error) else Error("no_answer", source="driver")

    def forget_action(self, key: tuple[str, str, str], task: asyncio.Task[Params | Error]) -> None:
        if self.actions.get(key) is task:
            self.actions.pop(key, None)

    async def action(self, operation: str, params: Params) -> Params:
        """Run an explicit Driver action. Any cache change stays with that Driver."""
        if operation not in ("check", "usage", "models"):
            raise Error("invalid_input")
        try:
            async with asyncio.timeout(self.total):
                raw = await self.raw(params["driver"])
                public = Public(self.secrets())
                rows = [public.subscription(row) for row in raw]
                if not any(row["id"] == params["subscription"] for row in rows):
                    raise Error("invalid_input")
                key = (operation, params["driver"], params["subscription"])
                task = self.actions.get(key)
                if task is None or task.done():
                    task = asyncio.create_task(self.action_outcome(key))
                    self.actions[key] = task
                    task.add_done_callback(lambda done: self.forget_action(key, done))
                result = await asyncio.shield(task)
                if isinstance(result, Error):
                    raise result
                return result
        except TimeoutError as error:
            raise Error("no_answer", source="driver") from error

    async def close(self) -> None:
        self.closed = True
        self.catalogues.fetch = None
        tasks = [*self.raws.values(), *self.actions.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.raws.clear()
        self.actions.clear()
