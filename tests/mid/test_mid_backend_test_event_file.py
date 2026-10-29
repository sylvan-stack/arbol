"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_event_file as _support
from backend.test_event_file import (
    Any,
    CHUNK,
    Envelope,
    Files,
    MAX_LINE,
    Path,
    ROOT,
    Scanner,
    asyncio,
    completed,
    event,
    json,
    meta,
    metadata,
    os,
    superseded,
    sys,
    tempfile,
    tracemalloc,
    unittest,
)


class Files(_support.Files):


# TEST-TIER-BEGIN tests/backend/test_event_file.py::Files.test_oversized_payload_has_bounded_memory_and_metadata_can_follow_its_text
    async def test_oversized_payload_has_bounded_memory_and_metadata_can_follow_its_text(self) -> None:
        """live.oversized-line; live.bounded-file-memory"""
        prefix = b'{"event":{"text":"'
        self.append(prefix)
        for _ in range(MAX_LINE // CHUNK + 2):
            self.append(b"x" * CHUNK)
        self.append(b'","type":"text","runId":"r","parentCallId":"child"},"n":7}\n')
        length = os.fstat(self.fd).st_size
        self.append(event(8, "text_delta", text="after"))
        ticks = 0
        done = False
        async def other() -> None:
            nonlocal ticks
            while not done:
                ticks += 1
                await asyncio.sleep(0)
        task = asyncio.create_task(other())
        tracemalloc.start()
        try:
            lines = [line async for line in Scanner(self.fd).lines()]
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
            done = True
            await task
        self.assertEqual([line.meta.n for line in lines], [7, 8])
        self.assertIsNone(lines[0].value)
        self.assertEqual(lines[0].wire(), {"n": 7, "tooLarge": True, "bytes": length})
        self.assertEqual((lines[0].meta.run, lines[0].meta.parent, lines[0].meta.kind), ("r", "child", "text"))
        self.assertLess(peak, 32 * 1024 * 1024)
        self.assertGreater(ticks, 10)
# TEST-TIER-END tests/backend/test_event_file.py::Files.test_oversized_payload_has_bounded_memory_and_metadata_can_follow_its_text
