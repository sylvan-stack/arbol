"""Seqoya's local native Bridge adapter for opening bound usage dashboards."""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .accounts import Accounts, BrowserReplacement
from .bridge import Error, Params, Registry
from .browser_commands import BROWSER_SECONDS, INSTANCE, SEQOYA_PROFILE, USAGE_CLAIM, BrowserCommands, unavailable
from .browser_profiles import BrowserProfiles, ProfileBinding
from .browser_usage import BrowserUsage
from .database import Database
from .model import Refused

DESTINATIONS = {
    ("codex", "chatgpt"): "https://chatgpt.com/settings/usage",
    ("pi", "chatgpt"): "https://chatgpt.com/settings/usage",
    ("claude", "anthropic"): "https://claude.ai/settings/usage",
    ("pi", "kimi-coding"): "https://www.kimi.ai/code/console",
    ("pi", "deepseek"): "https://platform.deepseek.com/usage",
    ("mimo", "xiaomi"): "https://platform.xiaomimimo.com/console/plan-manage",
    ("pi", "zai"): "https://z.ai/manage-apikey/coding-plan/personal/my-plan",
    ("pi", "minimax"): "https://platform.minimax.io/console/usage",
}
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
SELECTION_SECONDS = 120
MAX_SELECTIONS = 128


@dataclass(frozen=True)
class OfferedReplacement:
    target: tuple[str, str]
    replacement: BrowserReplacement
    expires: float


@dataclass
class UsageClaim:
    provider: str
    binding: ProfileBinding
    verify: Callable[[], Awaitable[None]]
    expires: float
    claimed: bool = False
    admitted: bool = False


class BrowserBridge:
    def __init__(self, accounts: Accounts, database: Database, registry: Registry) -> None:
        self.accounts = accounts
        self.browser = BrowserCommands(database.identity)
        self.profiles = BrowserProfiles(database)
        self.selections: dict[str, OfferedReplacement] = {}
        self.usage_claims: dict[str, UsageClaim] = {}
        registry.method("seqoya.browser.open", self.open, self.open_params)
        registry.method("seqoya.browser.rebind", self.rebind, self.rebind_params)
        registry.method("seqoya.browser.usage.check", self.check_usage, self.claim_params)
        registry.method("seqoya.browser.usage.claim", self.claim_usage, self.claim_params)
        self.usage = BrowserUsage(accounts, self.browser, self.profiles, self.capture_usage, tuple(DESTINATIONS))
        registry.method("seqoya.browser.usage.saved", self.usage.saved)
        registry.method("seqoya.browser.usage.refresh", self.usage.refresh)

    async def capture_usage(self, provider: tuple[str, str], binding: ProfileBinding,
                            verify: Callable[[], Awaitable[None]]) -> Params:
        if (provider not in DESTINATIONS or binding.driver != provider[0] or binding.state != "active"
                or binding.instance is None or len(self.usage_claims) >= len(DESTINATIONS)):
            raise unavailable()
        key = "/".join(provider)
        token = secrets.token_urlsafe(32)
        claim = UsageClaim(key, binding, verify, time.monotonic() + BROWSER_SECONDS)
        self.usage_claims[token] = claim
        try:
            result = await self.browser.capture_usage(key, binding.profile, binding.instance, token)
            if not claim.admitted:
                raise unavailable()
            return result
        finally:
            self.usage_claims.pop(token, None)

    async def claim_params(self, params: Params) -> Params:
        token, provider, profile, instance = (params.get(key) for key in ("claim", "provider", "profile", "instance"))
        if (params.keys() != {"claim", "provider", "profile", "instance"} or not isinstance(token, str)
                or USAGE_CLAIM.fullmatch(token) is None or not isinstance(provider, str) or len(provider) > 64
                or not isinstance(profile, str) or SEQOYA_PROFILE.fullmatch(profile) is None
                or not isinstance(instance, str) or INSTANCE.fullmatch(instance) is None):
            raise Error("invalid_input")
        return params

    async def check_usage(self, params: Params) -> Params:
        return await self.admit_usage(params, consume=False)

    async def claim_usage(self, params: Params) -> Params:
        return await self.admit_usage(params, consume=True)

    async def admit_usage(self, params: Params, *, consume: bool) -> Params:
        token = params["claim"]
        claim = self.usage_claims.get(token)
        if (claim is None or claim.claimed or time.monotonic() >= claim.expires
                or (claim.provider, claim.binding.profile, claim.binding.instance)
                != (params["provider"], params["profile"], params["instance"])):
            raise Error("invalid_input")
        if consume:
            claim.claimed = True
        await claim.verify()
        if (self.usage_claims.get(token) is not claim or time.monotonic() >= claim.expires
                or (not consume and claim.claimed)):
            raise Error("invalid_input")
        if consume:
            claim.admitted = True
        return {"admitted": True}

    @staticmethod
    def unavailable(error: Refused) -> Params:
        if error.code == "maintenance":
            return {"status": "maintenance"}
        if isinstance(error, Error) and error.source == "driver":
            return {"status": "catalogue_unavailable"}
        return {"status": "unavailable"}

    @staticmethod
    def target(params: Params) -> tuple[str, str]:
        driver, subscription = params.get("driver"), params.get("subscription")
        if not isinstance(driver, str) or not isinstance(subscription, str) or (driver, subscription) not in DESTINATIONS:
            raise Error("invalid_input")
        return driver, subscription

    async def open_params(self, params: Params) -> Params:
        if params.keys() != {"driver", "subscription"}:
            raise Error("invalid_input")
        self.target(params)
        return params

    async def rebind_params(self, params: Params) -> Params:
        token = params.get("selection")
        if (params.keys() != {"driver", "subscription", "selection", "confirmed"} or params["confirmed"] is not True
                or not isinstance(token, str) or TOKEN.fullmatch(token) is None):
            raise Error("invalid_input")
        self.target(params)
        return params

    async def open(self, params: Params) -> Params:
        target = self.target(params)
        try:
            await self.profiles.open(self.accounts, self.browser, *target, DESTINATIONS[target])
        except Refused as error:
            if error.code != "needs_rebind":
                return self.unavailable(error)
            try:
                replacement = await self.accounts.prepare_browser_rebind(*target)
            except Refused as refused:
                return self.unavailable(refused)
            now = time.monotonic()
            self.selections = {token: offer for token, offer in self.selections.items() if offer.expires > now}
            if len(self.selections) >= MAX_SELECTIONS:
                del self.selections[next(iter(self.selections))]
            token = secrets.token_urlsafe(32)
            self.selections[token] = OfferedReplacement(target, replacement, now + SELECTION_SECONDS)
            return {"status": "rebind_required", "selection": token}
        return {"status": "opened"}

    async def rebind(self, params: Params) -> Params:
        target = self.target(params)
        token = params["selection"]
        offer = self.selections.get(token)
        if offer is None or offer.target != target or offer.expires <= time.monotonic():
            return {"status": "selection_expired"}
        del self.selections[token]
        try:
            async with self.accounts.rebind_browser_identity(*target, replacement=offer.replacement) as (selected, verify):
                binding = await self.profiles.reconcile(selected, self.browser)
                await self.profiles.require_binding(selected, binding)
                await verify()
                if binding.instance is None:
                    return {"status": "unavailable"}
                await self.browser.open(binding.profile, binding.instance, DESTINATIONS[target])
                await self.profiles.require_binding(selected, binding)
        except Refused as error:
            if error.code == "needs_rebind":
                return {"status": "selection_expired"}
            return self.unavailable(error)
        return {"status": "opened"}
