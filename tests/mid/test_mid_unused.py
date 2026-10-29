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

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::MixedRegistry.test_real_cli_mixed_registry
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-drill
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_real_cli_mixed_registry(self) -> None:
#         """builds.unused-drill"""
#         result = drill()
#         self.assertEqual(result['rounds'], 5)
#         self.assertTrue(result['activeGuardKeptFiles'])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::UseGuards.test_a_pruning_guard_never_waits_a_named_launcher_and_does_not_record_a_start
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.use-guard-pruning
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_a_pruning_guard_never_waits_a_named_launcher_and_does_not_record_a_start(self) -> None:
#         """builds.use-guard-pruning"""
#         f = Fixture(self)
#         f.build()
#         fd = open_use_guard(f.registry,f.component,'1',exclusive=True)
#         try:
#             result = f.launch('-v','1')
#             self.assertEqual(result.returncode, 1)
#             self.assertIn('being pruned',document(result)['error']['message'])
#             self.assertFalse(Path(f.path('1','last-start')).exists())
#         finally:
#             os.close(fd)
#         self.assertEqual(document(f.launch('-v','1'))['build'], '1')
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::UseGuards.test_guard_metadata_failure_does_not_stop_launch_but_prevents_removal
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.use-guard-unverifiable
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_guard_metadata_failure_does_not_stop_launch_but_prevents_removal(self) -> None:
#         """builds.use-guard-unverifiable"""
#         f = Fixture(self)
#         f.build()
#         f.build()
#         place = Path(f.registry,f.component,'.uses')
#         place.write_text('private broken metadata')
#         self.assertEqual(document(f.launch('-v','1'))['build'], '1')
#         before = Path(f.path('1','build.json')).read_bytes()
#         result = f.call('prune',f.component,'--keep','1')
#         self.assertEqual(document(result), {'component':f.component,'pruned':[],'unverifiable':['1']})
#         self.assertEqual(Path(f.path('1','build.json')).read_bytes(), before)
#         self.assertTrue(Path(f.path('1','program.py')).is_file())
#         self.assertEqual(place.read_text(), 'private broken metadata')
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::UseGuards.test_nonregular_guard_never_blocks_or_follows_another_file
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.use-guard-nonregular
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_nonregular_guard_never_blocks_or_follows_another_file(self) -> None:
#         """builds.use-guard-nonregular"""
#         f = Fixture(self)
#         f.build()
#         f.build()
#         place = Path(f.registry,f.component,'.uses')
#         place.mkdir()
#         target = Path(f.home,'outside')
#         target.write_text('untouched')
#         for kind in ['fifo','symlink']:
#             with self.subTest(kind=kind):
#                 guard = place / '1'
#                 if kind == 'fifo':
#                     os.mkfifo(guard)
#                 else:
#                     guard.symlink_to(target)
#                 self.assertEqual(document(f.launch('-v','1'))['build'], '1')
#                 self.assertEqual(document(f.call('prune',f.component,'--keep','1'))['unverifiable'], ['1'])
#                 self.assertTrue(Path(f.path('1','program.py')).is_file())
#                 self.assertEqual(target.read_text(), 'untouched')
#                 guard.unlink()
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::Settings.test_missing_file_or_key_disables_and_positive_finite_fractions_are_allowed
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-settings
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_missing_file_or_key_disables_and_positive_finite_fractions_are_allowed(self) -> None:
#         """builds.unused-settings"""
#         import tempfile
#
#         from arbol_builds.unused import read_days
#         with tempfile.TemporaryDirectory(prefix='unused-settings-') as temporary:
#             home = Path(temporary)
#             self.assertIsNone(read_days(home))
#             settings = home / '.arbol/arbol-builds.json'
#             settings.parent.mkdir()
#             for value,want in [({},None), ({'future':3},None), ({'removeUnusedAfterDays':1},1.0),
#                                ({'removeUnusedAfterDays':0.5,'future':3},0.5)]:
#                 with self.subTest(value=value):
#                     settings.write_text(json.dumps(value))
#                     self.assertEqual(read_days(home), want)
#             invalid_values: list[object] = [0,-1,True,False,None,'1',{},[]]
#             for raw in ['[]','null','{bad}', '{"removeUnusedAfterDays":NaN}', '{"removeUnusedAfterDays":Infinity}',
#                         *[json.dumps({'removeUnusedAfterDays':candidate}) for candidate in invalid_values]]:
#                 with self.subTest(raw=raw):
#                     settings.write_text(raw)
#                     with self.assertRaises(ValueError):
#                         read_days(home)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::Settings.test_nonregular_or_symlink_settings_refuse_without_blocking
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-settings-nonregular
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_nonregular_or_symlink_settings_refuse_without_blocking(self) -> None:
#         """builds.unused-settings-nonregular"""
#         import tempfile
#
#         from arbol_builds.unused import read_days
#         with tempfile.TemporaryDirectory(prefix='unused-settings-') as temporary:
#             home = Path(temporary)
#             path = home / '.arbol/arbol-builds.json'
#             path.parent.mkdir()
#             os.mkfifo(path)
#             with self.assertRaises(ValueError):
#                 read_days(home)
#             path.unlink()
#             target = home / 'outside'
#             target.write_text('{"removeUnusedAfterDays":1}')
#             path.symlink_to(target)
#             with self.assertRaises(ValueError):
#                 read_days(home)
#             path.unlink()
#             path.mkdir()
#             with self.assertRaises(ValueError):
#                 read_days(home)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::Settings.test_disabled_cli_has_no_mutation_manager_query_or_root_catalogue_read
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-disabled
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_disabled_cli_has_no_mutation_manager_query_or_root_catalogue_read(self) -> None:
#         """builds.unused-disabled"""
#         f = Fixture(self)
#         f.build()
#         root_catalogue = Path(f.home,'Library/Application Support/Arbol/roots')
#         root_catalogue.parent.mkdir(parents=True)
#         os.mkfifo(root_catalogue)
#         before = {str(p):p.read_bytes() for p in Path(f.registry).rglob('*') if p.is_file()}
#         result = f.call('prune','--unused')
#         self.assertEqual((result.returncode,document(result)), (0,[{'component':'sample','pruned':[]}]))
#         self.assertEqual({str(p):p.read_bytes() for p in Path(f.registry).rglob('*') if p.is_file()}, before)
#         self.assertFalse(Path(f.registry,'sample/.uses').exists())
#         settings = Path(f.home,'.arbol/arbol-builds.json')
#         settings.parent.mkdir()
#         settings.write_text('{"future":true}')
#         self.assertEqual(document(f.call('prune','--unused')), [{'component':'sample','pruned':[]}])
#         self.assertFalse(Path(f.registry,'sample/.uses').exists())
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::Settings.test_invalid_options_and_settings_refuse_before_registry_mutation
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-input
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_invalid_options_and_settings_refuse_before_registry_mutation(self) -> None:
#         """builds.unused-input"""
#         f = Fixture(self)
#         f.build()
#         before = {str(p):p.read_bytes() for p in Path(f.registry).rglob('*') if p.is_file()}
#         cases = [('prune','sample','--unused'), ('prune','','--unused'), ('prune','--unused','--keep','1'),
#                  ('prune','--unused=true'), ('prune','--unused','--unused'), ('list','--unused'),
#                  ('prune','--unused','--root','sapling')]
#         for args in cases:
#             with self.subTest(args=args):
#                 result = f.call(*args)
#                 self.assertEqual(result.returncode, 1)
#                 self.assertEqual(document(result)['error']['code'], 'builds_failed')
#         settings = Path(f.home,'.arbol/arbol-builds.json')
#         settings.parent.mkdir()
#         settings.write_text('{"removeUnusedAfterDays":false}')
#         self.assertEqual(f.call('prune','--unused').returncode, 1)
#         self.assertEqual({str(p):p.read_bytes() for p in Path(f.registry).rglob('*') if p.is_file()}, before)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::ManagerSnapshots.test_all_retained_roots_are_queried_and_every_listed_trunk_build_is_protected
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-manager-snapshot
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_all_retained_roots_are_queried_and_every_listed_trunk_build_is_protected(self) -> None:
#         """builds.unused-manager-snapshot"""
#         f = self.prepare(('sapling','second'))
#         path = Path(f.home,'replies.json')
#         replies = json.loads(path.read_text())
#         replies['sapling']['exchanges'] = [self.exchange()]
#         path.write_text(json.dumps(replies))
#         result = self.snapshot(f)
#         self.assertEqual(result.trunks, {'arbol-trunk/trivial':{'1'}})
#         self.assertEqual(result.unavailable, [])
#         self.assertEqual(result.roots_with_exchanges, ['sapling'])
#         self.assertEqual(set(result.roots), {'sapling','second'})
#         calls = [json.loads(line) for line in Path(f.home,'manager-calls.jsonl').read_text().splitlines()]
#         self.assertEqual([call['args'] for call in calls], [['--root','sapling','list'],['--root','second','list']])
#         self.assertTrue(all(call['path'].split(os.pathsep)[0]==f.bin for call in calls))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::ManagerSnapshots.test_damaged_root_or_absent_working_manager_is_unavailable_without_query
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-manager-missing
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_damaged_root_or_absent_working_manager_is_unavailable_without_query(self) -> None:
#         """builds.unused-manager-missing"""
#         f = self.prepare()
#         root = Path(f.home,'Library/Application Support/Arbol/roots/sapling/root.json')
#         root.write_text('{bad}')
#         self.assertEqual(self.snapshot(f).unavailable, ['sapling'])
#         self.assertFalse(Path(f.home,'manager-calls.jsonl').exists())
#         root.write_text(json.dumps({'root':'sapling','status':'failed','rootContract':1,
#                                    'createdAt':'2026-10-26T09:00:00.000Z'}))
#         self.assertEqual(f.call('withdraw','arbol-root@1','--reason','private fixture').returncode, 0)
#         self.assertEqual(self.snapshot(f).unavailable, ['sapling'])
#         self.assertFalse(Path(f.home,'manager-calls.jsonl').exists())
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::ManagerSnapshots.test_partial_wrong_identity_and_malformed_listing_or_exchange_is_unavailable
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-manager-invalid
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_partial_wrong_identity_and_malformed_listing_or_exchange_is_unavailable(self) -> None:
#         """builds.unused-manager-invalid"""
#         f = self.prepare()
#         path = Path(f.home,'replies.json')
#         original = json.loads(path.read_text())['sapling']
#         variants = [{}, {**original,'root':'second'}, {**original,'rootBuild':'f'},
#                     {**original,'rootPackageVersion':'wrong'}, {**original,'unreadable':['damaged']},
#                     {**original,'exchanges':[{}]}, {**original,'exchanges':[{**self.exchange(),'trunk':'../x'}]},
#                     {**original,'exchanges':[{**self.exchange(),'trunk':None}]}]
#         for value in variants:
#             with self.subTest(value=value):
#                 path.write_text(json.dumps({'sapling':value}))
#                 result = self.snapshot(f)
#                 self.assertEqual(result.unavailable, ['sapling'])
#                 self.assertEqual(result.trunks, {})
#         Path(f.bin,'arbol-root').write_text('#!/bin/sh\necho \'{"error":{"code":"unknown_root"}}\'\nexit 1\n')
#         self.assertEqual(self.snapshot(f).unavailable, ['sapling'])
#         Path(f.bin,'arbol-root').unlink()
#         self.assertEqual(self.snapshot(f).unavailable, ['sapling'])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::ManagerSnapshots.test_timeout_is_bounded_and_never_exposes_raw_output
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-manager-timeout
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_timeout_is_bounded_and_never_exposes_raw_output(self) -> None:
#         """builds.unused-manager-timeout"""
#         from unittest import mock
#         f = self.prepare()
#         with mock.patch('arbol_builds.unused.subprocess.run',side_effect=subprocess.TimeoutExpired('fixture',30)) as query:
#             self.assertEqual(self.snapshot(f).unavailable, ['sapling'])
#         self.assertEqual(query.call_args.kwargs['timeout'], 30)
#         self.assertEqual(query.call_args.kwargs['stdin'], subprocess.DEVNULL)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::ManagerSnapshots.test_missing_catalogue_is_empty_but_unlistable_catalogue_refuses
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-catalogue
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_missing_catalogue_is_empty_but_unlistable_catalogue_refuses(self) -> None:
#         """builds.unused-catalogue"""
#         from unittest import mock
#         f = Fixture(self)
#         self.assertEqual(self.snapshot(f).roots, {})
#         with mock.patch('arbol_builds.pruning.os.scandir',side_effect=PermissionError('private fixture')):
#             with self.assertRaises(ValueError):
#                 self.snapshot(f)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::AgedRemoval.test_exact_age_future_start_and_regular_mtime_fallback_keep_the_right_files
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-age
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_exact_age_future_start_and_regular_mtime_fallback_keep_the_right_files(self) -> None:
#         """builds.unused-age"""
#         f = Fixture(self)
#         for _ in range(4):
#             f.build()
#         self.setting(f)
#         for number in ['1','2','3','4']:
#             self.aged(f,number)
#         Path(f.path('2','last-start')).write_text(self.iso(self.CLOCK-86_400_000)+'\n')
#         Path(f.path('3','last-start')).write_text(self.iso(self.CLOCK+86_400_000)+'\n')
#         self.assertEqual(self.prune(f), [{'component':'sample','pruned':['1']}])
#         self.assertTrue(Path(f.path('2','program.py')).is_file())
#         self.assertTrue(Path(f.path('3','program.py')).is_file())
#         self.assertTrue(Path(f.path('4','program.py')).is_file())
#         marker = Path(f.path('2','last-start'))
#         marker.write_text('damaged regular marker')
#         stamp = (self.CLOCK-3*86_400_000)/1000
#         os.utime(marker,(stamp,stamp))
#         self.assertEqual(self.prune(f), [{'component':'sample','pruned':['2']}])
#         self.assertEqual(marker.read_text(), 'damaged regular marker')
#         for number in ['1','2']:
#             self.assertIn('prunedAt',json.loads(Path(f.path(number,'build.json')).read_text()))
#             self.assertTrue(Path(f.path(number,'build.log')).is_file())
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::AgedRemoval.test_old_failed_and_withdrawn_payloads_go_but_defaults_and_locks_stay
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-statuses
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_old_failed_and_withdrawn_payloads_go_but_defaults_and_locks_stay(self) -> None:
#         """builds.unused-statuses"""
#         f = Fixture(self)
#         for _ in range(3):
#             f.build()
#         self.assertEqual(f.call('lock','sample@1').returncode, 0)
#         self.assertEqual(f.call('withdraw','sample@2','--reason','private fixture').returncode, 0)
#         f.configure(checks=[{'name':'private-failure','kind':'unit','command':'exit 1'}])
#         failed = f.call('build','sample','--repo',f.repo)
#         self.assertEqual(document(failed)['status'], 'failed')
#         self.setting(f)
#         for number in ['1','2','3','4']:
#             self.aged(f,number)
#         self.assertEqual(self.prune(f), [{'component':'sample','pruned':['4','2']}])
#         self.assertTrue(Path(f.path('1','program.py')).is_file())
#         self.assertTrue(Path(f.path('3','program.py')).is_file())
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::AgedRemoval.test_building_and_damaged_records_never_authorize_removal
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-building-damaged
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_building_and_damaged_records_never_authorize_removal(self) -> None:
#         """builds.unused-building-damaged"""
#         f = Fixture(self)
#         for _ in range(3):
#             f.build()
#         self.setting(f)
#         path = Path(f.path('1','build.json'))
#         value = json.loads(path.read_text())
#         value['status'] = 'building'
#         value.pop('finishedAt',None)
#         path.write_text(json.dumps(value))
#         Path(f.path('2','build.json')).write_text('{bad}')
#         before = {str(p):p.read_bytes() for p in Path(f.registry).rglob('*') if p.is_file()}
#         self.assertEqual(self.prune(f), [{'component':'sample','pruned':[]}])
#         self.assertEqual({str(p):p.read_bytes() for p in Path(f.registry).rglob('*') if p.is_file()}, before)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_unused.py::AgedRemoval.test_an_active_old_build_is_kept_even_when_its_start_is_older_than_the_period
# Reason: Reviewed lifecycle case: routine registry/CLI branches or another variant of a retained lock, interrupted publication, unsafe-path or destructive-cleanup case; no distinct failure mechanism warrants separate execution. Case reviewed: builds.unused-active-process
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_unused.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_an_active_old_build_is_kept_even_when_its_start_is_older_than_the_period(self) -> None:
#         """builds.unused-active-process"""
#         import time
#         f = Fixture(self)
#         f.build()
#         f.build()
#         self.setting(f)
#         child = subprocess.Popen([str(Path(f.bin,'sample')),'-v','1','--wait'],env=f.env(),
#                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE)
#         self.addCleanup(finish,child)
#         first_line(child)
#         clock = time.time()*1000+10*86_400_000
#         self.assertEqual(self.prune(f,clock), [{'component':'sample','pruned':[],'inUse':['1']}])
#         self.assertTrue(Path(f.path('1','program.py')).is_file())
#         finish(child)
#         self.assertEqual(self.prune(f,clock), [{'component':'sample','pruned':['1']}])
# LOW-TIER-SOURCE-END
# LOW-TIER-END
