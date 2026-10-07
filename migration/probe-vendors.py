#!/usr/bin/env python3
"""Record fresh packaged-Python vendor checks without sending inference input."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def snapshot(home: Path) -> dict[str, list[Any]]:
    """Record only file metadata; never read an owner's credential content."""
    roots = [home / '.claude.json']
    for directory, names in [('.claude', ['settings.json', 'settings.local.json', 'config.json', '.credentials.json', 'skills', 'agents', 'commands', 'plugins', 'mcp.json']),
                             ('.codex', ['config.toml', 'auth.json', 'skills', 'mcp.json'])]:
        roots.extend(home / directory / name for name in names)
    result: dict[str, list[Any]] = {}
    def visit(path: Path) -> None:
        relative = str(path.relative_to(home))
        try:
            info = path.lstat()
        except FileNotFoundError:
            result[relative] = ['absent']
            return
        result[relative] = [info.st_mode, info.st_size, info.st_mtime_ns,
                            os.readlink(path) if path.is_symlink() else None]
        if path.is_dir() and not path.is_symlink():
            for child in sorted(path.iterdir()):
                visit(child)
    for root in roots:
        visit(root)
    return result


def shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(item) for item in value]
    if value is None:
        return None
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, str):
        return 'string'
    return 'number'


def call(entry: Path, arguments: list[str], env: dict[str, str], cwd: Path) -> Any:
    result = subprocess.run([str(entry), *arguments], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=90)
    try:
        value = json.loads(result.stdout)
    except ValueError:
        raise ValueError('Python executable returned malformed probe JSON; output withheld') from None
    if result.returncode:
        error = value.get('error', {}) if isinstance(value, dict) else {}
        raise ValueError(f"Python probe failed with exit {result.returncode}, code {error.get('code', 'unknown')}; details withheld")
    return value


def main(arguments: argparse.Namespace) -> int:
    owner = Path.home()
    before = snapshot(owner)
    report: dict[str, Any] = {'issue': 'SYL-95', 'check': 'migration.packaged-python-no-prompt-probes',
                             'at': datetime.now(timezone.utc).isoformat(), 'inferenceRequests': 0, 'drivers': {}}
    try:
        for driver in ('claude', 'codex'):
            entry = Path(getattr(arguments, driver)).resolve(strict=True)
            artifact = entry.parent.parent
            manifest = json.loads((artifact / 'package-manifest.json').read_text())
            env = {'HOME': str(owner), 'PATH': f'{owner / ".local/bin"}:/opt/homebrew/bin:/usr/bin:/bin', 'LANG': 'C'}
            state = Path(getattr(arguments, driver + '_state')).resolve(strict=True)
            subscription = 'test-anthropic' if driver == 'claude' else 'test-chatgpt'
            if not (state / 'subscriptions' / subscription / 'record.json').is_file():
                raise ValueError(f'The existing signed-in {subscription} test state is missing')
            info = call(entry, ['info', '--state-dir', str(state)], env, artifact)
            if not info.get('tool', {}).get('supported'):
                raise ValueError(f'The installed {driver} tool is unsupported')
            record: dict[str, Any] = {'entry': str(entry), 'runtime': manifest['python'],
                'source': manifest.get('source', {'unverified': True}), 'tool': info['tool'],
                'build': info['build'], 'version': info['version'], 'contract': info['contract'],
                'stateDirectory': str(state), 'subscriptionId': subscription, 'checks': [], 'inferenceRequests': 0}
            report['drivers'][driver] = record
            # Each transport/version test receives an empty private temporary state.
            with tempfile.TemporaryDirectory(prefix=f'syl95-real-{driver}-') as directory:
                home = Path(directory)
                settings = home / '.arbol'
                settings.mkdir(mode=0o700)
                (settings / f'arbol-{driver}-driver.json').write_text(json.dumps({'toolPath': info['tool']['path']}))
                disposable_env = {**env, 'HOME': str(home), 'TMPDIR': str(home)}
                fresh = call(entry, ['info'], disposable_env, home)
                if not fresh['tool']['supported'] or not Path(fresh['stateDirectory']).is_relative_to(home):
                    raise ValueError('No-prompt version probe did not use its disposable state')
                record['checks'].append({'check': 'probe.python-info-private-state', 'passed': True,
                                         'toolVersion': fresh['tool']['version']})
            # Check/catalog/usage are account RPCs, never a run, user message or turn.
            status = call(entry, ['subscriptions', 'check', subscription, '--state-dir', str(state)], env, artifact)
            if status.get('state') != 'signed_in':
                raise ValueError(f'The designated {subscription} login is unavailable')
            catalog = call(entry, ['subscriptions', 'models', subscription, '--state-dir', str(state)], env, artifact)
            if not catalog.get('models'):
                raise ValueError('The no-prompt account model catalog is empty')
            usage = call(entry, ['subscriptions', 'usage', subscription, '--state-dir', str(state)], env, artifact)
            record['checks'].append({'check': 'probe.python-account-catalog-usage', 'passed': True,
                                     'accountShape': shape(status), 'catalogShape': shape(catalog),
                                     'usageShape': shape(usage), 'usageOutcome': usage['outcome']})
            if driver == 'claude':
                probe = call(entry, ['dev', 'probe', '--state-dir', str(state)], env, artifact)
                if probe.get('outcome') != 'passed' or probe.get('inferenceRequests') != 0:
                    raise ValueError('The packaged Claude dev probe did not pass without inference')
                record['checks'].append({'check': 'dev.probe', 'passed': True, 'record': probe})
            record['outcome'] = 'passed'
        after = snapshot(owner)
        changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
        report['ownerConfigurationUnchanged'] = not changed
        if changed:
            report['changedOwnerMetadataPaths'] = changed
            raise ValueError('Owner vendor configuration metadata changed during the no-prompt probes')
        report['outcome'] = 'passed'
    except Exception as error:
        report['outcome'] = 'failed'
        report['error'] = str(error)
    Path(arguments.output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'outcome': report['outcome'], 'inferenceRequests': 0,
                      'evidence': arguments.output, **({'error': report['error']} if 'error' in report else {})}))
    return 0 if report['outcome'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claude', required=True)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--claude-state', required=True)
    parser.add_argument('--codex-state', required=True)
    parser.add_argument('--output', required=True)
    raise SystemExit(main(parser.parse_args()))
