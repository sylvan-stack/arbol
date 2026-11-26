"""Seqoya's scoped Browser observations, retained by exact installation and profile binding."""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .accounts import Accounts
from .bridge import Params, constant, finite, pairs
from .browser_commands import BrowserCommands, unavailable
from .browser_profiles import BrowserProfiles, ProfileBinding
from .model import Refused

LIMIT = 128 * 1024
AMOUNT = re.compile(r"\d{1,18}(?:\.\d{1,8})?\Z")
PLAN = {"plus", "pro", "pro-200", "max", "team", "enterprise"}
ISSUES = {
    "deferred": "Usage refresh paused for activity in Arbol Browser.",
    "authentication_required": "Sign in from this subscription's Browser profile and refresh again.",
    "dashboard_unavailable": "The usage dashboard did not report readable allowance data.",
    "needs_rebind": "Open this subscription to verify its Browser profile.",
    "maintenance": "Usage refresh is paused during Arbol maintenance.",
}
Provider = tuple[str, str]
Verify = Callable[[], Awaitable[None]]
Capture = Callable[[Provider, ProfileBinding, Verify], Awaitable[Params]]


def instant(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 32 or "T" not in value:
        raise ValueError
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError
    return parsed


def percent(value: Any) -> float:
    if type(value) not in (int, float) or not 0 <= value <= 100:
        raise ValueError
    return float(value)


def amount(value: Any) -> str:
    if not isinstance(value, str) or AMOUNT.fullmatch(value) is None:
        raise ValueError
    return value


def report(provider: Provider, value: Any) -> tuple[Params, list[str]]:
    optional = {
        ("codex", "chatgpt"): {"plan", "resetCredits"}, ("pi", "chatgpt"): {"plan", "piCapPercent"},
        ("claude", "anthropic"): {"plan", "resetCredits"}, ("pi", "deepseek"): {"deepseekBalance"},
        ("mimo", "xiaomi"): {"plan", "mimoCredits"}, ("pi", "minimax"): {"minimax"},
    }
    required = {"observedAt", "windows"}
    if not isinstance(value, dict) or not required <= value.keys() <= required | optional.get(provider, set()):
        raise ValueError
    observed = instant(value.get("observedAt"))
    if observed > datetime.now(UTC):
        raise ValueError
    windows: list[Params] = []
    approximate: list[str] = []
    extra: Params = {}
    seen: set[int] = set()
    rows = value.get("windows")
    if not isinstance(rows, list) or len(rows) > 3:
        raise ValueError
    driver, subscription = provider
    if rows and subscription in ("xiaomi", "deepseek"):
        raise ValueError
    for row in rows:
        if not isinstance(row, dict) or not row.keys() <= {"minutes", "usedPercent", "resetAt", "creditsTotal"}:
            raise ValueError
        minutes = row.get("minutes")
        if type(minutes) is not int or minutes not in (300, 10080, 43200) or minutes in seen:
            raise ValueError
        seen.add(minutes)
        name = {300: "Five hours", 10080: "Seven days", 43200: "Monthly, Kimi Code"}[minutes]
        if provider == ("pi", "chatgpt"):
            name = "Shared five-hour quota" if minutes == 300 else "Shared weekly quota"
        resource = ("calls" if minutes == 300 else "credits") if subscription == "kimi-coding" else (
            "credits" if subscription in ("zai", "minimax") else "tokens")
        window: Params = {"label": name, "windowMinutes": minutes, "resource": resource,
                          "kind": {300: "session", 10080: "weekly", 43200: "other"}[minutes],
                          "usedPercent": percent(row.get("usedPercent"))}
        if "resetAt" in row:
            window["resetsAt"] = instant(row["resetAt"]).isoformat()
            approximate.append(name)
        if "creditsTotal" in row:
            total = row["creditsTotal"]
            if subscription != "zai" or type(total) is not int or not 1 <= total <= 10**12:
                raise ValueError
            window["creditsTotal"] = total
        windows.append(window)
    reading: Params = {"fetchedAt": observed.isoformat(), "windows": windows}
    if "plan" in value:
        plan = value["plan"]
        if not isinstance(plan, str) or plan not in PLAN:
            raise ValueError
        reading["plan"] = plan
    if provider == ("pi", "chatgpt"):
        cap = percent(value.get("piCapPercent"))
        extra["connectedApp"] = {"allowed": cap > 0, "capPercent": cap}
    if "resetCredits" in value:
        resets = value["resetCredits"]
        if driver not in ("claude", "codex") or not isinstance(resets, dict) or resets.keys() != {"available", "expiries"}:
            raise ValueError
        count, expiries = resets["available"], resets["expiries"]
        if type(count) is not int or not isinstance(expiries, list) or not 0 <= len(expiries) <= count <= 100:
            raise ValueError
        extra["rateLimitResetCredits"] = {"availableCount": count, "credits": [
            {"id": str(index), "title": "Full reset", "status": "available", "expiresAt": int(instant(expiry).timestamp())}
            for index, expiry in enumerate(expiries)
        ]}
    if subscription == "deepseek":
        balance = amount(value.get("deepseekBalance"))
        extra["apiBalance"] = {"balance": balance, "observedAt": observed.isoformat()}
        extra["balances"] = [{"currency": "USD", "amount": balance}]
    if subscription == "xiaomi":
        credits = value.get("mimoCredits")
        if not isinstance(credits, dict) or credits.keys() != {"total", "remaining", "resetAt"}:
            raise ValueError
        total, remaining = amount(credits["total"]), amount(credits["remaining"])
        if not total.isdecimal() or not remaining.isdecimal() or not 0 <= int(remaining) <= int(total) <= 10**15 or not int(total):
            raise ValueError
        extra["planCredits"] = {"total": total, "remaining": remaining}
        windows.append({"label": "Token Plan", "windowMinutes": 43200, "kind": "other", "resource": "credits",
                        "resetsAt": instant(credits["resetAt"]).isoformat(),
                        "usedPercent": (int(total) - int(remaining)) * 100 / int(total)})
    if subscription == "minimax":
        minimax = value.get("minimax")
        if (not isinstance(minimax, dict) or not {"activePlan", "credits", "llmTokens", "period"} <= minimax.keys()
                <= {"activePlan", "credits", "llmTokens", "period", "cacheHitPercent"}
                or type(minimax["activePlan"]) is not bool or minimax["period"] not in ("Today", "Last 7 days", "Last 30 days")
                or not isinstance(minimax["llmTokens"], str) or not re.fullmatch(r"\d[\d,.]{0,25}[KMBT]?", minimax["llmTokens"])):
            raise ValueError
        details = {"activePlan": minimax["activePlan"], "creditBalance": amount(minimax["credits"]),
                   "llmTokens": minimax["llmTokens"], "period": minimax["period"]}
        if "cacheHitPercent" in minimax:
            details["cacheHitPercent"] = percent(minimax["cacheHitPercent"])
        extra["minimax"] = details
    if not windows and subscription not in ("deepseek", "minimax"):
        raise ValueError
    if extra:
        reading["extra"] = extra
    return reading, approximate


def cache_read(path: Path) -> dict[str, Params]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > LIMIT):
            raise ValueError
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError
    value = json.loads(data, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite)
    if (not isinstance(value, dict) or value.keys() != {"format", "receipts"} or type(value["format"]) is not int
            or value["format"] != 1 or not isinstance(value["receipts"], dict) or len(value["receipts"]) > 8
            or any(not isinstance(entry, dict) for entry in value["receipts"].values())):
        raise ValueError
    return value["receipts"]


def cache_write(path: Path, receipts: dict[str, Params]) -> None:
    data = json.dumps({"format": 1, "receipts": receipts}, allow_nan=False, separators=(",", ":")).encode() + b"\n"
    if len(data) > LIMIT:
        raise ValueError
    fd, name = tempfile.mkstemp(prefix=".seqoya-usage-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def binding_key(binding: ProfileBinding) -> list[str | None]:
    return [binding.installation, binding.driver, binding.incarnation, binding.profile, binding.instance]


class BrowserUsage:
    def __init__(self, accounts: Accounts, browser: BrowserCommands, profiles: BrowserProfiles, capture: Capture,
                 providers: tuple[Provider, ...]) -> None:
        self.accounts, self.browser, self.profiles, self.capture = accounts, browser, profiles, capture
        self.providers = providers
        self.path = browser.identity.folder / "seqoya-signed-usage.json"
        self.lock = asyncio.Lock()
        self.cursor = 0

    async def one(self, provider: Provider, receipts: dict[str, Params], *, refresh: bool) -> tuple[Params | None, str | None]:
        driver, subscription = provider
        key = "/".join(provider)
        pending = None
        async with self.accounts.browser_identity_request(*provider) as (selected, verify_proof, _):
            binding = await self.profiles.active(selected, self.browser)

            async def current_account() -> Params:
                account = await self.accounts.browser_slot(*provider)
                if account.get("state") != "signed_in" or account.get("family") != subscription or not account.get("createdAt"):
                    raise Refused("needs_rebind", ISSUES["needs_rebind"])
                return account

            async def verify() -> None:
                await verify_proof()
                await self.profiles.require_binding(selected, binding)
                await current_account()

            failure = None
            entry = receipts.get(key, {})
            if refresh:
                try:
                    await verify()
                    result = await self.capture(provider, binding, verify)
                    if result.get("status") == "read" and result.keys() == {"status", "reading"}:
                        report(provider, result["reading"])
                        await self.profiles.verify(selected, binding, self.browser)
                        entry = {"binding": binding_key(binding), "capture": result["reading"]}
                        pending = entry
                    else:
                        status = result.get("status")
                        failure = ISSUES.get(status, ISSUES["dashboard_unavailable"]) if isinstance(status, str) else ISSUES["dashboard_unavailable"]
                except (OSError, ValueError, Refused):
                    failure = ISSUES["dashboard_unavailable"]
            if entry.get("binding") != binding_key(binding):
                return None, failure
            account = await current_account()
            await verify()
            reading, approximate = report(provider, entry.get("capture"))
            result = {"driver": driver, "subscription": subscription, "createdAt": account["createdAt"],
                      "checkedAt": account.get("checkedAt"), "report": reading, "approximateWindows": approximate}
        if pending is not None:
            cache_write(self.path, {**receipts, key: pending})
            receipts[key] = pending
        return result, failure

    async def saved(self, params: Params) -> Params:
        return await self.collect(refresh=False)

    async def refresh(self, params: Params) -> Params:
        if self.lock.locked():
            return await self.saved(params)
        async with self.lock:
            return await self.collect(refresh=True)

    async def collect(self, *, refresh: bool) -> Params:
        try:
            receipts = cache_read(self.path)
            if receipts.keys() - {"/".join(provider) for provider in self.providers}:
                raise ValueError
        except (OSError, ValueError, Refused):
            raise unavailable() from None
        evidence, issues = [], {}
        cutoff = asyncio.get_running_loop().time() + (104 if refresh else 10)
        providers = self.providers[self.cursor:] + self.providers[:self.cursor] if refresh else self.providers
        attempted = 0
        for provider in providers:
            key = "/".join(provider)
            if not refresh and key not in receipts:
                continue
            attempted += 1
            try:
                async with asyncio.timeout_at(cutoff):
                    entry, failure = await self.one(provider, receipts, refresh=refresh)
                if entry:
                    evidence.append(entry)
                if failure:
                    issues[key] = failure
            except TimeoutError:
                issues[key] = ISSUES["dashboard_unavailable"]
                break
            except (OSError, ValueError, Refused) as error:
                code = error.code if isinstance(error, Refused) else "dashboard_unavailable"
                issues[key] = ISSUES.get(code, ISSUES["dashboard_unavailable"])
        if refresh:
            self.cursor = (self.cursor + max(1, attempted)) % len(self.providers)
        return {"evidence": {"browserReports": evidence}, "issues": issues}
