"""Rehearse the packaged importer using prepared, disposable Chat Session copies.

Run with the candidate's Python. Put its src, runtime/site-packages, tests
and database directories ahead of this checkout on PYTHONPATH, then use
`python -B -m tools.session_import_rehearsal --candidate ... --prior ...
--inputs ...`. Inputs must be a private, prepared HOME under /private/tmp
containing only the reader-approved files and a consistent SQLite copy for
Codex and Mimo. The program never stages captures from a native HOME.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import stat
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from arbol_backend.model import Refused
from arbol_import import command
from arbol_import.mapping import JsonObject
from arbol_import.readers.claude_code import _archive_name
from arbol_import.readers.form import TOOLS, Session, Source, Tool
from arbol_import.readers.lines import open_input
from arbol_import.readers.mimo import catalogue as mimo_catalogue
from tools.backend_journeys import Bridge
from tools.elma_bundle import verify
from tools.session_import_drill import DrillError, owner_only
from tools.session_import_probe import Ledger
from tools.session_import_qualification import Qualification

_TEMP = Path('/private/tmp')
_WORKER = 'ARBOL_IMPORT_REHEARSAL_WORKER'
_SCHEMA = {'compatibilityVersion': 1, 'revision': 5}
_WRITES = {'imported', 'extended', 'rearchived'}


@dataclass(frozen=True)
class Inputs:
    tool: Tool
    home: Path
    driver: Path | None

    def allows(self, file: Path, ledger: Ledger) -> bool:
        if not ledger.eligible(file, dynamic=True):
            return False
        if self.driver is not None and file.is_relative_to(self.driver):
            return True
        relative = file.relative_to(self.home)
        if self.tool == 'claude-code':
            return _archive_name(relative)
        return self.tool != 'kimi-code' or relative.parts[0] != 'locks'


def _private_inputs(path: Path) -> Path:
    path = path.absolute()
    if path.resolve(strict=True) != path or path == _TEMP or not path.is_relative_to(_TEMP):
        raise DrillError('Use a physical input directory under /private/tmp.')
    return owner_only(path)


def _restricted_arguments(options: argparse.Namespace) -> list[str]:
    protected = {Path.home() / name for name in (*command._HOMES.values(), '.arbol')}
    protected.update(path.resolve() for path in tuple(protected))
    protected.add(Path('/Volumes/Mercury'))
    profile = '(version 1)(allow default)'
    profile += ''.join(f'(deny file-read* file-write* (subpath {json.dumps(str(path))}))'
                       for path in sorted(protected))
    profile += f'(deny file-write* (subpath {json.dumps(str(options.inputs))}))'
    return ['/usr/bin/sandbox-exec', '-p', profile, sys.executable, '-B', '-m', 'tools.session_import_rehearsal',
            '--inputs', str(options.inputs), '--candidate', str(options.candidate), '--prior', str(options.prior)]


def _copy_file(root: Path, source: Path, destination: Path) -> None:
    with open_input(root, source.relative_to(root).as_posix()) as saved:
        before = os.fstat(saved.fileno())
        with destination.open('xb') as output:
            shutil.copyfileobj(saved, output)
        after = os.fstat(saved.fileno())
        named = source.lstat()
    if (before.st_nlink != 1 or not os.path.samestat(before, after) or not os.path.samestat(before, named)
            or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns or after.st_ctime_ns != named.st_ctime_ns):
        raise DrillError('Prepared input changed during staging.')
    os.utime(destination, ns=(before.st_mtime_ns, before.st_mtime_ns))
    destination.chmod(0o400)


def _walk_error(error: OSError) -> None:
    raise error


def _copy_inputs(inputs: Path, home: Path) -> None:
    for tool in TOOLS:
        native = inputs / command._HOMES[tool]
        driver_name = command._DRIVER_STATE.get(tool)
        driver = inputs / '.arbol' / 'drivers' / driver_name if driver_name is not None else None
        locations = Inputs(tool, native, driver)
        ledger = Ledger(tool, native, driver)
        for root in (native, driver):
            if root is None or (root == driver and not os.path.lexists(root)):
                continue
            if not root.is_dir() or root.resolve(strict=True) != root:
                raise DrillError('A prepared session or Driver directory is missing or aliased.')
            target = home / root.relative_to(inputs)
            target.mkdir(parents=True, mode=0o700, exist_ok=True)
            aliases = []
            for folder, _, files in root.walk(on_error=_walk_error):
                for name in files:
                    source = folder / name
                    if not locations.allows(source, ledger):
                        raise DrillError('The snapshot contains a file outside the reader-approved inputs.')
                    destination = target / source.relative_to(root)
                    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    if source.is_symlink():
                        physical = source.resolve(strict=True)
                        if (not physical.is_relative_to(root) or not locations.allows(physical, ledger)
                                or not stat.S_ISREG(physical.lstat().st_mode)):
                            raise DrillError('A prepared input alias escapes the approved files.')
                        aliases.append((destination, target / physical.relative_to(root)))
                    else:
                        _copy_file(root, source, destination)
            for link, copied in aliases:
                if not copied.is_file():
                    raise DrillError('A prepared input alias has no copied target.')
                link.symlink_to(os.path.relpath(copied, link.parent))
            for folder, _, _ in target.walk(top_down=False, on_error=_walk_error):
                folder.chmod(0o500)


def _rows(rows: list[JsonObject], *, ignore_chat: bool = False) -> dict[str, JsonObject]:
    result = {}
    for row in rows:
        native = row['native']
        if not isinstance(native, str) or native in result:
            raise DrillError('The importer returned an ambiguous session identity.')
        result[native] = {key: value for key, value in row.items() if not ignore_chat or key != 'chat'}
    return result


def _aggregate(rows: list[JsonObject]) -> list[dict[str, object]]:
    counts = Counter((str(row.get('kind', 'unknown')), str(row.get('outcome', 'unstarted'))) for row in rows)
    return [{'kind': kind, 'outcome': outcome, 'sessions': count}
            for (kind, outcome), count in sorted(counts.items())]


def _fingerprints(run: Qualification) -> Any:
    return run.cluster.value('''
        SELECT json_build_array(
            (SELECT md5(string_agg(p::text, ',' ORDER BY p.tool, p.native_id)) FROM chat_imports p),
            (SELECT md5(string_agg(e::text, ',' ORDER BY e.chat_id, e.turn_key)) FROM exchange_imports e))
    ''')


def _probe(run: Qualification) -> str | None:
    home = run.home / command._HOMES['mimo']
    with TemporaryDirectory(dir=run.root, prefix='mimo-') as work:
        with mimo_catalogue(Source(home, None, Path(work), datetime.now(UTC))) as sessions:
            for entry in sessions:
                item = entry.load()
                if isinstance(item, Session) and item.kind == 'probe' and item.turns and not item.live:
                    return item.native_id
    return None


def _cohort(run: Qualification, tool: Tool, *selection: str) -> dict[str, object]:
    args = (tool, *selection)
    before = _fingerprints(run)
    dry = run.execute(*args, dry=True)
    if dry.archive_bytes or _fingerprints(run) != before:
        raise DrillError('The first dry run changed disposable state.')
    real = run.execute(*args)
    durable = _fingerprints(run)
    replay = run.execute(*args)
    if replay.archive_bytes or _fingerprints(run) != durable:
        raise DrillError('Replay changed disposable provenance or archived bytes.')

    unavailable = run.archive.path.with_name('unavailable-imports')
    run.archive.path.rename(unavailable)
    try:
        again = run.execute(*args, dry=True)
    finally:
        unavailable.rename(run.archive.path)
    if again.archive_bytes or _fingerprints(run) != durable:
        raise DrillError('The archive-independent dry run changed disposable state.')

    real_by_id = _rows(real.sessions)
    replay_by_id = _rows(replay.sessions)
    same_projection = _rows(dry.sessions, ignore_chat=True) == _rows(real.sessions, ignore_chat=True)
    stable_ids = replay_by_id.keys() == real_by_id.keys() and all(
        replay_by_id[native].get('chat') == row.get('chat') and
        replay_by_id[native].get('outcome') == ('unchanged' if row.get('outcome') in _WRITES else row.get('outcome'))
        for native, row in real_by_id.items()
    )
    repeat_without_archive = _rows(again.sessions) == replay_by_id
    complete = (same_projection and stable_ids and repeat_without_archive
                and not any(report.exit_status for report in (dry, real, replay, again)))
    failure_codes = Counter(code for report in (dry, real, replay, again) for row in report.sessions
                            if isinstance(error := row.get('error'), dict)
                            and isinstance(code := error.get('code'), str))
    return {'complete': complete, 'sameProjection': same_projection, 'stableSessions': stable_ids,
            'repeatWithoutArchive': repeat_without_archive, 'firstImport': _aggregate(real.sessions),
            'replay': _aggregate(replay.sessions), 'failureCodes': dict(failure_codes),
            'archiveBytesWritten': real.archive_bytes}


async def _playback(run: Qualification) -> bool:
    with (run.root / 'rehearsal-backend.log').open('xb') as log:
        process = subprocess.Popen([str(run.bin / 'arbol'), '-v', run.candidate.name, 'backend'], env=run.env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            async with asyncio.timeout(25):
                endpoint = run.runtime / 'backend.sock'
                while not endpoint.is_socket():
                    if process.poll() is not None:
                        raise DrillError('The disposable Backend exited during startup.')
                    await asyncio.sleep(0.05)
                bridge = await Bridge.connect(endpoint)
                try:
                    hello = next(event for event in bridge.events if event['type'] == 'hello')
                    if hello['build'] != run.build or hello['installation']['schema'] != _SCHEMA:
                        raise DrillError('The Bridge opened a different Build or schema.')
                    page = await bridge.call('chats.page', {'archived': True, 'limit': 1})
                    if 'result' not in page:
                        raise DrillError('The Bridge refused to read the disposable archive.')
                    for row in page['result']['chats']:
                        if not row['archived'] or not row.get('imported'):
                            raise DrillError('An imported Chat Session has no provenance.')
                        reply = await bridge.call('chat.send', {'chat': row['chat'], 'exchange': str(uuid4())})
                        if reply.get('error', {}).get('code') != 'imported_chat':
                            raise DrillError('The disposable Bridge did not refuse an imported send.')
                        return True
                    return False
                finally:
                    await bridge.close()
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, 10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, 10)


def _rehearse(options: argparse.Namespace) -> dict[str, object]:
    if not (Path(command.__file__).resolve().is_relative_to(options.candidate / 'src')
            and Path(sys.executable).resolve().is_relative_to(options.candidate / 'runtime')):
        raise DrillError('Start the rehearsal with the exact packaged candidate and its interpreter.')
    with TemporaryDirectory(prefix='sir-', dir=_TEMP) as directory:
        root = Path(directory)
        if root.is_relative_to(options.inputs) or options.inputs.is_relative_to(root):
            raise DrillError('Use a source snapshot separate from the disposable installation.')
        run = Qualification(root, options.candidate, options.prior)
        try:
            _copy_inputs(options.inputs, run.home)
            (run.home / 'repos' / 'sylvan-stack').mkdir(parents=True, mode=0o700)
            run.prepare()
            run.upgrade(4, 'prior', bootstrap=True)
            run.upgrade(5, 'candidate')
            renderer = verify(run.candidate / 'ui' / 'elma', run.build)
            cohorts = {tool: _cohort(run, tool) for tool in TOOLS}
            probe = _probe(run)
            probe_result = _cohort(run, 'mimo', '--session', probe, '--include', 'probe') if probe is not None else None
            playback = asyncio.run(_playback(run))
            complete = (playback and all(report['complete'] for report in cohorts.values())
                        and probe_result is not None and bool(probe_result['complete']))
            return {'complete': complete, 'build': run.build, 'source': run.commit, 'schema': _SCHEMA,
                    'rendererBuild': renderer['build'], 'designSource': renderer['designSystem']['commit'],
                    'bridgePlayback': playback,
                    'privateRelease': run.releases['candidate'][1], 'harnesses': cohorts, 'mimoProbe': probe_result}
        finally:
            if not run.cluster.stop():
                raise DrillError('The rehearsal PostgreSQL server did not stop.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--prior', type=Path, required=True)
    options = parser.parse_args()
    try:
        options.inputs = _private_inputs(options.inputs)
        options.candidate = options.candidate.resolve(strict=True)
        options.prior = options.prior.resolve(strict=True)
        if os.environ.get(_WORKER) != '1':
            child = subprocess.run(_restricted_arguments(options), env={**os.environ, _WORKER: '1'}, check=False)
            return child.returncode
        previous_umask = os.umask(0o077)
        try:
            receipt = _rehearse(options)
        finally:
            os.umask(previous_umask)
    except (Refused, OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        print(json.dumps({'complete': False, 'error': 'private_rehearsal_refused'}))
        return 1
    print(json.dumps({**receipt, 'privateCopiesRemoved': True}, sort_keys=True))
    return int(not receipt['complete'])


if __name__ == '__main__':
    raise SystemExit(main())
