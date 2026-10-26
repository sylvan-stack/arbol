"""Unused pruning and nonblocking process-use protection, in private registries only."""

import json
import os
import subprocess
import unittest
from pathlib import Path

from test_builds import TRUNK_PROGRAM, Fixture, document, finish, first_line

from arbol_builds.launcher import open_use_guard


class UseGuards(unittest.TestCase):
    def root(self, f: Fixture) -> None:
        place = Path(f.home) / 'Library/Application Support/Arbol/roots/sapling'
        place.mkdir(parents=True)
        (place / 'root.json').write_text(json.dumps({'root':'sapling','status':'working','rootContract':1,
                                                    'createdAt':'2026-10-26T09:00:00.000Z'}))

    def test_plain_root_and_trunk_exec_hold_use_until_the_process_exits(self) -> None:
        """builds.use-guard-exec"""
        for component in ['sample','arbol-root','arbol-trunk/trivial']:
            with self.subTest(component=component):
                f = Fixture(self,component)
                if component == 'arbol-trunk/trivial':
                    Path(f.repo,'program.py').write_text(TRUNK_PROGRAM)
                if component in ['arbol-root','arbol-trunk/trivial']:
                    self.root(f)
                args = ['--root','sapling'] if component == 'arbol-root' else []
                f.build(*args)
                f.build(*args)
                launcher = 'arbol-trunk' if component == 'arbol-trunk/trivial' else component
                prefix = ['--root','sapling','trivial'] if component == 'arbol-trunk/trivial' else args
                child = subprocess.Popen([str(Path(f.bin,launcher)),*prefix,'-v','1','--wait'], env=f.env(),
                                         cwd=f.home, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.addCleanup(finish,child)
                self.assertEqual(json.loads(first_line(child))['pid'], child.pid)
                guard = Path(f.registry,component,'.uses/1')
                self.assertTrue(guard.is_file())
                self.assertEqual(guard.read_bytes(), b'')
                before = Path(f.path('1','build.json')).read_bytes()
                result = f.call('prune',component,'--keep','1')
                self.assertEqual(document(result), {'component':component,'pruned':[],'inUse':['1']})
                self.assertEqual(Path(f.path('1','build.json')).read_bytes(), before)
                self.assertTrue(Path(f.path('1','program.py')).is_file())
                finish(child)
                self.assertEqual(document(f.call('prune',component,'--keep','1'))['pruned'], ['1'])
                self.assertTrue(guard.is_file())
                self.assertEqual(sorted(path.name for path in Path(f.path('1')).iterdir()),
                                 ['build.json','build.log','last-start'])

    def test_a_pruning_guard_never_waits_a_named_launcher_and_does_not_record_a_start(self) -> None:
        """builds.use-guard-pruning"""
        f = Fixture(self)
        f.build()
        fd = open_use_guard(f.registry,f.component,'1',exclusive=True)
        try:
            result = f.launch('-v','1')
            self.assertEqual(result.returncode, 1)
            self.assertIn('being pruned',document(result)['error']['message'])
            self.assertFalse(Path(f.path('1','last-start')).exists())
        finally:
            os.close(fd)
        self.assertEqual(document(f.launch('-v','1'))['build'], '1')

    def test_guard_metadata_failure_does_not_stop_launch_but_prevents_removal(self) -> None:
        """builds.use-guard-unverifiable"""
        f = Fixture(self)
        f.build()
        f.build()
        place = Path(f.registry,f.component,'.uses')
        place.write_text('private broken metadata')
        self.assertEqual(document(f.launch('-v','1'))['build'], '1')
        before = Path(f.path('1','build.json')).read_bytes()
        result = f.call('prune',f.component,'--keep','1')
        self.assertEqual(document(result), {'component':f.component,'pruned':[],'unverifiable':['1']})
        self.assertEqual(Path(f.path('1','build.json')).read_bytes(), before)
        self.assertTrue(Path(f.path('1','program.py')).is_file())
        self.assertEqual(place.read_text(), 'private broken metadata')

    def test_nonregular_guard_never_blocks_or_follows_another_file(self) -> None:
        f = Fixture(self)
        f.build()
        f.build()
        place = Path(f.registry,f.component,'.uses')
        place.mkdir()
        target = Path(f.home,'outside')
        target.write_text('untouched')
        for kind in ['fifo','symlink']:
            with self.subTest(kind=kind):
                guard = place / '1'
                if kind == 'fifo':
                    os.mkfifo(guard)
                else:
                    guard.symlink_to(target)
                self.assertEqual(document(f.launch('-v','1'))['build'], '1')
                self.assertEqual(document(f.call('prune',f.component,'--keep','1'))['unverifiable'], ['1'])
                self.assertTrue(Path(f.path('1','program.py')).is_file())
                self.assertEqual(target.read_text(), 'untouched')
                guard.unlink()
