"""The explicitly named no-vendor fixture keeps a real control protocol and private outputs."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

TOOL = Path(__file__).resolve().parents[2] / "tools/backend_fault_driver.py"


class FaultInput(unittest.TestCase):
    def test_capabilities_never_impersonate_a_native_driver_or_subscription(self) -> None:
        """journeys.fault-identity"""
        with tempfile.TemporaryDirectory() as temp:
            base = [sys.executable, "-I", "-B", str(TOOL), "--control-dir", temp]
            info = json.loads(subprocess.check_output([*base, "info"]))
            self.assertEqual((info["driver"], info["contract"], info["fixture"]), ("journey-fixture", 2, True))
            rows = json.loads(subprocess.check_output([*base, "subscriptions", "list"]))
            self.assertEqual([r["id"] for r in rows], ["private-fixture"])

    def exercise(self, model: str, control: dict[str, object] | list[dict[str, object]] | None = None) -> tuple[list[dict[str, object]], int]:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            request = folder / "request.json"
            request.write_text(json.dumps({"runId": str(uuid4()) + ".1", "subscriptionId": "private-fixture", "model": model}))
            commands = control if isinstance(control, list) else [control] if control else []
            child = subprocess.run([sys.executable, "-I", "-B", str(TOOL), "--control-dir", str(folder), "run",
                                    "--request", str(request), "--control"],
                                   input="".join(json.dumps(command) + "\n" for command in commands), capture_output=True, text=True, timeout=5)
            self.assertEqual(child.stderr, "")
            return [json.loads(line) for line in child.stdout.splitlines()], child.returncode

    def test_completed_fixture_is_ordered_and_distinct(self) -> None:
        """journeys.fault-completion"""
        events, status = self.exercise("complete")
        self.assertEqual(status, 0)
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(events[-1]["outcome"], "completed")
        self.assertEqual(events[0]["toolVersion"], "no-vendor-fixture")

    def test_stop_has_a_real_cancelled_receipt(self) -> None:
        """journeys.fault-stop-receipt"""
        events, status = self.exercise("hold", {"type": "stop"})
        self.assertEqual(status, 2)
        self.assertEqual(events[-1]["outcome"], "cancelled")

    def test_question_receipt_closes_the_controlled_tool(self) -> None:
        """journeys.fault-question-receipt"""
        events, status = self.exercise("question", [{"type": "answer", "askId": "controlled-choice",
                                                       "answer": {"type": "answers", "answers": {"choice": ["First branch"]}}},
                                                      {"type": "stop"}])
        self.assertEqual(status, 2)
        self.assertIn("ask_opened", [e["type"] for e in events])
        self.assertIn("ask_closed", [e["type"] for e in events])
        self.assertIn("tool_finished", [e["type"] for e in events])
        self.assertEqual(events[-1]["outcome"], "cancelled")
