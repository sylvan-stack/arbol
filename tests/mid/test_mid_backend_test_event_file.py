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
# TEST-TIER-BEGIN tests/backend/test_event_file.py::Files.test_catchup_compacts_only_completed_matching_run_parent_and_tool
    async def test_catchup_compacts_only_completed_matching_run_parent_and_tool(self) -> None:
        """live.compaction"""
        raw = [event(1, "text_delta", text="old"), event(2, "text", text="whole"),
            event(3, "thinking_delta", text="still thinking"),
            event(4, "tool_output_delta", callId="text", text="partial tool"),
            event(5, "tool_finished", callId="text", ok=True, result="whole tool"),
            event(6, "text_delta", text="unfinished after whole"),
            event(7, "text_delta", text="child", parentCallId="child"),
            event(8, "text", text="another run", runId="r2"),
            event(9, "thinking_delta", text="old thought", runId="r2"),
            event(10, "thinking", text="whole thought", runId="r2")]
        for line in raw:
            self.append(line)
        cutoff, blocks = await completed(self.fd, os.fstat(self.fd).st_size)
        reader = Scanner(self.fd)
        lines = [line async for line in reader.lines(limit=cutoff) if not superseded(line, blocks)]
        self.assertEqual([line.meta.n for line in lines], [2, 3, 5, 6, 7, 8, 10])
        self.assertEqual(lines[0].value, json.loads(raw[1]))
        self.assertEqual(lines[4].value, json.loads(raw[6]))
# TEST-TIER-END tests/backend/test_event_file.py::Files.test_catchup_compacts_only_completed_matching_run_parent_and_tool

# TEST-TIER-BEGIN tests/backend/test_event_file.py::Files.test_unknown_fields_survive_unknown_lines_and_duplicate_numbers_are_ignored
    async def test_unknown_fields_survive_unknown_lines_and_duplicate_numbers_are_ignored(self) -> None:
        """live.forward-compatibility"""
        known = {"n": 1, "event": {"runId": "r", "type": "text", "text": "kept", "future": {"x": [1, 2]}}}
        self.append((json.dumps(known) + "\n").encode())
        self.append(b'{"n":2,"future":{"x":true}}\n')
        self.append(event(2, "text", text="duplicate unknown number"))
        self.append(event(3, "future_event", text="ignore this"))
        self.append(event(4, "text", text="next"))
        self.append(event(1, "text", text="backwards"))
        lines = [line async for line in Scanner(self.fd).lines()]
        self.assertEqual([line.meta.n for line in lines], [1, 4])
        self.assertEqual(lines[0].value, known)
# TEST-TIER-END tests/backend/test_event_file.py::Files.test_unknown_fields_survive_unknown_lines_and_duplicate_numbers_are_ignored

# TEST-TIER-BEGIN tests/backend/test_event_file.py::Files.test_malformed_complete_lines_do_not_poison_later_valid_data
    async def test_malformed_complete_lines_do_not_poison_later_valid_data(self) -> None:
        """live.malformed-lines"""
        self.append(b'not json\n{"n":1,"n":2,"end":{}}\n{"n":true,"end":{}}\n\xff\n')
        self.append(event(5, "text", text="safe"))
        lines = [line async for line in Scanner(self.fd).lines()]
        self.assertEqual([line.meta.n for line in lines], [5])
# TEST-TIER-END tests/backend/test_event_file.py::Files.test_malformed_complete_lines_do_not_poison_later_valid_data

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

# TEST-TIER-BEGIN tests/backend/test_event_file.py::Files.test_streaming_envelope_handles_escapes_unicode_arrays_numbers_and_any_order
    async def test_streaming_envelope_handles_escapes_unicode_arrays_numbers_and_any_order(self) -> None:
        """live.streaming-metadata"""
        value = {"unknown": [True, False, None, {"deep": [0, -1, 1.25, 3e-4]}],
            "event": {"text": 'a "quote" and \\ and 🙂', "runId": "r", "type": "tool_finished", "callId": "c"}, "n": 42}
        raw = json.dumps(value, ensure_ascii=True).encode()
        reader = Envelope()
        for part in raw:
            reader.feed(bytes([part]))
        reader.feed(b"", final=True)
        self.assertEqual(metadata(reader.values, reader.bodies), meta(value))
        for raw in [b'{"n":1,"n":2,"end":{}}', b'{"event":{},"event":{},"n":1}',
                    b'{"n":01}', b'{"n":1,}', b'{"n":1.}', b'{"n":1e}', b'{"x":"\\q"}', b'{"x":"raw\n"}']:
            with self.assertRaises((ValueError, UnicodeError), msg=repr(raw)):
                reader = Envelope()
                reader.feed(raw, final=True)
# TEST-TIER-END tests/backend/test_event_file.py::Files.test_streaming_envelope_handles_escapes_unicode_arrays_numbers_and_any_order
