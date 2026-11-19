"""SIM-3's qualification drill: migration revision 3 through the fenced procedure on a populated disposable installation.

It runs only on disposable state. The run folder (retained output: release records, snapshots, restore receipts,
images and `results.jsonl`) and the live folder (a short folder under /tmp holding the private home, its runtime and
every PostgreSQL cluster) must both be owner-only, and the private home must lie inside the live folder. Nothing is
written to the caller's installation; the Builds are read from the registry named on the command line.

Phases, in order (IMP-0.11, IMP-0.16, IMP-0.18): `baseline` (8.1), `upgrade2` (8.2), `upgrade3` (8.3 and 8.4),
`revision3` (8.5) and `reserved` (8.6). `--until <phase>` stops after that phase. Every chat is fictional, and no
result line holds chat text.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

PHASES = ("baseline", "upgrade2", "upgrade3", "revision3", "reserved")
PG = Path("/opt/homebrew/opt/postgresql@17/bin")
DATABASE = "arbol"
ROLE = "arbol"
PORT = 5432
LEDGER = ("arbol_schema_migrations", "arbol_schema_upgrades")
ROUTE = {"driver": "journey-fixture", "subscription": "private-fixture"}
TRUNK_CHECKOUT = Path.home() / "repos/sylvan-stack/arbol-trunk/trunks/trivial"
ARBOL_CHECKOUT = Path.home() / "repos/sylvan-stack/arbol"
DESIGN_CHECKOUT = Path.home() / "repos/sylvan-stack/arbol-design-system"


class DrillError(RuntimeError):
    """A drill precondition or check failed; the run folder keeps the evidence."""


def require(value: object, message: str) -> None:
    if not value:
        raise DrillError(message)


def owner_only(path: Path) -> Path:
    path = path.resolve(strict=True)
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077,
            f"{path} must be an owner-only folder.")
    return path


def private_folder(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    return path


def private_json(path: Path, value: Any) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, default=str)
        stream.write("\n")


# --- 4.1 Setup and observation -------------------------------------------------------------------------------------


@dataclass
class Cluster:
    """A socket-only PostgreSQL 17 cluster in the live folder; its role is the cluster's administrator."""

    base: Path

    @property
    def socket(self) -> Path:
        return self.base / "socket"

    @property
    def data(self) -> Path:
        return self.base / "data"

    @property
    def server_address(self) -> str:
        return f"postgresql://{ROLE}@{quote(str(self.socket), safe='')}:{PORT}"

    def environment(self) -> dict[str, str]:
        environment = {key: value for key, value in os.environ.items() if not key.startswith(("PG", "ARBOL_"))}
        environment.setdefault("LC_ALL", "C.UTF-8")
        return environment

    def create(self, *, database: bool) -> Cluster:
        private_folder(self.base)
        private_folder(self.socket)
        log = self.base / "initdb.log"
        with log.open("wb") as stream:
            subprocess.run([str(PG / "initdb"), "-D", str(self.data), "-U", ROLE, "-A", "trust", "--no-locale",
                            "-E", "UTF8"], check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=60,
                           env=self.environment())
        self.start()
        if database:
            subprocess.run([str(PG / "createdb"), "-h", str(self.socket), "-p", str(PORT), "-U", ROLE, DATABASE],
                           check=True, capture_output=True, timeout=30, env=self.environment())
        return self

    def start(self) -> None:
        options = f"-k {shlex.quote(str(self.socket))} -h '' -p {PORT} -F"
        subprocess.run([str(PG / "pg_ctl"), "-D", str(self.data), "-o", options, "-l", str(self.base / "postgres.log"),
                        "-w", "-t", "60", "start"], check=True, capture_output=True, timeout=90,
                       env=self.environment())

    def stop(self) -> None:
        if (self.data / "postmaster.pid").exists():
            subprocess.run([str(PG / "pg_ctl"), "-D", str(self.data), "-m", "fast", "-w", "-t", "60", "stop"],
                           check=False, capture_output=True, timeout=90, env=self.environment())

    def psql(self, sql: str, *, database: str = DATABASE) -> str:
        result = subprocess.run([str(PG / "psql"), "-X", "-At", "-v", "ON_ERROR_STOP=1", "-h", str(self.socket),
                                 "-p", str(PORT), "-U", ROLE, "-d", database], input=sql.encode(), capture_output=True,
                                timeout=60, env=self.environment())
        if result.returncode:
            raise DrillError(f"psql refused: {result.stderr.decode(errors='replace').strip()}")
        return result.stdout.decode()

    def value(self, sql: str) -> Any:
        return json.loads(self.psql(sql))


def image(cluster: Cluster) -> dict[str, Any]:
    """An independent image of the database, read with psql: every table's rows in key order, the ledger tables
    apart, the database OID, and the functions and triggers of `public`."""
    tables = cluster.psql("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1").split()
    rows: dict[str, Any] = {}
    for table in tables:
        keys = cluster.psql(
            "SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY k.n) FROM pg_index i "
            "CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, n) "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum "
            f"WHERE i.indrelid = 'public.{table}'::regclass AND i.indisprimary").strip()
        order = keys or "1"
        rows[table] = cluster.value(
            f"SELECT coalesce(json_agg(row_to_json(t) ORDER BY {order}), '[]'::json) FROM public.{table} t")
    return {
        "databaseOid": int(cluster.psql("SELECT oid FROM pg_database WHERE datname = current_database()")),
        "tables": {name: value for name, value in rows.items() if name not in LEDGER},
        "ledger": {name: rows.get(name, []) for name in LEDGER},
        "functions": cluster.value(
            "SELECT coalesce(json_agg(json_build_object('name', p.proname, 'sourceMd5', md5(p.prosrc)) "
            "ORDER BY p.proname), '[]'::json) FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace"),
        "triggers": cluster.value(
            "SELECT coalesce(json_agg(json_build_object('name', t.tgname, 'table', c.relname, "
            "'function', p.proname) ORDER BY t.tgname), '[]'::json) FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_proc p ON p.oid = t.tgfoid "
            "WHERE NOT t.tgisinternal AND c.relnamespace = 'public'::regnamespace"),
    }


class Drill:
    def __init__(self, options: argparse.Namespace) -> None:
        self.source = options.source.resolve(strict=True)
        self.run = owner_only(options.run)
        self.live = owner_only(options.live)
        require(self.live.is_relative_to(Path("/private/tmp")) and not any(self.live.iterdir()),
                "The live folder must be a new, empty folder under /tmp.")
        require(not self.run.is_relative_to(self.live) and not self.live.is_relative_to(self.run),
                "The run folder and the live folder must be separate.")
        self.out = private_folder(self.run / f"drill-{time.strftime('%Y%m%dT%H%M%S')}")
        self.results = self.out / "results.jsonl"
        self.registry = owner_only(options.registry)
        self.prior = self.build(options.prior, "arbol")
        self.upgrade = self.build(options.upgrade, "arbol")
        self.trunk = self.build(options.trunk, "arbol-trunk/trivial")
        self.python = self.source / ".venv/bin/python"
        self.home = private_folder(self.live / "home")
        require(self.home != Path.home().resolve() and self.home.is_relative_to(self.live),
                "The private home must lie inside the live folder.")
        self.runtime = self.home / "Library/Application Support/Arbol/runtime"
        self.bin = self.home / ".local/bin"
        self.settings = self.home / ".arbol"
        self.work = private_folder(self.live / "work")
        self.control = private_folder(self.live / "driver-control")
        for folder in (self.runtime, self.bin, self.settings):
            folder.mkdir(mode=0o700, parents=True)
        self.cluster = Cluster(self.live / "source")
        self.restores = 0
        self.chats: dict[str, str] = {}
        self.exchanges: dict[str, str] = {}
        self.sessions: dict[str, str] = {}
        self.releases: dict[str, tuple[Path, str]] = {}
        self.until = options.until

    def build(self, folder: Path, component: str) -> Any:
        sys.path[:0] = [str(self.source / relative) for relative in ("", "src", "tests", "scripts", "database")]
        from tools.trunk_runtime_journeys import Build

        folder = folder.resolve(strict=True)
        require(folder.is_relative_to(self.registry), f"The {component} Build must come from the private registry.")
        return Build.checked(folder, component)

    def environment(self) -> dict[str, str]:
        environment = self.cluster.environment()
        environment.update({"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin"})
        return environment

    def record(self, step: str, check: str, outcome: bool | str, **detail: Any) -> None:
        line = {"step": step, "check": check,
                "outcome": outcome if isinstance(outcome, str) else ("passed" if outcome else "failed"),
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **detail}
        with self.results.open("a") as stream:
            stream.write(json.dumps(line, sort_keys=True, default=str) + "\n")
        os.chmod(self.results, 0o600)
        print(json.dumps(line, default=str), flush=True)

    def checked(self, step: str, check: str, value: bool, **detail: Any) -> None:
        self.record(step, check, value, **detail)
        require(value, f"{step} {check} failed.")

    def save_image(self, name: str) -> dict[str, Any]:
        value = image(self.cluster)
        private_json(self.out / f"image-{name}.json", value)
        return value

    def prepare(self) -> None:
        """The source cluster, its settings, the launchers and the fixture Driver of the private home."""
        self.cluster.create(database=True)
        private_json(self.settings / "database.json", {"address": self.cluster.server_address, "database": DATABASE})
        from arbol_builds.service import write_launcher

        for component in ("arbol", "arbol-trunk"):
            write_launcher(str(self.bin), str(self.registry), component, sys.executable)
        driver = self.bin / "arbol-journey-fixture-driver"
        command = shlex.join([sys.executable, "-I", "-B", str(self.source / "tools/backend_fault_driver.py"),
                              "--control-dir", str(self.control)])
        driver.write_text(f'#!/bin/sh\nexec {command} "$@"\n')
        driver.chmod(0o700)
        self.stage_tools(self.prior)
        status = self.tool("database/migrate_schema.py", "--socket", str(self.cluster.socket), "--port", str(PORT),
                           "--user", ROLE, "--database", DATABASE, "initialize", "--authorize-empty")
        self.checked("8.1", "baseline-initialized", status == {"status": "ready", "revision": 1,
                                                               "compatibilityVersion": 1}, status=status)

    def stage_tools(self, build: Any) -> None:
        """The installation's shared schema tools, from the release being installed, as `arbol-builds` installs
        them; every Build reads the migration manifest here. They are never downgraded."""
        place = self.bin / ".arbol-builds/schema"
        if place.exists():
            shutil.rmtree(place)
        shutil.copytree(build.folder / "runtime/site-packages", place)
        database = build.folder / "database"
        migrations = tomllib.loads((database / "migrations.toml").read_text())["migrations"]
        for name in ("migrate_schema.py", "database_server.py", "migrations.toml", *(m["file"] for m in migrations)):
            shutil.copy2(database / name, place / name)
        self.record("8", "schema-tools-staged", True, build=build.number, revisions=len(migrations))

    def tool(self, script: str, *arguments: str, expect_json: bool = True) -> Any:
        result = subprocess.run([str(self.python), "-B", str(self.source / script), *arguments],
                                cwd=self.source, env={**self.environment(), "PYTHONPATH": str(self.source / "src")},
                                capture_output=True, timeout=300)
        output = result.stdout.decode().strip()
        if result.returncode:
            raise DrillError(f"{script} {arguments[-1] if arguments else ''} refused: "
                             f"{(output or result.stderr.decode(errors='replace')).strip()[-600:]}")
        return json.loads(output.splitlines()[-1]) if expect_json else output

    @property
    def source_identity(self) -> dict[str, Any]:
        oid = int(self.cluster.psql("SELECT oid FROM pg_database WHERE datname = current_database()"))
        return {"host": str(self.cluster.socket), "port": PORT, "database": DATABASE, "databaseOid": oid}

    # --- 4.2 The fenced upgrade ------------------------------------------------------------------------------------

    def context(self, build: Any) -> Any:
        from arbol_backend.exchange_context import Context
        from arbol_backend.model import identity, parse

        return Context(identity(build.folder, parse(["backend"]), home=self.home))

    def release(self, label: str, build: Any) -> tuple[Path, str]:
        """A release record by `recovery_release.py`, from a private inventory of the Builds the release selects."""
        if label in self.releases:
            return self.releases[label]
        folder = private_folder(self.out / f"release-{label}")
        checkout = ARBOL_CHECKOUT if build is self.prior else Path(
            json.loads((build.folder / "build.json").read_text())["source"]["repository"])
        inventory = {
            "kind": "current",
            "builds": [{"directory": str(build.folder), "checkout": str(checkout)},
                       {"directory": str(self.trunk.folder), "checkout": str(TRUNK_CHECKOUT)}],
            "configuration": {"installation": str(self.settings / "database.json")},
            "designCheckout": str(DESIGN_CHECKOUT),
        }
        private_json(folder / "inventory.json", inventory)
        digest = self.tool("database/recovery_release.py", "--inventory", str(folder / "inventory.json"),
                           "--output", str(folder / "release"))["releaseSha256"]
        self.releases[label] = (folder / "release", digest)
        return self.releases[label]

    def verified(self, label: str) -> Callable[[], str]:
        from recovery_release import verify_release

        folder, _ = self.releases[label]
        return lambda: verify_release(folder)[1]

    def open_admission(self, build: Any, label: str, schema: dict[str, int]) -> None:
        """First activation: close admission, freeze, then reopen to the verified release."""
        from arbol_backend.exchange_drain import begin_maintenance, freeze, reopen

        _, digest = self.release(label, build)
        source = self.source_identity
        session = begin_maintenance(source, runtime=self.runtime)
        freeze(self.context(build), source, session)
        reopen(self.context(build), source, session, release=digest, schema=schema, verify_release=self.verified(label))

    def maintenance(self, prior: Any) -> tuple[dict[str, Any], str]:
        from arbol_backend.exchange_drain import begin_maintenance, freeze

        source = self.source_identity
        session = begin_maintenance(source, runtime=self.runtime)
        freeze(self.context(prior), source, session)
        return source, session

    def fenced_upgrade(self, step: str, *, prior: tuple[Any, str], upgrade: tuple[Any, str], target: int,
                       held: tuple[dict[str, Any], str] | None = None) -> dict[str, Any]:
        """The fenced upgrade of `database/README.md`: release records, the exclusive session, the snapshot, the
        verified isolated restore, `migrate_schema.py upgrade`, then reopening to the upgrade release."""
        from arbol_backend.exchange_drain import reopen

        prior_folder, prior_digest = self.release(prior[1], prior[0])
        upgrade_folder, upgrade_digest = self.release(upgrade[1], upgrade[0])
        source, session = held or self.maintenance(prior[0])
        if upgrade[0] is not prior[0]:
            self.stage_tools(upgrade[0])
        attempt = private_folder(self.out / f"upgrade-{target}")
        self.tool("database/recovery.py", "--database", DATABASE, "--socket", str(self.cluster.socket), "--port",
                  str(PORT), "--user", ROLE, "snapshot", "--session", session, "--release", str(prior_folder),
                  "--output", str(attempt / "snapshot"))
        self.restores += 1
        restore = Cluster(self.live / f"restore-{self.restores}").create(database=False)
        try:
            self.tool("database/recovery.py", "--database", DATABASE, "--socket", str(restore.socket), "--port",
                      str(PORT), "--user", ROLE, "restore", "--snapshot", str(attempt / "snapshot"), "--output",
                      str(attempt / "restore-attempt"))
        finally:
            restore.stop()
        receipt = json.loads((attempt / "restore-attempt/restore.json").read_text())
        self.checked(step, "isolated-restore-verified", receipt.get("status") == "verified",
                     snapshotSha256=receipt.get("snapshotSha256"), targetCluster=receipt.get("targetCluster"))
        status = self.tool("database/migrate_schema.py", "--socket", str(self.cluster.socket), "--port", str(PORT),
                           "--user", ROLE, "--database", DATABASE, "upgrade", "--target-revision", str(target),
                           "--maintenance-session", session, "--prior-release", prior_digest, "--upgrade-release",
                           upgrade_digest, "--snapshot-dir", str(attempt / "snapshot"), "--restore-receipt",
                           str(attempt / "restore-attempt/restore.json"))
        schema = {"revision": target, "compatibilityVersion": 1}
        self.checked(step, "upgrade-ready", status == {"status": "ready", **schema}, status=status)
        reopen(self.context(upgrade[0]), source, session, release=upgrade_digest, schema=schema,
               verify_release=self.verified(upgrade[1]))
        self.record(step, "reopened", True, build=upgrade[0].number, release=upgrade_digest, prior=prior_digest,
                    session=session)
        return {"session": session, "prior": prior_digest, "upgrade": upgrade_digest}
