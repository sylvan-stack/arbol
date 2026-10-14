"""The pinned standalone Python, as every Build carries it; deliberately local to this repository."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# The Drivers and the classifier keep the same pinned archive here; it is checked by its SHA-256 before use.
ARCHIVE_CACHE = Path.home() / ".cache/arbol-driver-build/python"


def pin() -> dict[str, Any]:
    value: object = json.loads((ROOT / "scripts/python-distribution.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("python-distribution.json must contain a JSON object.")
    return value


def target() -> str:
    architecture = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64"}.get(platform.machine())
    if sys.platform != "darwin" or architecture is None:
        raise ValueError("The pinned Python is available for macOS arm64 and x86_64.")
    return f"{architecture}-apple-darwin"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def archive(distribution: dict[str, Any]) -> Path:
    checksum = distribution.get("sha256")
    url = distribution.get("url")
    if (not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None or not isinstance(url, str)
            or not url.startswith("https://github.com/astral-sh/python-build-standalone/releases/download/")):
        raise ValueError("The standalone distribution must have a pinned URL and SHA-256 digest.")
    cache = Path(os.environ.get("ARBOL_PYTHON_ARCHIVE_CACHE", str(ARCHIVE_CACHE)))
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / f"{checksum}.tar.gz"
    if destination.exists() and digest(destination) != checksum:
        raise ValueError("The cached standalone Python archive has the wrong SHA-256 digest.")
    if not destination.exists():
        fd, name = tempfile.mkstemp(prefix="download-", suffix=".tar.gz", dir=cache)
        os.close(fd)
        temporary = Path(name)
        try:
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            if digest(temporary) != checksum:
                raise ValueError("The downloaded standalone Python archive has the wrong SHA-256 digest.")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination
