"""Typed public account projections; unknown producer fields are never a secret channel."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from .bridge import Error, Params
from .metadata import iso
from .migration import message

SENSITIVE = re.compile(r"password|secret|credential|keychain|api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|token(?!s(?:\b|_)|iz)|authorization|cookie", re.I)
PRIVATE_VALUE = re.compile(r"\b(?:bearer\s+\S+|(?:password|secret|token|api[-_ ]?key)\s*[:=]\s*\S+|(?:sk-|sess-)[A-Za-z0-9_-]{8,})", re.I)
CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class Public:
    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        self.secrets = secrets
        self.nodes = 0

    def fail(self) -> Error:
        return Error("no_answer", source="driver")

    def text(self, value: Any, *, empty: bool = False) -> str:
        if (not isinstance(value, str) or not empty and not value.strip() or
                any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in value)):
            raise self.fail()
        try:
            if len(value.encode("utf-8")) > 8192:
                raise self.fail()
        except UnicodeError as error:
            raise self.fail() from error
        if PRIVATE_VALUE.search(value) or any(secret and secret in value for secret in self.secrets):
            raise self.fail()
        return value

    def id(self, value: Any) -> str:
        result = self.text(value)
        if result.startswith("-") or len(result.encode()) > 256 or any(c.isspace() or ord(c) < 32 or 127 <= ord(c) <= 159 for c in result):
            raise self.fail()
        return result

    def time(self, value: Any) -> str:
        text = self.text(value)
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                raise ValueError("An absolute time is required.")
            return iso(parsed)
        except ValueError as error:
            raise self.fail() from error

    def object(self, value: Any) -> Params:
        if not isinstance(value, dict):
            raise self.fail()
        return value

    def array(self, value: Any) -> list[Any]:
        if not isinstance(value, list):
            raise self.fail()
        return value

    def strings(self, value: Any) -> list[str]:
        return [self.text(item) for item in self.array(value)]

    def generic(self, value: Any, depth: int = 0) -> Any:
        self.nodes += 1
        if depth > 8 or self.nodes > 4096:
            raise self.fail()
        if value is None or type(value) in (bool, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise self.fail()
            return value
        if isinstance(value, str):
            return self.text(value, empty=True)
        if isinstance(value, list):
            result = []
            for item in value:
                try:
                    result.append(self.generic(item, depth+1))
                except Error:
                    if depth > 8 or self.nodes > 4096:
                        raise
            return result
        data = self.object(value)
        projected: Params = {}
        for key, item in data.items():
            if not isinstance(key, str) or SENSITIVE.search(key) or key.lower() in {"key", "token", "bearer"}:
                continue
            try:
                projected[self.text(key)] = self.generic(item, depth+1)
            except Error:
                if depth > 8 or self.nodes > 4096:
                    raise
        return projected

    @staticmethod
    def number(value: Any, *, maximum: float = math.inf) -> bool:
        if type(value) not in (int, float):
            return False
        try:
            return math.isfinite(value) and 0 <= value <= maximum
        except OverflowError:
            return False

    def optional(self, result: Params, data: Params, keys: tuple[str, ...]) -> None:
        for key in keys:
            if key in data:
                result[key] = self.text(data[key], empty=True)

    def problem(self, value: Any) -> Params:
        data = self.object(value)
        code = data.get("code")
        if not isinstance(code, str) or not CODE.fullmatch(code) or type(data.get("retryable")) is not bool:
            raise self.fail()
        result: Params = {"code": code, "message": message(data.get("message"), secrets=self.secrets,
            fallback="The Driver could not confirm this account operation."), "retryable": data["retryable"]}
        if self.number(data.get("retryAfterSeconds")):
            result["retryAfterSeconds"] = data["retryAfterSeconds"]
        if "remedy" in data:
            result["remedy"] = message(data["remedy"], secrets=self.secrets, fallback="Check this Subscription with its Driver.")
        if "detail" in data:
            detail = self.object(data["detail"])
            projected: Params = {}
            self.optional(projected, detail, ("basis", "vendorCode", "limit", "toolVersion", "neededVersion"))
            for key in ("vendorStatus", "toolExit"):
                if type(detail.get(key)) is int:
                    projected[key] = detail[key]
            if projected:
                result["detail"] = projected
        return result

    def usage(self, value: Any) -> Params:
        data = self.object(value)
        if data.get("outcome") not in ("ok", "needs_sign_in", "unavailable", "unsupported"):
            raise self.fail()
        result: Params = {"outcome": data["outcome"], "fetchedAt": self.time(data.get("fetchedAt")), "windows": []}
        if data["outcome"] != "ok":
            result["message"] = message(data.get("message"), secrets=self.secrets,
                fallback="The Driver did not provide a current usage reading.")
        self.optional(result, data, ("plan",))
        for raw in self.array(data.get("windows")):
            window = self.object(raw)
            if window.get("kind") not in ("session", "weekly", "other"):
                raise self.fail()
            entry = {"kind": window["kind"], "label": self.text(window.get("label"))}
            if window.get("resource") in ("tokens", "credits", "calls"):
                entry["resource"] = window["resource"]
            for key, maximum in (("usedPercent", 100), ("windowMinutes", math.inf)):
                if self.number(window.get(key), maximum=maximum):
                    entry[key] = window[key]
            if type(window.get("limitReached")) is bool:
                entry["limitReached"] = window["limitReached"]
            if "resetsAt" in window:
                entry["resetsAt"] = self.time(window["resetsAt"])
            result["windows"].append(entry)
        if "detailsUrl" in data:
            url = self.text(data["detailsUrl"])
            try:
                parsed = urlsplit(url)
                if parsed.scheme == "https" and parsed.hostname and parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment:
                    result["detailsUrl"] = url
            except ValueError:
                pass
        if "extra" in data:
            result["extra"] = self.generic(self.object(data["extra"]))
        return result

    def subscription(self, value: Any) -> Params:
        data = self.object(value)
        result: Params = {"id": self.id(data.get("id"))}
        for key in ("family", "label", "auth", "state"):
            result[key] = self.text(data.get(key))
        result.update(createdAt=self.time(data.get("createdAt")), updatedAt=self.time(data.get("updatedAt")),
                      settings=self.generic(self.object(data.get("settings"))))
        if "account" in data:
            account: Params = {}
            self.optional(account, self.object(data["account"]), ("name", "email", "organization", "plan"))
            result["account"] = account
        if result["state"] == "needs_attention":
            result["problem"] = self.problem(data.get("problem"))
        if "checkedAt" in data:
            result["checkedAt"] = self.time(data["checkedAt"])
        if "lastUsage" in data:
            try:
                usage = self.usage(data["lastUsage"])
                if usage["outcome"] == "ok":
                    result["lastUsage"] = usage
            except Error:
                pass  # An unavailable optional last reading is never replaced with invented zeroes.
        return result

    def models(self, value: Any) -> Params:
        data = self.object(value)
        if data.get("source") not in ("vendor", "tool", "builtin"):
            raise self.fail()
        result: Params = {"source": data["source"], "fetchedAt": self.time(data.get("fetchedAt")), "models": []}
        for raw in self.array(data.get("models")):
            model = self.object(raw)
            entry: Params = {"id": self.text(model.get("id")), "label": self.text(model.get("label"))}
            self.optional(entry, model, ("description", "defaultEffort"))
            for key in ("efforts", "serviceTiers"):
                if key in model:
                    entry[key] = self.strings(model[key])
            if type(model.get("isDefault")) is bool:
                entry["isDefault"] = model["isDefault"]
            result["models"].append(entry)
        return result
