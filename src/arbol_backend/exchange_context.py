"""Installation paths and verified database reads shared by the Exchange commands."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import unquote, urlsplit

from psycopg.conninfo import make_conninfo

from .database import Database
from .model import Identity, Refused, identity, object_file, private_directory


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
        if self.identity.database is not None:
            env["ARBOL_EXCHANGE_RUNTIME_DIR"] = str(self.identity.folder)
            env["ARBOL_EXCHANGE_BIN_DIR"] = str(self.bin_dir)
        return env

    def database(self) -> Database:
        if self.identity.database is not None:
            return Database(self.identity)
        isolated = socket_target(self.identity.home)
        return Database(replace(self.identity, database=isolated)) if isolated is not None else Database(self.identity)


def socket_target(home: Path) -> str | None:
    """Use the same credential-free private socket configuration that the Trunk launcher sees."""
    try:
        value = object_file(home / ".arbol/database.json")
        url = urlsplit(value["address"])
        host = unquote(url.hostname or "", errors="strict")
        if not host.startswith("/"):
            return None
        database = value["database"]
        user = unquote(url.username or "", errors="strict")
        directory = Path(host).resolve(strict=True)
        if (set(value) != {"address", "database"} or url.scheme not in ("postgres", "postgresql")
                or not user.strip() or "\0" in user or not url.port or url.password is not None
                or url.path not in ("", "/") or url.query or url.fragment or "," in str(directory)
                or not isinstance(database, str) or not database.strip() or "\0" in database
                or len(database.encode("utf-8")) > 63 or database.lower() in {"postgres", "template0", "template1"}
                or directory == (home / "Library/Application Support/Arbol/database/socket").resolve()
                or not directory.is_dir()):
            raise ValueError
        private_directory(directory)
        return make_conninfo(host=str(directory), port=url.port, user=user, dbname=database)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, Refused):
        return None


def context(package: Path, options: dict[str, str]) -> Context:
    selected = {key: options[key] for key in ("--runtime-dir", "--bin-dir") if key in options}
    if any(not Path(value).is_absolute() for value in selected.values()):
        raise Refusal("invalid_input", "Isolated runtime and bin directories must be absolute.")
    installed = identity(package, selected)
    if selected:
        target = socket_target(installed.home)
        if target is None:
            raise Refusal("invalid_input", "Runtime overrides require a configured private PostgreSQL socket.")
        installed = replace(installed, database=target)
    return Context(installed)
