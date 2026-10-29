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
