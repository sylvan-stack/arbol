"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_unused as _support
from test_unused import (Fixture ,Path ,TRUNK_PROGRAM ,document ,finish ,first_line ,json ,open_use_guard ,subprocess)


class UseGuards(_support.UseGuards):
# TEST-TIER-BEGIN tests/test_unused.py::UseGuards.test_plain_root_and_trunk_exec_hold_use_until_the_process_exits
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
# TEST-TIER-END tests/test_unused.py::UseGuards.test_plain_root_and_trunk_exec_hold_use_until_the_process_exits


class AgedRemoval(_support.AgedRemoval):


# TEST-TIER-BEGIN tests/test_unused.py::AgedRemoval.test_last_start_is_read_again_after_exclusive_guard_acquisition
    def test_last_start_is_read_again_after_exclusive_guard_acquisition(self) -> None:
        """builds.unused-recent-start"""
        from unittest import mock
        f = Fixture(self)
        f.build()
        f.build()
        self.setting(f)
        self.aged(f,'1')
        def acquire(registry: str, component: str, number: str, *, exclusive: bool = False) -> int:
            fd = open_use_guard(registry,component,number,exclusive=exclusive)
            Path(f.path(number,'last-start')).write_text(self.iso(self.CLOCK)+'\n')
            return fd
        with mock.patch('arbol_builds.service.open_use_guard',side_effect=acquire):
            self.assertEqual(self.prune(f), [{'component':'sample','pruned':[]}])
        self.assertTrue(Path(f.path('1','program.py')).is_file())
        self.assertNotIn('prunedAt',json.loads(Path(f.path('1','build.json')).read_text()))
# TEST-TIER-END tests/test_unused.py::AgedRemoval.test_last_start_is_read_again_after_exclusive_guard_acquisition

# TEST-TIER-BEGIN tests/test_unused.py::AgedRemoval.test_removal_failure_keeps_record_log_and_unavailable_mark
    def test_removal_failure_keeps_record_log_and_unavailable_mark(self) -> None:
        """builds.unused-removal-failure"""
        from unittest import mock
        f = Fixture(self)
        f.build()
        f.build()
        self.setting(f)
        self.aged(f,'1')
        Path(f.path('1','payload')).mkdir()
        with mock.patch('arbol_builds.service.shutil.rmtree',side_effect=PermissionError('private fixture')):
            with self.assertRaises(PermissionError):
                self.prune(f)
        self.assertIn('prunedAt',json.loads(Path(f.path('1','build.json')).read_text()))
        self.assertTrue(Path(f.path('1','build.log')).is_file())
        self.assertEqual(f.launch('-v','1').returncode, 1)
# TEST-TIER-END tests/test_unused.py::AgedRemoval.test_removal_failure_keeps_record_log_and_unavailable_mark
