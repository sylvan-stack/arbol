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


class Settings(unittest.TestCase):
    def test_missing_file_or_key_disables_and_positive_finite_fractions_are_allowed(self) -> None:
        """builds.unused-settings"""
        import tempfile

        from arbol_builds.unused import read_days
        with tempfile.TemporaryDirectory(prefix='unused-settings-') as temporary:
            home = Path(temporary)
            self.assertIsNone(read_days(home))
            settings = home / '.arbol/arbol-builds.json'
            settings.parent.mkdir()
            for value,want in [({},None), ({'future':3},None), ({'removeUnusedAfterDays':1},1.0),
                               ({'removeUnusedAfterDays':0.5,'future':3},0.5)]:
                with self.subTest(value=value):
                    settings.write_text(json.dumps(value))
                    self.assertEqual(read_days(home), want)
            invalid_values: list[object] = [0,-1,True,False,None,'1',{},[]]
            for raw in ['[]','null','{bad}', '{"removeUnusedAfterDays":NaN}', '{"removeUnusedAfterDays":Infinity}',
                        *[json.dumps({'removeUnusedAfterDays':candidate}) for candidate in invalid_values]]:
                with self.subTest(raw=raw):
                    settings.write_text(raw)
                    with self.assertRaises(ValueError):
                        read_days(home)

    def test_nonregular_or_symlink_settings_refuse_without_blocking(self) -> None:
        import tempfile

        from arbol_builds.unused import read_days
        with tempfile.TemporaryDirectory(prefix='unused-settings-') as temporary:
            home = Path(temporary)
            path = home / '.arbol/arbol-builds.json'
            path.parent.mkdir()
            os.mkfifo(path)
            with self.assertRaises(ValueError):
                read_days(home)
            path.unlink()
            target = home / 'outside'
            target.write_text('{"removeUnusedAfterDays":1}')
            path.symlink_to(target)
            with self.assertRaises(ValueError):
                read_days(home)
            path.unlink()
            path.mkdir()
            with self.assertRaises(ValueError):
                read_days(home)

    def test_disabled_cli_has_no_mutation_manager_query_or_root_catalogue_read(self) -> None:
        """builds.unused-disabled"""
        f = Fixture(self)
        f.build()
        root_catalogue = Path(f.home,'Library/Application Support/Arbol/roots')
        root_catalogue.parent.mkdir(parents=True)
        os.mkfifo(root_catalogue)
        before = {str(p):p.read_bytes() for p in Path(f.registry).rglob('*') if p.is_file()}
        result = f.call('prune','--unused')
        self.assertEqual((result.returncode,document(result)), (0,[{'component':'sample','pruned':[]}]))
        self.assertEqual({str(p):p.read_bytes() for p in Path(f.registry).rglob('*') if p.is_file()}, before)
        self.assertFalse(Path(f.registry,'sample/.uses').exists())
        settings = Path(f.home,'.arbol/arbol-builds.json')
        settings.parent.mkdir()
        settings.write_text('{"future":true}')
        self.assertEqual(document(f.call('prune','--unused')), [{'component':'sample','pruned':[]}])
        self.assertFalse(Path(f.registry,'sample/.uses').exists())

    def test_invalid_options_and_settings_refuse_before_registry_mutation(self) -> None:
        """builds.unused-input"""
        f = Fixture(self)
        f.build()
        before = {str(p):p.read_bytes() for p in Path(f.registry).rglob('*') if p.is_file()}
        cases = [('prune','sample','--unused'), ('prune','','--unused'), ('prune','--unused','--keep','1'),
                 ('prune','--unused=true'), ('prune','--unused','--unused'), ('list','--unused'),
                 ('prune','--unused','--root','sapling')]
        for args in cases:
            with self.subTest(args=args):
                result = f.call(*args)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(document(result)['error']['code'], 'builds_failed')
        settings = Path(f.home,'.arbol/arbol-builds.json')
        settings.parent.mkdir()
        settings.write_text('{"removeUnusedAfterDays":false}')
        self.assertEqual(f.call('prune','--unused').returncode, 1)
        self.assertEqual({str(p):p.read_bytes() for p in Path(f.registry).rglob('*') if p.is_file()}, before)
