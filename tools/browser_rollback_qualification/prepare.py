"""Reconstruct only the reviewed private source; never import the product."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).absolute().parent
CANONICAL = Path('/Users/msix/repos/sylvan-stack/arbol')
BUILDS = Path('/Users/msix/Builds')
FILES = ('README.md', 'baseline.json', 'prepare.py', 'install.py', 'common.patch', 'browser_qualification.py')
LIMIT = 64 * 1024 * 1024
_WITNESSES = {}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict(raw):
    def pairs(items):
        value = dict(items)
        require(len(value) == len(items), 'Duplicate JSON member')
        return value
    def invalid(value):
        raise ValueError('Non-integral JSON number')
    require(b'\0' not in raw and not raw.startswith(b'\xef\xbb\xbf'), 'Invalid JSON encoding')
    value = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=pairs,
                       parse_float=invalid, parse_constant=invalid)
    def depth(item, level=0):
        require(level <= 16, 'JSON nesting exceeds bound')
        if isinstance(item, dict):
            for key, child in item.items():
                require('\0' not in key, 'NUL in key')
                depth(child, level + 1)
        elif isinstance(item, list):
            for child in item:
                depth(child, level + 1)
        elif isinstance(item, str):
            require('\0' not in item, 'NUL in value')
            item.encode('utf-8', 'strict')
    depth(value)
    return value


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def physical(path):
    require(path.is_absolute() and str(path) == os.path.normpath(path), 'Noncanonical path')
    require(path.resolve(strict=True) == path, 'Linked path')
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid in (0, os.getuid())
                and not info.st_mode & 0o022, f'Unsafe source ancestor: {part}')


def read(path, maximum=LIMIT):
    physical(path.parent)
    parent = path.parent.stat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_uid in (0, os.getuid()) and not before.st_mode & 0o022
                and 0 <= before.st_size <= maximum, f'Unsafe source file: {path}')
        require(stamp(before) == stamp(path.lstat()), 'Source changed before read')
        data = stream.read(maximum + 1)
        require(len(data) == before.st_size and stamp(before) == stamp(os.fstat(fd))
                == stamp(path.lstat()) and os.path.samestat(parent, path.parent.stat()), 'Source changed during read')
        witness = (stamp(before), (parent.st_dev, parent.st_ino), sha(data))
        require(_WITNESSES.setdefault(path, witness) == witness, 'Source identity changed between reads')
    return data


def git(repo, *args):
    result = subprocess.run(['/usr/bin/git', '--no-replace-objects', '-C', str(repo), *args],
                            env={'PATH': '/usr/bin:/bin', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'},
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=True)
    require(len(result.stdout) <= LIMIT, 'Git output exceeds bound')
    return result.stdout


def relative(name):
    require(isinstance(name, str) and len(name.encode()) <= 512 and '\\' not in name,
            'Invalid relative source path')
    path = PurePosixPath(name)
    require(str(path) == name and not path.is_absolute() and all(p not in ('', '.', '..', '.git') for p in path.parts),
            'Unsafe relative source path')
    return path


def apply_patch(tree, raw, allowed):
    """Exact unified hunks, never searching, offsetting, or invoking patch/git apply."""
    lines = raw.decode('utf-8', 'strict').splitlines(keepends=True)
    pos, touched = 0, set()
    while pos < len(lines):
        require(lines[pos].startswith('--- a/'), 'Unsupported patch header')
        name = lines[pos][6:].rstrip('\n')
        relative(name)
        require(name in allowed and name not in touched and name in tree, 'Patch target outside scope')
        require(pos + 1 < len(lines) and lines[pos + 1] == '+++ b/' + name + '\n', 'Rename or creation refused')
        pos += 2
        original = tree[name][1].decode('utf-8', 'strict').splitlines(keepends=True)
        output, cursor, count = [], 0, 0
        while pos < len(lines) and lines[pos].startswith('@@ '):
            match = re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n', lines[pos])
            require(match is not None, 'Malformed patch hunk')
            a, an, b, bn = (int(v) if v is not None else 1 for v in match.groups())
            start = a - 1 if an else a
            require(cursor <= start <= len(original), 'Overlapping/out-of-range hunk')
            output.extend(original[cursor:start])
            cursor = start
            require(len(output) == (b - 1 if bn else b), 'Hunk offset refused')
            pos += 1
            removed = added = 0
            while pos < len(lines) and lines[pos][:1] in (' ', '-', '+') and not lines[pos].startswith('--- a/'):
                line = lines[pos]
                mark, text = line[0], line[1:]
                if mark in (' ', '-'):
                    require(cursor < len(original) and original[cursor] == text, 'Hunk old bytes differ')
                    cursor += 1
                    removed += 1
                if mark in (' ', '+'):
                    output.append(text)
                    added += 1
                pos += 1
            require((removed, added) == (an, bn), 'Hunk counts differ')
            count += 1
        require(count > 0, 'Empty patch file')
        output.extend(original[cursor:])
        tree[name] = (tree[name][0], ''.join(output).encode())
        touched.add(name)
    require(touched == set(allowed), 'Patch must name exactly its reviewed targets')


def source_identity(inputs):
    prefix = 'tools/browser_rollback_qualification/'
    # Bind the durable overlay checkpoint, not unrelated later Arbol commits.
    head = git(CANONICAL, 'log', '-1', '--format=%H', 'HEAD', '--', prefix).decode().strip()
    try:
        matched = bool(re.fullmatch(r'[0-9a-f]{40}', head)) and all(
            git(CANONICAL, 'show', head + ':' + prefix + name) == data for name, data in inputs.items())
        published = subprocess.run(['/usr/bin/git', '--no-replace-objects', '-C', str(CANONICAL),
                                    'merge-base', '--is-ancestor', head, 'refs/remotes/origin/main'],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=30).returncode == 0
    except subprocess.CalledProcessError:
        matched = published = False
    return {'commit': head if matched and published else 'unpublished',
            'files': {name: sha(data) for name, data in sorted(inputs.items())}}


def reconstruct():
    _WITNESSES.clear()
    inputs = {name: read(HERE / name) for name in FILES}
    pins = strict(inputs['baseline.json'])
    require(set(pins) == {'schema','historical','migration','received','captures','modules','installer','commonFiles','additive'}
            and type(pins['schema']) is int and pins['schema'] == 1, 'Unknown baseline schema')
    historical = pins['historical']
    repo = Path(historical['repository'])
    commit = historical['commit']
    require(git(repo, 'rev-parse', commit + '^{tree}').decode().strip() == historical['tree'], 'Historical tree mismatch')
    captured = []
    for entry in pins['captures']:
        root = Path(entry['root'])
        data = read(root / 'capture.json')
        require(sha(data) == entry['sha256'], 'Capture pin mismatch')
        declaration = strict(data)
        require(declaration['files'] == entry['files'], 'Capture member map mismatch')
        members = {name: read(root / str(relative(name))) for name in entry['files']}
        require(all(sha(data) == entry['files'][name] for name, data in members.items()), 'Capture member mismatch')
        captured.append(members)
    base, selector = captured
    historical_files = {}
    for row in git(repo, 'ls-tree', '-r', '-z', commit).split(b'\0'):
        if not row:
            continue
        metadata, name = row.split(b'\t')
        mode, kind, oid = metadata.decode().split()
        name = name.decode('utf-8', 'strict')
        relative(name)
        require(kind == 'blob' and mode in ('100644','100755'), 'Unsupported historical tree entry')
        historical_files[name] = (mode, oid)
    tree, seen, total = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(base['tool-source.tar']), mode='r:') as archive:
        for member in archive:
            require(len(seen) < 20000, 'Too many source entries')
            name = member.name.rstrip('/') if member.isdir() else member.name
            relative(name)
            require(name not in seen, 'Duplicate archive entry')
            seen.add(name)
            require(member.isdir() or member.isfile(), 'Unsupported archive entry type')
            if member.isdir():
                continue
            total += member.size
            require(0 <= member.size <= LIMIT and total <= 512*1024*1024, 'Source archive exceeds bound')
            data = archive.extractfile(member).read(member.size + 1)
            mode = '100755' if member.mode & 0o111 else '100644'
            oid = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            require(len(data) == member.size and historical_files.get(name) == (mode, oid), 'Archive differs from historical Git')
            tree[name] = (mode, data)
    require(set(tree) == set(historical_files) and len(tree) == 504, 'Incomplete historical source')
    original = inventory(tree)
    composition = strict(base['tool-source.json'])
    migration = pins['migration']
    require(composition['toolBaseline'] == commit and composition['migrationTip'] == migration['commit'], 'Composition identity mismatch')
    for name, row in composition['scopedFiles'].items():
        require((sha(tree[name][1]) if name in tree else None) == row['baselineSha256'], 'Exchange before mismatch')
        require(sha(git(Path(migration['repository']), 'show', migration['commit'] + ':' + name)) == row['migrationSha256'], 'Migration Git mismatch')
        data = base['overlay/' + name]
        require(sha(data) == row['assembledSha256'], 'Exchange assembled mismatch')
        tree[name] = ('100644', data)
    apply_patch(tree, selector['browser-source-route.patch'], ['src/arbol_builds/cli.py'])
    received = Path(pins['received'])
    require(len(pins['modules']) == 37, 'Expected 37 received modules')
    for name, expected in pins['modules'].items():
        require(sha(tree[name][1]) == expected == sha(read(received / 'source' / name))
                == sha(read(received / 'bin/.arbol-builds' / name.removeprefix('src/'))), 'Received module mismatch: ' + name)
    for name, expected in pins['installer'].items():
        require(sha(tree[name][1]) == expected == sha(read(received / 'source' / name)), 'Installer pin mismatch')
    for name, (mode, data) in tree.items():
        path = received / 'source' / name
        require(read(path) == data and bool(path.stat().st_mode & 0o111) == (mode == '100755'),
                'Received complete source differs: ' + name)
    before = inventory(tree)
    apply_patch(tree, inputs['common.patch'], pins['commonFiles'])
    require(pins['additive'] not in tree, 'Additive module already exists')
    tree[pins['additive']] = ('100644', inputs['browser_qualification.py'])
    after = inventory(tree)
    changed = sorted(name for name in after if after[name] != before.get(name))
    require(set(changed) == set(pins['commonFiles']) | {pins['additive']}, 'Unexpected overlay changes')
    # Reopen every external input after reconstruction, including the received37.
    for entry, members in zip(pins['captures'], captured, strict=False):
        root = Path(entry['root'])
        require(sha(read(root / 'capture.json')) == entry['sha256'], 'Capture changed')
        require(all(read(root / name) == data for name, data in members.items()), 'Captured bytes changed')
    require(all(read(HERE / name) == data for name, data in inputs.items()), 'Canonical overlay changed')
    for name, expected in pins['modules'].items():
        require(expected == sha(read(received / 'source' / name))
                == sha(read(received / 'bin/.arbol-builds' / name.removeprefix('src/'))), 'Received module changed')
    # Exact first-read identity and bytes, not merely a second matching hash.
    # Include every received source file, both installed/source module sets,
    # installer inputs and all canonical/captured declarations.
    for path in tuple(_WITNESSES):
        read(path)
    return tree, {'schema':1, 'status':'prepared-source-only', 'historical':historical,
                  'migration':migration, 'captures':pins['captures'], 'receivedModules':pins['modules'],
                  'installer':pins['installer'], 'overlay':source_identity(inputs), 'historicalFiles':original,
                  'before':before, 'after':after, 'changed':changed, 'qualification':'unexecuted'}


def inventory(tree):
    return {name:{'mode':mode, 'sha256':sha(data)} for name,(mode,data) in sorted(tree.items())}


def run_path(value, exists):
    path = Path(value)
    require(str(path) == value and path.parent == BUILDS and path.name.startswith('afm9-rollback-overlay-')
            and len(path.name) <= 128 and re.fullmatch(r'[A-Za-z0-9.-]+', path.name), 'Invalid source output path')
    physical(BUILDS)
    if exists:
        physical(path)
        info = path.stat()
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, 'Unsafe output directory')
    else:
        require(not os.path.lexists(path), 'Output already exists; retain it and choose a fresh attempt')
    return path


def write_new(path, data, mode=0o600):
    physical(path.parent)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        require(os.path.samestat(os.fstat(parent), path.parent.lstat()), 'Output parent changed')
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)
        require(os.path.samestat(os.fstat(parent), path.parent.lstat()), 'Output parent changed')
    finally:
        os.close(parent)


def verify_prepared(path, tree):
    source = path / 'source'
    physical(source)
    seen = set()
    for parent, dirs, files in os.walk(source, followlinks=False):
        physical(Path(parent))
        require(stat.S_IMODE(Path(parent).stat().st_mode) == 0o700, 'Unsafe prepared directory mode')
        for name in dirs:
            require(not (Path(parent)/name).is_symlink(), 'Linked prepared directory')
        for name in files:
            file = Path(parent)/name
            relative_name = str(file.relative_to(source))
            require(relative_name in tree, 'Extra prepared file')
            mode, data = tree[relative_name]
            require(read(file) == data and stat.S_IMODE(file.stat().st_mode) == (0o755 if mode == '100755' else 0o644), 'Prepared bytes or mode differ')
            seen.add(relative_name)
    require(seen == set(tree), 'Missing prepared file')


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    path = run_path(args.out, False)
    tree, manifest = reconstruct()
    path.mkdir(mode=0o700)
    source = path/'source'
    source.mkdir(mode=0o700)
    held = {path:os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW),
            source:os.open(source,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)}
    def recheck():
        for directory,fd in held.items():
            require(os.path.samestat(os.fstat(fd),directory.lstat()), 'Prepared directory changed')
    try:
        for name, (mode, data) in sorted(tree.items()):
            destination = source/name
            for directory in reversed((destination.parent, *destination.parent.parents)):
                if directory == source or not directory.is_relative_to(source):
                    continue
                if directory not in held:
                    recheck()
                    os.mkdir(directory.name,0o700,dir_fd=held[directory.parent])
                    held[directory]=os.open(directory.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,
                                            dir_fd=held[directory.parent])
            recheck()
            fd=os.open(destination.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,
                       0o755 if mode=='100755' else 0o644,dir_fd=held[destination.parent])
            with os.fdopen(fd,'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            recheck()
        for fd in held.values():
            os.fsync(fd)
    finally:
        for fd in held.values():
            os.close(fd)
    verify_prepared(path, tree)
    # Materialization can take time. Recheck every original input immediately
    # before claiming a completed attempt, with its first-read identity intact.
    for original in tuple(_WITNESSES):
        read(original)
    write_new(path/'source-manifest.json', (json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode())
    print(json.dumps({'status':manifest['status'],'path':str(path),'overlay':manifest['overlay'], 'files':len(tree)}))


if __name__ == '__main__':
    main()
