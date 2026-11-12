"""Capture and verify one PostgreSQL recovery point under exclusive maintenance."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

if TYPE_CHECKING:
    from database_server import BIN, MAJOR, Places, environment
    from migrate_schema import Database, Refusal, Target, database_target
    from recovery_release import (
        DIGEST,
        RecoveryError,
        canonical,
        digest,
        document,
        private_dir,
        publish_directory,
        sha,
        verify_release,
        write_private,
    )

else:
    def sibling(name: str) -> Any:
        return importlib.import_module(f".{name}", __package__) if __package__ else importlib.import_module(name)

    _server = sibling("database_server")
    BIN, MAJOR, Places, environment = _server.BIN, _server.MAJOR, _server.Places, _server.environment
    _migration = sibling("migrate_schema")
    Refusal, database_target = _migration.Refusal, _migration.database_target
    _release = sibling("recovery_release")
    DIGEST, RecoveryError, canonical, digest = _release.DIGEST, _release.RecoveryError, _release.canonical, _release.digest
    document, private_dir, publish_directory = _release.document, _release.private_dir, _release.publish_directory
    sha, verify_release, write_private = _release.sha, _release.verify_release, _release.write_private

Identity = dict[str, str | int]
Exclusive = Callable[[Identity, str], AbstractContextManager[str]]
REQUIRED_CHAT = frozenset({"chats", "exchanges", "messages"})
VIGOR = frozenset({"vigor_profiles", "vigor_reports", "vigor_results"})
SAMPLES = REQUIRED_CHAT | VIGOR | {"drafts"}
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
ARCHIVE = "database.dump"
SNAPSHOT = "snapshot.json"


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def source_identity(connection: Database, host: str, port: int) -> Identity:
    """Read on the connection that will be used, not from an operator-supplied name alone."""
    row = connection.execute(
        """
        SELECT datname, oid::bigint, pg_catalog.host(pg_catalog.inet_server_addr()), inet_server_port()
        FROM pg_catalog.pg_database WHERE datname = current_database()
        """
    ).fetchone()
    if row is None or type(row[1]) is not int:
        raise RecoveryError("PostgreSQL did not establish the database identity.")
    if host.startswith("/"):
        if row[2] is not None or row[3] is not None or connection.info.port != port:
            raise RecoveryError("PostgreSQL is not connected through the specified private socket.")
    elif row[2] != host or row[3] != port:
        raise RecoveryError("PostgreSQL did not connect to the specified installed address.")
    return {"host": host, "port": port, "database": row[0], "databaseOid": row[1]}


def tool(name: str, arguments: list[str], target: Target | None = None) -> str:
    extra: dict[str, str] = {}
    if target is not None and target.password:
        extra["PGPASSWORD"] = target.password
    try:
        result = subprocess.run(
            [str(BIN / name), *arguments], capture_output=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, env=environment(Path.home(), extra), timeout=7200, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RecoveryError(f"{name} did not start or finish.") from None
    if result.returncode:
        # PostgreSQL can include private row content or credentials in diagnostics.
        raise RecoveryError(f"{name} failed with exit status {result.returncode}.")
    return result.stdout


def connection_arguments(target: Target) -> list[str]:
    conninfo = make_conninfo(
        host=target.host, port=str(target.port), dbname=target.database, user=target.user,
        passfile=os.devnull, sslmode="disable", gssencmode="disable", connect_timeout="5",
    )
    return ["--no-password", "--dbname", conninfo]


def check_version(connection: Database) -> None:
    if connection.info.server_version // 10000 != MAJOR:
        raise RecoveryError("Use the installed PostgreSQL major version for recovery.")


def control_identity(connection: Database) -> str | None:
    permitted = connection.execute(
        "SELECT has_function_privilege('pg_catalog.pg_control_system()', 'EXECUTE')"
    ).fetchone()
    if permitted and permitted[0]:
        row = connection.execute("SELECT system_identifier::text FROM pg_catalog.pg_control_system()").fetchone()
        if row is not None:
            return str(row[0])
    return None


def installation_cluster() -> str:
    info = tool("pg_controldata", [str(Places(Path.home()).data)])
    match = re.search(r"^Database system identifier:\s*([0-9]+)$", info, re.MULTILINE)
    if match is None:
        raise RecoveryError("The installed PostgreSQL cluster identity is unavailable.")
    return match[1]


def cluster_identity(connection: Database, target: Target) -> str:
    actual = control_identity(connection)
    if target.host.startswith("/"):
        if actual is None:
            raise RecoveryError("The private source role must be able to read its PostgreSQL cluster identity.")
        return actual
    expected = installation_cluster()
    if actual is not None and actual != expected:
        raise RecoveryError("The installed endpoint and data directory identify different PostgreSQL clusters.")
    return expected


def observations(connection: Database, legacy_release: str | None) -> dict[str, Any]:
    """Capture the ledger, table shape and a small deterministic sample without saving row contents."""
    connection.execute("SET LOCAL TIME ZONE 'UTC'")
    connection.execute("SET LOCAL datestyle TO 'ISO, YMD'")
    connection.execute("SET LOCAL intervalstyle TO 'iso_8601'")
    connection.execute("SET LOCAL extra_float_digits TO 3")
    rows = connection.execute(
        """
        SELECT c.relname::text, c.relkind::text, a.attname::text, pg_catalog.format_type(a.atttypid, a.atttypmod),
               a.attnotnull, a.attidentity::text, a.attgenerated::text
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
        ORDER BY c.relname COLLATE "C", a.attnum
        """
    ).fetchall()
    tables = {row[0] for row in rows if row[1] in ("r", "p")}
    if not REQUIRED_CHAT <= tables or (legacy_release is None and not VIGOR <= tables):
        raise RecoveryError("The database is missing required Arbol tables.")
    if legacy_release is not None:
        if {"arbol_schema_migrations", "arbol_schema_upgrades"} & {row[0] for row in rows}:
            raise RecoveryError("A database with a migration ledger cannot be treated as a legacy release.")
        schema: dict[str, str | int] = {"legacyRelease": legacy_release}
        ledger: list[tuple[Any, ...]] = []
    else:
        if not {"arbol_schema_migrations", "arbol_schema_upgrades"} <= tables:
            raise RecoveryError("The current database has no complete migration ledger.")
        ledger = connection.execute(
            """
            SELECT revision, migration_id, checksum, compatibility_version
            FROM public.arbol_schema_migrations ORDER BY revision
            """
        ).fetchall()
        previous = 0
        identities = set()
        for index, (revision, identity, checksum, version) in enumerate(ledger, 1):
            allowed = {previous, previous + 1} if index > 1 else {1}
            if (type(revision) is not int or revision != index or not isinstance(identity, str) or not identity
                    or identity in identities or not isinstance(checksum, str) or not DIGEST.fullmatch(checksum)
                    or type(version) is not int or version not in allowed):
                raise RecoveryError("The migration ledger is not a valid ordered history.")
            identities.add(identity)
            previous = version
        if not ledger:
            raise RecoveryError("The database has not been initialized.")
        schema = {"revision": len(ledger), "compatibilityVersion": previous}

    samples = {}
    for name in sorted(SAMPLES & tables):
        keys = connection.execute(
            """
            SELECT a.attname FROM pg_catalog.pg_index i
            CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, position)
            JOIN pg_catalog.pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
            WHERE i.indrelid = pg_catalog.to_regclass(%s) AND i.indisprimary AND k.position <= i.indnkeyatts
            ORDER BY k.position
            """,
            (f"public.{name}",),
        ).fetchall()
        if not keys:
            raise RecoveryError(f"Cannot choose representative rows without the primary key for {name}.")
        sample = connection.execute(
            sql.SQL("SELECT to_jsonb(sample)::text FROM (SELECT * FROM {} ORDER BY {} LIMIT 3) AS sample").format(
                sql.Identifier("public", name), sql.SQL(", ").join(sql.Identifier(key[0]) for key in keys),
            )
        ).fetchall()
        samples[name] = {"rowsRead": len(sample), "sha256": sha(canonical(sample))}
    return {"schema": schema, "ledgerSha256": sha(canonical(ledger)),
            "shapeSha256": sha(canonical(rows)), "samples": samples}


def required_roles(connection: Database) -> list[str]:
    return [row[0] for row in connection.execute(
        """
        SELECT DISTINCT r.rolname::text COLLATE "C"
        FROM pg_catalog.pg_database d
        JOIN pg_catalog.pg_roles r ON r.oid = d.datdba OR r.oid IN (
            SELECT dep.refobjid FROM pg_catalog.pg_shdepend dep
            WHERE dep.refclassid = 'pg_catalog.pg_authid'::regclass
              AND (dep.dbid = d.oid OR (dep.dbid = 0 AND dep.classid = 'pg_catalog.pg_database'::regclass
                                       AND dep.objid = d.oid))
            UNION
            SELECT c.relowner FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public'
        )
        WHERE d.datname = current_database()
        ORDER BY 1
        """
    ).fetchall()]


def check_archive_name(path: Path, database: str) -> None:
    output = tool("pg_restore", ["--list", str(path)])
    if [line[1:].strip().removeprefix("dbname: ") for line in output.splitlines()
            if line.startswith(";") and line[1:].strip().startswith("dbname: ")] != [database]:
        raise RecoveryError("The archive header does not identify the specified database.")


def capture(
    target: Target, release_dir: Path, destination: Path, *, maintenance_session: str, exclusive: Exclusive,
    legacy_release: str | None = None,
) -> Path:
    if not SESSION.fullmatch(maintenance_session):
        raise RecoveryError("An explicit maintenance session is required.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]*", target.database) or target.database != target.database.strip():
        raise RecoveryError("The database name must be unambiguous in a PostgreSQL archive header.")
    if legacy_release is not None and not SESSION.fullmatch(legacy_release):
        raise RecoveryError("Name the exact legacy release in its recovery record.")
    with target.connect() as connection:
        check_version(connection)
        source = source_identity(connection, target.host, target.port)
        # The interlock prevents reopening until publication and remains exclusive on failure.
        with exclusive(source, maintenance_session) as held, publish_directory(destination) as staging:
            if held != maintenance_session:
                raise RecoveryError("The exclusive handoff belongs to a different maintenance session.")
            release_dir = private_dir(release_dir)
            release, release_sha256 = verify_release(release_dir)
            if release["kind"] != ("legacy" if legacy_release is not None else "current"):
                raise RecoveryError("The release record does not describe the requested database kind.")
            if legacy_release is not None:
                root = document(release_dir / "configuration/root")
                roots = {build["root"] for build in release["builds"] if build["component"] in {"arbol", "arbol-root"}}
                if legacy_release != release_sha256 or root.get("database") != target.database or roots != {root["root"]}:
                    raise RecoveryError("The saved legacy release and Root record do not identify this database.")
            with connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                if source_identity(connection, target.host, target.port) != source:
                    raise RecoveryError("The source changed before the snapshot.")
                cluster = cluster_identity(connection, target)
                data = observations(connection, legacy_release)
                roles = required_roles(connection)
                exported = connection.execute("SELECT pg_catalog.pg_export_snapshot()").fetchone()
                if exported is None:
                    raise RecoveryError("PostgreSQL did not export a database snapshot.")
                path = staging / ARCHIVE
                path.touch(mode=0o600, exist_ok=False)
                tool("pg_dump", ["--format=custom", "--snapshot", str(exported[0]), "--file", str(path),
                                 *connection_arguments(target)], target)
            check_archive_name(path, target.database)
            receipt = {"format": 1, "kind": "arbol-recovery-snapshot", "source": source, "sourceCluster": cluster,
                       "schema": data["schema"], "observation": data, "roles": roles,
                       "archiveSha256": digest(path), "releaseSha256": release_sha256, "releaseDirectory": str(release_dir),
                       "maintenanceSession": maintenance_session, "capturedAt": timestamp()}
            write_private(staging / SNAPSHOT, receipt)
    return destination.resolve() / SNAPSHOT


def production_exclusive(source: Identity, session: str) -> AbstractContextManager[str]:
    try:
        module = importlib.import_module("arbol_backend.exchange_drain")
        boundary = module.exclusive_upgrade
    except (ImportError, AttributeError):
        raise RecoveryError("The installed exclusive maintenance adapter is unavailable.") from None
    return cast(AbstractContextManager[str], boundary(source, session))


def main(argv: list[str] | None = None, *, exclusive: Exclusive | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--user")
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--release", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.add_argument("--session", required=True)
    snapshot.add_argument("--legacy-release")
    args = parser.parse_args(argv)
    try:
        if args.legacy_release and exclusive is None:
            raise RecoveryError("Legacy capture requires the cutover adapter that verifies both writer sets are fenced.")
        target = database_target(args.database, socket=args.socket, port=args.port, user=args.user)
        result = capture(target, args.release, args.output, maintenance_session=args.session,
                         exclusive=exclusive or production_exclusive, legacy_release=args.legacy_release)
    except (RecoveryError, Refusal) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, psycopg.Error, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        print("Recovery refused: a required database or private recovery input could not be verified.", file=sys.stderr)
        return 1
    print(json.dumps({"snapshot": str(result)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
