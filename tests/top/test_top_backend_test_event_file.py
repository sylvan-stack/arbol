"""Individually selected top-tier cases. Shared fixtures retain their original paths."""
from __future__ import annotations

import backend.test_event_file as _support
from backend.test_event_file import (
    Scanner,
    completed,
    event,
    os,
    superseded,
)


class Files(_support.Files):
    async def test_captured_cutoff_excludes_later_blocks_and_partial_line_finishes_on_next_poll(self) -> None:
        """live.cutoff; live.partial-line"""
        first = event(1, "text_delta", text="initial")
        partial = event(2, "text", text="later 🙂")
        self.append(first + partial[:20])
        initial = os.fstat(self.fd).st_size
        self.append(partial[20:] + event(3, "text_delta", text="next"))
        cutoff, blocks = await completed(self.fd, initial)
        self.assertEqual(cutoff, len(first))
        reader = Scanner(self.fd)
        lines = [line async for line in reader.lines(limit=cutoff)]
        self.assertEqual([line.meta.n for line in lines if not superseded(line, blocks)], [1])
        self.assertEqual([line.meta.n async for line in reader.lines()], [2, 3])
        partial = event(4, "text", text="a new block")
        self.append(partial[:-1])
        self.assertEqual([line async for line in reader.lines()], [])
        self.append(b"\n")
        self.assertEqual([line.meta.n async for line in reader.lines()], [4])
