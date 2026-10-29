# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Real private Driver children qualify exact account commands, identity and cancellation."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from backend.account_support import AT, install, models, subscription, usage  # noqa: E402
from backend.test_accounts import AccountFixture  # noqa: E402


class Actions(AccountFixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.commands: dict[str, Any] = {
            "list": {"output": [subscription(), subscription("other", state="signed_out")]},
            "check": {"output": subscription(checkedAt=AT)}, "usage": {"output": usage()},
            "models": {"output": models()}}
        self.configure()

    def configure(self) -> None:
        install(self.frame, "claude", self.commands)


# Archived complete imports; restore needed names in their original scope, not at this file tail.
