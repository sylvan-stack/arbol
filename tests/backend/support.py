"""Own every file, launcher and PostgreSQL process; never touch a retained Root."""

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
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
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
        'path':os.environ['PATH'],'cwd':os.getcwd()}
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
            "root": "t1",
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
            "t1",
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


class Cluster:
    def __init__(self) -> None:
        if not (PG / "initdb").is_file():
            raise RuntimeError("The private PostgreSQL checks require installed PostgreSQL 17 tools.")
        self.temp = tempfile.TemporaryDirectory(prefix="ab-pg-", dir="/tmp")
        self.base = Path(self.temp.name)
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
            )
            self.child = subprocess.Popen(
                [str(PG / "postgres"), "-D", str(self.data), "-k", str(self.socket), "-h", "", "-p", "5432", "-F"],
                stdin=subprocess.DEVNULL,
                stdout=self.stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            for _ in range(200):
                if (
                    subprocess.run(
                        [str(PG / "pg_isready"), "-h", str(self.socket), "-p", "5432", "-U", "bkd"],
                        capture_output=True,
                        timeout=2,
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
            )
            fixture = ROOT / "tests/backend/layout.sql"
            if not fixture.is_file():
                fixture = Path.home() / "repos/sylvan-stack/readonly/arbol-root/contract/1/layout.sql"
            self.layout = fixture.read_bytes()
            subprocess.run(
                [
                    str(PG / "psql"),
                    "-X",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-h",
                    str(self.socket),
                    "-p",
                    "5432",
                    "-U",
                    "bkd",
                    "-d",
                    "arbol_test",
                ],
                input=self.layout,
                capture_output=True,
                check=True,
                timeout=10,
            )
        except BaseException:
            self.close()
            raise

    @property
    def address(self) -> str:
        from urllib.parse import quote

        return "postgresql://bkd@" + quote(str(self.socket), safe="") + "/arbol_test"

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
                )
            self.child.wait(timeout=5)
        self.stream.close()
        self.temp.cleanup()
