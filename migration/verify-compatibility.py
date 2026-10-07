#!/usr/bin/env python3
"""Offline bidirectional CLI/state checks against immutable TypeScript baselines."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shlex
import shutil
import signal
import stat
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NODE = Path(os.environ.get('ARBOL_NODE_EXECUTABLE', shutil.which('node') or '/usr/bin/node'))
ROOT = Path(__file__).resolve().parents[2]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class Fixture:
    def __init__(self, directory: Path, driver: str, baseline: Path, candidate: Path):
        self.home = directory
        self.driver = driver
        self.state = directory / 'state'
        self.tool = directory / 'tool'
        self.old = [str(NODE), str(baseline / f'arbol-{driver}-driver/bin/arbol-{driver}-driver.mjs')]
        self.new = [str(candidate)]
        self.commands = {'typescript': self.old, 'python': self.new}
        self.env = {'HOME': str(directory), 'PATH': f'{NODE.parent}:/usr/bin:/bin',
                    'LANG': 'C', 'TMPDIR': str(directory), 'ARBOL_TEST_TIME_SCALE': '10'}
        self.active: set[asyncio.subprocess.Process] = set()

    def prepare(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.tool.mkdir(mode=0o700)
        settings = self.home / '.arbol'
        settings.mkdir(mode=0o700)
        launcher = self.tool / 'vendor'
        words = shlex.join([*self.old, 'dev', 'stand-in', str(self.tool), '--'])
        launcher.write_text(f'#!/bin/sh\nexec {words} "$@"\n')
        launcher.chmod(0o700)
        (settings / f'arbol-{self.driver}-driver.json').write_text(json.dumps({'toolPath': str(launcher)}))
        self.part('C14', 'success')

    def part(self, scenario: str, part: str) -> None:
        (self.tool / 'scenario').write_text(f'{scenario} {part}\n')

    async def start(self, language: str, args: list[str], *, input_pipe: bool = False) -> asyncio.subprocess.Process:
        command = self.commands[language]
        child = await asyncio.create_subprocess_exec(*command, '--state-dir', str(self.state), *args,
                env=self.env, cwd=self.home, stdin=asyncio.subprocess.PIPE if input_pipe else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
        self.active.add(child)
        return child

    async def finish(self, child: asyncio.subprocess.Process, expected: int = 0) -> tuple[str, str]:
        try:
            stdout, stderr = await asyncio.wait_for(child.communicate(), timeout=20)
        except TimeoutError:
            os.killpg(child.pid, signal.SIGKILL)
            await child.wait()
            raise AssertionError('Driver exceeded offline test deadline') from None
        finally:
            self.active.discard(child)
        out, err = stdout.decode(), stderr.decode()
        check(child.returncode == expected, f'Unexpected exit {child.returncode}: {out[:1500]} {err[:1500]}')
        return out, err

    async def call(self, language: str, args: list[str], expected: int = 0) -> str:
        return (await self.finish(await self.start(language, args), expected))[0]

    async def value(self, language: str, args: list[str], expected: int = 0) -> Any:
        return json.loads(await self.call(language, args, expected))

    async def run(self, language: str, request: dict[str, Any], expected: str = 'completed') -> list[dict[str, Any]]:
        file = self.home / f'request-{time.monotonic_ns()}.json'
        file.write_text(json.dumps(request, ensure_ascii=True))
        raw = await self.call(language, ['run', '--request', str(file)], {'completed': 0, 'cancelled': 2, 'failed': 1}[expected])
        events = [json.loads(line) for line in raw.splitlines()]
        check(bool(events) and events[-1].get('type') == 'finished', 'Missing final event')
        check(sum(event.get('type') == 'finished' for event in events) == 1, 'Duplicate final event')
        check([event.get('seq') for event in events] == list(range(1, len(events)+1)), 'Event sequence changed')
        check(events[-1]['outcome'] == expected, 'Wrong outcome')
        return events

    async def cleanup(self) -> None:
        # Restore only this temporary fixture's format so baseline orphan recovery can run.
        if self.state.exists():
            (self.state / "format").write_text("1\n")
        for child in self.active.copy():
            if child.returncode is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await child.wait()
        self.active.clear()
        if self.state.exists():
            try:
                await self.call("typescript", ["runs", "list"])
            except Exception:
                pass


async def collect_events(child: asyncio.subprocess.Process, events: list[dict[str, Any]]) -> None:
    assert child.stdout is not None
    while line := await child.stdout.readline():
        events.append(json.loads(line))


async def process_output(arguments: list[str]) -> tuple[int, str]:
    child = await asyncio.create_subprocess_exec(*arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    stdout, _ = await child.communicate()
    assert child.returncode is not None
    return child.returncode, stdout.decode().strip()


async def checked_output(arguments: list[str]) -> str:
    code, output = await process_output(arguments)
    check(code == 0, 'A provenance command failed')
    return output


def append_history(history: list[dict[str, Any]], input: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [*history, {'type': 'message', **input}, *[
        {'type': 'message', 'role': 'assistant', 'text': event['text']}
        for event in events if event['type'] == 'text' and not event.get('parentCallId')]]


async def exercise(fixture: Fixture, passed: list[str]) -> list[str]:
    fixture.prepare()
    family = 'anthropic' if fixture.driver == 'claude' else 'chatgpt'
    old_created = await fixture.value('typescript', ['subscriptions', 'create', '--family', family, '--label', 'Old language', '--id', 'from-ts'])
    new_list = await fixture.value('python', ['subscriptions', 'list'])
    check(next(item for item in new_list if item['id'] == 'from-ts') == old_created, 'Python cannot read TypeScript account record')
    updated = await fixture.value('python', ['subscriptions', 'update', 'from-ts', '--label', 'Python label'])
    old_list = await fixture.value('typescript', ['subscriptions', 'list'])
    check(next(item for item in old_list if item['id'] == 'from-ts') == updated, 'TypeScript cannot read Python update')
    new_created = await fixture.value('python', ['subscriptions', 'create', '--family', family, '--label', 'New language', '--id', 'from-py'])
    old_list = await fixture.value('typescript', ['subscriptions', 'list'])
    check(next(item for item in old_list if item['id'] == 'from-py') == new_created, 'TypeScript cannot read Python-created record')
    await fixture.call('typescript', ['subscriptions', 'remove', 'from-py'])
    await fixture.call('python', ['subscriptions', 'remove', 'from-ts'])
    check(all(item['id'] not in {'from-ts', 'from-py'} for item in await fixture.value('python', ['subscriptions', 'list'])), 'Mixed removal failed')
    passed.append('state.subscription-bidirectional')
    # Eight simultaneous old/new automatic creations must elect distinct IDs.
    created = await asyncio.gather(*[
        fixture.value('typescript' if index % 2 else 'python', ['subscriptions', 'create', '--family', family, '--label', f'Concurrent {index}'])
        for index in range(8)])
    check(len({item['id'] for item in created}) == 8, 'Mixed implementations lost a creation or shared an ID')
    for language in ('typescript', 'python'):
        listed = await fixture.value(language, ['subscriptions', 'list'])
        check(all(any(item['id'] == made['id'] and item['label'] == made['label'] for item in listed) for made in created), 'Concurrent account state lost')
    passed.append('state.mixed-locking-reservations')
    for file in fixture.state.rglob('record.json'):
        check(stat.S_IMODE(file.stat().st_mode) == 0o600, 'Account permission changed')
    check((fixture.state / 'format').read_text().strip() == '1', 'State format changed')
    passed.append('state.format-permissions')
    # The retained stand-in signs in only the synthetic account inside this home.
    await fixture.call('typescript', ['subscriptions', 'sign-in', family])
    for first_language, second_language in [('typescript', 'python'), ('python', 'typescript')]:
        fixture.part('C14', 'plain')
        chat = f'{first_language}-to-{second_language}/😀'
        first_input = {'role': 'user', 'text': 'Unicode café 中文 😀 "quote"\ncontrol\t', 'images': [{'mediaType': 'image/png', 'data': 'aQ=='}]}
        request = {'subscriptionId': family, 'chatSessionId': chat, 'workingDirectory': str(fixture.home),
                   'tools': 'none', 'history': [], 'input': first_input}
        first = await fixture.run(first_language, request)
        check(first[0]['continuity'] == 'fresh', 'First run not fresh')
        key = hashlib.sha256(chat.encode()).hexdigest()
        mapping = fixture.state / 'subscriptions' / family / 'chats' / f'{key}.json'
        entry = json.loads(mapping.read_text())
        history = append_history([], first_input, first)
        second_input = {'role': 'user', 'text': 'continued'}
        second = await fixture.run(second_language, {**request, 'history': history, 'input': second_input})
        check(second[0]['continuity'] == 'resumed', f'{first_language} -> {second_language} did not resume: {second[0]}')
        check(json.loads(mapping.read_text())['conversation'] == entry['conversation'], 'Native conversation changed during continuation')
        check(stat.S_IMODE(mapping.stat().st_mode) == 0o600, 'Map permission changed')
        for text in ['Unicode café', 'continued']:
            check(text not in mapping.read_text(), 'Map leaked history')
        passed.append(f'continuity.{first_language}-to-{second_language}')
        latest_request = {**request, 'history': append_history(history, second_input, second), 'input': {'role': 'user', 'text': 'held recovery'}}
        latest_map = mapping
    for owner_language, peer_language in [('typescript', 'python'), ('python', 'typescript')]:
        fixture.part('C15', 'stopping')
        run_id = f'mixed-{owner_language}-owner'
        owner = await fixture.start(owner_language, ['run', '--subscription', family, '--run-id', run_id, 'answer'])
        collected: list[dict[str, Any]] = []
        reader = asyncio.create_task(collect_events(owner, collected))
        try:
            deadline = time.monotonic() + 10
            while not any(event.get('type') == 'started' for event in collected):
                check(time.monotonic() < deadline, f'Mixed owner did not start: {collected}')
                await asyncio.sleep(0.01)
            listed = await fixture.value(peer_language, ['runs', 'list'])
            check(any(item['runId'] == run_id for item in listed), 'Peer cannot see other language run')
            # Both callers reject a duplicate ID before starting another vendor run.
            duplicate = await fixture.run(peer_language, {'runId': run_id, 'subscriptionId': family, 'history': [], 'tools': 'none', 'input': {'role': 'user', 'text': 'duplicate'}}, 'failed')
            check(duplicate[-1]['error']['code'] == 'in_use', 'Mixed duplicate ID not refused')
            check(await fixture.call(peer_language, ['runs', 'stop', run_id]) == '', 'Peer stop changed empty output')
            await asyncio.wait_for(owner.wait(), 5)
            await asyncio.wait_for(reader, 5)
            check(owner.returncode == 2, 'Mixed owner stop exit changed')
            check(sum(event.get('type') == 'finished' for event in collected) == 1 and collected[-1]['outcome'] == 'cancelled', 'Mixed peer stop finalization changed')
            check(await fixture.value(peer_language, ['runs', 'list']) == [], 'Mixed run record remained')
            fixture.active.discard(owner)
            passed.append(f'runs.{owner_language}-owner-{peer_language}-stop')
        finally:
            reader.cancel()
    # Recover each language's killed owner while keeping a newer chat-map writer.
    for owner_language in ('typescript', 'python'):
        fixture.part('C38', 'hold')
        run_id = f'orphan-{owner_language}'
        request_file = fixture.home / f'{run_id}.json'
        request_file.write_text(json.dumps({**latest_request, 'runId': run_id}))
        owner = await fixture.start(owner_language, ['run', '--request', str(request_file)])
        collected = []
        reader = asyncio.create_task(collect_events(owner, collected))
        try:
            deadline = time.monotonic() + 10
            record_file = fixture.state / 'runs' / f'{run_id}.json'
            record = None
            while record is None or not record.get('tool') or not any(item.get('type') == 'started' for item in collected):
                check(time.monotonic() < deadline, 'Killed-owner fixture failed to start')
                if record_file.exists():
                    record = json.loads(record_file.read_text())
                await asyncio.sleep(0.01)
            check(collected[0]['continuity'] == 'resumed', 'Recovery fixture must resume the existing map')
            preserved = json.loads(latest_map.read_text())
            preserved['conversation'] = str(uuid.uuid4())
            # A newer completed writer is allowed while the resumed run is active.
            latest_map.write_text(json.dumps(preserved))
            os.kill(owner.pid, signal.SIGKILL)
            await asyncio.wait_for(owner.wait(), 5)
            await asyncio.gather(fixture.value('typescript', ['runs', 'list']), fixture.value('python', ['runs', 'list']))
            check(not record_file.exists(), 'Mixed recovery left the killed-owner run record')
            check(not (fixture.state / 'tmp' / run_id).exists(), 'Mixed recovery left its temporary folder')
            check(json.loads(latest_map.read_text()) == preserved, 'Mixed recovery deleted or changed a newer conversation record')
            code, status = await process_output(['/bin/ps', '-p', str(record['tool']['pid']), '-o', 'stat='])
            check(code == 1 or status.startswith('Z'), 'Mixed recovery left the vendor process alive')
            fixture.active.discard(owner)
            passed.append(f'recovery.{owner_language}-owner-mixed-election-newer-map')
            # Restore the known vendor conversation for the next independent case.
            preserved['conversation'] = record['continuedConversation']
            latest_map.write_text(json.dumps(preserved))
        finally:
            reader.cancel()
    # Simulate a reused PID with a sacrificial process whose start identity differs.
    sentinel = await asyncio.create_subprocess_exec('/bin/sleep', '60', start_new_session=True)
    try:
        stale = {'pid': sentinel.pid, 'startedAt': '2000-01-01T00:00:00.000Z'}
        record = {'runId': 'pid-reuse', 'subscriptionId': family,
                  'owner': {'pid': 9999999, 'startedAt': stale['startedAt']}, 'tool': stale,
                  'startedAt': '2000-01-01T00:00:00.000Z'}
        for language in ('typescript', 'python'):
            destination = fixture.state / 'runs' / 'pid-reuse.json'
            destination.write_text(json.dumps(record))
            await fixture.value(language, ['runs', 'list'])
            check(sentinel.returncode is None, 'Recovery signalled a process with a reused PID')
            check(not destination.exists(), 'Stale reused-PID record remained')
        passed.append('recovery.pid-reuse-no-signal')
    finally:
        if sentinel.returncode is None:
            os.killpg(sentinel.pid, signal.SIGTERM)
        await sentinel.wait()
    # Higher-format data must be refused without replacing its file.
    before = b'2\n'
    format_file = fixture.state / 'format'
    format_file.write_bytes(before)
    for language in ('typescript', 'python'):
        rejected = await fixture.value(language, ['subscriptions', 'list'], expected=1)
        check(rejected['error']['code'] == 'state_newer', 'Higher format not refused')
        check(format_file.read_bytes() == before, 'Higher format changed')
    passed.append('state.newer-preserved')
    return passed


async def main(args: argparse.Namespace) -> int:
    report: dict[str, Any] = {'issue': 'SYL-95', 'check': 'migration.bidirectional-state-cli',
        'at': datetime.now(timezone.utc).isoformat(), 'runtime': await checked_output([args.python, '--version']),
        'node': await checked_output([str(NODE), '--version']), 'vendorRequests': 0, 'validationMode': args.mode, 'drivers': {}}
    try:
        report['scope'] = args.drivers
        for driver in args.drivers:
            candidate = Path(getattr(args, driver)).resolve()
            baseline_repo = Path(args.baseline).resolve() / f'arbol-{driver}-driver'
            with tempfile.TemporaryDirectory(prefix=f'syl95-mixed-{driver}-') as directory:
                fixture = Fixture(Path(directory).resolve(), driver, Path(args.baseline).resolve(), candidate)
                source = ROOT / f'arbol-{driver}-driver'
                entry: dict[str, Any] = {'candidate': str(candidate), 'baselineCommit': await checked_output(['git', '-C', str(baseline_repo), 'rev-parse', 'HEAD']),
                    'sourceCommit': await checked_output(['git', '-C', str(source), 'rev-parse', 'HEAD']), 'checks': []}
                manifest = candidate.parent.parent / 'package-manifest.json'
                if manifest.is_file():
                    packaged = json.loads(manifest.read_text())
                    entry['artifactSource'] = packaged['source']
                    entry['artifactPython'] = packaged['python']
                    entry['manifestSha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
                report['drivers'][driver] = entry
                try:
                    entry['checks'] = await exercise(fixture, entry['checks'])
                    entry['outcome'] = 'passed'
                finally:
                    await fixture.cleanup()
        report['outcome'] = 'passed'
    except Exception as error:
        report['outcome'] = 'failed'
        report['error'] = str(error)
    finally:
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))
    return 0 if report['outcome'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--claude', required=True)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--output', required=True)
    parser.add_argument('--mode', choices=['python-migration', 'baseline-harness-rehearsal'], default='python-migration')
    parser.add_argument('--drivers', nargs='+', choices=['claude', 'codex'], default=['claude', 'codex'])
    raise SystemExit(asyncio.run(main(parser.parse_args())))
