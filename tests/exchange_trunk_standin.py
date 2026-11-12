"""Detached protocol peer for the start coordinator; no database or Driver."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def wait_for(path: Path) -> None:
    deadline = time.monotonic() + 12
    while not path.is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError(path.name)
        time.sleep(0.01)


def main() -> None:
    place = Path(sys.argv[1])
    if sys.argv[2:7] != ["trivial", "-v", "a", "run", "--detach"]:
        raise ValueError("Expected the selected detached Trunk invocation.")
    fixture = json.loads((place / "reply.json").read_text())
    reply = (json.dumps(fixture["reply"]) + "\n").encode()
    if fixture["mode"] == "fragmented":
        os.write(1, reply[:12])
        wait_for(place / "finish-reply")
        reply = reply[12:]
    elif fixture["mode"] == "late":
        wait_for(place / "finish-reply")
    else:
        raise ValueError("Unknown fixture mode.")
    os.write(1, reply)  # A closed pipe would fail before the completion marker.
    wait_for(place / "finish-work")
    (place / "work-finished").touch()


if __name__ == "__main__":
    main()
