# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Runtime SQL selection and application use only private records and stand-ins."""

import hashlib
import json
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_roots  # noqa: E402

from arbol_roots.model import Places, save_record  # noqa: E402


def image(paths: Places, number: str = "1", root: str = "sapling", older: str | None = None,
          **changes: Any) -> Path:
    test_roots.build_record(paths, "arbol-root", number, root=root, **changes)
    folder = paths.registry / "arbol-root" / number
    (folder / "layout").mkdir()
    for name in ["chat-tables.sql", "root-tables.sql", *(["migrate.sql"] if older else [])]:
        (folder / "layout" / name).write_text("-- private SQL fixture\n")
    manifest = {"component":"arbol-root", "root":root, "build":number,
                "layout":{"root":root,"rootContract":1,"grewFrom":older},
                "files":{str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (folder / "layout").iterdir()}}
    (folder / "package-manifest.json").write_text(json.dumps(manifest))
    return folder


class Selection(unittest.TestCase):
    def setUp(self) -> None:
        self.paths = test_roots.database_fixture(self)
        self.record = test_roots.record()
        (self.paths.roots / "sapling").mkdir(parents=True)
        save_record(self.paths, self.record)


class Layout(unittest.TestCase):
    def setUp(self) -> None:
        self.paths = test_roots.database_fixture(self)
        self.record = test_roots.record(state="working")
        (self.paths.roots / "sapling").mkdir(parents=True)
        save_record(self.paths, self.record)
        self.folder = image(self.paths)


class Migration(unittest.TestCase):
    def setUp(self) -> None:
        self.paths = test_roots.database_fixture(self)
        self.record = {**test_roots.record("second"), "grewFrom":"sapling"}
        for record in [test_roots.record(state="working"), self.record]:
            (self.paths.roots / record["root"]).mkdir(parents=True)
            save_record(self.paths, record)
        self.folder = image(self.paths, root="second", older="sapling")
        client = test_roots.DATABASE_STAND_IN.replace(
            "'env': dict(os.environ)",
            "'env': dict(os.environ), 'cwd': os.getcwd(), 'mode': os.stat('.').st_mode & 511, 'pid': os.getpid()")
        client = client.replace("time.sleep(config.get('delay', 0))", """
migrating = kind == 'psql' and '--file' in sys.argv and sys.argv[sys.argv.index('--file')+1].endswith('migrate.sql')
if migrating:
    Path('private.copy').write_text('fictional copied rows')
time.sleep(config.get('delay', 0))""")
        client = client.replace("sys.exit(config.get('status', 0))",
                                "sys.exit(config.get('migrationStatus', 0) if migrating else config.get('status', 0))")
        Path(self.paths.psql).write_text(client)

    def calls(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in (self.paths.home / "calls.jsonl").read_text().splitlines()
                if json.loads(line)["kind"] == "psql"]


class InUseModes(unittest.TestCase):
    CHAT = "10000000-0000-4000-8000-000000000001"

    def setUp(self) -> None:
        self.paths = test_roots.database_fixture(self)
        self.record = {**test_roots.record("second",state="working"),"grewFrom":"sapling"}
        for record in [test_roots.record(state="working"),self.record]:
            (self.paths.roots/record["root"]).mkdir(parents=True)
            save_record(self.paths,record)
        self.folder = image(self.paths,root="second",older="sapling")
        self.capability()

    def capability(self) -> None:
        value = {"version":1,"modes":["check","chat"]}
        path = self.folder/"layout/migration-modes.json"
        path.write_text(json.dumps(value))
        manifest = json.loads((self.folder/"package-manifest.json").read_text())
        manifest["layout"]["migrationModes"] = value
        manifest["files"]["layout/migration-modes.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.folder/"package-manifest.json").write_text(json.dumps(manifest))

    def configure(self, value: Any, **extra: Any) -> None:
        (self.paths.home/"psql.json").write_text(json.dumps({"stdout":json.dumps(value),**extra}))

    def result(self, mode: str = "chat", action: str = "replaced") -> dict[str, Any]:
        if mode=="check":
            return {"mode":"check","fromRoot":"sapling","checked":2,"stale":[self.CHAT]}
        return {"mode":"chat","fromRoot":"sapling","chat":self.CHAT,"fromChat":self.CHAT,
                "resultChat":self.CHAT if action=="replaced" else "10000000-0000-4000-8000-000000000002",
                "action":action,"endedThrough":2,"snapshotAt":"2026-10-27T04:00:00+00:00"}


# Archived complete imports; restore needed names in their original scope, not at this file tail.
