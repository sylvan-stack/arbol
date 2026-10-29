"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_account_actions as _support
from backend.test_account_actions import (
    AT,
    AccountFixture,
    Actions,
    Any,
    Path,
    ROOT,
    asyncio,
    install,
    json,
    models,
    signal,
    subscription,
    sys,
    time,
    usage,
)


class Actions(_support.Actions):
# TEST-TIER-BEGIN tests/backend/test_account_actions.py::Actions.test_exact_check_usage_models_and_unsigned_states_are_delegated_without_inference
    async def test_exact_check_usage_models_and_unsigned_states_are_delegated_without_inference(self) -> None:
        """accounts.allowed-actions; accounts.driver-authority; accounts.no-inference"""
        r, w = await self.open()
        before = len(self.frame.calls())
        for method in ("check", "usage", "models"):
            result = await self.call(r, w, "accounts."+method, {"driver": "claude", "subscription": "private"})
            self.assertIn("result", result)
        self.commands["list"]["output"][0]["state"] = "signed_out"
        self.commands["usage"]["output"] = usage(outcome="needs_sign_in", message="Sign in with the Driver", windows=[])
        self.configure()
        result = await self.call(r, w, "accounts.usage", {"driver": "claude", "subscription": "private"})
        self.assertEqual(result["result"]["outcome"], "needs_sign_in")
        calls = self.driver_calls(after=before)
        self.assertEqual([row["args"] for row in calls], [args for op in ("check", "usage", "models", "usage")
            for args in (["subscriptions", "list"], ["subscriptions", op, "private"])])
# TEST-TIER-END tests/backend/test_account_actions.py::Actions.test_exact_check_usage_models_and_unsigned_states_are_delegated_without_inference

# TEST-TIER-BEGIN tests/backend/test_account_actions.py::Actions.test_invalid_syntax_has_no_child_effect_and_unknown_or_deleted_membership_has_no_action
    async def test_invalid_syntax_has_no_child_effect_and_unknown_or_deleted_membership_has_no_action(self) -> None:
        """accounts.identifier-before-effects; accounts.fresh-membership; accounts.deleted-subscription"""
        r, w = await self.open()
        before = len(self.frame.calls())
        for params in ({}, {"driver": "no-such", "subscription": "private"}, {"driver": "claude", "subscription": "--sign-in"},
                       {"driver": "claude", "subscription": "white space"}, {"driver": "claude", "subscription": "x"*257}):
            result = await self.call(r, w, "accounts.models", params)
            self.assertEqual(result["error"]["code"], "invalid_input")
        self.assertEqual(len(self.frame.calls()), before)
        for selected in ("missing", "private"):
            if selected == "private":
                self.commands["list"]["output"] = []
                self.configure()
            before = len(self.frame.calls())
            result = await self.call(r, w, "accounts.models", {"driver": "claude", "subscription": selected})
            self.assertEqual(result["error"]["code"], "invalid_input")
            self.assertEqual([row["args"] for row in self.driver_calls(after=before)], [["subscriptions", "list"]])
        (self.frame.bin / "arbol-claude-driver").unlink()
        before = len(self.frame.calls())
        result = await self.call(r, w, "accounts.usage", {"driver": "claude", "subscription": "private"})
        self.assertEqual(result["error"]["code"], "invalid_input")
        self.assertEqual(len(self.frame.calls()), before)
# TEST-TIER-END tests/backend/test_account_actions.py::Actions.test_invalid_syntax_has_no_child_effect_and_unknown_or_deleted_membership_has_no_action

# TEST-TIER-BEGIN tests/backend/test_account_actions.py::Actions.test_failed_or_malformed_fresh_list_never_uses_stale_membership
    async def test_failed_or_malformed_fresh_list_never_uses_stale_membership(self) -> None:
        """accounts.no-stale-action; accounts.public-membership-proof"""
        r, w = await self.open()
        self.assertIn("private", self.backend.chats.catalogues.subscriptions["claude"])
        for option in ({"status": 2, "raw": "unreadable"}, {"output": [{"id": "private"}]}):
            self.commands["list"] = option
            self.configure()
            before = len(self.frame.calls())
            result = await self.call(r, w, "accounts.check", {"driver": "claude", "subscription": "private"})
            self.assertEqual((result["error"]["code"], result["error"]["source"]), ("no_answer", "driver"))
            self.assertEqual([row["args"] for row in self.driver_calls(after=before)], [["subscriptions", "list"]])
# TEST-TIER-END tests/backend/test_account_actions.py::Actions.test_failed_or_malformed_fresh_list_never_uses_stale_membership

# TEST-TIER-BEGIN tests/backend/test_account_actions.py::Actions.test_three_windows_share_one_action_and_a_later_request_is_fresh
    async def test_three_windows_share_one_action_and_a_later_request_is_fresh(self) -> None:
        """accounts.shared-action; accounts.fresh-action"""
        self.commands["list"]["sleep"] = 0.08
        self.commands["models"]["sleep"] = 0.1
        self.configure()
        clients = [await self.open() for _ in range(3)]
        before = len(self.frame.calls())
        replies = await asyncio.gather(*(self.call(r, w, "accounts.models", {"driver": "claude", "subscription": "private"}) for r, w in clients))
        self.assertTrue(all(reply["result"] == replies[0]["result"] for reply in replies))
        self.assertEqual([row["args"] for row in self.driver_calls(after=before)], [["subscriptions", "list"], ["subscriptions", "models", "private"]])
        await self.call(*clients[0], "accounts.models", {"driver": "claude", "subscription": "private"})
        self.assertEqual(len(self.driver_calls(after=before)), 4)
# TEST-TIER-END tests/backend/test_account_actions.py::Actions.test_three_windows_share_one_action_and_a_later_request_is_fresh

# TEST-TIER-BEGIN tests/backend/test_account_actions.py::Actions.test_cancelled_caller_keeps_the_shared_action_alive_for_another
    async def test_cancelled_caller_keeps_the_shared_action_alive_for_another(self) -> None:
        """accounts.action-caller-shield; accounts.action-owner"""
        self.commands["usage"]["sleep"] = 0.2
        self.configure()
        params = {"driver": "claude", "subscription": "private"}
        first = asyncio.create_task(self.backend.accounts.action("usage", params))
        async with asyncio.timeout(2):
            while not any(row["args"] == ["subscriptions", "usage", "private"] for row in self.driver_calls()):
                await asyncio.sleep(0.005)
        second = asyncio.create_task(self.backend.accounts.action("usage", params))
        await asyncio.sleep(0.03)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        self.assertEqual((await second)["outcome"], "ok")
        self.assertEqual(len([row for row in self.driver_calls() if row["args"] == ["subscriptions", "usage", "private"]]), 1)
# TEST-TIER-END tests/backend/test_account_actions.py::Actions.test_cancelled_caller_keeps_the_shared_action_alive_for_another

# TEST-TIER-BEGIN tests/backend/test_account_actions.py::Actions.test_actual_account_command_deadline_is_bounded_and_other_driver_can_answer
    async def test_actual_account_command_deadline_is_bounded_and_other_driver_can_answer(self) -> None:
        """accounts.command-bound; accounts.action-driver-isolation"""
        self.backend.programs.limits["account"] = 0.08
        self.commands["usage"]["sleep"] = 2
        self.configure()
        r, w = await self.open()
        before = time.monotonic()
        result = await self.call(r, w, "accounts.usage", {"driver": "claude", "subscription": "private"})
        self.assertEqual((result["error"]["code"], result["error"]["source"]), ("no_answer", "driver"))
        self.assertLess(time.monotonic()-before, 0.5)
        self.assertIn("result", await self.call(r, w, "accounts.list"))
        self.backend.programs.reap()
        self.assertFalse(any(key[0] == "account" for key in self.backend.programs.running))
# TEST-TIER-END tests/backend/test_account_actions.py::Actions.test_actual_account_command_deadline_is_bounded_and_other_driver_can_answer

# TEST-TIER-BEGIN tests/backend/test_account_actions.py::Actions.test_wrong_identity_malformed_result_and_unknown_refusal_remain_safe
    async def test_wrong_identity_malformed_result_and_unknown_refusal_remain_safe(self) -> None:
        """accounts.check-identity; accounts.action-result; accounts.unknown-driver-code"""
        r, w = await self.open()
        for op, option in (("check", {"output": subscription("other")}), ("usage", {"raw": '{"outcome":NaN}'}),
                           ("models", {"output": models(models=[{"id": "m"}])}),
                           ("check", {"status": 1, "output": {"error": {"code": "future_refusal", "message": "Authorization Bearer fictional-bearer"}}})):
            self.commands[op] = option
            self.configure()
            result = await self.call(r, w, "accounts."+op, {"driver": "claude", "subscription": "private"})
            self.assertEqual(result["error"]["source"], "driver")
            self.assertEqual(result["error"]["code"], "future_refusal" if option.get("status") else "no_answer")
            self.assertNotIn("fictional-bearer", json.dumps(result))
# TEST-TIER-END tests/backend/test_account_actions.py::Actions.test_wrong_identity_malformed_result_and_unknown_refusal_remain_safe

# TEST-TIER-BEGIN tests/backend/test_account_actions.py::Actions.test_real_backend_process_logs_neither_public_projection_secrets_nor_driver_diagnostics
    async def test_real_backend_process_logs_neither_public_projection_secrets_nor_driver_diagnostics(self) -> None:
        """accounts.process-privacy; accounts.no-secret-argv-log"""
        self.backend.stopped.set()
        await self.running
        secret = "Bearer fictional-process-bearer"
        self.commands["list"]["output"] = [subscription(settings={"apiKey": secret, "safe": True})]
        self.commands["usage"] = {"status": 1, "output": {"error": {"code": "future_private", "message": secret}}}
        self.configure()
        child = self.frame.start(args=self.frame.options(self.cluster.address))
        await asyncio.to_thread(self.frame.line, child)
        r, w = await self.open()
        result = await self.call(r, w, "accounts.list")
        self.assertNotIn(secret, json.dumps(result))
        result = await self.call(r, w, "accounts.usage", {"driver": "claude", "subscription": "private"})
        self.assertNotIn(secret, json.dumps(result))
        child.send_signal(signal.SIGTERM)
        out, err = await asyncio.to_thread(child.communicate, timeout=3)
        self.assertEqual((child.returncode, out, err), (0, b"", b""))
        self.assertNotIn(secret, json.dumps(self.frame.calls()))
        self.assertFalse(any(row["args"][1] not in ("list", "usage") for row in self.driver_calls()
                             if row["program"] == "arbol-claude-driver"))
# TEST-TIER-END tests/backend/test_account_actions.py::Actions.test_real_backend_process_logs_neither_public_projection_secrets_nor_driver_diagnostics
