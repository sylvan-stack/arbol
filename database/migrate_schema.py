"""The sole writer of Arbol's ordered PostgreSQL schema (ARC-4)."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import stat
import subprocess
import tomllib
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import Connection, sql
from psycopg.conninfo import make_conninfo

if TYPE_CHECKING:
    from database_server import SECURITY, SERVICE, Places, run
else:
    _server = import_module(".database_server", __package__) if __package__ else import_module("database_server")
    SECURITY, SERVICE, Places, run = _server.SECURITY, _server.SERVICE, _server.Places, _server.run

MANIFEST = Path(__file__).resolve().with_name("migrations.toml")
# PostgreSQL advisory locks are scoped to a database. Hold this session lock
# across all transactions in a change; PostgreSQL releases it on disconnect.
MIGRATION_LOCK = 0x4152424F4C534348  # ARBOLSCH
CHECKSUM = re.compile(r"[0-9a-f]{64}")
LedgerRow = tuple[int, str, str, int]
UpgradePin = tuple[int, int, str, str, str]
SourceIdentity = dict[str, str | int]
Database = Connection[tuple[Any, ...]]


class Refusal(Exception):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Target:
    database: str
    host: str
    port: int
    user: str
    password: str = field(default="", repr=False)

    def connect(self) -> Database:
        # A service can supply parameters before libpq applies its defaults.
        # Refuse it rather than changing the ambient environment of callers.
        if "PGSERVICE" in os.environ:
            raise Refusal("unavailable", "Unset PGSERVICE to use the explicit Arbol database connection.")
        try:
            conninfo = make_conninfo(
                dbname=self.database,
                host=self.host,
                hostaddr="" if self.host.startswith("/") else self.host,
                port=str(self.port),
                user=self.user,
                password=self.password,
                passfile=os.devnull,
                sslmode="disable",
                gssencmode="disable",
                target_session_attrs="any",
                client_encoding="UTF8",
                connect_timeout="5",
                options=(
                    "-csearch_path=public -cstatement_timeout=5000 -clock_timeout=5000 "
                    "-cdefault_transaction_read_only=off"
                ),
            )
            connection = psycopg.connect(conninfo, autocommit=True)
        except (psycopg.Error, ValueError, OSError, UnicodeError):
            raise Refusal("unavailable", "Cannot connect to the specified PostgreSQL database.") from None
        if connection.info.dbname != self.database:
            connection.close()
            raise Refusal("unavailable", "PostgreSQL did not connect to the specified database.")
        return connection

    def identity(self, connection: Database) -> SourceIdentity:
        row = connection.execute(
            "SELECT oid FROM pg_catalog.pg_database WHERE datname = pg_catalog.current_database()"
        ).fetchone()
        if not row or type(row[0]) is not int or row[0] <= 0 or connection.info.dbname != self.database:
            raise Refusal("unavailable", "Cannot verify the connected PostgreSQL database identity.")
        return {"host": self.host, "port": self.port, "database": self.database, "databaseOid": row[0]}


def database_target(
    database: str, *, socket: Path | None = None, port: int | None = None, user: str | None = None
) -> Target:
    """Resolve an explicit installed database, or an independent private socket."""
    if (
        not database.strip()
        or "\0" in database
        or len(database.encode("utf-8")) > 63
        or database.lower() in {"postgres", "template0", "template1"}
    ):
        raise Refusal("invalid_input", "Name one Arbol database explicitly.")
    if socket is not None:
        try:
            if not socket.is_absolute() or port is None or not 1 <= port <= 65535 or not user or "\0" in user:
                raise ValueError
            directory = socket.resolve(strict=True)
            mode = directory.stat()
            if (
                "," in str(directory)
                or directory == Places(Path.home()).socket.resolve()
                or not stat.S_ISDIR(mode.st_mode)
                or mode.st_uid != os.getuid()
                or mode.st_mode & 0o077
            ):
                raise ValueError
        except (OSError, ValueError, RuntimeError):
            raise Refusal(
                "invalid_input", "A private socket requires an absolute owner-only directory, port and role."
            ) from None
        return Target(database, str(directory), port, user)
    if port is not None or user is not None:
        raise Refusal("invalid_input", "--port and --user require --socket.")

    home = Path.home()
    try:
        config = json.loads(Places(home).settings.read_text(encoding="utf-8"))
        if (
            not isinstance(config, dict)
            or set(config) not in ({"address"}, {"address", "database"})
            or not isinstance(config["address"], str)
            or ("database" in config and config["database"] != database)
        ):
            raise ValueError
        address = urlsplit(config["address"])
        if (
            address.scheme not in {"postgresql", "postgres"}
            or not address.hostname
            or not address.port
            or not address.username
            or address.password is not None
            or address.path not in {"", "/"}
            or address.query
            or address.fragment
        ):
            raise ValueError
        ip = ipaddress.ip_address(address.hostname)
        if not ip.is_loopback:
            raise ValueError
        role = unquote(address.username, errors="strict")
        if not role.strip() or "\0" in role:
            raise ValueError
        port = address.port
    except (OSError, ValueError):
        raise Refusal("unavailable", "The installed PostgreSQL address is missing or invalid.") from None
    try:
        result = run([SECURITY, "find-generic-password", "-s", SERVICE, "-a", role, "-w"], home, timeout=2)
        password = result.stdout.removesuffix("\n")
        if result.returncode or not password:
            raise ValueError
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise Refusal("unavailable", "Cannot read the installed database credential from Keychain.") from None
    return Target(database, str(ip), port, role, password)


@dataclass(frozen=True)
class Migration:
    revision: int
    predecessor: int
    identity: str
    checksum: str
    compatibility_version: int
    statement: str = field(repr=False)

    def ledger_row(self) -> LedgerRow:
        return self.revision, self.identity, self.checksum, self.compatibility_version


@dataclass(frozen=True)
class Manifest:
    migrations: tuple[Migration, ...]
    checksum: str


def load_manifest(path: Path = MANIFEST) -> Manifest:
    """Read and hash all release inputs before using a connection."""
    try:
        source = path.read_bytes()
        data = tomllib.loads(source.decode("utf-8"))
        if set(data) != {"format", "migrations"} or type(data["format"]) is not int or data["format"] != 1:
            raise ValueError
        entries = data["migrations"]
        if not isinstance(entries, list) or not entries:
            raise ValueError
        migrations: list[Migration] = []
        identities: set[str] = set()
        files: set[str] = set()
        for revision, entry in enumerate(entries, 1):
            if not isinstance(entry, dict) or set(entry) != {
                "revision", "predecessor", "id", "file", "sha256", "compatibility_version"
            }:
                raise ValueError
            predecessor = entry["predecessor"]
            identity, filename, checksum = entry["id"], entry["file"], entry["sha256"]
            compatibility = entry["compatibility_version"]
            previous_version = migrations[-1].compatibility_version if migrations else 1
            allowed = {previous_version, previous_version + 1} if migrations else {1}
            if (
                type(entry["revision"]) is not int
                or entry["revision"] != revision
                or type(predecessor) is not int
                or predecessor != revision - 1
                or type(compatibility) is not int
                or compatibility not in allowed
                or not isinstance(identity, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", identity)
                or identity in identities
                or not isinstance(filename, str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]+\.sql", filename)
                or filename in files
                or not isinstance(checksum, str)
                or not CHECKSUM.fullmatch(checksum)
            ):
                raise ValueError
            migration_file = path.with_name(filename)
            if migration_file.is_symlink():
                raise ValueError
            payload = migration_file.read_bytes()
            if sha256(payload).hexdigest() != checksum or not payload.strip() or b"\0" in payload:
                raise ValueError
            migrations.append(Migration(revision, predecessor, identity, checksum, compatibility, payload.decode()))
            identities.add(identity)
            files.add(filename)
        return Manifest(tuple(migrations), sha256(source).hexdigest())
    except (OSError, ValueError):
        raise Refusal("invalid", "The release migration manifest or one of its SQL checksums is invalid.") from None


def _empty_database(connection: Database) -> bool:
    row = connection.execute(
        """
        SELECT pg_catalog.to_regnamespace('public') IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_namespace
               WHERE nspname NOT IN ('public', 'information_schema', 'pg_catalog', 'pg_toast')
                 AND nspname !~ '^pg_(toast_)?temp_[0-9]+$'
           )
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname ~ '^pg_(toast_)?temp_[0-9]+$'
           )
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_depend
               WHERE refclassid = 'pg_catalog.pg_namespace'::pg_catalog.regclass
                 AND refobjid = pg_catalog.to_regnamespace('public')
           )
           AND NOT EXISTS (
               SELECT 1 FROM pg_catalog.pg_extension WHERE extname <> 'plpgsql'
           )
           AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_event_trigger)
        """
    ).fetchone()
    return row is not None and row[0] is True


def read_prefix(connection: Database, manifest: Manifest) -> tuple[LedgerRow, ...]:
    """Read in the caller's transaction so discovery and rows share its snapshot."""
    relations = connection.execute(
        """
        SELECT c.relname, c.relkind, c.relpersistence
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname IN ('arbol_schema_migrations', 'arbol_schema_upgrades')
        """
    ).fetchall()
    if not relations and _empty_database(connection):
        return ()
    if set(relations) != {
        ("arbol_schema_migrations", "r", "p"),
        ("arbol_schema_upgrades", "r", "p"),
    }:
        raise Refusal("invalid", "The database does not contain the single-database migration ledger.")
    try:
        rows = connection.execute(
            """
            SELECT revision, migration_id, checksum, compatibility_version
            FROM public.arbol_schema_migrations
            ORDER BY revision LIMIT %s
            """,
            (len(manifest.migrations) + 1,),
        ).fetchall()
    except (psycopg.errors.UndefinedColumn, psycopg.errors.InsufficientPrivilege):
        raise Refusal("invalid", "The migration ledger is malformed or unreadable.") from None
    expected = tuple(m.ledger_row() for m in manifest.migrations[:len(rows)])
    if not rows or tuple(rows) != expected or any(type(row[0]) is not int or type(row[3]) is not int for row in rows):
        raise Refusal("invalid", "The installed migration ledger is not a prefix of this release.")
    return expected


def _ready(row: LedgerRow) -> dict[str, str | int]:
    return {"status": "ready", "revision": row[0], "compatibilityVersion": row[3]}


def _read_committed(connection: Database, manifest: Manifest) -> tuple[LedgerRow, ...]:
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return read_prefix(connection, manifest)


def lookup(target: Target, manifest: Manifest) -> dict[str, str | int]:
    """Look up the installed pair without changing data, schema or admission."""
    with target.connect() as connection:
        rows = _read_committed(connection, manifest)
    return _ready(rows[-1]) if rows else {"status": "uninitialized"}


def _lock(connection: Database) -> None:
    row = connection.execute("SELECT pg_catalog.pg_try_advisory_lock(%s)", (MIGRATION_LOCK,)).fetchone()
    if row != (True,):
        raise Refusal("busy", "Another schema operation already holds this database's migration lock.")


def _execute_sql(connection: Database, migration: Migration) -> None:
    # SQL runs inside SPI within the explicit client transaction. A migration
    # cannot COMMIT, ROLLBACK or otherwise leave that transaction.
    connection.execute("SET LOCAL statement_timeout = 0")
    statement = sql.Literal(migration.statement).as_string(connection)
    body = sql.Literal(f"BEGIN EXECUTE {statement}; END;")
    connection.execute(sql.SQL("DO LANGUAGE plpgsql {}").format(body))


def _record(connection: Database, migration: Migration) -> None:
    connection.execute(
        """
        INSERT INTO public.arbol_schema_migrations (revision, migration_id, checksum, compatibility_version)
        VALUES (%s, %s, %s, %s)
        """,
        migration.ledger_row(),
    )


def initialize(target: Target, manifest: Manifest, *, authorized: bool) -> dict[str, str | int]:
    """Initialize only an authorized empty database. The cutover owns its external fence."""
    if not authorized:
        raise Refusal("invalid_input", "Baseline initialization requires --authorize-empty.")
    with target.connect() as connection:
        _lock(connection)
        baseline = manifest.migrations[0]
        with connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE")
            if read_prefix(connection, manifest):
                raise Refusal("invalid", "Baseline initialization requires an empty database.")
            _execute_sql(connection, baseline)
            _record(connection, baseline)
            if read_prefix(connection, manifest) != (baseline.ledger_row(),):
                raise Refusal("invalid", "Cannot verify the baseline ledger.")
        rows = _read_committed(connection, manifest)
        if rows != (baseline.ledger_row(),):
            raise Refusal("invalid", "Cannot read back the committed baseline ledger.")
        return _ready(rows[-1])


def _check_target(manifest: Manifest, prefix: tuple[LedgerRow, ...], target_revision: int) -> None:
    if type(target_revision) is not int or not 1 <= target_revision <= len(manifest.migrations):
        raise Refusal("invalid_input", "The target revision is not declared in this release.")
    if not prefix:
        raise Refusal("uninitialized", "Initialize the empty database before upgrading it.")
    if target_revision < prefix[-1][0]:
        raise Refusal("invalid_input", "A schema upgrade cannot target an earlier revision.")


def _apply_prefix(
    connection: Database,
    manifest: Manifest,
    prefix: tuple[LedgerRow, ...],
    target_revision: int,
    verify_pin: Callable[[], None],
) -> dict[str, str | int]:
    """Apply SQL under the caller's migration lock and exclusive admission."""
    _check_target(manifest, prefix, target_revision)
    for migration in manifest.migrations[len(prefix):target_revision]:
        expected = (*prefix, migration.ledger_row())
        try:
            with connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE")
                if migration.predecessor != prefix[-1][0] or read_prefix(connection, manifest) != prefix:
                    raise Refusal("invalid", "The migration predecessor could not be verified.")
                _execute_sql(connection, migration)
                if read_prefix(connection, manifest) != prefix:
                    raise Refusal("invalid", "Migration SQL modified the installed ledger.")
                _record(connection, migration)
                if read_prefix(connection, manifest) != expected:
                    raise Refusal("invalid", "The migration ledger entry could not be verified.")
                verify_pin()
            prefix = _read_committed(connection, manifest)
        except psycopg.Error as error:
            code = f" (SQLSTATE {error.sqlstate})" if error.sqlstate else ""
            raise Refusal(
                "migration_failed",
                f"Could not confirm revision {migration.revision}{code}. Verify the committed ledger before retrying.",
            ) from None
        if prefix != expected:
            raise Refusal("invalid", "The committed migration ledger does not match the requested revision.")
    return _ready(prefix[-1])


@dataclass(frozen=True)
class Upgrade:
    target_revision: int
    maintenance_session: str
    prior_release: str
    upgrade_release: str
    snapshot_dir: Path
    restore_receipt: Path


class RecoveryVerifier(Protocol):
    def __call__(
        self,
        snapshot_dir: Path,
        restore_receipt: Path,
        /,
        *,
        source: SourceIdentity,
        schema: dict[str, int],
        release_sha256: str,
        maintenance_session: str,
    ) -> object: ...


Exclusive = Callable[[SourceIdentity, str], AbstractContextManager[str]]


def _read_pin(connection: Database, session: str) -> UpgradePin | None:
    row = connection.execute(
        """
        SELECT starting_revision, target_revision, prior_release, release_checksum, receipt_checksum
        FROM public.arbol_schema_upgrades WHERE maintenance_session = %s
        """,
        (session,),
    ).fetchone()
    if row is None:
        return None
    starting, target, prior, release, receipt = row
    if type(starting) is not int or type(target) is not int or not all(
        isinstance(value, str) and CHECKSUM.fullmatch(value) for value in (prior, release, receipt)
    ):
        raise Refusal("invalid", "The recorded upgrade checkpoint is invalid.")
    return starting, target, prior, release, receipt


def _receipt_digest(path: Path) -> str:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError:
        raise Refusal("recovery_refused", "The original isolated restore receipt could not be read.") from None


def upgrade(
    target: Target,
    manifest: Manifest,
    request: Upgrade,
    *,
    exclusive: Exclusive,
    verify_recovery: RecoveryVerifier,
) -> dict[str, str | int]:
    """Apply or resume under the same durable fence, release and recovery proof."""
    session = request.maintenance_session
    if not session.strip() or "\0" in session:
        raise Refusal("invalid_input", "An exclusive maintenance session ID is required.")
    if not CHECKSUM.fullmatch(request.prior_release) or not CHECKSUM.fullmatch(request.upgrade_release):
        raise Refusal("invalid_input", "Name both releases by their lowercase SHA-256 digests.")
    release_checksum = sha256(f"{request.upgrade_release}:{manifest.checksum}".encode("ascii")).hexdigest()
    with target.connect() as connection, ExitStack() as held:
        source = target.identity(connection)
        try:
            authoritative_session = held.enter_context(exclusive(source, session))
        except Exception:
            raise Refusal("maintenance", "Could not hold exclusive maintenance for this database and session.") from None
        if authoritative_session != session:
            raise Refusal("maintenance", "The exclusive handoff belongs to a different maintenance session.")

        _lock(connection)
        prefix = _read_committed(connection, manifest)
        revision = request.target_revision
        _check_target(manifest, prefix, revision)
        pin = _read_pin(connection, session)
        installed = len(prefix)
        if pin is None and installed == revision:
            return _ready(prefix[-1])
        starting = pin[0] if pin else installed
        if not 1 <= starting <= installed or starting >= revision:
            raise Refusal("invalid", "The installed ledger does not match the fenced upgrade checkpoint.")

        receipt_checksum = _receipt_digest(request.restore_receipt)
        expected = (starting, revision, request.prior_release, release_checksum, receipt_checksum)
        if pin is not None and pin != expected:
            raise Refusal("recovery_refused", "Retry requires the original receipt, releases and target revision.")
        try:
            proof = verify_recovery(
                request.snapshot_dir,
                request.restore_receipt,
                source=source,
                schema={"revision": starting, "compatibilityVersion": prefix[starting - 1][3]},
                release_sha256=request.prior_release,
                maintenance_session=session,
            )
        except Exception:
            raise Refusal("recovery_refused", "The archive or isolated restore receipt does not verify.") from None
        if (
            not isinstance(proof, dict)
            or proof.get("receiptSha256") != receipt_checksum
            or _receipt_digest(request.restore_receipt) != receipt_checksum
        ):
            raise Refusal("recovery_refused", "The isolated restore receipt changed or could not be verified.")

        if pin is None:
            with connection.transaction():
                connection.execute(
                    """
                    INSERT INTO public.arbol_schema_upgrades
                        (maintenance_session, starting_revision, target_revision,
                         prior_release, release_checksum, receipt_checksum)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (session, *expected),
                )

        def verify_pin() -> None:
            if _read_pin(connection, session) != expected:
                raise Refusal("invalid", "The original upgrade checkpoint could not be verified.")

        verify_pin()
        return _apply_prefix(connection, manifest, prefix, revision, verify_pin)


@contextmanager
def _runtime_exclusive(source: SourceIdentity, session: str) -> Iterator[str]:
    # ASD-7 owns the admission state and reopen. No private-file or session-ID
    # fallback can authorize an installed schema change.
    drain = import_module("arbol_backend.exchange_drain")
    with drain.exclusive_upgrade(source, session) as held:
        yield held


def _recovery_verifier(
    snapshot_dir: Path,
    restore_receipt: Path,
    /,
    *,
    source: SourceIdentity,
    schema: dict[str, int],
    release_sha256: str,
    maintenance_session: str,
) -> object:
    recovery = import_module(".recovery", __package__) if __package__ else import_module("recovery")
    return recovery.verify_recovery(
        snapshot_dir,
        restore_receipt,
        source=source,
        schema=schema,
        release_sha256=release_sha256,
        maintenance_session=maintenance_session,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--socket", type=Path, help="Use an explicit private PostgreSQL socket directory.")
    parser.add_argument("--port", type=int, help="Port of the private socket.")
    parser.add_argument("--user", help="Role on the private socket.")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("status", help="Read the installed migration ledger.")
    initialize_action = actions.add_parser("initialize", help="Initialize revision 1 in an empty database.")
    initialize_action.add_argument("--authorize-empty", action="store_true")
    upgrade_action = actions.add_parser("upgrade", help="Upgrade or resume under an exclusive maintenance session.")
    upgrade_action.add_argument("--target-revision", type=int, required=True)
    upgrade_action.add_argument("--maintenance-session", required=True)
    upgrade_action.add_argument("--prior-release", required=True, help="Prior release record SHA-256.")
    upgrade_action.add_argument("--upgrade-release", required=True, help="Upgrade release record SHA-256.")
    upgrade_action.add_argument("--snapshot-dir", type=Path, required=True)
    upgrade_action.add_argument("--restore-receipt", type=Path, required=True)
    args = parser.parse_args()
    result: dict[str, str | int]
    try:
        manifest = load_manifest()
        target = database_target(args.database, socket=args.socket, port=args.port, user=args.user)
        if args.action == "status":
            result = lookup(target, manifest)
        elif args.action == "initialize":
            result = initialize(target, manifest, authorized=args.authorize_empty)
        else:
            result = upgrade(
                target,
                manifest,
                Upgrade(
                    args.target_revision,
                    args.maintenance_session,
                    args.prior_release,
                    args.upgrade_release,
                    args.snapshot_dir,
                    args.restore_receipt,
                ),
                exclusive=_runtime_exclusive,
                verify_recovery=_recovery_verifier,
            )
    except Refusal as error:
        result = {"status": error.status, "message": str(error)}
    except psycopg.Error as error:
        result = {"status": "unavailable", "message": "PostgreSQL could not complete the schema operation."}
        if error.sqlstate:
            result["sqlstate"] = error.sqlstate
    print(json.dumps(result))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
