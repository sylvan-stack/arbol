import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { execFileSync, spawn, spawnSync } from 'node:child_process';
import type { ChildProcess } from 'node:child_process';
import type { TestContext } from 'node:test';
import { reserve } from '../service.js';
import type { BuildDescription } from '../config.js';
import type { BuildRecord } from '../records.js';

const root = resolve(import.meta.dirname, '../../..');
const cli = join(root, 'builds/bin/arbol-builds.mjs');
const installer = join(root, 'dist/builds/install.js');
const env = { PATH: `${dirname(process.execPath)}:/usr/bin:/bin`, LANG: 'en_US.UTF-8' };
const program = `#!/usr/bin/env node
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
const record = JSON.parse(readFileSync(join(import.meta.dirname, 'build.json'), 'utf8'));
const args = process.argv.slice(2);
if (args[0] === '--echo') { process.stdin.pipe(process.stdout); process.stderr.write('diagnostic\\n'); }
else if (args[0] === '--wait') {
  process.stdout.write(JSON.stringify({pid: process.pid}) + '\\n');
  process.on('SIGINT', () => { process.stdout.write('interrupted\\n'); process.exit(2); });
  setInterval(() => {}, 1000);
} else if (args[0] === '--state') {
  const state = JSON.parse(readFileSync(args[1], 'utf8'));
  if (state.format > record.dataFormat) { console.log(JSON.stringify({error: 'newer data', found: state.format, supported: record.dataFormat})); process.exitCode = 1; }
  else console.log(JSON.stringify({format: state.format, build: record.build}));
} else if (args[0] === '--exit') process.exit(Number(args[1]));
else console.log(JSON.stringify({build: record.build, version: record.packageVersion, args, cwd: process.cwd(), marker: process.env.MARKER, pid: process.pid}));
`;
const builder = `import { copyFileSync, chmodSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
const dir = process.env.ARBOL_BUILD_DIR;
copyFileSync('program.mjs', join(dir, 'program.mjs')); chmodSync(join(dir, 'program.mjs'), 0o755);
writeFileSync(join(dir, 'build-environment.json'), JSON.stringify({number: process.env.ARBOL_BUILD_NUMBER, dir, cwd: process.cwd()}));
`;
const checker = `import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
const dir = process.env.ARBOL_BUILD_DIR;
const record = JSON.parse(readFileSync(join(dir, 'build.json')));
if (record.status !== 'building') throw new Error('check must run before working');
const result = spawnSync(join(dir, record.entry), ['direct-check'], {encoding: 'utf8'});
if (result.status !== 0 || JSON.parse(result.stdout).build !== process.env.ARBOL_BUILD_NUMBER) throw new Error('wrong entry');
writeFileSync(join(dir, 'check-environment.json'), JSON.stringify({number: process.env.ARBOL_BUILD_NUMBER, dir, cwd: process.cwd()}));
`;

function fixture(t: TestContext, component = 'sample') {
  const home = realpathSync(mkdtempSync(join(tmpdir(), "Arbol's builds ")));
  const repo = join(home, 'repository'); const registry = join(home, 'registry'); const bin = join(home, 'bin');
  mkdirSync(repo); t.after(() => rmSync(home, { recursive: true, force: true }));
  writeFileSync(join(repo, 'package.json'), '{"version":"1.2.3","type":"module"}\n');
  writeFileSync(join(repo, 'program.mjs'), program); writeFileSync(join(repo, 'build.mjs'), builder); writeFileSync(join(repo, 'check.mjs'), checker);
  let config: BuildDescription = { component, build: ['node build.mjs'], entry: 'program.mjs', checks: [{ name: 'sample-check', command: 'node check.mjs' }], dataFormat: 1 };
  const configure = (patch: Partial<BuildDescription>) => { config = { ...config, ...patch }; writeFileSync(join(repo, 'arbol-build.json'), JSON.stringify(config)); };
  configure({});
  const git = (...args: string[]) => execFileSync('git', args, { cwd: repo, env: { ...env, HOME: home }, encoding: 'utf8' }).trim();
  git('init', '-q', '-b', 'main'); git('add', '.'); git('-c', 'user.name=Build Tests', '-c', 'user.email=builds@example.invalid', 'commit', '-qm', 'Sample');
  const call = (...args: string[]) => spawnSync(process.execPath, [cli, '--registry-dir', registry, '--bin-dir', bin, ...args], { cwd: home, env: { ...env, HOME: home }, encoding: 'utf8' });
  const build = () => {
    const result = call('build', component, '--repo', repo);
    assert.equal(result.status, 0, result.stdout + result.stderr);
    return JSON.parse(result.stdout) as BuildRecord;
  };
  const launch = (args: string[] = [], opts: { input?: string | Buffer; marker?: string } = {}) => spawnSync(join(bin, component), args, { cwd: home, env: { ...env, HOME: home, MARKER: opts.marker ?? 'caller' }, input: opts.input, encoding: 'utf8' });
  return { home, repo, registry, bin, component, configure, call, build, launch, git };
}

function waitForOutput(child: ChildProcess): Promise<string> {
  return new Promise((done, fail) => {
    const timeout = setTimeout(() => { child.kill('SIGKILL'); fail(new Error('Process did not become ready.')); }, 5000);
    let output = '';
    child.stdout!.on('data', data => { output += String(data); if (output.includes('\n')) { clearTimeout(timeout); done(output); } });
    child.once('error', error => { clearTimeout(timeout); fail(error); });
    child.once('exit', () => { clearTimeout(timeout); if (!output.includes('\n')) fail(new Error('Process ended before ready.')); });
  });
}
function finished(child: ChildProcess): Promise<{code: number | null; signal: NodeJS.Signals | null}> {
  return new Promise((done, fail) => { child.once('error', fail); child.once('close', (code, signal) => done({ code, signal })); });
}

test('builds.two-builds runs the newest Build and an explicitly named older Build', t => {
  const f = fixture(t);
  assert.equal(f.build().build, '1'); assert.equal(f.build().build, '2');
  assert.equal(JSON.parse(f.launch().stdout).build, '2');
  assert.equal(JSON.parse(f.launch(['-v', '1']).stdout).build, '1');
  assert.deepEqual(JSON.parse(f.call('list', f.component).stdout).map((r: BuildRecord & {default: boolean}) => [r.build, r.default]), [['2', true], ['1', false]]);
  assert.equal(JSON.parse(f.call('show', f.component).stdout).build, '2');
  assert.equal(JSON.parse(f.call('show', `${f.component}@1`).stdout).build, '1');
});

test('builds.numbering uses hexadecimal, arbitrary precision, independent components and damaged directories', t => {
  const f = fixture(t);
  for (let n = 1; n <= 17; n++) assert.equal(reserve(f.registry, f.component).build, n.toString(16));
  assert.equal(reserve(f.registry, 'other').build, '1');
  mkdirSync(join(f.registry, f.component, 'ffffffffffffffff'));
  assert.equal(reserve(f.registry, f.component).build, '10000000000000000');
});

test('builds.concurrent invocations never reserve the same number', async t => {
  const f = fixture(t);
  const results = await Promise.all(Array.from({ length: 4 }, () => {
    const child = spawn(process.execPath, [cli, 'build', f.component, '--repo', f.repo, '--registry-dir', f.registry, '--bin-dir', f.bin], { env: { ...env, HOME: f.home } });
    let output = ''; child.stdout.on('data', data => { output += String(data); });
    return finished(child).then(result => { assert.equal(result.code, 0, output); return JSON.parse(output).build as string; });
  }));
  assert.deepEqual(results.sort(), ['1', '2', '3', '4']);
  assert.equal(JSON.parse(f.launch().stdout).build, '4');
});

test('builds.source records package, repository, branch, commit and uncommitted changes', t => {
  const f = fixture(t); const commit = f.git('rev-parse', 'HEAD');
  const first = f.build();
  assert.equal(first.packageVersion, '1.2.3');
  assert.deepEqual(first.source, { repository: f.repo, branch: 'main', commit, uncommittedChanges: false });
  writeFileSync(join(f.repo, 'uncommitted.txt'), 'new');
  assert.equal(f.build().source.uncommittedChanges, true);
});

test('builds.folder-alone launches a relocated Build after its source and tool libraries disappear', t => {
  const f = fixture(t); f.build();
  const moved = join(f.home, 'moved'); mkdirSync(moved);
  cpSync(join(f.registry, f.component, '1'), join(moved, f.component, '1'), { recursive: true });
  // The launcher source contains only Node built-ins; changing its registry is sufficient.
  const launcher = join(f.bin, f.component);
  writeFileSync(launcher, readFileSync(launcher, 'utf8').replace(JSON.stringify(f.registry), JSON.stringify(moved)));
  rmSync(f.repo, { recursive: true }); rmSync(f.registry, { recursive: true });
  const result = f.launch(); assert.equal(result.status, 0, result.stderr); assert.equal(JSON.parse(result.stdout).build, '1');
});

test('builds.failed-check keeps its record and log, consumes its number and preserves the default', t => {
  const f = fixture(t); f.build();
  f.configure({ checks: [{ name: 'unavailable-account', kind: 'live', command: 'echo account-signed-out >&2; exit 1' }] });
  const result = f.call('build', f.component, '--repo', f.repo); assert.equal(result.status, 1);
  const record = JSON.parse(result.stdout) as BuildRecord;
  assert.equal(record.status, 'failed'); assert.equal(record.build, '2'); assert.equal(record.failure?.name, 'unavailable-account');
  assert.deepEqual(record.checks, [{name: 'unavailable-account', passed: false}]);
  assert.match(readFileSync(join(f.registry, f.component, '2/build.log'), 'utf8'), /account-signed-out/);
  assert.equal(JSON.parse(f.launch().stdout).build, '1');
  f.configure({ checks: [{name: 'sample-check', command: 'node check.mjs'}] }); assert.equal(f.build().build, '3');
});

test('builds.failed-command and missing entry cannot become working', t => {
  const f = fixture(t);
  f.configure({ build: ['echo compile-failed; exit 7'] });
  const command = JSON.parse(f.call('build', f.component, '--repo', f.repo).stdout);
  assert.equal(command.status, 'failed'); assert.equal(command.failure.stage, 'build'); assert.deepEqual(command.checks, []);
  assert.match(readFileSync(join(f.registry, f.component, '1/build.log'), 'utf8'), /compile-failed[\s\S]*Exit: 7/);
  f.configure({ build: ['true'] });
  const entry = JSON.parse(f.call('build', f.component, '--repo', f.repo).stdout);
  assert.equal(entry.status, 'failed'); assert.equal(entry.failure.stage, 'entry');
  f.configure({ build: ['node build.mjs'], checks: [{name: 'removed-entry', command: 'rm "$ARBOL_BUILD_DIR/program.mjs"'}] });
  assert.equal(JSON.parse(f.call('build', f.component, '--repo', f.repo).stdout).status, 'failed');
});

test('builds.description passes folder and number to ordered commands and checks against the building entry', t => {
  const f = fixture(t);
  f.configure({ build: ['node build.mjs', 'echo second > "$ARBOL_BUILD_DIR/order"'], checks: [
    {name: 'sample-check', command: 'node check.mjs'},
    {name: 'ordered-check', command: 'test "$(cat "$ARBOL_BUILD_DIR/order")" = second'},
  ], contract: 1, dataFormat: 2 });
  const record = f.build(); assert.equal(record.contract, 1); assert.equal(record.dataFormat, 2);
  const dir = join(f.registry, f.component, '1');
  for (const name of ['build', 'check']) assert.deepEqual(JSON.parse(readFileSync(join(dir, `${name}-environment.json`), 'utf8')), {number: '1', dir, cwd: f.repo});
  assert.deepEqual(record.checks, [{name: 'sample-check', passed: true}, {name: 'ordered-check', passed: true}]);
});

test('builds.driver-checks requires unit, contract and live checks and fails when the live check fails', t => {
  const f = fixture(t, 'arbol-claude-driver');
  assert.equal(f.call('build', f.component, '--repo', f.repo).status, 1); assert.ok(!existsSync(f.registry));
  f.configure({ contract: 1, dataFormat: 1, checks: [
    {name: 'unit', kind: 'unit', command: 'node check.mjs'},
    {name: 'contract', kind: 'contract', command: 'node check.mjs'},
    {name: 'one-real-message', kind: 'live', command: 'echo synthetic-live-failure; exit 1'},
  ] });
  const result = f.call('build', f.component, '--repo', f.repo); const record = JSON.parse(result.stdout);
  assert.equal(result.status, 1); assert.equal(record.status, 'failed'); assert.equal(record.failure.name, 'one-real-message');
  f.configure({ checks: [{name: 'unit', kind: 'unit', command: 'node check.mjs'}, {name: 'contract', kind: 'contract', command: 'node check.mjs'}, {name: 'live-stand-in', kind: 'live', command: 'node check.mjs'}] });
  assert.equal(f.build().status, 'working');
});

test('builds.withdraw changes the computed default and warns only for an explicit withdrawn Build', t => {
  const f = fixture(t); f.build(); f.build();
  const result = f.call('withdraw', `${f.component}@2`, '--reason', 'Bad result on Tuesday');
  assert.equal(result.status, 0); assert.equal(JSON.parse(result.stdout).status, 'withdrawn');
  assert.equal(JSON.parse(f.launch().stdout).build, '1');
  const named = f.launch(['-v', '2']); assert.equal(named.status, 0); assert.equal(JSON.parse(named.stdout).build, '2'); assert.match(named.stderr, /withdrawn: Bad result on Tuesday/);
  assert.equal(f.call('withdraw', `${f.component}@2`, '--reason', 'again').status, 1);
});

test('builds.launch-refusal lists runnable Builds and consumes -v only in first position', t => {
  const f = fixture(t); f.build();
  f.configure({build: ['false']}); f.call('build', f.component, '--repo', f.repo);
  for (const args of [['-v', '2'], ['-v', '3'], ['-v'], ['-v', '01'], ['-v', 'A']]) {
    const result = f.launch(args); assert.equal(result.status, 1); assert.deepEqual(JSON.parse(result.stdout).error.available, ['1']);
  }
  assert.deepEqual(JSON.parse(f.launch(['run', '-v', '2', '', 'a b', 'a\'b']).stdout).args, ['run', '-v', '2', '', 'a b', "a'b"]);
});

test('builds.streams preserves standard input, output, errors, working folder, environment and exit status', t => {
  const f = fixture(t); f.build();
  const input = 'ñ\u0000data\nline two\n'; const echo = f.launch(['--echo'], {input});
  assert.equal(echo.stdout, input); assert.equal(echo.stderr, 'diagnostic\n'); assert.equal(echo.status, 0);
  const result = JSON.parse(f.launch(['text'], {marker: 'custom'}).stdout);
  assert.equal(result.cwd, f.home); assert.equal(result.marker, 'custom');
  for (const code of ['0', '1', '2', '7', '143']) assert.equal(f.launch(['--exit', code]).status, Number(code));
});

test('builds.signals replaces the launcher process and passes handled and native signals directly', async t => {
  const f = fixture(t); f.build();
  for (const signal of ['SIGINT', 'SIGTERM'] as const) {
    const child = spawn(join(f.bin, f.component), ['--wait'], { env: { ...env, HOME: f.home } });
    t.after(() => { if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); });
    const done = finished(child);
    const ready = JSON.parse((await waitForOutput(child)).split('\n')[0]!);
    assert.equal(ready.pid, child.pid);
    child.kill(signal);
    const result = await done;
    if (signal === 'SIGINT') assert.equal(result.code, 2); else assert.equal(result.signal, 'SIGTERM');
  }
});

test('builds.damaged-record isolates malformed, missing, mismatched and nonexecutable entries', t => {
  const f = fixture(t); f.build(); f.build(); const path = join(f.registry, f.component, '2/build.json'); const original = readFileSync(path, 'utf8');
  for (const bad of ['{', '{}', original.replace('"build": "2"', '"build": "9"'), original.replace('"entry": "program.mjs"', '"entry": "../../outside"')]) {
    writeFileSync(path, bad); assert.equal(JSON.parse(f.launch().stdout).build, '1'); assert.equal(JSON.parse(f.call('list').stdout).length, 1);
  }
  rmSync(path); assert.equal(JSON.parse(f.launch().stdout).build, '1');
  writeFileSync(path, original); chmodSync(join(f.registry, f.component, '2/program.mjs'), 0o600);
  assert.equal(JSON.parse(f.launch().stdout).build, '1');
});

test('builds.prune retains records, logs, default and withdrawn Builds and never reuses a number', t => {
  const f = fixture(t); f.build(); f.build(); f.build(); f.build();
  f.call('withdraw', `${f.component}@2`, '--reason', 'keep for diagnosis');
  const result = f.call('prune', f.component, '--keep', '1'); assert.equal(result.status, 0); assert.deepEqual(JSON.parse(result.stdout).pruned, ['3', '1']);
  for (const number of ['1', '3']) {
    const dir = join(f.registry, f.component, number);
    assert.ok(JSON.parse(readFileSync(join(dir, 'build.json'), 'utf8')).prunedAt); assert.ok(existsSync(join(dir, 'build.log'))); assert.ok(!existsSync(join(dir, 'program.mjs')));
    assert.equal(f.launch(['-v', number]).status, 1); assert.equal(f.call('show', `${f.component}@${number}`).status, 0);
  }
  assert.equal(JSON.parse(f.launch().stdout).build, '4'); assert.equal(f.launch(['-v', '2']).status, 0);
  assert.deepEqual(JSON.parse(f.call('prune', f.component, '--keep', '1').stdout).pruned, []);
  assert.equal(f.build().build, '5');
  for (const keep of ['0', '-1', '1.5', 'two']) assert.equal(f.call('prune', f.component, '--keep', keep).status, 1);
});

test('builds.shared-data-format records declarations while the sample component guards its own shared data', t => {
  const f = fixture(t); f.build(); f.configure({dataFormat: 2}); f.build();
  const state = join(f.home, 'shared-state.json'); const contents = '{"format":2,"value":"unchanged"}'; writeFileSync(state, contents);
  const older = f.launch(['-v', '1', '--state', state]); assert.equal(older.status, 1); assert.deepEqual(JSON.parse(older.stdout), {error: 'newer data', found: 2, supported: 1});
  assert.equal(f.launch(['--state', state]).status, 0); assert.equal(readFileSync(state, 'utf8'), contents);
});

test('builds.paths uses default repository, registry and bin, or explicit paths with spaces and quotes', t => {
  const f = fixture(t); const defaultRepo = join(f.home, 'repos/sylvan-stack', f.component);
  mkdirSync(dirname(defaultRepo), {recursive: true}); renameSync(f.repo, defaultRepo);
  const result = spawnSync(process.execPath, [cli, 'build', f.component], {env: {...env, HOME: f.home}, encoding: 'utf8'});
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.ok(existsSync(join(f.home, 'Library/Application Support/Arbol/builds', f.component, '1/build.json')));
  const launcher = join(f.home, '.local/bin', f.component);
  assert.equal(JSON.parse(spawnSync(launcher, [], {env, encoding:'utf8'}).stdout).build, '1');
});

test('builds.invalid-description and CLI input refuse without reserving a number', t => {
  const f = fixture(t);
  for (const args of [[], ['unknown'], ['build'], ['show', 'sample@01'], ['prune', 'sample'], ['withdraw', 'sample@1'], ['build', '../outside'], ['list', 'sample@1'], ['list', '--repo', f.repo], ['list', '--registry-dir'], ['list', '--unknown'], ['list', '--bin-dir=a', '--bin-dir=b']]) assert.equal(f.call(...args).status, 1);
  for (const patch of [{entry: '../outside'}, {build: []}, {checks: []}, {dataFormat: 0}, {checks: [{name:'same', command:'true'}, {name:'same', command:'true'}]}]) {
    f.configure(patch); assert.equal(f.call('build', f.component, '--repo', f.repo).status, 1); assert.ok(!existsSync(f.registry));
  }
});

test('builds.install installs an independent tool that can create a standalone component launcher', t => {
  const f = fixture(t);
  const result = spawnSync(process.execPath, [installer, `--bin-dir=${f.bin}`], {env: {...env, HOME: f.home}, encoding: 'utf8'});
  assert.equal(result.status, 0, result.stdout + result.stderr);
  const installed = join(f.bin, 'arbol-builds');
  const build = spawnSync(installed, ['--registry-dir', f.registry, 'build', f.component, '--repo', f.repo, '--bin-dir', f.bin], {env, encoding:'utf8'});
  assert.equal(build.status, 0, build.stdout + build.stderr);
  assert.equal(JSON.parse(f.launch().stdout).build, '1');
  assert.equal(spawnSync(installed, ['list', `--registry-dir=${f.registry}`], {env, encoding:'utf8'}).status, 0);
  assert.equal(spawnSync(process.execPath, [installer, '--unknown'], {env, encoding:'utf8'}).status, 1);
});

test('builds.interrupted-build keeps a failed record and consumes its reserved number', async t => {
  const f = fixture(t);
  f.configure({build: ['node -e "console.log(\'waiting\'); setInterval(() => {}, 1000)"']});
  const child = spawn(process.execPath, [cli, 'build', f.component, '--repo', f.repo, '--registry-dir', f.registry, '--bin-dir', f.bin], {env});
  let output = ''; child.stdout.on('data', data => { output += String(data); }); const done = finished(child);
  for (let i=0; i<500; i++) {
    if (existsSync(join(f.registry, f.component, '1/build.log')) && readFileSync(join(f.registry, f.component, '1/build.log'), 'utf8').includes('waiting')) break;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  child.kill('SIGTERM'); assert.equal((await done).code, 1);
  assert.equal(JSON.parse(output).status, 'failed'); assert.match(JSON.parse(output).failure.message, /stopped by the caller/);
  f.configure({build:['node build.mjs']}); assert.equal(f.build().build, '2');
});
