"""Install an independently published overlay with the unchanged pinned installer.

The source grant and producer package must already exist. This command never
publishes a grant and never authorizes qualification operations.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import signal
import subprocess
from pathlib import Path

from prepare import HERE, read, reconstruct, require, run_path, sha, strict, verify_prepared, write_new


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--prepared',required=True)
    args=parser.parse_args()
    run=run_path(args.prepared,True)
    tree,manifest=reconstruct()
    require(manifest['overlay']['commit']!='unpublished','Overlay has not been published through the managed source route')
    recorded=strict(read(run/'source-manifest.json',16*1024*1024))
    require(recorded==manifest,'Prepared source manifest differs; prepare a fresh published attempt')
    verify_prepared(run,tree)
    # Import only this reviewed gate module, not any reconstructed product package.
    spec=importlib.util.spec_from_file_location('afm9_delivery_gate',HERE/'browser_qualification.py')
    gate=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    grant,review=gate.source_admission()
    require(grant['sourceGit']==manifest['overlay']['commit'] and grant['sourceFiles']==manifest['overlay']['files'],
            'Published source declaration differs from this exact overlay')
    producer_raw=gate.read(gate.D/'delivery/producer-manifest.json',16*1024*1024,0o600)
    require(sha(producer_raw)==grant['producerManifestSha256'],'Missing accepted Browser producer pin package')
    producer=gate.strict(producer_raw,16*1024*1024)
    gate.keys(producer,'schema kind sourceGit files compileRecord productSources productOutputs compilerInputs roleReviews executables osVersion')
    require(producer['files']==gate.tree_map(gate.PRODUCER),'Producer bytes differ from admitted package')
    # Software installation is coordinated separately from implementation holds.
    holds=strict(read(Path('/Users/msix/Artifacts/forester/holds.json'),16*1024*1024))
    require(holds.get('schema')==1 and isinstance(holds.get('bookings'),list),'Unrecognized Forester holds')
    conflicts=[row['id'] for row in holds['bookings'] if any(path.startswith('arbol:') for path in
               row.get('territory',[])+[path for widening in row.get('widened',[]) for path in widening.get('paths',[])])]
    require(not conflicts,'Private installation awaits coordinated no-open-Arbol-booking window: '+', '.join(conflicts))
    destination=gate.BIN
    gate.ancestors(destination.parent)
    require(not os.path.lexists(destination),'Private bin already exists; never overwrite or retry this attempt')
    bootstrap=grant['bootstrap']
    python=Path(bootstrap['python']['path'])
    uv=Path(bootstrap['uv']['path'])
    require(uv.name=='uv','Expected pinned uv executable')
    for name,path in (('python',python),('uv',uv)):
        gate.check_reference(bootstrap[name],path,256*1024*1024)
    require(re.fullmatch(r'uv 0\.12\.23(?: \([^\r\n]+\))?',gate.child([uv,'--version'],b'',run,15).decode().strip()),
            'Unexpected supported uv version')
    require(gate.child([python,'-I','-B','-c','import platform; print(platform.python_version())'],b'',run,15).decode().strip()=='3.14.8',
            'Unexpected pinned bootstrap Python version')
    # Reobserve the entire prepared source and exact pins immediately before the first write.
    verify_prepared(run,tree)
    require(gate.source_admission()==(grant,review),'Source acceptance changed during preflight')
    destination.mkdir(mode=0o700)
    cache=run/'installation-cache'
    cache.mkdir(mode=0o700)
    environment={'PATH':str(uv.parent)+':/usr/bin:/bin','HOME':'/Users/msix','LANG':'C.UTF-8',
                 'ARBOL_PYTHON_ARCHIVE_CACHE':str(cache/'python'),'UV_CACHE_DIR':str(cache/'uv'),
                 'UV_PYTHON_DOWNLOADS':'never','PYTHONDONTWRITEBYTECODE':'1'}
    log=run/'installation.log'
    with os.fdopen(os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as stream:
        process=subprocess.Popen([str(python),'-I','-B',str(run/'source/scripts/install_builds.py'),
                               '--bin-dir',str(destination)],cwd=run/'source',env=environment,
                              stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            status=process.wait(timeout=600)
        except BaseException:
            # The historical installer traps TERM and cleans its own compile
            # groups. Give that handler time before ending remaining members.
            try:
                os.kill(process.pid,signal.SIGTERM)
            except ProcessLookupError:
                pass
            cooperative=True
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                cooperative=False
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            write_new(run/'installation-interrupted.json',gate.encode({
                'schema':1,'status':'incomplete','installerPid':process.pid,
                'installerExit':process.returncode,'cooperativeExitObserved':cooperative,
                'descendantDisposition':'historical-cleanup-returned' if cooperative else 'not-proven-quiescent',
                'qualification':'unexecuted'})+b'\n')
            raise
    require(status==0,'Pinned installer failed; preserve the private bin, source and installation.log')
    verify_prepared(run,tree)
    actual_python=destination/'.arbol-builds/runtime/3.14.8-d15291f940cf/python/bin/python3.14'
    version=gate.child([actual_python,'-I','-B','-c','import platform; print(platform.python_version())'],b'',run,15).decode().strip()
    require(version=='3.14.8','Installed interpreter version differs')
    modules={name:row[1] for name,row in tree.items() if name.startswith(('src/arbol_builds/','src/arbol_agents/','src/arbol_installation/')) and name.endswith('.py')}
    require(len(modules)==38,'Expected exactly 38 installed source modules')
    installed={str(p.relative_to(destination/'.arbol-builds')):p for package in ('arbol_builds','arbol_agents','arbol_installation')
               for p in (destination/'.arbol-builds'/package).rglob('*.py')}
    require(set(installed)=={name.removeprefix('src/') for name in modules},'Installed module set differs')
    for name,data in modules.items():
        require(gate.read(installed[name.removeprefix('src/')],64*1024*1024)==data,'Installed module differs: '+name)
    observed={'schema':1,'kind':'afm9-browser-private-tool','sourceGit':grant['sourceGit'],'sourceFiles':grant['sourceFiles'],
              'files':gate.tree_map(destination),
              'executables':{'python':gate.reference(actual_python,256*1024*1024),
                             'launcher':gate.reference(destination/'arbol-builds',1024*1024,0o755)},
              'pythonArchiveSha256':'d15291f940cfecd2e54010d5e37d2e03aa192f076a65d26ab741372fff2dabfe'}
    write_new(gate.D/'delivery/tool-manifest.json',gate.encode(observed)+b'\n')
    receipt={'schema':1,'status':'installed-unqualified','sourceReview':review,'sourceGit':grant['sourceGit'],
             'pythonVersion':version,'toolManifestSha256':sha(gate.encode(observed)+b'\n'),
             'installedModules':{name:sha(data) for name,data in modules.items()},'qualification':'unexecuted'}
    write_new(run/'installation-receipt.json',(json.dumps(receipt,indent=2,sort_keys=True)+'\n').encode())
    print(json.dumps(receipt,sort_keys=True))


if __name__=='__main__':
    main()
