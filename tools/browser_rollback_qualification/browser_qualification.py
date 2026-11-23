"""Fixed AFM-9 qualification boundary; common modules own every state transition.

No import has side effects. Published declarations authorize exact delivery bytes;
only a direct authenticated Browser child can establish release authority.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import unicodedata

D = Path('/Users/msix/Builds/afm9-rollback-plan.49cXVsFk')
F = D / 'qualification/fixture'
BIN = D / 'delivery/bin'
PRODUCER = D / 'delivery/browser-producer'
AUTHORITY = D / 'qualification/authority.json'
NODE = Path('/Users/msix/.nvm/versions/node/v24.22.1/bin/node')
NODE_SHA = '6f32069480ec14d52b6d7b1f3c7124cfbbc46203abf5ddf5c65b127435f3f329'
FORESTER = Path('/Users/msix/Artifacts/forester')
ARBOL = Path('/Users/msix/repos/sylvan-stack/arbol')
PLAN = 'sagas/sylvan-stack/arbol-format-2-migration/browser-profile-migration/AFM-9.md'
ROLES = ('historical', 'A', 'B', 'C')
HEX = re.compile(r'[0-9a-f]{64}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}\Z')
BUILD = re.compile(r'[1-9a-f][0-9a-f]{0,15}\Z')
DECIMAL = re.compile(r'(?:0|[1-9][0-9]{0,19})\Z')
SOURCE_FILES = ('README.md','baseline.json','prepare.py','install.py','common.patch','browser_qualification.py')
PROTECTED = tuple(map(Path, (
    '/Users/msix/.arbol', '/Users/msix/Applications/Arbol Browser', '/Users/msix/Applications/Arbol',
    '/Users/msix/.local/lib/sylvan-stack/arbol-browser', '/Users/msix/.local/lib/sylvan-stack/arbol/stable',
    '/Users/msix/Builds/registries', '/Users/msix/repos/sylvan-stack/arbol', '/Users/msix/repos/sylvan-stack/arbol-browser',
    '/Users/msix/Builds/afm9-source-route.qB70OQDO', '/Users/msix/Builds/afm-exchange-release.0XzxD2ml',
    '/Volumes/Mercury/Arbol/backups/browser-build-tool-exchange-baseline-826237f',
    '/Volumes/Mercury/Arbol/backups/browser-format-2-source-route-e32111a7',
))) + (BIN, PRODUCER)
_TOKEN = object()


class Refused(ValueError):
    def __init__(self, code, message, exit_code=3):
        super().__init__(message)
        self.code, self.exit_code = code, exit_code


def require(ok, message, code='authority-refused'):
    if not ok:
        raise Refused(code, message, 2 if code == 'invalid-input' else 3)


def keys(value, names):
    require(type(value) is dict and set(value) == set(names.split()), 'Unexpected object grammar', 'invalid-input')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def strict(raw, limit):
    require(0 < len(raw) <= limit and not raw.startswith(b'\xef\xbb\xbf') and b'\0' not in raw,
            'Invalid JSON encoding or size', 'invalid-input')
    def pairs(items):
        value = dict(items)
        require(len(value) == len(items), 'Duplicate JSON key', 'invalid-input')
        return value
    def invalid(_):
        raise Refused('invalid-input', 'Non-integral JSON number', 2)
    try:
        value = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=pairs,
                           parse_float=invalid, parse_constant=invalid)
        def visit(item, depth=0):
            require(depth <= 16, 'JSON nesting bound exceeded', 'invalid-input')
            if isinstance(item, dict):
                for key, child in item.items(): visit(key, depth+1); visit(child, depth+1)
            elif isinstance(item, list):
                for child in item: visit(child, depth+1)
            elif isinstance(item, str):
                item.encode('utf-8', 'strict')
                require('\0' not in item, 'NUL in JSON string', 'invalid-input')
        visit(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise Refused('invalid-input', 'Invalid bounded JSON', 2) from error


def matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def identity(info):
    return {'device':str(info.st_dev), 'inode':str(info.st_ino), 'uid':info.st_uid, 'mode':stat.S_IMODE(info.st_mode)}


def stamp(info):
    return (info.st_dev,info.st_ino,info.st_uid,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def identity_shape(value):
    keys(value, 'device inode uid mode')
    require(all(matches(DECIMAL, value[k]) and int(value[k]) < 2**64 for k in ('device','inode'))
            and type(value['uid']) is int and value['uid'] >= 0
            and type(value['mode']) is int and 0 <= value['mode'] <= 0o7777, 'Invalid identity')


def canonical(path):
    require(isinstance(path, str) and len(path.encode()) <= 1024 and path.startswith('/')
            and unicodedata.normalize('NFC', path) == path and os.path.normpath(path) == path,
            'Noncanonical absolute path', 'invalid-input')
    return Path(path)


def ancestors(path):
    """Only metadata, never production contents. Preserve lexical spelling."""
    require(path.resolve(strict=True) == path, 'Linked path', 'state-changed')
    for directory in (*reversed(path.parents), path):
        info = directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid in (0, os.getuid()) and not info.st_mode & 0o022,
                'Unsafe path ancestor', 'state-changed')


@contextmanager
def safe_file(path, maximum, mode=None):
    ancestors(path.parent)
    parent = path.parent.stat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid in (0,os.getuid())
                and not info.st_mode & 0o022 and 0 <= info.st_size <= maximum
                and (mode is None or stat.S_IMODE(info.st_mode) == mode), 'Unsafe file', 'state-changed')
        require(stamp(info) == stamp(path.lstat()), 'File changed', 'state-changed')
        yield stream, info
        require(stamp(info) == stamp(os.fstat(fd)) == stamp(path.lstat())
                and os.path.samestat(parent, path.parent.stat()), 'File changed during read', 'state-changed')


def read(path, maximum, mode=None):
    with safe_file(path, maximum, mode) as (stream, info):
        data = stream.read(maximum+1)
        require(len(data) == info.st_size, 'Incomplete read', 'state-changed')
    return data


def reference(path, maximum, mode=None):
    with safe_file(path, maximum, mode) as (stream, info):
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path':str(path), 'identity':identity(info), 'size':str(info.st_size), 'sha256':digest}


def check_reference(value, path, maximum, mode=None):
    keys(value, 'path identity size sha256'); identity_shape(value['identity'])
    require(value['path'] == str(path) and matches(DECIMAL,value['size']) and int(value['size']) <= maximum
            and matches(HEX,value['sha256']), 'Invalid file reference')
    require(reference(path,maximum,mode) == value, 'Pinned file identity or bytes changed', 'pin-mismatch')


def child(argv, payload, cwd, timeout, stdout_limit=65536):
    """Bound both pipes while running; never allocate unbounded communicate output."""
    environment = {'PATH':'/usr/bin:/bin', 'HOME':'/Users/msix', 'LANG':'C.UTF-8', 'GIT_OPTIONAL_LOCKS':'0'}
    process = subprocess.Popen([str(v) for v in argv], cwd=cwd, env=environment,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    buffers = {process.stdout:bytearray(),process.stderr:bytearray()}
    deadline = time.monotonic()+timeout
    try:
        if payload: process.stdin.write(payload)
        process.stdin.close()
        with selectors.DefaultSelector() as selector:
            for stream in buffers:
                os.set_blocking(stream.fileno(),False); selector.register(stream,selectors.EVENT_READ)
            while selector.get_map():
                require(time.monotonic() < deadline, 'Child deadline exceeded; retain operation evidence', 'interrupted')
                for key,_ in selector.select(min(0.25,max(0,deadline-time.monotonic()))):
                    data = os.read(key.fileobj.fileno(),65536)
                    if not data: selector.unregister(key.fileobj); continue
                    buffers[key.fileobj].extend(data)
                    require(len(buffers[key.fileobj]) <= (stdout_limit if key.fileobj is process.stdout else 4096),
                            'Child output bound exceeded', 'authority-refused')
        status = process.wait(timeout=max(0.01,deadline-time.monotonic()))
        require(status == 0, 'Pinned child refused; no no-mutation claim follows', 'installer-refused')
        return bytes(buffers[process.stdout])
    finally:
        if process.poll() is None:
            try: os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait()
        for stream in buffers: stream.close()


def git(repo, *args):
    return child(['/usr/bin/git','--no-replace-objects','-C',repo,*args],b'',repo,30,16*1024*1024)


def published_block(marker, at=None):
    # Locator is fixed; neither request nor a mutable approval file chooses a review.
    tip = at or git(FORESTER,'rev-parse','refs/remotes/origin/main').decode().strip()
    require(matches(COMMIT,tip), 'Missing published Forester identity', 'pin-mismatch')
    text = git(FORESTER,'show',tip+':'+PLAN).decode('utf-8','strict')
    begin,end = '<!-- '+marker+':BEGIN -->','<!-- '+marker+':END -->'
    require(text.count(begin) == text.count(end) == 1, 'Missing unique independently published delivery declaration', 'pin-mismatch')
    block = text.split(begin,1)[1].split(end,1)[0].strip().encode()
    return strict(block,16*1024*1024), tip


def source_admission():
    grant,review = published_block('AFM-9-QUALIFICATION-SOURCE-DELIVERY')
    keys(grant,'schema status scope sourceGit sourceFiles sourceCheckpoint sourceVerdict producerManifestSha256 bootstrap')
    require(type(grant['schema']) is int and grant['schema'] == 1 and grant['status'] == 'accepted'
            and grant['scope'] == 'isolated-tool-source' and matches(COMMIT,grant['sourceGit'])
            and matches(HEX,grant['producerManifestSha256']), 'Invalid source delivery declaration','pin-mismatch')
    require(type(grant['sourceFiles']) is dict and set(grant['sourceFiles']) == set(SOURCE_FILES)
            and all(matches(HEX,v) for v in grant['sourceFiles'].values()), 'Incomplete overlay source map','pin-mismatch')
    git(ARBOL,'merge-base','--is-ancestor',grant['sourceGit'],'refs/remotes/origin/main')
    for name,want in grant['sourceFiles'].items():
        path='tools/browser_rollback_qualification/'+name
        require(sha(git(ARBOL,'show',grant['sourceGit']+':'+path)) == want,'Published overlay source mismatch','pin-mismatch')
    for field in ('sourceCheckpoint','sourceVerdict'):
        ref=grant[field]
        require(canonical(ref['path']).is_relative_to(Path('/Users/msix/Builds')), 'Review evidence outside private handoff')
        check_reference(ref,canonical(ref['path']),16*1024*1024)
    keys(grant['bootstrap'],'python uv')
    for ref in grant['bootstrap'].values():
        check_reference(ref,canonical(ref['path']),256*1024*1024)
        require(ref['identity']['mode'] & 0o111, 'Bootstrap is not executable')
    return grant, review


def tree_map(root):
    """Complete installed/importable tree; links must remain inside this sealed root."""
    ancestors(root)
    result={}
    for parent,dirs,files in os.walk(root,followlinks=False):
        for name in sorted(dirs+files):
            path=Path(parent)/name; relative=str(path.relative_to(root)); info=path.lstat()
            require(len(result)<65536 and len(relative.encode())<=512,'Delivery tree exceeds bound','pin-mismatch')
            require(info.st_uid in (0,os.getuid()),'Unsafe delivery owner','pin-mismatch')
            if stat.S_ISLNK(info.st_mode):
                require(path.resolve(strict=True).is_relative_to(root),'Escaping delivery link','pin-mismatch')
                result[relative]={'kind':'link','target':os.readlink(path)}
            elif stat.S_ISDIR(info.st_mode):
                require(not info.st_mode&0o022,'Writable delivery directory','pin-mismatch')
                result[relative]={'kind':'directory','mode':stat.S_IMODE(info.st_mode)}
            else:
                require(stat.S_ISREG(info.st_mode) and not info.st_mode&0o022,'Unsupported delivery member','pin-mismatch')
                result[relative]={'kind':'file','mode':stat.S_IMODE(info.st_mode),'sha256':reference(path,1024**3)['sha256']}
    return dict(sorted(result.items()))


def delivery():
    grant,review=source_admission()
    raw=read(D/'delivery/producer-manifest.json',16*1024*1024,0o600)
    require(sha(raw)==grant['producerManifestSha256'],'Producer manifest not admitted','pin-mismatch')
    producer=strict(raw,16*1024*1024)
    keys(producer,'schema kind sourceGit files compileRecord productSources productOutputs compilerInputs roleReviews executables osVersion')
    require(type(producer['schema']) is int and producer['schema']==1 and producer['kind']=='afm9-browser-producer'
            and matches(COMMIT,producer['sourceGit']), 'Invalid producer manifest','pin-mismatch')
    for field in ('compileRecord','productSources','productOutputs','compilerInputs','roleReviews'):
        require(type(producer[field]) is dict and 0<len(producer[field])<=65536,'Missing complete producer admission map','pin-mismatch')
    require(producer['files']==tree_map(PRODUCER),'Producer tree drift','pin-mismatch')
    require(producer['osVersion']=={'macOS':platform.mac_ver()[0], 'kernel':os.uname().release,
                                    'machine':os.uname().machine},'OS version drift','pin-mismatch')
    keys(producer['executables'],'node codesign hdiutil diskutil plutil git')
    toolraw=read(D/'delivery/tool-manifest.json',16*1024*1024,0o600)
    runtime, runtime_review=published_block('AFM-9-QUALIFICATION-RUNTIME-DELIVERY')
    keys(runtime,'schema status scope sourceReview toolManifestSha256 producerManifestSha256')
    require(type(runtime['schema']) is int and runtime['schema']==1 and runtime['status']=='accepted'
            and runtime['scope']=='isolated-tool-runtime' and matches(COMMIT,runtime['sourceReview'])
            and runtime['toolManifestSha256']==sha(toolraw) and runtime['producerManifestSha256']==sha(raw),
            'Missing exact runtime delivery acceptance','pin-mismatch')
    git(FORESTER,'merge-base','--is-ancestor',runtime['sourceReview'],runtime_review)
    source_at_review,_=published_block('AFM-9-QUALIFICATION-SOURCE-DELIVERY',runtime['sourceReview'])
    require(source_at_review==grant,'Runtime review names a different source delivery declaration','pin-mismatch')
    tool=strict(toolraw,16*1024*1024)
    keys(tool,'schema kind sourceGit sourceFiles files executables pythonArchiveSha256')
    require(type(tool['schema']) is int and tool['schema']==1 and tool['kind']=='afm9-browser-private-tool'
            and tool['sourceGit']==grant['sourceGit'] and tool['sourceFiles']==grant['sourceFiles']
            and tool['pythonArchiveSha256']=='d15291f940cfecd2e54010d5e37d2e03aa192f076a65d26ab741372fff2dabfe',
            'Tool provenance mismatch','pin-mismatch')
    require(tool['files']==tree_map(BIN),'Installed tool tree drift','pin-mismatch')
    keys(tool['executables'],'python launcher')
    fixed={'node':NODE,'codesign':Path('/usr/bin/codesign'),'hdiutil':Path('/usr/bin/hdiutil'),
           'diskutil':Path('/usr/sbin/diskutil'),'plutil':Path('/usr/bin/plutil'),'git':Path('/usr/bin/git')}
    for name,path in fixed.items(): check_reference(producer['executables'][name],path,256*1024*1024)
    require(producer['executables']['node']['sha256']==NODE_SHA,'Node pin differs','pin-mismatch')
    python=BIN/'.arbol-builds/runtime/3.14.8-d15291f940cf/python/bin/python3.14'
    check_reference(tool['executables']['python'],python,256*1024*1024)
    check_reference(tool['executables']['launcher'],BIN/'arbol-builds',1024*1024,0o755)
    require(Path(sys.executable).resolve()==python.resolve() and Path(sys.argv[0])==BIN/'arbol-builds'
            and Path(__file__)==BIN/'.arbol-builds/arbol_builds/browser_qualification.py'
            and sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,
            'Qualification requires the pinned private installed launcher','pin-mismatch')
    library=BIN/'.arbol-builds'; runtime=python.parents[1]
    allowed={str(library),str(runtime/'lib/python314.zip'),str(runtime/'lib/python3.14'),
             str(runtime/'lib/python3.14/lib-dynload')}
    require(set(sys.path)<=allowed and str(library) in sys.path,'Ambient Python import path','pin-mismatch')
    for module in tuple(sys.modules.values()):
        file=getattr(module,'__file__',None)
        if file is not None:
            require(Path(file).is_absolute() and Path(file).resolve().is_relative_to(BIN),
                    'Module loaded outside pinned installation','pin-mismatch')
    return sha(toolraw),sha(raw)


def authority():
    raw=read(AUTHORITY,16384,0o600); value=strict(raw,16384)
    keys(value,'schema kind releases'); keys(value['releases'],'historical A B C')
    require(type(value['schema']) is int and value['schema']==1 and value['kind']=='afm9-browser-rollback-qualification','Invalid authority')
    for role in ROLES:
        row=value['releases'][role]; keys(row,'image signedReceipt review')
        root=D/'qualification/artifacts'/role
        require(row['image']==str(root/'ArbolBrowser.dmg') and row['signedReceipt']==str(root/'signed-release.json')
                and matches(COMMIT,row['review']), 'Invalid fixed release input')
    return value,sha(raw)


def producer_verify(auth,auth_sha,producer_sha):
    raw=child([NODE,PRODUCER/'scripts/isolated-release.mjs','qualification-verify-v1'],
              encode({'schema':1,'action':'verify','authoritySha256':auth_sha})+b'\n',PRODUCER,600)
    require(raw.endswith(b'\n') and raw.count(b'\n')==1,'Producer must emit one JSON line')
    value=strict(raw,65536); keys(value,'schema authoritySha256 producerManifestSha256 fixture releases')
    require(type(value['schema']) is int and value['schema']==1 and value['authoritySha256']==auth_sha
            and value['producerManifestSha256']==producer_sha,'Producer identity chain differs')
    fixture=value['fixture']; keys(fixture,'root directories')
    require(fixture['root']==str(F),'Wrong signed root')
    keys(fixture['directories'],'fixture support registry uses runtime stateParent bin')
    for row in fixture['directories'].values(): identity_shape(row)
    keys(value['releases'],'historical A B C'); builds=[]; inodes=set()
    for role in ROLES:
        row=value['releases'][role]
        keys(row,'role build source sourceDigest productDigest payloadDigest profileFormat review reviewDigest signedReceipt image launcherSha256 launcherRole liveMode')
        require(row['role']==role and matches(BUILD,row['build']) and matches(COMMIT,row['source'])
                and row['review']==auth['releases'][role]['review'] and type(row['profileFormat']) is int
                and row['profileFormat']==(1 if role=='historical' else 2)
                and row['launcherRole']==('historical-launcher' if role=='historical' else 'isolated-maintenance-launcher')
                and type(row['liveMode']) is int and row['liveMode']==(0o755 if role=='historical' else 0o700)
                and all(matches(HEX,row[k]) for k in ('sourceDigest','productDigest','payloadDigest','reviewDigest','launcherSha256')),
                'Invalid authenticated release view')
        builds.append(int(row['build'],16))
        for field,limit in (('image',1024**3),('signedReceipt',8*1024**2)):
            check_reference(row[field],Path(auth['releases'][role][field]),limit,0o600)
            inode=(row[field]['identity']['device'],row[field]['identity']['inode'])
            require(inode not in inodes,'Duplicate release input inode'); inodes.add(inode)
    require(builds[0]==1 and builds==sorted(set(builds)) and len(builds)==4
            and value['releases']['A']['source']!=value['releases']['B']['source']
            and value['releases']['C']['source']!=value['releases']['B']['source'], 'Invalid genuine release cohort')
    require(sha(read(AUTHORITY,16384,0o600))==auth_sha,'Authority changed','state-changed')
    return value


class Context:
    """Private custody and policy only; no rollback/catalog algorithm lives here."""
    def __init__(self, token, view, *, read_only=False):
        require(token is _TOKEN,'Unauthenticated context')
        self._view=encode(view)
        self.root=F; self.support=F/'support'; self.registries=self.support/'build-tool/registries'
        self.registry=self.registries/'arbol/arbol-browser'; self.uses=F/'arbol-browser/.uses'
        self.launcher=F/'bin/arbol-browser'; self.alias=F/'aliases/arbol-browser'
        self._dirs={}; self._guards=[]; self._reads={}; self._absent=set(); self._inventories={}; self._assets={}
        self._stable=False; self._custody=None; self._catalog=False; self._pending=None; self._temporary=None
        self._read_only=read_only
        self._releases={row['build']:row for row in view['releases'].values()}
        try:
            normalized=lambda p:unicodedata.normalize('NFC',str(p)).casefold().rstrip('/')
            root=normalized(F)
            for protected in PROTECTED:
                other=normalized(protected.resolve(strict=False))
                require(root!=other and not root.startswith(other+'/') and not other.startswith(root+'/'),'Fixture overlaps protected tree')
                if protected.exists():
                    require(not os.path.samestat(F.stat(),protected.stat()),'Fixture shares protected inode')
            named={'fixture':F,'support':self.support,'registry':F/'arbol-browser','uses':self.uses,
                   'runtime':F/'runtime','stateParent':F/'state','bin':F/'bin'}
            seen=set()
            for name,path in named.items():
                fd=self.directory(path)
                info=os.fstat(fd); ident=identity(info)
                require(ident==view['fixture']['directories'][name],'Signed directory changed','state-changed')
                inode=(info.st_dev,info.st_ino); require(inode not in seen,'Aliased signed directories'); seen.add(inode)
                for protected in PROTECTED:
                    if protected.exists():
                        require(not os.path.samestat(info,protected.stat()),'Signed directory aliases protected inode')
            self.directory(F/'state/browser')
            self.directory(F/'aliases')
            self.directory(self.support/'images'); self.directory(self.support/'releases')
            # Keep the authenticated original artifact inodes alive throughout
            # this invocation. They can never be replaced by our mutations.
            for row in view['releases'].values():
                for field,limit in (('image',1024**3),('signedReceipt',8*1024**2)):
                    ref=row[field]; path=Path(ref['path'])
                    with safe_file(path,limit,0o600) as (stream,info):
                        require(identity(info)==ref['identity'] and str(info.st_size)==ref['size']
                                and hashlib.file_digest(stream,'sha256').hexdigest()==ref['sha256'],
                                'Artifact changed after producer verification','state-changed')
                        self._assets[path]=(os.dup(stream.fileno()),stamp(info))
        except BaseException:
            self.close(); raise

    def close(self):
        self.temporary_closed()
        self.clear_reads()
        for fd,_ in self._assets.values(): os.close(fd)
        self._assets.clear()
        for fd in self._dirs.values(): os.close(fd)
        self._dirs.clear()

    def clear_reads(self):
        for fd,_ in self._reads.values(): os.close(fd)
        self._reads.clear()
        self._absent.clear()
        self._inventories.clear()

    def retain(self,path,fd,info):
        previous=self._reads.get(path)
        if previous is not None:
            require(stamp(info)==previous[1],'Read identity changed','state-changed')
        else:
            self._reads[path]=(os.dup(fd),stamp(info))

    def directory(self,path,create=False):
        require(not create or not self._read_only,'Read-only verification cannot initialize private state')
        require(path==F or path.is_relative_to(F),'Directory outside fixture')
        if path in self._dirs:
            self.revalidate(); return self._dirs[path]
        if path==F:
            ancestors(F.parent); parent=None; name=str(F)
        else:
            parent=self.directory(path.parent); name=path.name
        if create:
            require(self._stable or path in (self.support/'build-tool',self.registries,self.registries/'arbol',self.registry),
                    'Creation outside stable custody')
            try: os.mkdir(name,0o700,dir_fd=parent)
            except FileExistsError: pass
        fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
        info=os.fstat(fd)
        if not (info.st_uid==os.getuid()==os.geteuid() and stat.S_IMODE(info.st_mode)==0o700
                and (path==F or info.st_dev==os.fstat(self._dirs[F]).st_dev)):
            os.close(fd); raise Refused('state-changed','Unsafe private directory')
        require(os.path.samestat(info,path.lstat()),'Directory changed','state-changed')
        self._dirs[path]=fd
        return fd

    def revalidate(self):
        try:
            for path,fd in self._dirs.items():
                info=os.fstat(fd)
                require(os.path.samestat(info,path.lstat()) and stat.S_IMODE(info.st_mode)==0o700
                        and info.st_uid==os.getuid(),'Held directory replaced','state-changed')
            for path,fd,expected in self._guards:
                require(stamp(os.fstat(fd))==expected==stamp(path.lstat()),'Held guard replaced','state-changed')
            for path,(fd,expected) in (*self._reads.items(),*self._assets.items()):
                require(stamp(os.fstat(fd))==stamp(path.lstat())==expected,
                        'Observed file changed before mutation','state-changed')
            for path in self._absent:
                require(not os.path.lexists(path),'Previously absent entry appeared','state-changed')
            for path,names in self._inventories.items():
                expected=set(names)
                if self._temporary is not None and self._temporary[0].parent==path:
                    temporary,fd=self._temporary
                    info=os.fstat(fd)
                    require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid()
                            and os.path.samestat(info,temporary.lstat()),'Own temporary inode changed','state-changed')
                    expected.add(temporary.name)
                require(set(os.listdir(self._dirs[path]))==expected,'Observed archive membership changed','state-changed')
        except FileNotFoundError as error:
            raise Refused('state-changed','A retained path disappeared') from error

    @contextmanager
    def file(self,path,mode=0o600,maximum=1024**3):
        parent=self.directory(path.parent); self.revalidate()
        try: fd=os.open(path.name,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW,dir_fd=parent)
        except FileNotFoundError:
            if self._stable: self._absent.add(path)
            raise
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1
                    and stat.S_IMODE(info.st_mode)==mode and 0<=info.st_size<=maximum,'Unsafe fixture file','state-changed')
            require(stamp(info)==stamp(path.lstat()),'Fixture file changed','state-changed')
            yield stream,info
            require(stamp(info)==stamp(os.fstat(fd))==stamp(path.lstat()),'Fixture file changed during read','state-changed')
            self.revalidate()
            if self._stable:
                self.retain(path,fd,info)

    def document(self,path,maximum=16384):
        with self.file(path,maximum=maximum) as (stream,_): raw=stream.read(maximum+1)
        value=strict(raw,maximum); require(type(value) is dict,'Invalid fixture document')
        return value,sha(raw)

    def digest(self,path,maximum,mode=0o600):
        with self.file(path,mode,maximum) as (stream,_): return hashlib.file_digest(stream,'sha256').hexdigest()

    def optional_reference(self,path,maximum):
        try:
            with self.file(path,maximum=maximum) as (stream,info):
                digest=hashlib.file_digest(stream,'sha256').hexdigest()
                return {'path':str(path),'identity':identity(info),'size':str(info.st_size),'sha256':digest}
        except FileNotFoundError: return None

    def observe_optional(self,path,maximum=16384,mode=0o600):
        try:
            with self.file(path,mode,maximum): pass
        except FileNotFoundError: pass

    @contextmanager
    def lock(self,path,create=False):
        parent=self.directory(path.parent)
        if create:
            try:
                fd=os.open(path.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
            except FileExistsError: pass
            else: os.close(fd); os.fsync(parent)
        with self.file(path,maximum=4096) as (stream,info):
            try: fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error: raise Refused('busy','Fixture is busy',4) from error
            self._guards.append((path,stream.fileno(),stamp(info)))
            try: self.revalidate(); yield
            finally: self._guards.pop()

    @contextmanager
    def operation(self,component):
        require(component=='arbol-browser' and not self._stable,'Invalid stable operation')
        for path in (self.support/'build-tool',self.registries,self.registries/'arbol',self.registry): self.directory(path,create=not self._read_only)
        with self.lock(self.registry/'.stable-promotion.lock',create=not self._read_only):
            self._stable=True
            try: yield self.registry
            finally:
                self._stable=False
                self.clear_reads()

    @contextmanager
    def custody(self,builds=()):
        require(self._stable,'Selection custody requires stable component lock')
        wanted=set(b for b in builds if b is not None)
        require(wanted<=set(self._releases),'Unknown Build guard')
        if self._custody is not None:
            require(wanted<=self._custody,'Nested custody cannot widen held guards')
            self.revalidate(); yield; self.revalidate(); return
        with ExitStack() as stack:
            stack.enter_context(self.lock(self.support/'selection.lock'))
            selected,_=self.document(self.support/'selected.json',4096)
            keys(selected,'format build imageSha256')
            require(type(selected['format']) is int and selected['format']==1 and selected['build'] in self._releases,'Unknown selected Build')
            wanted.add(selected['build'])
            for build in sorted(wanted): stack.enter_context(self.lock(self.uses/build))
            self._custody=frozenset(wanted)
            try:
                yield
                self.revalidate()
            finally:
                self._custody=None
                # A real installer may replace mutable entries after custody is
                # released. No previous observation survives that handoff.
                self.clear_reads()

    @contextmanager
    def catalog_lock(self):
        require(self._custody is not None and not self._catalog,'Catalog lock order violated')
        with self.lock(self.registries/'.stable-catalog.lock',create=True):
            self._catalog=True
            try: yield
            finally: self._catalog=False

    def check_receipt(self,receipt):
        require(type(receipt['format']) is int,'Invalid receipt format')
        row=self._releases.get(receipt['build']); require(row is not None,'Receipt outside cohort')
        require(receipt=={'format':1,'build':row['build'],'imageSha256':row['image']['sha256'],
                         'source':row['source'],'payloadDigest':row['payloadDigest'],'launcherSha256':row['launcherSha256']},
                'Installed receipt differs from signed release')

    def launcher_release(self,digest):
        rows=[r for r in self._releases.values() if r['launcherSha256']==digest]
        require(len(rows)==1,'Launcher digest not uniquely bound to admitted role')
        return rows[0]

    def requirement(self,digest):
        row=self.launcher_release(digest)
        identifier='com.sylvan-stack.arbol-browser.'+('launcher' if row['role']=='historical' else 'isolated-maintenance-launcher')
        return ('anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] exists '
                'and certificate leaf[field.1.2.840.113635.100.6.1.13] exists '
                'and certificate leaf[subject.OU] = "7V372XL59S" and identifier "'+identifier+'"')

    def live_mode(self,digest): return self.launcher_release(digest)['liveMode']
    def file_mode(self,path,digest): return self.live_mode(digest) if path==self.launcher else 0o755
    def verify_signature(self,path,digest):
        # Reopen the exact bytes after the OS verifier too; no signature result
        # survives a changed pathname or content identity.
        with self.file(path,self.file_mode(path,digest),64*1024**2) as (stream,_):
            require(hashlib.file_digest(stream,'sha256').hexdigest()==digest,'Launcher bytes differ')
            child(['/usr/bin/codesign','--verify','--strict','-R','='+self.requirement(digest),path],
                  b'',F,120)

    def require_archive(self,path):
        require(path.parent==self.support/'rollback-launchers' and path.name in self._releases,'Unknown archive path')
        require(os.path.lexists(path),'Active rollback launcher is unavailable','archive-unavailable')
    def observed_live_mode(self):
        info=self.launcher.lstat(); mode=stat.S_IMODE(info.st_mode)
        require(mode in (0o700,0o755),'Invalid live mode'); return mode

    def check_failure(self,value,build):
        keys(value,'status sourceCommit reason failedAt restoredBuild')
        require(build in self._releases and value['status']=='failed' and value['sourceCommit']==self._releases[build]['source']
                and value['restoredBuild'] in self._releases and int(value['restoredBuild'],16)<int(build,16)
                and isinstance(value['failedAt'],str) and len(value['failedAt'])<=64,'Invalid deployment failure')
        reason(value['reason'])

    def check_failure_ledger(self):
        path=self.registry/'.failed-deployments.json'
        try: value,_=self.document(path,1024**2)
        except FileNotFoundError: return
        keys(value,'schemaVersion builds')
        require(type(value['schemaVersion']) is int and value['schemaVersion']==1 and type(value['builds']) is dict
                and len(value['builds'])<=4,'Invalid failure ledger')
        for build,row in value['builds'].items(): self.check_failure(row,build)

    def failures(self,component):
        from .launcher import deployment_failures
        require(component=='arbol-browser','Foreign failure registry')
        self.check_failure_ledger()
        path=self.registry/'.failed-deployments.json'
        try:
            with self.file(path,maximum=1024**2) as (stream,_):
                before=stream.read(); result=deployment_failures(str(self.registries/'arbol'),component)
                stream.seek(0); require(stream.read()==before,'Ledger changed','state-changed')
                require(result==strict(before,1024**2)['builds'],'Failure parser disagrees')
                return result
        except FileNotFoundError:
            require(not os.path.lexists(path),'Ledger appeared','state-changed'); return {}

    def catalog_document(self):
        value,_=self.document(self.registries/'stable-builds.json',1024**2)
        keys(value,'schemaVersion builds')
        require(type(value['schemaVersion']) is int and value['schemaVersion']==1 and type(value['builds']) is list
                and len(value['builds'])<=4,'Invalid private catalog')
        seen=set()
        for row in value['builds']:
            require(type(row) is dict and set(row) in ({'component','build','timestamp','timestampSource','description','current'},
                    {'component','build','timestamp','timestampSource','description','current','deploymentFailure'})
                    and row['component']=='arbol-browser' and row['build'] in self._releases and row['build'] not in seen
                    and type(row['current']) is bool and row['timestampSource']=='installReceipt'
                    and isinstance(row['timestamp'],str) and len(row['timestamp'])<=64
                    and row['description']=='Arbol Browser','Invalid private catalog row')
            seen.add(row['build'])
            if 'deploymentFailure' in row: self.check_failure(row['deploymentFailure'],row['build'])
        return value

    def archive_inventory(self):
        directory=self.support/'rollback-launchers'
        if not os.path.lexists(directory): return
        self.directory(directory)
        retired=self.support/'pre-format-2-rollback-launchers'
        if os.path.lexists(retired):
            self.directory(retired)
            require(not os.path.samestat(directory.lstat(),retired.lstat()),'Active archive aliases retired inode')
        names=os.listdir(self._dirs[directory]); require(len(names)<=4096,'Archive entry bound exceeded')
        total=0
        from .browser_rollback import signed_launcher
        for name in names:
            require(name in self._releases,'Unknown active archive member')
            if os.path.lexists(retired): require(self._releases[name]['profileFormat']==2,'Historical active archive after retirement')
            data=signed_launcher(directory/name,self._releases[name]['launcherSha256'],self)
            total+=len(data); require(total<=256*1024**2,'Archive byte bound exceeded')
        self._inventories[directory]=tuple(sorted(names))
        self.revalidate()

    @contextmanager
    def publication(self,path):
        require(self._stable and self._custody is not None and self._pending is None,'Mutation without custody')
        allowed={self.launcher,self.support/'selected.json',self.support/'install-transaction.json',
                 self.support/'install-previous-launcher',self.registry/'.failed-deployments.json',self.registries/'stable-builds.json'}
        archive=path.parent==self.support/'rollback-launchers' and path.name in self._releases
        require(path in allowed or archive,'Mutation outside bounded interface')
        require(path!=self.registries/'stable-builds.json' or self._catalog,'Catalog publication without lock')
        parent=self.directory(path.parent); self.revalidate()
        if os.path.lexists(path):
            mode=self.observed_live_mode() if path==self.launcher else (0o755 if archive or path.name=='install-previous-launcher' else 0o600)
            with self.file(path,mode) as (_,info): expected=stamp(info)
        else: expected=None
        self._pending=(path,expected)
        try:
            yield parent
            self._absent.discard(path)
            if path.parent in self._inventories:
                names=set(self._inventories[path.parent])
                if os.path.lexists(path): names.add(path.name)
                else: names.discard(path.name)
                self._inventories[path.parent]=tuple(sorted(names))
            previous=self._reads.pop(path,None)
            if previous: os.close(previous[0])
            if os.path.lexists(path):
                fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
                try:
                    info=os.fstat(fd)
                    require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1
                            and not info.st_mode&0o022 and stamp(info)==stamp(path.lstat()),'Unsafe published file','state-changed')
                    self.retain(path,fd,info)
                finally: os.close(fd)
            self.revalidate()
        finally:
            self.temporary_closed()
            self._pending=None

    def temporary_created(self,name,fd):
        require(self._pending is not None and self._temporary is None,'Unexpected temporary publication')
        path=self._pending[0]
        require(Path(name).name==name and name.startswith(path.name+'.'+str(os.getpid())+'.') and name.endswith('.tmp'),
                'Temporary outside exact publication')
        temporary=path.parent/name; info=os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid()
                and os.path.samestat(info,temporary.lstat()),'Unsafe exclusive temporary')
        self._temporary=(temporary,os.dup(fd))

    def temporary_closed(self):
        if self._temporary is not None:
            os.close(self._temporary[1]); self._temporary=None

    def before_replace(self,contents=None,mode=None):
        self.revalidate(); path,expected=self._pending
        actual=stamp(path.lstat()) if os.path.lexists(path) else None
        require(actual==expected,'Publication target changed','state-changed')
        if contents is not None:
            require(self._temporary is not None,'Missing exclusive temporary')
            temporary,fd=self._temporary; info=os.fstat(fd)
            require(info.st_size==len(contents) and stat.S_IMODE(info.st_mode)==mode
                    and stamp(info)==stamp(temporary.lstat()),'Temporary identity changed','state-changed')
            # The common writer opens this FD write-only; independently reopen
            # its exact retained inode for the final byte check.
            with self.file(temporary,mode,len(contents)) as (stream,current):
                require(os.path.samestat(info,current) and hashlib.file_digest(stream,'sha256').hexdigest()==sha(contents),
                        'Temporary bytes differ','state-changed')
            observed=self._reads.pop(temporary,None)
            if observed: os.close(observed[0])

    def unlink(self,path,missing_ok=False):
        require(path in (self.support/'install-transaction.json',self.support/'install-previous-launcher'),'Unlink outside legacy transaction')
        with self.publication(path) as parent:
            self.before_replace()
            try: os.unlink(path.name,dir_fd=parent)
            except FileNotFoundError:
                if not missing_ok: raise
            os.fsync(parent)


def reason(value):
    require(isinstance(value,str) and 1<=len(value.encode('utf-8'))<=1024
            and all(c==' ' or (c.isprintable() and not c.isspace()) for c in value),'Invalid failure reason','invalid-input')


def request(path):
    path=canonical(path)
    require(path.parent==D/'requests' and path.name not in ('','.','..'),'Request outside fixed directory','invalid-input')
    require(stat.S_IMODE(path.parent.stat().st_mode)==0o700 and path.parent.stat().st_uid==os.getuid()
            and path.lstat().st_uid==os.getuid(),'Unsafe request owner or directory','invalid-input')
    raw=read(path,16384,0o600); value=strict(raw,16384)
    action=value.get('action') if type(value) is dict else None
    if action in ('verify','catalog','archive'): keys(value,'schema action')
    elif action=='rollback':
        keys(value,'schema action from to reason')
        require(value['from']=='B' and value['to'] in ('historical','A'),'Invalid rollback roles','invalid-input'); reason(value['reason'])
    elif action=='forward':
        keys(value,'schema action to'); require(value['to']=='C','Invalid forward role','invalid-input')
    else: raise Refused('invalid-input','Unknown action',2)
    require(type(value['schema']) is int and value['schema']==1,'Unsupported request schema','invalid-input')
    return value,sha(raw)


def perform(req,request_sha):
    from .browser_rollback import archive_launcher
    from .promotion import stable_lock
    from .rollback import rollback
    from .service import check_stable_source, installed_browser_selection
    from .stable_catalog import refresh
    tool_sha,producer_sha=delivery()
    auth,auth_sha=authority(); view=producer_verify(auth,auth_sha,producer_sha)
    context=Context(_TOKEN,view,read_only=req['action']=='verify'); failure=None; expected_selected=None
    releases=view['releases']; action=req['action']
    try:
        if action=='rollback':
            outcome=rollback('arbol-browser',releases['B']['build'],req['reason'],to=releases[req['to']]['build'],context=context)
            failure=outcome['deploymentFailure']
            expected_selected=outcome['stableBuild']
        else:
            with stable_lock(F,'arbol-browser',context):
                if action=='forward':
                    with context.custody():
                        current=installed_browser_selection(F,context)
                        require(current and current['build']==releases['A']['build'],'Forward requires restored A','ineligible-source')
                        failures=context.failures('arbol-browser')
                        require(releases['B']['build'] in failures,'Forward requires actual B failure','ineligible-source')
                        check_stable_source(F,'arbol-browser',releases['C']['source'],context)
                        require(releases['C']['build'] not in failures,'C is failed','ineligible-source')
                    raw=child([NODE,PRODUCER/'scripts/install-release.mjs','qualification-forward-v1'],
                        encode({'schema':1,'action':'forward','authoritySha256':auth_sha})+b'\n',PRODUCER,31*60)
                    require(raw.endswith(b'\n') and raw.count(b'\n')==1,'Installer must emit one JSON line','installer-refused')
                    result=strict(raw,65536)
                    keys(result,'schema authoritySha256 selected')
                    require(type(result['schema']) is int and result['schema']==1 and result['authoritySha256']==auth_sha
                            and result['selected']==releases['C']['build'],'Installer result differs','installer-refused')
                with context.custody():
                    selected=installed_browser_selection(F,context)
                    require(selected is not None,'No actually installed historical/current selection')
                    expected_selected=selected['build']
                    if action=='forward':
                        require(selected['build']==releases['C']['build'],'C was not selected','installer-refused')
                        require(context.failures('arbol-browser')==failures,'Failure quarantine changed during forward','state-changed')
                    context.archive_inventory()
                    if action=='archive': archive_launcher(F,context)
                    if action in ('catalog','forward'): refresh(F,context)
        # Observe results under a fresh component/selection/use custody interval.
        with stable_lock(F,'arbol-browser',context),context.custody():
            selected=installed_browser_selection(F,context)
            require(selected is not None and selected['build']==expected_selected,'Selection changed before result','state-changed')
            context.check_failure_ledger()
            catalog=context.registries/'stable-builds.json'; ledger=context.registry/'.failed-deployments.json'
            result={'schema':1,'action':action,'requestSha256':request_sha,'authoritySha256':auth_sha,
                    'toolManifestSha256':tool_sha,'producerManifestSha256':producer_sha,
                    'disposition':{'verify':'verified','catalog':'cataloged','archive':'archived','rollback':'rolled-back','forward':'forward-selected'}[action],
                    'fixture':view['fixture'],'releases':releases,'selected':selected['build'],
                    'catalog':context.optional_reference(catalog,1024**2),
                    'failureLedger':context.optional_reference(ledger,1024**2),'deploymentFailure':failure}
            require(sha(read(AUTHORITY,16384,0o600))==auth_sha,'Authority changed','state-changed')
            require(delivery()==(tool_sha,producer_sha),'Delivery changed','pin-mismatch')
            return result
    finally: context.close()


def entry(args):
    req=None; digest=None
    try:
        require(len(args)==2 and args[0]=='--request','Usage: browser-release qualification --request <fixed-request-file>','invalid-input')
        req,digest=request(args[1]); result=perform(req,digest); status=0
    except (Refused,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        code=error.code if isinstance(error,Refused) else 'state-changed'
        status=error.exit_code if isinstance(error,Refused) else 5
        result={'schema':1,'action':req['action'] if req else None,'requestSha256':digest,'code':code,
                'message':str(error)[:1024] if isinstance(error,Refused) else 'Qualification incomplete; retain protected before/after evidence'}
    data=encode(result)+b'\n'
    require(len(data)<=65536,'Result exceeded bound')
    sys.stdout.buffer.write(data); sys.stdout.buffer.flush()
    return status
