# Mid-tier source from scripts/unused_drill.py; see MID_TIER.md.
# Shared helpers and refusal entry points remain at the original path.

# TEST-TIER-DISABLED-BEGIN scripts/unused_drill.py
# """Exercise unused pruning through the real CLI in a disposable mixed registry."""
#
# from __future__ import annotations
#
# import argparse
# import json
# import os
# import shlex
# import subprocess
# import sys
# import tempfile
# from datetime import UTC, datetime, timedelta
# from pathlib import Path
# from typing import Any
#
# ROOT = Path(__file__).resolve().parents[1]
#
#
# def drill(tool: list[str] | None = None) -> dict[str, Any]:
#     tool = tool or [sys.executable,'-I','-B',str(ROOT / 'bin/builds_entry.py')]
#     with tempfile.TemporaryDirectory(prefix='unused-mixed-') as temporary:
#         home = Path(temporary).resolve()
#         registry, binary = home / 'registry with spaces', home / 'bin'
#         binary.mkdir()
#         env = {'HOME':str(home),'PATH':os.environ.get('PATH',os.defpath),'LANG':'en_US.UTF-8'}
#         old = (datetime.now(UTC)-timedelta(days=20)).isoformat(timespec='milliseconds').replace('+00:00','Z')
#         recent = datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00','Z')
#
#         def call(*args: str) -> Any:
#             result = subprocess.run([*tool,*args,'--registry-dir',str(registry),'--bin-dir',str(binary)],
#                                     env=env,cwd=home,capture_output=True,check=False,timeout=90)
#             if result.returncode:
#                 raise ValueError(f'Private CLI failed: {args}: {result.stdout!r} {result.stderr!r}')
#             return json.loads(result.stdout)
#
#         def record(component: str, number: str, *, root: str | None = None,
#                    versions: list[int] | None = None, locked: bool = False, young: bool = False) -> None:
#             folder = registry / component / number
#             folder.mkdir(parents=True,exist_ok=False)
#             value: dict[str, Any] = {'component':component,'build':number,'packageVersion':'1.0.0','status':'working',
#                                      'startedAt':old,'finishedAt':old,'entry':'program',
#                                      'source':{'repository':str(home / 'fictional'),'branch':'main',
#                                                'commit':'fixture','uncommittedChanges':False},
#                                      'checks':[{'name':'fixture','kind':'unit','passed':True}]}
#             if root is not None:
#                 value['root'] = root
#             if versions is not None:
#                 value['rootContracts'] = versions
#             if locked:
#                 value['lockedAt'] = old
#             (folder / 'build.json').write_text(json.dumps(value))
#             (folder / 'build.log').write_text('fictional private Build\n')
#             (folder / 'last-start').write_text((recent if young else old)+'\n')
#             (folder / 'program').write_text('#!/bin/sh\nexit 0\n')
#             (folder / 'program').chmod(0o755)
#             (folder / 'payload.txt').write_text('fictional payload\n')
#
#         for name,version,status in [('sapling',1,'working'),('second',2,'failed')]:
#             place = home / 'Library/Application Support/Arbol/roots' / name
#             place.mkdir(parents=True)
#             (place / 'root.json').write_text(json.dumps({'root':name,'rootContract':version,'status':status,'createdAt':old}))
#         for component in ['arbol','arbol-root']:
#             record(component,'1',root='sapling')
#             record(component,'2',root='sapling')
#             record(component,'3',root='second')
#         for component in ['arbol-app','arbol-claude-driver','arbol-classifier']:
#             record(component,'1')
#             record(component,'2')
#         for number,versions in [('1',[1]),('2',[2]),('3',[1]),('4',[1]),('5',[3])]:
#             record('arbol-trunk/trivial',number,versions=versions)
#         for number in ['1','2','3','4']:
#             record('sample',number,locked=number=='1',young=number=='2')
#         mode = home / 'manager-mode'
#         mode.write_text('active')
#         manager = home / 'manager.py'
#         manager.write_text('''import json,os,sys
# from pathlib import Path
# home=Path(os.environ['HOME']); root=sys.argv[2]; mode=(home/'manager-mode').read_text()
# with (home/'manager-calls.jsonl').open('a') as out: out.write(json.dumps(sys.argv[1:])+'\\n')
# if mode=='unavailable' and root=='second':
#     print('{"error":{"code":"root_unavailable","message":"fictional failure"}}');sys.exit(1)
# entries=[]
# if mode=='active' and root=='sapling':
#     entries=[{'root':root,'exchange':'7f3a2c1e-4b5d-4e6f-8a9b-0c1d2e3f4a5b',
#               'chat':'c3d4e5f6-0718-4293-a4b5-c6d7e8f90a1b','trunk':'trivial','build':'1',
#               'process':{'pid':123,'startedAt':'2026-10-26T09:00:00.000Z','alive':False},'state':'unsaved',
#               'signsOfLife':{'heartbeat':4,'waitingFor':'database','since':'2026-10-26T09:00:00.000Z'}}]
# print(json.dumps({'root':root,'rootBuild':{'sapling':'2','second':'3'}[root],
#                   'rootPackageVersion':'1.0.0','exchanges':entries,'unreadable':[]}))
# ''')
#         (binary / 'arbol-root').write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' -I -B '+
#                                          shlex.quote(str(manager))+' "$@"\n')
#         (binary / 'arbol-root').chmod(0o755)
#         # Real CLI builds generate all launcher paths without installing anything outside this home.
#         repo = home / 'fictional repository'
#         repo.mkdir()
#         (repo / 'package.json').write_text('{"version":"1.0.0"}')
#         (repo / 'program').write_text('#!/bin/sh\ndirectory=${0%/*}\nexec '+shlex.quote(sys.executable)+
#                                     ' -I -B "$directory/program.py" "$@"\n')
#         (repo / 'program.py').write_text('''import json,os,sys,time
# from pathlib import Path
# if '--hold' in sys.argv:
#     print(json.dumps({'pid':os.getpid()}),flush=True)
#     while not (Path(os.environ['HOME'])/'release').exists(): time.sleep(.01)
# ''')
#         description: dict[str, Any] = {'component':'sample-active','entry':'program',
#                                       'build':['cp program program.py "$ARBOL_BUILD_DIR/" && chmod +x "$ARBOL_BUILD_DIR/program"'],
#                                       'checks':[{'name':'fixture','kind':'unit','command':'"$ARBOL_BUILD_DIR/program"'}]}
#         config = repo / 'arbol-build.json'
#         config.write_text(json.dumps(description))
#         for args in [['git','init','-q','-b','main'],['git','add','--','package.json','program','program.py','arbol-build.json'],
#                      ['git','commit','-qm','Private unused-Build pruning fixture']]:
#             subprocess.run(args,cwd=repo,check=True,capture_output=True)
#         call('build','sample-active','--repo',str(repo))
#         call('build','sample-active','--repo',str(repo))
#         description.update(component='arbol-trunk/fixture',rootContracts=[1])
#         config.write_text(json.dumps(description))
#         subprocess.run(['git','add','--','arbol-build.json'],cwd=repo,check=True,capture_output=True)
#         subprocess.run(['git','commit','-qm','Private Trunk inventory fixture'],cwd=repo,check=True,capture_output=True)
#         call('build','arbol-trunk/fixture','--repo',str(repo))
#         for root,chosen in [('sapling','4'),('second','2')]:
#             answer = subprocess.run([str(binary / 'arbol-trunk'),'--root',root,'trivial','list'],env=env,
#                                     capture_output=True,check=True)
#             builds = json.loads(answer.stdout)['trunks'][0]['builds']
#             if [value['build'] for value in builds if value['chosen']] != [chosen]:
#                 raise ValueError('The real Trunk launcher and private version defaults disagree.')
#         child = subprocess.Popen([str(binary / 'sample-active'),'-v','1','--hold'],env=env,
#                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE)
#         try:
#             assert child.stdout is not None
#             if json.loads(child.stdout.readline())['pid'] != child.pid:
#                 raise ValueError('The private active Build did not retain its process identity.')
#             for number in ['1','2']:
#                 place = registry / 'sample-active' / number
#                 value = json.loads((place / 'build.json').read_text())
#                 value.update(startedAt=old,finishedAt=old)
#                 (place / 'build.json').write_text(json.dumps(value))
#                 (place / 'last-start').write_text(old+'\n')
#             disabled = call('prune','--unused')
#             if any(row['pruned'] for row in disabled) or (home / 'manager-calls.jsonl').exists():
#                 raise ValueError('Disabled pruning mutated files or queried a manager.')
#             settings = home / '.arbol/arbol-builds.json'
#             settings.parent.mkdir()
#             settings.write_text('{"removeUnusedAfterDays":5}')
#
#             def check_round(expected: dict[str, list[str]]) -> list[dict[str, Any]]:
#                 rows: list[dict[str, Any]] = call('prune','--unused')
#                 names = [row['component'] for row in rows]
#                 if names != sorted(names):
#                     raise ValueError('Unused results are not in component order.')
#                 actual = {row['component']:row['pruned'] for row in rows}
#                 wanted = {name:expected.get(name,[]) for name in names}
#                 if actual != wanted or not set(expected).issubset(actual):
#                     raise ValueError(f'Wrong private removals: expected {wanted!r}, got {actual!r}')
#                 for component,numbers in actual.items():
#                     for number in numbers:
#                         place = registry / component / number
#                         value = json.loads((place / 'build.json').read_text())
#                         if ('prunedAt' not in value or not (place / 'build.log').is_file()
#                                 or (place / 'program').exists() or (place / 'payload.txt').exists()):
#                             raise ValueError('A pruned Build lost its retained record/log or kept its payload.')
#                 return rows
#
#             first = check_round({'arbol':['1'],'arbol-root':['1'],'arbol-app':['1'],
#                                  'arbol-trunk/trivial':['3'],'sample':['3']})
#             indexed = {row['component']:row for row in first}
#             if indexed['sample-active'].get('inUse') != ['1']:
#                 raise ValueError('The active old Build was not held by its process-use guard.')
#             for component in ['arbol-claude-driver','arbol-classifier']:
#                 if indexed[component].get('rootsWithExchanges') != ['sapling']:
#                     raise ValueError('Unknown runtime identity was not conservatively protected.')
#             mode.write_text('empty')
#             second = check_round({'arbol-trunk/trivial':['1'],'arbol-claude-driver':['1'],'arbol-classifier':['1']})
#             record('arbol-trunk/trivial','6',versions=[1])
#             record('arbol-claude-driver','3')
#             record('arbol-classifier','3')
#             mode.write_text('unavailable')
#             third = check_round({})
#             for row in third:
#                 if row['component'].startswith('arbol-trunk/') or row['component'] in ['arbol-claude-driver','arbol-classifier']:
#                     if row.get('unavailableRoots') != ['second']:
#                         raise ValueError('The unavailable Root was not reported on a protected runtime component.')
#             (home / 'release').touch()
#             if child.wait(timeout=5) != 0:
#                 raise ValueError('The private active Build did not end normally.')
#             fourth = check_round({'sample-active':['1']})
#             mode.write_text('empty')
#             resumed = check_round({'arbol-trunk/trivial':['5','4'],'arbol-claude-driver':['2'],'arbol-classifier':['2']})
#             return {'check':'builds.unused-drill','roots':2,'rounds':5,'disabledNoMutationOrQuery':True,
#                     'firstPruned':{row['component']:row['pruned'] for row in first if row['pruned']},
#                     'afterExchangeRemoved':{row['component']:row['pruned'] for row in second if row['pruned']},
#                     'unavailableRoot':'second','activeGuardKeptFiles':True,'versionDefaultsAgreeWithLauncher':True,
#                     'afterProcessEnded':{row['component']:row['pruned'] for row in fourth if row['pruned']},
#                     'afterManagerRecovered':{row['component']:row['pruned'] for row in resumed if row['pruned']},
#                     'ownerRegistryChanged':False,'vendorRequests':0,'temporaryStateRemovedOnReturn':True}
#         finally:
#             if child.poll() is None:
#                 child.terminate()
#                 child.wait(timeout=5)
#             for stream in [child.stdout,child.stderr]:
#                 if stream is not None:
#                     stream.close()
#
#
# def main() -> int:
#     parser = argparse.ArgumentParser(description=__doc__)
#     parser.add_argument('--tool',type=Path,help='Installed arbol-builds to qualify instead of this source entry')
#     args = parser.parse_args()
#     print(json.dumps(drill([str(args.tool.resolve())] if args.tool else None),indent=2))
#     return 0
#
#
# if __name__ == '__main__':
#     raise SystemExit(main())
# TEST-TIER-DISABLED-END scripts/unused_drill.py


raise RuntimeError("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.")
