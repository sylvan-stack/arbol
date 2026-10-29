"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_live as _support
from backend.test_live import (
    Any,
    MAX_LINE,
    Params,
    Path,
    ROOT,
    Trunk,
    WindowFixture,
    Windows,
    asyncio,
    chat,
    json,
    mock,
    processes,
    sys,
    time,
)


class Windows(_support.Windows):

# TEST-TIER-BEGIN tests/backend/test_live.py::Windows.test_replacement_snapshot_and_truncated_file_restart_replay
    async def test_replacement_snapshot_and_truncated_file_restart_replay(self) -> None:
        """live.snapshot-generation; live.truncated-file"""
        trunk = await Trunk.make(self.frame, chat(1))
        await trunk.accept(self.db)
        for n in range(3):
            trunk.event("text_delta", text=str(n))
        r, w = await self.open()
        key = {"chat": chat(1)}
        await self.subscribe(r, w, "chat", "chat", key)
        self.assertEqual([line["n"] for line in await self.lines(r, "chat", 3)], [1, 2, 3])
        snapshot = await self.backend.chats.chat_view.snapshot(key)
        self.backend.chats.chat_view.topic.publish(snapshot.event, params=key)
        await self.event(r, "chat", "snapshot")
        self.assertEqual([line["n"] for line in await self.lines(r, "chat", 3)], [1, 2, 3])
        replacement = {"n": 1, "event": {"runId": trunk.exchange+".1", "type": "text", "text": "replacement"}}
        path = trunk.folder / "events.jsonl"
        path.write_text(json.dumps(replacement)+"\n")
        await self.event(r, "chat", "snapshot")
        self.assertEqual(await self.lines(r, "chat", 1), [replacement])
        replacement["event"]["text"] = "atomic replacement"  # type: ignore[index]
        temporary = path.with_suffix(".new")
        temporary.write_text(json.dumps(replacement)+"\n")
        temporary.chmod(0o600)
        temporary.replace(path)
        await self.event(r, "chat", "snapshot")
        self.assertEqual(await self.lines(r, "chat", 1), [replacement])
# TEST-TIER-END tests/backend/test_live.py::Windows.test_replacement_snapshot_and_truncated_file_restart_replay
