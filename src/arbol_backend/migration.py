"""Filter process diagnostics before projecting them through the Bridge."""

from __future__ import annotations

import re
from typing import Any


def message(value: Any, *, secrets: tuple[str, ...] = (),
            fallback: str = "The command could not confirm the operation.") -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    if any(secret and secret in value for secret in secrets):
        return fallback
    try:
        if len(value.encode("utf-8")) > 1024:
            return fallback
    except UnicodeError:
        return fallback
    if re.search(r"\b(password|token|secret|api[-_ ]?key|jev[-_ ]?key|authorization|bearer)\b", value, re.I):
        return fallback
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        return fallback
    return value

