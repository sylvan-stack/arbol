"""Maintenance-database access through psql and the Keychain (ARC-D65)."""

import json
import os
import subprocess
from urllib.parse import unquote, urlsplit

from .model import Places, Refused, nonblank

SERVICE = "com.sylvan-stack.arbol.database"


class DatabaseError(Refused):
    def __init__(self, message: str, *, uncertain: bool = False) -> None:
        super().__init__("database_unavailable", message)
        self.uncertain = uncertain


def environment(paths: Places, password: str | None = None) -> dict[str, str]:
    values = {"HOME": str(paths.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
              "LANG": os.environ.get("LANG", "en_US.UTF-8")}
    if password is not None:
        values["PGPASSWORD"] = password
    return values


def connection(paths: Places) -> tuple[str, str]:
    try:
        value = json.loads(paths.database_config.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {"address"} or not isinstance(value["address"], str):
            raise ValueError("expected only an address")
        parsed = urlsplit(value["address"])
        if (parsed.scheme not in ("postgresql", "postgres") or not parsed.username or not parsed.hostname
                or parsed.password is not None or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                or parsed.port is None):
            raise ValueError("expected a role, host and port, with no database, password or query")
        role = nonblank(unquote(parsed.username), "Database role")
        return parsed._replace(path="/postgres").geturl(), role
    except Exception as error:
        # The malformed address might itself hold a password: never echo it or a parser's exception.
        raise DatabaseError("Cannot read the database address: expected a role, host and port, no password/database "
                            f"in {paths.database_config}.") from error


def keychain_password(paths: Places, role: str) -> str | None:
    try:
        result = subprocess.run([paths.security, "find-generic-password", "-s", SERVICE, "-a", role, "-w"],
                                env=environment(paths), cwd=paths.home, capture_output=True, text=True,
                                timeout=2, check=False)
    except subprocess.TimeoutExpired as error:
        raise DatabaseError("The database Keychain lookup did not answer within 2 seconds.") from error
    except Exception as error:
        raise DatabaseError("The database Keychain lookup could not be started or read.") from error
    if result.returncode == 44:
        return None
    if result.returncode != 0:
        raise DatabaseError(f"The database Keychain lookup failed with status {result.returncode}.")
    return result.stdout.removesuffix("\n")


class Database:
    def __init__(self, paths: Places) -> None:
        self.paths = paths
        self.address, role = connection(paths)
        self.password = keychain_password(paths, role)

    def run(self, sql: str, *, changing: bool = False) -> str:
        try:
            result = subprocess.run([self.paths.psql, "--no-psqlrc", "--no-password", "--set", "ON_ERROR_STOP=1",
                                     "--no-align", "--tuples-only", "--dbname", self.address, "--command", sql],
                                    env=environment(self.paths, self.password), cwd=self.paths.home,
                                    capture_output=True, text=True, timeout=30, check=False)
        except subprocess.TimeoutExpired as error:
            raise DatabaseError("psql did not answer within 30 seconds.", uncertain=changing) from error
        except OSError as error:
            raise DatabaseError("psql could not be started.") from error
        except UnicodeError as error:
            raise DatabaseError("psql returned unreadable output.", uncertain=changing) from error
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            if self.password:
                detail = detail.replace(self.password, "[password removed]")
            raise DatabaseError(f"psql failed with status {result.returncode}: {detail[:4096]}",
                                uncertain=changing and result.returncode != 3)
        return result.stdout.strip()
