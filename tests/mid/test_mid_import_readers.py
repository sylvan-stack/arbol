"""Fictional reader fixtures for explicit mid-tier qualification."""

from __future__ import annotations

import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from socket import gethostname
from tempfile import TemporaryDirectory
from typing import Any

from arbol_import.readers import kimi_code
from arbol_import.readers.form import Failed, Session, Source

CLOCK = datetime(2026, 1, 2, 12, tzinfo=UTC)


def write_records(path: Path, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def milliseconds(at: datetime) -> int:
    return int(at.timestamp() * 1000)


class Kimi(unittest.TestCase):
    def test_lock_claim_and_subagent_wire_control_liveness(self) -> None:
        holding = "00000000-0000-4000-8000-000000000001"
        stale_claim = "00000000-0000-4000-8000-000000000002"
        recent_child = "00000000-0000-4000-8000-000000000003"
        old = CLOCK - timedelta(days=1)
        recent = CLOCK - timedelta(minutes=1)
        prompt = {
            "type": "turn.prompt", "time": milliseconds(old),
            "turnId": "turn-1", "promptId": "prompt-1", "origin": {"kind": "user"},
            "input": [{"type": "text", "text": "Fictional request"}],
        }

        with TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            locks = home / "locks" / "sessions"
            locks.mkdir(parents=True)
            for native_id in (holding, stale_claim, recent_child):
                agents = home / "sessions" / "fictional-workspace-test" / f"session_{native_id}" / "agents"
                main = write_records(agents / "main" / "wire.jsonl", [prompt])
                os.utime(main, (old.timestamp(), old.timestamp()))
                if native_id == recent_child:
                    wire = write_records(agents / "child" / "wire.jsonl", [
                        {"type": "metadata", "created_at": milliseconds(old), "protocol_version": "1.5.0"},
                    ])
                    os.utime(wire, (recent.timestamp(), recent.timestamp()))

            claim_files = {}
            for native_id, started_at in ((holding, datetime.now(UTC)), (stale_claim, datetime(2000, 1, 1, tzinfo=UTC))):
                claim = locks / f"session_{native_id}.lock"
                claim.write_text(json.dumps({
                    "pid": os.getpid(), "hostname": gethostname(), "startedAt": milliseconds(started_at),
                }), encoding="utf-8")
                claim_files[claim] = (claim.read_bytes(), claim.stat().st_mtime_ns)

            results = list(kimi_code.read(Source(home, None, None, CLOCK)))
            self.assertEqual(len(results), 3)
            flags = {}
            for result in results:
                self.assertNotIsInstance(result, Failed)
                if isinstance(result, Session):
                    flags[result.native_id] = result.live
            self.assertEqual(flags, {holding: True, stale_claim: False, recent_child: True})
            for claim, expected in claim_files.items():
                self.assertEqual((claim.read_bytes(), claim.stat().st_mtime_ns), expected)
