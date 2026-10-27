"""The checks' database and Drivers for Subscriptions Vigor: a private cluster with the Vigor tables and stand-in launchers.

The database is made as `tests/backend/support.py` makes one, with the contract's chat tables, and gets the Vigor
tables from `tests/radar/layout.sql`, a copy of what both Roots' own layouts carry (SGM-1.10). The stand-in Drivers of
`drivers` answer `subscriptions list` and `subscriptions usage <id>` each with their own reply and record every call.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from backend.support import PG, Cluster, Frame  # noqa: E402

from arbol_backend.database import Database  # noqa: E402
from arbol_backend.model import identity, parse  # noqa: E402
from arbol_radar.model import Subscription  # noqa: E402
from arbol_radar.records import Records  # noqa: E402
from radar.support import CLAUDE, CODEX, FETCHED, KIMI, ZAI, claude, codex, kimi  # noqa: E402

LAYOUT = ROOT / "tests/radar/layout.sql"
TABLES = ("vigor_profiles", "vigor_reports", "vigor_results")

# A stand-in Driver that answers by the command it was given: `behavior.json` maps the launcher's name to a reply per
# command, `list` or `usage <id>`, each with `output`, `raw` or `status`; every call is appended to `calls.jsonl`.
STANDIN = """import json,os,sys
from pathlib import Path
launcher=Path(sys.argv.pop(1))
base=launcher.parent
name=launcher.name
args=sys.argv[1:]
record={'program':name,'args':args,'pid':os.getpid(),'pgid':os.getpgrp(),
        'path':os.environ['PATH'],'cwd':os.getcwd(),'home':os.environ.get('HOME'),'pgOverrides':[k for k in os.environ if k.startswith('PG')]}
fd=os.open(base/'calls.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
os.write(fd,(json.dumps(record)+'\\n').encode());os.close(fd)
command=' '.join(args[1:] if args[:1]==['subscriptions'] else args)
config=json.loads((base/'behavior.json').read_text()).get(name,{}).get(command)
if config is None:print(json.dumps({'error':{'code':'invalid_input','message':'no stand-in reply for '+command}}),flush=True);sys.exit(1)
if config.get('raw') is not None:print(config['raw'],flush=True)
else:print(json.dumps(config.get('output',{})),flush=True)
sys.exit(config.get('status',0))
"""


def drivers(frame: Frame, behavior: dict[str, Any]) -> None:
    """Give the frame's three Driver launchers replies by command, in place of its one reply per launcher."""
    frame.behavior = behavior
    frame.configure()
    for name in ("arbol-claude-driver", "arbol-codex-driver", "arbol-pi-driver"):
        path = frame.bin / name
        path.write_text(
            "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -I -c " + shlex.quote(STANDIN) + ' "$0" "$@"\n'
        )
        path.chmod(0o700)


def usage(
    windows: list[dict[str, Any]], *, fetched: str = FETCHED, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A `UsageReport` as a Driver stores it with the Subscription (DRV-1.18)."""
    value: dict[str, Any] = {"outcome": "ok", "fetchedAt": fetched, "windows": windows}
    if extra is not None:
        value["extra"] = extra
    return value


def record(subscription: Subscription, last_usage: dict[str, Any] | None = None, **more: Any) -> dict[str, Any]:
    """A Subscription record as `subscriptions list` delivers it (DRV-1, `Subscription`), never a secret."""
    value: dict[str, Any] = {
        "id": subscription.id,
        "family": subscription.family,
        "label": subscription.id.title(),
        "auth": "vendor_login",
        "state": "signed_in",
        "settings": {},
        "createdAt": "2026-10-01T00:00:00Z",
        "updatedAt": "2026-10-26T09:55:00Z",
        **more,
    }
    if last_usage is not None:
        value["lastUsage"] = last_usage
    return value


LISTING = {
    "arbol-claude-driver": {"output": [record(CLAUDE, usage(claude(), extra={"isUsingOverage": False}))]},
    "arbol-codex-driver": {"output": [record(CODEX, usage(codex()))]},
    "arbol-pi-driver": {"output": [record(KIMI, usage(kimi())), record(ZAI)]},
}


class RecordFixture(unittest.IsolatedAsyncioTestCase):
    """A private cluster with the chat tables and the Vigor tables, a private Root folder and stand-in launchers."""

    cluster: Cluster

    @classmethod
    def setUpClass(cls) -> None:
        cls.cluster = Cluster()
        try:
            subprocess.run(
                [
                    str(PG / "psql"),
                    "-X",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-h",
                    str(cls.cluster.socket),
                    "-p",
                    "5432",
                    "-U",
                    "bkd",
                    "-d",
                    "arbol_test",
                ],
                input=LAYOUT.read_bytes(),
                capture_output=True,
                check=True,
                timeout=10,
            )
        except BaseException:
            cls.cluster.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.cluster.close()

    async def asyncSetUp(self) -> None:
        self.frame = Frame()
        self.selected = identity(ROOT, parse(self.frame.options(self.cluster.address)), home=self.frame.home)
        self.db = Database(self.selected)
        self.records = Records(self.db)
        await self.db.execute("TRUNCATE vigor_results, vigor_reports, vigor_profiles")

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.frame.close()

    async def count(self, table: str) -> int:
        rows = await self.db.execute(f"SELECT count(*) FROM {table}")
        return int(rows[0][0])

    def vigor(self, *extra: str) -> list[str]:
        """The command line of `arbol vigor` against the check's Root, launchers and database."""
        words = self.frame.options(self.cluster.address)
        words[words.index("backend")] = "vigor"
        return words + list(extra)
