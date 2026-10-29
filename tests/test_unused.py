# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Unused pruning and nonblocking process-use protection, in private registries only."""
import subprocess


import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any

from test_builds import Fixture

from arbol_builds.unused import Usage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from test_builds import TRUNK_PROGRAM, Fixture, document, finish, first_line
from arbol_builds.launcher import open_use_guard
from unused_drill import drill  # noqa: E402


class MixedRegistry(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


class UseGuards(unittest.TestCase):
    def root(self, f: Fixture) -> None:
        place = Path(f.home) / 'Library/Application Support/Arbol/roots/sapling'
        place.mkdir(parents=True)
        (place / 'root.json').write_text(json.dumps({'root':'sapling','status':'working','rootContract':1,
                                                    'createdAt':'2026-10-26T09:00:00.000Z'}))


class Settings(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


class ManagerSnapshots(unittest.TestCase):
    def prepare(self, names: tuple[str, ...] = ('sapling',)) -> Fixture:
        import shlex
        import sys
        f = Fixture(self,'arbol-root')
        replies = {}
        for name in names:
            place = Path(f.home,'Library/Application Support/Arbol/roots',name)
            place.mkdir(parents=True)
            (place / 'root.json').write_text(json.dumps({'root':name,'status':'preparing','rootContract':1,
                                                        'createdAt':'2026-10-26T09:00:00.000Z'}))
            built = f.build('--root',name)
            replies[name] = {'root':name,'rootBuild':built['build'],'rootPackageVersion':'1.2.3',
                             'exchanges':[],'unreadable':[]}
        Path(f.home,'replies.json').write_text(json.dumps(replies))
        script = Path(f.home,'manager.py')
        script.write_text('''import json,os,sys
from pathlib import Path
from typing import Any
home=Path(os.environ['HOME']); root=sys.argv[2]
with (home/'manager-calls.jsonl').open('a') as out:
    out.write(json.dumps({'args':sys.argv[1:],'path':os.environ['PATH']})+'\\n')
print(json.dumps(json.loads((home/'replies.json').read_text())[root]))
''')
        launcher = Path(f.bin,'arbol-root')
        launcher.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' -I -B '+shlex.quote(str(script))+' "$@"\n')
        launcher.chmod(0o755)
        return f

    def exchange(self, root: str = 'sapling') -> dict[str, object]:
        return {'root':root,'exchange':'7f3a2c1e-4b5d-4e6f-8a9b-0c1d2e3f4a5b',
                'chat':'c3d4e5f6-0718-4293-a4b5-c6d7e8f90a1b','trunk':'trivial','build':'1',
                'process':{'pid':123,'startedAt':'2026-10-26T09:00:00.000Z','alive':False},'state':'unsaved',
                'signsOfLife':{'heartbeat':4,'waitingFor':'database','since':'2026-10-26T09:00:00.000Z'}}

    def snapshot(self, f: Fixture) -> Usage:
        from unittest import mock

        from arbol_builds.config import Locations
        from arbol_builds.unused import usage_snapshot
        with mock.patch.dict(os.environ,f.env()):
            return usage_snapshot(Locations(f.registry,f.bin))


class AgedRemoval(unittest.TestCase):
    CLOCK = 1793016000000.0  # 2026-10-26T12:00:00.000Z; every age assertion supplies this clock.

    def setting(self, f: Fixture, days: float = 1) -> None:
        path = Path(f.home,'.arbol/arbol-builds.json')
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'removeUnusedAfterDays':days}))

    def iso(self, stamp: float) -> str:
        from datetime import UTC, datetime
        return datetime.fromtimestamp(stamp/1000,UTC).isoformat(timespec='milliseconds').replace('+00:00','Z')

    def aged(self, f: Fixture, number: str, stamp: float | None = None) -> None:
        path = Path(f.path(number,'build.json'))
        value = json.loads(path.read_text())
        stamp = self.CLOCK-2*86_400_000 if stamp is None else stamp
        value['startedAt'] = self.iso(stamp-1000)
        if value['status'] != 'building':
            value['finishedAt'] = self.iso(stamp)
        path.write_text(json.dumps(value))

    def prune(self, f: Fixture, clock: float | None = None) -> list[dict[str, Any]]:
        from unittest import mock

        from arbol_builds.config import Locations
        from arbol_builds.unused import prune_unused
        with mock.patch.dict(os.environ,f.env()):
            return prune_unused(Locations(f.registry,f.bin),now_ms=self.CLOCK if clock is None else clock)


# Archived complete imports; restore needed names in their original scope, not at this file tail.
