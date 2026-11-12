"""Inject process table changes at the installation's force-stop boundary."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))

from arbol_backend import exchange_groups  # noqa: E402
from arbol_backend.exchange_context import Refusal as Refusal  # noqa: E402

STARTED = datetime(2026, 10, 26, 9, tzinfo=UTC)
LEADER = 50


@contextmanager
def changed_group(replacement: dict[int, datetime]) -> Iterator[Mock]:
    with (
        patch.object(exchange_groups, "process_alive", return_value=True),
        patch.object(exchange_groups, "members", side_effect=[{LEADER: STARTED}, replacement]),
        patch.object(os, "getpgid", return_value=LEADER),
        patch.object(os, "getpgrp", return_value=99999),
        patch.object(os, "killpg") as send,
    ):
        yield send


def force() -> bool:
    elapsed = 0.0

    def pause(seconds: float) -> None:
        nonlocal elapsed
        elapsed += seconds

    return exchange_groups.force_group({"pid": LEADER, "startedAt": STARTED.isoformat()}, lambda: elapsed, pause)
