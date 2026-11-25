"""Seqoya's local native Bridge adapter for opening bound usage dashboards."""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass

from .accounts import Accounts, BrowserReplacement
from .bridge import Error, Params, Registry
from .browser_commands import BrowserCommands
from .browser_profiles import BrowserProfiles
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


class BrowserBridge:
    def __init__(self, accounts: Accounts, database: Database, registry: Registry) -> None:
        self.accounts = accounts
        self.browser = BrowserCommands(database.identity)
        self.profiles = BrowserProfiles(database)
        self.selections: dict[str, OfferedReplacement] = {}
        registry.method("seqoya.browser.open", self.open, self.open_params)
        registry.method("seqoya.browser.rebind", self.rebind, self.rebind_params)

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
                return {"status": "unavailable"}
            try:
                replacement = await self.accounts.prepare_browser_rebind(*target)
            except Refused:
                return {"status": "unavailable"}
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
            return {"status": "selection_expired" if error.code == "needs_rebind" else "unavailable"}
        return {"status": "opened"}
