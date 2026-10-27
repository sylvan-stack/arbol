"""Independent bounded psycopg connections, autocommit and consistent snapshots."""

from __future__ import annotations

import asyncio
import os
import signal
import tempfile
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import AsyncConnection
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import tuple_row

from .model import Identity, Refused, object_file, root_record

SERVICE = "com.sylvan-stack.arbol.database"
SECONDS = 5.0


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
                or not info["dbname"]
                or set(info) - {"host", "port", "user", "dbname"}
            ):
                raise ValueError("Explicit database must name only a private host/port/user/database.")
            if any(not isinstance(item, str) for item in info.values()):
                raise ValueError("Database fields must be strings.")
            return {
                **{key: str(value) for key, value in info.items()},
                "port": str(info.get("port", "5432")),
                "password": "",
            }
        value = object_file(identity.home / ".arbol/database.json")
        if set(value) != {"address"} or not isinstance(value["address"], str):
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
        record = root_record(identity.folder, identity.root)
        role = unquote(url.username)
        result = {
            "host": url.hostname,
            "port": str(url.port),
            "user": role,
            "dbname": record["database"],
        }
    except (OSError, ValueError, psycopg.Error, UnicodeError) as error:
        raise Refused("database_unavailable", "Cannot read the Root's database configuration.") from error
    try:
        result["password"] = await password(role)
    except OSError as error:
        raise Refused("database_unavailable", "The database Keychain lookup could not be started.") from error
    return result


class Session:
    def __init__(self, connection: AsyncConnection[tuple[Any, ...]], seconds: float) -> None:
        self.connection = connection
        self.seconds = seconds

    async def execute(self, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
        try:
            async with asyncio.timeout(self.seconds):
                async with self.connection.cursor() as cursor:
                    await cursor.execute(sql, params)
                    return await cursor.fetchall() if cursor.description else []
        except (TimeoutError, psycopg.errors.QueryCanceled) as error:
            raise Refused("timeout", "The database statement exceeded five seconds.") from error
        except psycopg.Error as error:
            raise Refused("database_unavailable", "The database statement failed.") from error


class Database:
    def __init__(self, identity: Identity, *, seconds: float = SECONDS) -> None:
        self.identity = identity
        self.seconds = seconds
        self.parameters: dict[str, str] | None = None
        self.connections: set[AsyncConnection[tuple[Any, ...]]] = set()
        self.passfile: Path | None = None
        self.credentials_lock = asyncio.Lock()

    @asynccontextmanager
    async def session(self, *, snapshot: bool = False) -> AsyncIterator[Session]:
        connection: AsyncConnection[tuple[Any, ...]] | None = None
        try:
            async with self.credentials_lock:
                if self.parameters is None:
                    self.parameters = await credentials(self.identity)
                    fd, name = tempfile.mkstemp(prefix="arbol-backend-empty-passfile-")
                    os.close(fd)
                    self.passfile = Path(name)
                    self.parameters["passfile"] = name
            async with asyncio.timeout(self.seconds):
                connection = await AsyncConnection.connect(
                    make_conninfo(**self.parameters),
                    autocommit=True,
                    row_factory=tuple_row,
                    connect_timeout=5,
                    options="-c statement_timeout=5000 -c lock_timeout=5000 -c client_encoding=UTF8",
                )
            self.connections.add(connection)
            session = Session(connection, self.seconds)
            if snapshot:
                await session.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            try:
                yield session
            except BaseException:
                # Closing discards an unfinished read-only snapshot, with no extra network wait.
                raise
            else:
                if snapshot:
                    await session.execute("COMMIT")
        except (TimeoutError, psycopg.errors.QueryCanceled, psycopg.errors.ConnectionTimeout) as error:
            raise Refused("timeout", "The database connection exceeded five seconds.") from error
        except psycopg.Error as error:
            raise Refused("database_unavailable", "The Root database cannot be reached.") from error
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
