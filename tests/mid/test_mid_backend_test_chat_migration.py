"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_chat_migration as _support
from backend.test_chat_migration import (
    Backend,
    CHAT,
    CHILD,
    COPY,
    Cluster,
    Database,
    Delegation,
    Frame,
    LIMITS,
    Params,
    Path,
    ROOT,
    TEST_ROOT,
    UUID,
    asyncio,
    decode,
    encode,
    identity,
    json,
    os,
    parse,
    shlex,
    signal,
    subprocess,
    sys,
    time,
    unittest,
)


class Delegation(_support.Delegation):


# TEST-TIER-BEGIN tests/backend/test_chat_migration.py::Delegation.test_timeout_tracks_late_mutation_and_shutdown_does_not_kill_it
    async def test_timeout_tracks_late_mutation_and_shutdown_does_not_kill_it(self) -> None:
        """chats.reimport-uncertain"""
        await self.db.execute("UPDATE migrated_chats SET stale=true")
        self.config["chat"] = {"sleep": 0.4, "output": self.import_result(), "sql": "UPDATE migrated_chats SET stale=false"}
        self.configure()
        backend = await self.start()
        backend.programs.limits["reimport"] = 0.05
        self.assertEqual((LIMITS["reimport"], LIMITS["migrate-check"]), (90, 90))
        await self.settle_check(backend)
        reader, writer = await self.open()
        reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
        self.assertEqual(reply["error"]["code"], "no_answer")
        child = backend.programs.running[("reimport", CHAT)]
        self.assertIsNone(child.process.poll())
        self.children.append(child.process)
        reply = await self.call(reader, writer, "chat.reimport", {"chat": CHAT})
        self.assertEqual(reply["error"]["code"], "no_answer")
        started = time.monotonic()
        backend.stopped.set()
        assert self.running
        await asyncio.wait_for(self.running, 2)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(await asyncio.to_thread(child.process.wait, timeout=2), 0)
        self.assertFalse((await self.db.execute("SELECT stale FROM migrated_chats"))[0][0])
        self.assertEqual(len(self.calls("chat")), 1)
# TEST-TIER-END tests/backend/test_chat_migration.py::Delegation.test_timeout_tracks_late_mutation_and_shutdown_does_not_kill_it
