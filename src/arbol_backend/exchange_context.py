"""Installation paths and verified database reads shared by the Exchange commands."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .database import Database, configured_target
from .model import Identity, Refused, identity, private_directory


class Refusal(Refused):
    def __init__(self, code: str, message: str, available: list[str] | None = None) -> None:
        super().__init__(code, message)
        self.available = available


@dataclass(frozen=True)
class Context:
    identity: Identity

    @property
    def exchanges(self) -> Path:
        return self.identity.folder / "exchanges"

    @property
    def bin_dir(self) -> Path:
        return self.identity.bin_dir

    def environment(self) -> dict[str, str]:
        env = {
            key: value for key, value in os.environ.items()
            if not key.startswith("PG") and key not in {
                "ARBOL_ROOT", "ARBOL_CHAT", "ARBOL_EXCHANGE_RUNTIME_DIR", "ARBOL_EXCHANGE_BIN_DIR"
            }
        }
        env["HOME"] = str(self.identity.home)
        env["PATH"] = str(self.bin_dir) + os.pathsep + env.get("PATH", os.defpath)
        if self.identity.fixture:
            env["ARBOL_EXCHANGE_RUNTIME_DIR"] = str(self.identity.folder)
            env["ARBOL_EXCHANGE_BIN_DIR"] = str(self.bin_dir)
        return env

    def database(self) -> Database:
        return Database(self.identity)



def context(package: Path, options: dict[str, str]) -> Context:
    selected = {key: options[key] for key in ("--runtime-dir", "--bin-dir") if key in options}
    if any(not Path(value).is_absolute() for value in selected.values()):
        raise Refusal("invalid_input", "Isolated runtime and bin directories must be absolute.")
    installed = identity(package, selected)
    if os.path.lexists(installed.folder):
        private_directory(installed.folder)
    if selected:
        configured_target(installed)  # Verify that Trivial will use the same private socket.
    return Context(installed)
