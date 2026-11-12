"""Independent bounded psycopg connections, autocommit and consistent snapshots."""

from __future__ import annotations

import asyncio
import os
import re
import signal
import tempfile
import tomllib
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import AsyncConnection
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import tuple_row

from .model import Identity, Refused, object_file, private_directory

SERVICE = "com.sylvan-stack.arbol.database"
SECONDS = 5.0
SchemaRow = tuple[int, str, str, int]
SCHEMA_MESSAGES = {
    "unavailable": ("database_unavailable", "The installation database is unavailable."),
    "uninitialized": ("schema_uninitialized", "The installation database schema has not been initialized."),
    "incompatible": ("schema_incompatible", "This Build cannot use the installed database schema."),
}


@dataclass(frozen=True)
class Schema:
    state: str = "unavailable"
    revision: int | None = None
    version: int | None = None

    def pair(self) -> dict[str, int] | None:
        if self.revision is None or self.version is None:
            return None
        return {"revision": self.revision, "compatibilityVersion": self.version}

    def require(self) -> None:
        if self.state != "ready":
            raise Refused(*SCHEMA_MESSAGES[self.state])


def release_history(path: Path) -> tuple[SchemaRow, ...]:
    """The ledger must match a contiguous prefix of this Build's migration manifest."""
    try:
        with path.open("rb") as stream:
            manifest = tomllib.load(stream)
        entries = manifest["migrations"]
        if type(manifest.get("format")) is not int or manifest["format"] != 1 or not isinstance(entries, list):
            raise ValueError("Invalid manifest header.")
        rows: list[SchemaRow] = []
        identities: set[str] = set()
        for number, entry in enumerate(entries, 1):
            revision, predecessor = entry["revision"], entry["predecessor"]
            name, digest, version = entry["id"], entry["sha256"], entry["compatibility_version"]
            previous = rows[-1][3] if rows else 0
            if (type(revision) is not int or revision != number
                    or type(predecessor) is not int or predecessor != number - 1
                    or not isinstance(name, str) or not name or name in identities
                    or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                    or type(version) is not int or version < 1 or version not in (previous, previous + 1)):
                raise ValueError("Invalid migration entry.")
            rows.append((revision, name, digest, version))
            identities.add(name)
        if not rows:
            raise ValueError("Missing baseline.")
        return tuple(rows)
    except (OSError, ValueError, UnicodeError, KeyError, TypeError) as error:
        raise Refused("schema_incompatible", "The Build's migration manifest is unreadable.") from error


class Unavailable(Refused):
    """A classified connection/credential failure, never a statement deadline."""

    def __init__(self, cause: str) -> None:
        super().__init__("database_unavailable", cause)


async def password(role: str, *, program: str = "/usr/bin/security", seconds: float = 2.0) -> str:
    """No raw exception, stderr, token argument, inherited stdin or echo."""
    child = await asyncio.create_subprocess_exec(
        program,
        "find-generic-password",
        "-s",
        SERVICE,
        "-a",
        role,
        "-w",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    try:
        async with asyncio.timeout(seconds):
            assert child.stdout is not None
            data = await child.stdout.read(65537)
            status = await child.wait()
        if status == 44:
            return ""
        if status != 0 or len(data) > 65536:
            raise Refused("database_unavailable", "The database Keychain lookup failed.")
        return data.decode("utf-8").removesuffix("\n")
    except TimeoutError as error:
        raise Refused("timeout", "The database Keychain lookup exceeded two seconds.") from error
    except UnicodeError as error:
        raise Refused("database_unavailable", "The database Keychain reply is unreadable.") from error
    finally:
        if child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await child.wait()


async def credentials(identity: Identity) -> dict[str, str]:
    try:
        if identity.database is not None:
            info = conninfo_to_dict(identity.database)
            if (
                not {"host", "user", "dbname"} <= info.keys()
                or not info["dbname"] or not info["user"]
                or not Path(str(info["host"])).is_absolute() or "," in str(info["host"])
                or set(info) - {"host", "port", "user", "dbname"}
            ):
                raise ValueError("Explicit database must name only a private host/port/user/database.")
            if any(not isinstance(item, str) for item in info.values()):
                raise ValueError("Database fields must be strings.")
            private_directory(Path(str(info["host"])))
            return {
                **{key: str(value) for key, value in info.items()},
                "port": str(info.get("port", "5432")),
                "password": "",
            }
        value = object_file(identity.home / ".arbol/database.json")
        if (set(value) != {"address", "database"} or not isinstance(value["address"], str)
                or not isinstance(value["database"], str) or not value["database"].strip()
                or value["database"].lower() in {"postgres", "template0", "template1"}
                or "\0" in value["database"] or len(value["database"].encode("utf-8")) > 63):
            raise ValueError("Invalid database configuration.")
        url = urlsplit(value["address"])
        if (
            url.scheme not in ("postgres", "postgresql")
            or not url.username
            or not url.hostname
            or url.password is not None
            or url.path not in ("", "/")
            or not url.port
            or url.query
            or url.fragment
        ):
            raise ValueError("Invalid server address.")
        role = unquote(url.username)
        result = {
            "host": url.hostname,
            "port": str(url.port),
            "user": role,
            "dbname": value["database"],
        }
    except (OSError, ValueError, psycopg.Error, UnicodeError) as error:
        raise Unavailable("Cannot read the installation database configuration.") from error
    try:
        result["password"] = await password(role)
    except Refused as error:
        cause = ("The Keychain did not answer for the database's password." if error.code == "timeout"
                 else "The database Keychain lookup failed.")
        raise Unavailable(cause) from error
    except OSError as error:
        raise Unavailable("The database Keychain lookup could not be started.") from error
    return result


class Session:
    def __init__(self, connection: AsyncConnection[tuple[Any, ...]], seconds: float, on_success: Callable[[], None] | None = None) -> None:
        self.connection = connection
        self.seconds = seconds
        self.on_success = on_success

    async def execute(self, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
        try:
            async with asyncio.timeout(self.seconds):
                async with self.connection.cursor() as cursor:
                    await cursor.execute(sql, params)
                    result = await cursor.fetchall() if cursor.description else []
                    if self.on_success:
                        self.on_success()
                    return result
        except (TimeoutError, psycopg.errors.QueryCanceled) as error:
            raise Refused("timeout", "The database statement exceeded five seconds.") from error
        except psycopg.Error as error:
            code = error.sqlstate or ""
            if self.connection.closed or self.connection.broken or code.startswith("08") or code in {"57P01", "57P02", "57P03"}:
                raise Unavailable("The database connection was lost.") from error
            raise Refused("database_unavailable", "The database statement failed.") from error


class Database:
    def __init__(self, identity: Identity, *, seconds: float = SECONDS) -> None:
        self.identity = identity
        self.seconds = seconds
        self.parameters: dict[str, str] | None = None
        self.connections: set[AsyncConnection[tuple[Any, ...]]] = set()
        self.passfile: Path | None = None
        self.credentials_lock = asyncio.Lock()
        self.away = False
        self.schema = Schema()
        self.history: tuple[tuple[int, int, int], tuple[SchemaRow, ...]] | None = None
        self.on_failure: Callable[[str], None] | None = None
        self.on_connected: Callable[[], None] | None = None

    async def renew(self) -> None:
        async with self.credentials_lock:
            if self.passfile is not None:
                self.passfile.unlink(missing_ok=True)
            self.parameters, self.passfile = None, None

    async def read_schema(self, session: Session) -> Schema:
        manifest = (self.identity.bin_dir / ".arbol-builds/schema/migrations.toml"
                    if self.identity.build != "0" and self.identity.database is None
                    else self.identity.package / "database/migrations.toml")
        try:
            info = manifest.stat()
            stamp = (info.st_dev, info.st_ino, info.st_mtime_ns)
            if self.history is None or self.history[0] != stamp:
                self.history = stamp, await asyncio.to_thread(release_history, manifest)
            _, history = self.history
        except (OSError, Refused):
            return Schema("incompatible")
        try:
            rows = await session.execute(
                "SELECT revision, migration_id, checksum, compatibility_version "
                "FROM public.arbol_schema_migrations ORDER BY revision LIMIT %s",
                (len(history) + 1,),
            )
        except Unavailable:
            raise
        except Refused as error:
            if isinstance(error.__cause__, psycopg.errors.UndefinedTable):
                return Schema("uninitialized")
            if isinstance(error.__cause__, psycopg.errors.UndefinedColumn):
                return Schema("incompatible")
            raise
        if not rows or tuple(rows) != history[:len(rows)]:
            return Schema("incompatible")
        revision, _, _, version = history[len(rows) - 1]
        compatible = any(version == supported and revision >= minimum
                         for supported, minimum in self.identity.compatibility)
        return Schema("ready" if compatible else "incompatible", revision, version)

    @asynccontextmanager
    async def session(self, *, snapshot: bool = False, probe: bool = False) -> AsyncIterator[Session]:
        connection: AsyncConnection[tuple[Any, ...]] | None = None
        try:
            if self.away and not probe:
                raise Unavailable("The installation database is unavailable.")
            async with self.credentials_lock:
                if self.away and not probe:
                    raise Unavailable("The installation database is unavailable.")
                if self.parameters is None:
                    try:
                        self.parameters = await credentials(self.identity)
                    except Unavailable:
                        raise
                    except Refused as error:
                        raise Unavailable("Cannot read the installation database configuration.") from error
                    try:
                        fd, name = tempfile.mkstemp(prefix="arbol-backend-empty-passfile-")
                    except OSError as error:
                        raise Unavailable("Cannot prepare the private database connection settings.") from error
                    os.close(fd)
                    self.passfile = Path(name)
                    self.parameters["passfile"] = name
            try:
                async with asyncio.timeout(self.seconds):
                    connection = await AsyncConnection.connect(
                        make_conninfo(**self.parameters), autocommit=True, row_factory=tuple_row, connect_timeout=5,
                        options="-c statement_timeout=5000 -c lock_timeout=5000 -c client_encoding=UTF8",
                    )
            except (TimeoutError, psycopg.Error) as error:
                raise Unavailable("The database server does not answer.") from error
            self.connections.add(connection)
            session = Session(connection, self.seconds)
            if snapshot:
                await session.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            self.schema = await self.read_schema(session)
            if not probe:
                self.schema.require()
            try:
                yield session
            except BaseException:
                raise  # Closing discards an unfinished snapshot without another network wait.
            else:
                if snapshot:
                    await session.execute("COMMIT")
        except Unavailable as error:
            self.schema = Schema()
            if self.on_failure:
                self.on_failure(str(error))
            raise
        except psycopg.Error as error:
            # Raw database diagnostics can contain credentials and never cross the Bridge.
            raise Refused("database_unavailable", "The database statement failed.") from error
        finally:
            if connection is not None:
                self.connections.discard(connection)
                await connection.close()

    async def execute(self, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
        async with self.session() as session:
            return await session.execute(sql, params)

    async def close(self) -> None:
        for connection in list(self.connections):
            await connection.close()
        self.connections.clear()
        if self.passfile is not None:
            self.passfile.unlink(missing_ok=True)
            self.passfile = None
            self.parameters = None
