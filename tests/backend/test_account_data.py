"""Public family metadata remains useful without becoming a credential channel."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.account_data import Public  # noqa: E402
from arbol_backend.bridge import Error  # noqa: E402
from backend.account_support import models, subscription, usage  # noqa: E402


class Projection(unittest.TestCase):
    def test_public_records_usage_models_and_additive_metadata_are_typed(self) -> None:
        """accounts.public-records; accounts.forward-metadata; accounts.last-usage"""
        raw = subscription(state="future-state", auth="future-auth", settings={"timeout": 7, "nested": [False, None, "ok"]},
                           lastUsage=usage(), account={"name": "A", "email": "private@example.test", "future": "ignored"})
        result = Public().subscription(raw)
        self.assertEqual((result["state"], result["auth"]), ("future-state", "future-auth"))
        self.assertEqual(result["lastUsage"]["windows"][0]["resource"], "tokens")
        self.assertEqual(result["lastUsage"]["windows"][0]["resetsAt"], "2026-11-01T12:00:00.000Z")
        self.assertEqual(result["settings"], raw["settings"])
        self.assertNotIn("future", result["account"])
        self.assertEqual(Public().models(models())["models"][0]["efforts"], ["low", "high"])
        self.assertNotIn("lastUsage", Public().subscription(subscription(lastUsage=usage(outcome="unsupported"))))

    def test_recursive_private_keys_assignments_known_password_and_excerpts_are_omitted(self) -> None:
        """accounts.private-projection; accounts.no-diagnostic-excerpt"""
        private = "fictional-database-value"
        raw = subscription(secret="top-private", settings={"safe": 3, "API_KEY": "not-for-reply", "nativeToken": "not-for-reply",
            "nested": {"authorization": "not-for-reply", "keep": ["Bearer fictional-bearer", "token=fictional-token", private, "public"]}},
            lastUsage=usage(extra={"totalTokens": 1000, "password": private, "byModel": {"m": 42}}), state="needs_attention",
            problem={"code": "future_problem", "message": "Authorization Bearer fictional-bearer", "retryable": False,
                "remedy": "Check the account", "detail": {"basis": "fields", "excerpt": private}})
        result = Public((private,)).subscription(raw)
        rendered = json.dumps(result)
        for value in (private, "not-for-reply", "fictional-bearer", "fictional-token", "top-private", "excerpt"):
            self.assertNotIn(value, rendered)
        self.assertEqual(result["settings"], {"safe": 3, "nested": {"keep": ["public"]}})
        self.assertEqual(result["lastUsage"]["extra"], {"totalTokens": 1000, "byModel": {"m": 42}})
        self.assertEqual(result["problem"]["code"], "future_problem")

    def test_unknown_usage_numbers_are_absent_not_zero_and_unsafe_urls_never_escape(self) -> None:
        """accounts.unknown-usage; accounts.usage-units; accounts.safe-url"""
        window = {"kind": "other", "label": "Private", "usedPercent": True, "windowMinutes": -1,
                  "limitReached": 0, "resource": "future-units", "secret": "ignored"}
        for invalid in (True, -1, 101, float("nan"), float("inf"), 2**10000, "4"):
            window["usedPercent"] = invalid
            projected = Public().usage(usage(windows=[window], detailsUrl="https://usage.example.test/path?session=private"))
            self.assertEqual(projected["windows"], [{"kind": "other", "label": "Private"}])
            self.assertNotIn("detailsUrl", projected)
        self.assertNotIn("detailsUrl", Public().usage(usage(detailsUrl="https://[invalid")))
        projected = Public().usage(usage(windows=[{**window, "usedPercent": 0, "windowMinutes": 0, "limitReached": False,
                                                  "resource": "credits"}]))
        self.assertEqual(projected["windows"][0]["usedPercent"], 0)
        self.assertIs(projected["windows"][0]["limitReached"], False)

    def test_malformed_required_records_and_unbounded_public_json_are_refused(self) -> None:
        """accounts.public-validation; accounts.public-bound"""
        cases: tuple[dict[str, Any], ...] = ({"id": "--sign-in"}, {"id": "white space"}, {"id": "x"*257}, {"createdAt": "relative"},
                       {"settings": []}, {"label": "x"*8193}, {"state": "needs_attention"})
        for fields in cases:
            with self.assertRaises(Error):
                Public().subscription(subscription(**fields))
        with self.assertRaises(Error):
            Public().subscription(subscription(settings={"many": list(range(5000))}))
        with self.assertRaises(Error):
            Public().models(models(models=[{"id": "m"}]))
