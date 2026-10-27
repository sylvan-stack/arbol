"""Complete public Driver records and an owned per-command stand-in, with no credential."""

from __future__ import annotations

import shlex
import sys
from typing import Any

from backend.support import STANDIN, Frame

AT = "2026-10-27T12:00:00.000Z"


def usage(**fields: Any) -> dict[str, Any]:
    return {"outcome": "ok", "fetchedAt": AT, "windows": [{"kind": "weekly", "label": "Week", "usedPercent": 37,
            "resource": "tokens", "windowMinutes": 10080, "resetsAt": "2026-11-01T12:00:00Z"}], **fields}


def subscription(id: str = "private", **fields: Any) -> dict[str, Any]:
    return {"id": id, "family": "private-family", "label": "Private Subscription", "auth": "key", "state": "signed_in",
            "settings": {}, "createdAt": AT, "updatedAt": AT, **fields}


def models(**fields: Any) -> dict[str, Any]:
    return {"source": "builtin", "fetchedAt": AT, "models": [{"id": "private-model", "label": "Private model",
            "efforts": ["low", "high"], "defaultEffort": "low", "serviceTiers": ["default"], "isDefault": True}], **fields}


def install(frame: Frame, driver: str, commands: dict[str, Any]) -> None:
    code = STANDIN.replace("config=json.loads((base/'behavior.json').read_text()).get(name,{})",
        "config=json.loads((base/'behavior.json').read_text()).get(name,{})\nconfig=config.get('commands',{}).get(sys.argv[2],config)")
    (frame.bin / ("arbol-"+driver+"-driver")).write_text("#!/bin/sh\nexec "+shlex.quote(sys.executable)+" -I -c "+shlex.quote(code)+' "$0" "$@"\n')
    (frame.bin / ("arbol-"+driver+"-driver")).chmod(0o700)
    frame.behavior["arbol-"+driver+"-driver"] = {"commands": commands}
    frame.configure()
