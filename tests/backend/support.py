"""Own every file, launcher and PostgreSQL process used by the backend checks."""

from __future__ import annotations

import json
import os
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
BUILD = json.loads((ROOT / "build.json").read_text()) if (ROOT / "build.json").exists() else {}
TEST_ROOT = BUILD.get("root", "t1")
TEST_BUILD = BUILD.get("build", "0")
PG = Path("/opt/homebrew/opt/postgresql@17/bin")
if not PG.is_dir():
    PG = Path("/usr/local/opt/postgresql@17/bin")

STANDIN = """import json,os,signal,sys,time
from pathlib import Path
launcher=Path(sys.argv.pop(1))
base=launcher.parent
name=launcher.name
config=json.loads((base/'behavior.json').read_text()).get(name,{})
record={'program':name,'args':sys.argv[1:],'pid':os.getpid(),'pgid':os.getpgrp(),
        'path':os.environ['PATH'],'cwd':os.getcwd(),'home':os.environ.get('HOME'),'pgOverrides':[k for k in os.environ if k.startswith('PG')]}
fd=os.open(base/'calls.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
os.write(fd,(json.dumps(record)+'\\n').encode());os.close(fd)
if config.get('fork'):
 child=os.fork()
 if child==0:
  (base/'descendant.pid').write_text(str(os.getpid()))
  while True:time.sleep(1)
if config.get('ignoreTerm'):signal.signal(signal.SIGTERM,signal.SIG_IGN)
time.sleep(config.get('sleep',0))
if config.get('raw') is not None:print(config['raw'],flush=True)
else:print(json.dumps(config.get('output',[] if name=='arbol-roots' else {})),flush=True)
sys.exit(config.get('status',0))
"""


class Frame:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ab-", dir="/tmp")
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.root = self.base / "root space"
        self.bin = self.base / "bin"
        self.settings = self.base / "settings"
        for folder in (self.home, self.root, self.bin, self.settings):
            folder.mkdir(mode=0o700)
        self.record = {
            "root": TEST_ROOT,
            "name": "Test Root",
            "status": "preparing",
            "database": "arbol_test",
            "createdAt": "2026-10-27T06:00:00Z",
            "rootContract": 1,
            "app": "0",
        }
        self.save_root()
        self.behavior: dict[str, Any] = {}
        self.configure()
        for name in ("arbol-root", "arbol-roots", "arbol-claude-driver", "arbol-codex-driver", "arbol-pi-driver"):
            path = self.bin / name
            path.write_text(
                "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -I -c " + shlex.quote(STANDIN) + ' "$0" "$@"\n'
            )
            path.chmod(0o700)
        self.children: list[subprocess.Popen[bytes]] = []

    def save_root(self) -> None:
        (self.root / "root.json").write_text(json.dumps(self.record))

    def configure(self) -> None:
        (self.bin / "behavior.json").write_text(json.dumps(self.behavior))

    def calls(self) -> list[dict[str, Any]]:
        path = self.bin / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def options(self, database: str | None = None) -> list[str]:
        return [
            "--root",
            TEST_ROOT,
            "backend",
            "--root-dir",
            str(self.root),
            "--bin-dir",
            str(self.bin),
            "--settings-dir",
            str(self.settings),
            "--database",
            database or "postgresql://bkd@%2Ftmp%2Fabsent-backend-check/arbol_test",
        ]

    def start(self, *, args: list[str] | None = None, executable: list[str] | None = None) -> subprocess.Popen[bytes]:
        program = executable or [sys.executable, "-I", "-B", str(ROOT / "bin/arbol_entry.py")]
        child = subprocess.Popen(
            program + (args if args is not None else self.options()),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "HOME": str(self.home)},
            start_new_session=True,
        )
        self.children.append(child)
        return child

    def line(self, child: subprocess.Popen[bytes], seconds: float = 3) -> dict[str, Any]:
        assert child.stdout is not None
        if not select.select([child.stdout], [], [], seconds)[0]:
            raise AssertionError("No startup line within check deadline.")
        value: object = json.loads(child.stdout.readline())
        assert isinstance(value, dict)
        return value

    def close(self) -> None:
        for child in self.children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
            child.communicate(timeout=3)
        self.temp.cleanup()


def cluster_environment() -> dict[str, str]:
    """The inherited environment with a locale set.

    Without `LANG` or `LC_ALL` the postmaster on macOS becomes multithreaded during startup and exits, with the hint
    to set `LC_ALL`; sessions of the Claude desktop app carry no locale. The cluster is made with `--no-locale`, so any
    set locale serves, and one the session has is kept.
    """
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    if "LC_ALL" not in environment and "LANG" not in environment:
        environment["LC_ALL"] = "C.UTF-8"
    return environment


class Cluster:
    database = "arbol_test"
    role = "bkd"
    port = 5432

    def __init__(self, *, baseline: Path | None = None) -> None:
        if not (PG / "initdb").is_file():
            raise RuntimeError("The private PostgreSQL checks require installed PostgreSQL 17 tools.")
        self.temp = tempfile.TemporaryDirectory(prefix="ab-pg-", dir="/tmp")
        self.base = Path(self.temp.name).resolve()
        self.env = {**cluster_environment(), "HOME": str(self.base)}
        self.socket = self.base / "socket"
        self.socket.mkdir(mode=0o700)
        self.data = self.base / "data"
        self.log = self.base / "postgres.log"
        self.child: subprocess.Popen[bytes] | None = None
        self.stream = self.log.open("wb")
        try:
            subprocess.run(
                [str(PG / "initdb"), "-D", str(self.data), "-U", "bkd", "-A", "trust", "--no-locale", "-E", "UTF8"],
                check=True,
                stdout=self.stream,
                stderr=subprocess.STDOUT,
                timeout=20,
                env=self.env,
            )
            self.child = subprocess.Popen(
                [str(PG / "postgres"), "-D", str(self.data), "-k", str(self.socket), "-h", "", "-p", "5432", "-F"],
                stdin=subprocess.DEVNULL,
                stdout=self.stream,
                stderr=subprocess.STDOUT,
                env=self.env,
                start_new_session=True,
            )
            for _ in range(200):
                if (
                    subprocess.run(
                        [str(PG / "pg_isready"), "-h", str(self.socket), "-p", "5432", "-U", "bkd"],
                        capture_output=True,
                        timeout=2,
                        env=self.env,
                    ).returncode
                    == 0
                ):
                    break
                if self.child.poll() is not None:
                    raise RuntimeError("Private PostgreSQL exited during startup.")
                time.sleep(0.05)
            else:
                raise RuntimeError("Private PostgreSQL startup deadline.")
            subprocess.run(
                [str(PG / "createdb"), "-h", str(self.socket), "-p", "5432", "-U", "bkd", "arbol_test"],
                capture_output=True,
                check=True,
                timeout=5,
                env=self.env,
            )
            if baseline is not None:
                self.initialize(baseline)
            else:
                # Historical source-only fixtures may still request the Root layout.
                fixture = ROOT / "tests/backend/layout.sql"
                if not fixture.is_file():
                    fixture = ROOT.parent / "arbol-root/contract/1/layout.sql"
                self.layout = fixture.read_bytes()
                self.sql(self.layout)
        except BaseException:
            self.close()
            raise

    @property
    def address(self) -> str:
        return f"{self.server_address}/{self.database}"

    @property
    def server_address(self) -> str:
        return f"postgresql://{self.role}@{quote(str(self.socket), safe='')}:{self.port}"

    def sql(self, statement: bytes) -> bytes:
        return subprocess.run([str(PG / "psql"), "-X", "-At", "-v", "ON_ERROR_STOP=1", "-h", str(self.socket),
                               "-p", str(self.port), "-U", self.role, "-d", self.database],
                              input=statement, capture_output=True, check=True, timeout=10, env=self.env).stdout

    def initialize(self, package: Path) -> None:
        migration = package / "database/migrate_schema.py"
        # The packaged interpreter has its dependency directory outside sys.path.
        bootstrap = ("import runpy, sys; from pathlib import Path; "
                     "path = Path(sys.argv.pop(1)); sys.path[:0] = "
                     "[str(path.parent), str(path.parents[1] / 'runtime/site-packages')]; "
                     "runpy.run_path(str(path), run_name='__main__')")
        arguments = [sys.executable, "-I", "-B", "-c", bootstrap, str(migration), "--socket", str(self.socket),
                     "--port", str(self.port), "--user", self.role, "--database", self.database]
        for action in (["initialize", "--authorize-empty"], ["status"]):
            result = subprocess.run([*arguments, *action], capture_output=True, timeout=20, env=self.env)
            if result.returncode or json.loads(result.stdout) != {"status": "ready", **BASELINE}:
                raise RuntimeError(f"Private canonical schema did not report readiness after {action[0]}: "
                                   f"{result.stdout.decode(errors='replace').strip()}")

    def close(self) -> None:
        if self.child is not None:
            if self.child.poll() is None:
                # Only this exact child, on this cluster's unique private data folder.
                subprocess.run(
                    [str(PG / "pg_ctl"), "-D", str(self.data), "-m", "immediate", "-w", "-t", "5", "stop"],
                    stdout=self.stream,
                    stderr=subprocess.STDOUT,
                    timeout=7,
                    check=False,
                    env=self.env,
                )
            self.child.wait(timeout=5)
        self.stream.close()
        self.temp.cleanup()


BASELINE = {"revision": 1, "compatibilityVersion": 1}


class SingleInstallation:
    """Canonical database and one private home/runtime/bin for the backend and its children."""

    def __init__(self, package: Path = ROOT) -> None:
        self.package = package.resolve()
        self.cluster = Cluster(baseline=self.package)
        try:
            base = self.cluster.base
            self.home, self.runtime, self.bin, self.work = (base / name for name in ("home", "run", "bin", "work"))
            self.settings = self.home / ".arbol"
            for folder in (self.home, self.runtime, self.bin, self.work, self.settings):
                folder.mkdir(mode=0o700)
            (self.settings / "database.json").write_text(json.dumps({"address": self.cluster.server_address,
                                                                   "database": self.cluster.database}))
            self.env = {**self.cluster.env, "HOME": str(self.home),
                        "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", os.defpath)}
        except BaseException:
            self.close()
            raise

    def options(self) -> list[str]:
        return ["--runtime-dir", str(self.runtime), "--bin-dir", str(self.bin), "--settings-dir", str(self.settings)]

    @property
    def endpoint(self) -> Path:
        return self.runtime / "backend.sock"

    def open_admission(self) -> None:
        """Run off the asyncio event loop: the operator gate runs its own SQL probes."""
        from arbol_backend.exchange_context import Context
        from arbol_backend.exchange_drain import begin_maintenance, freeze, reopen
        from arbol_backend.model import identity, parse

        cluster = self.cluster
        configured = identity(self.package, parse(["backend", *self.options()]), home=self.home)
        context = Context(configured)
        oid = int(cluster.sql(b"SELECT oid FROM pg_database WHERE datname = current_database()"))
        source: dict[str, str | int] = {"host": str(cluster.socket), "port": cluster.port,
                                       "database": cluster.database, "databaseOid": oid}
        receipt = self.package / "package-manifest.json"
        if configured.build == "0":
            receipt = self.package / "database/migrations.toml"

        def release() -> str:
            return sha256(receipt.read_bytes()).hexdigest()

        session = begin_maintenance(source, runtime=self.runtime)
        freeze(context, source, session)
        reopen(context, source, session, release=release(), schema=BASELINE, verify_release=release)

    def close(self) -> None:
        self.cluster.close()
