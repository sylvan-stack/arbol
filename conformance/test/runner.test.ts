import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, copyFile, readFile, rm, stat } from 'node:fs/promises';
import { join, resolve, dirname } from 'node:path';
import { tmpdir } from 'node:os';
import { commandWords, resolveCommand, shellQuote } from '../command.js';
import { ScenarioHome } from '../harness.js';
import { invoke } from '../process.js';
import { runSuite, selectScenarios } from '../runner.js';
import type { Command } from '../command.js';

const root = resolve(import.meta.dirname, '../../..');
const fake = join(root, 'conformance/test/fake-driver.mjs');
const cli = join(root, 'conformance/bin/arbol-conformance.mjs');
const command: Command = [process.execPath, fake];

test('runner.shared-scenarios checks a second Driver protocol without Driver imports', async () => {
  const reports: string[] = [];
  assert.equal(await runSuite(command, selectScenarios('C1,C31,C32'), { write: line => reports.push(line) }), 0);
  assert.match(reports.join('\n'), /PASS C31/);
  assert.match(reports.join('\n'), /PASS C32.*info only/);
  assert.match(reports.join('\n'), /PASS C1.*removal/);
  assert.equal(reports.at(-1), '3/3 scenarios passed.');
});

test('runner.isolation gives each scenario a clean home, settings, time scale and working folder', async () => {
  const homes: string[] = [];
  const selected = selectScenarios('C31,C32').map(scenario => ({ ...scenario, async run(fixture: ScenarioHome) {
    homes.push(fixture.home);
    assert.equal((await stat(fixture.home)).mode & 0o777, 0o700);
    assert.equal(fixture.env.ARBOL_TEST_TIME_SCALE, '100');
    assert.equal(fixture.env.HOME, fixture.home);
    assert.equal(fixture.env.TMPDIR, fixture.home);
    for (const key of ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'NODE_OPTIONS']) assert.equal(fixture.env[key], undefined);
    for (const name of ['claude', 'codex']) {
      const settings = JSON.parse(await readFile(join(fixture.home, '.arbol', `arbol-${name}-driver.json`), 'utf8'));
      assert.equal(settings.toolPath, fixture.toolPath);
    }
    assert.deepEqual(await fixture.received(), []);
    await scenario.run(fixture);
    const record = (await fixture.received())[0]!;
    assert.equal(record.workingDirectory, fixture.home);
    assert.ok(record.environment.includes('ARBOL_TEST_TIME_SCALE'));
    assert.ok(!record.environment.includes('NODE_OPTIONS'));
  } }));
  assert.equal(await runSuite(command, selected, { write: () => {} }), 0);
  assert.notEqual(homes[0], homes[1]);
  for (const home of homes) await assert.rejects(stat(home), { code: 'ENOENT' });
});

test('runner.failure reports expected and received, continues, and cleans both homes', async () => {
  const homes: string[] = [];
  const reports: string[] = [];
  const selected = selectScenarios('C31,C32').map(scenario => ({ ...scenario, async run(home: ScenarioHome) {
    homes.push(home.home); await scenario.run(home);
  } }));
  assert.equal(await runSuite([...command, '--fixture=wrong'], selected, { write: line => reports.push(line) }), 1);
  assert.match(reports.join('\n'), /PASS C31[\s\S]*FAIL C32[\s\S]*Contract version[\s\S]*Expected: 1[\s\S]*Received: 99/);
  assert.equal(reports.at(-1), '1/2 scenarios passed.');
  for (const home of homes) await assert.rejects(stat(home), { code: 'ENOENT' });
});

test('runner.invalid-json and exit statuses cannot pass as valid info', async () => {
  for (const mode of ['bad-json', 'wrong-exit']) {
    const reports: string[] = [];
    assert.equal(await runSuite([...command, `--fixture=${mode}`], selectScenarios('C32'), { write: line => reports.push(line) }), 1);
    assert.match(reports.join('\n'), /FAIL C32[\s\S]*Expected:[\s\S]*Received:/);
  }
});

test('runner.timeout ends the Driver and its child before removing the scenario home', async () => {
  let path = '';
  let pids: number[] = [];
  const selected = [{ id: 'hang', title: 'hanging Driver', scope: 'runner self-test', covers: [], async run(home: ScenarioHome) {
    path = home.home;
    const outcome = home.call(['info']).catch(error => error);
    for (let i = 0; i < 100; i++) {
      try { pids = JSON.parse(await readFile(join(path, 'pids.json'), 'utf8')) as number[]; break; }
      catch { await new Promise(resolve => setTimeout(resolve, 10)); }
    }
    const result: unknown = await outcome;
    if (result instanceof Error) throw result;
    assert.fail('The hanging Driver unexpectedly completed.');
  } }];
  const reports: string[] = [];
  assert.equal(await runSuite([...command, '--fixture=hang'], selected, { timeoutMs: 1500, write: line => reports.push(line) }), 1);
  assert.match(reports.join('\n'), /timed out[\s\S]*Expected:.*1500/);
  assert.equal(pids.length, 2);
  for (const pid of pids) assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
  await assert.rejects(stat(path), { code: 'ENOENT' });
});

test('runner.commands handles spaces and single quotes without a shell', async t => {
  assert.deepEqual(commandWords(`node 'a b' "c d" '' e\\ f`), ['node', 'a b', 'c d', '', 'e f']);
  assert.deepEqual(commandWords('node "$(never-execute)" ";"'), ['node', '$(never-execute)', ';']);
  for (const invalid of ['', "'unclosed", 'node \\']) assert.throws(() => commandWords(invalid));
  const temp = await mkdtemp(join(tmpdir(), "suite's path "));
  t.after(() => rm(temp, { recursive: true, force: true }));
  const filename = join(temp, "fake Driver's program.mjs");
  await copyFile(fake, filename);
  assert.equal(await runSuite(await resolveCommand(`${shellQuote(process.execPath)} ${shellQuote(filename)}`), selectScenarios('C1,C31,C32'), { write: () => {} }), 0);
  assert.deepEqual(await resolveCommand('node conformance/test/fake-driver.mjs', root, dirname(process.execPath)), command);
});

test('runner.output preserves Unicode split across pipe chunks', async () => {
  const script = "process.stdout.write(Buffer.from([0xc3])); setTimeout(() => process.stdout.write(Buffer.from([0xb1])), 25);";
  const result = await invoke([process.execPath, '-e', script], [], { cwd: root, env: {}, timeoutMs: 1500 });
  assert.equal(result.status, 0); assert.equal(result.stdout, 'ñ');
});

test('runner.cancellation stops the active invocation and removes its home', async () => {
  const controller = new AbortController();
  let path = '';
  const selected = [{ id: 'cancel', title: 'cancelled Driver', scope: 'runner self-test', covers: [], async run(home: ScenarioHome) {
    path = home.home;
    const pending = home.call(['info']);
    const timer = setTimeout(() => controller.abort(), 100);
    try { await pending; } finally { clearTimeout(timer); }
  } }];
  const reports: string[] = [];
  assert.equal(await runSuite([...command, '--fixture=hang'], selected, { signal: controller.signal, write: line => reports.push(line) }), 2);
  assert.match(reports.join('\n'), /Driver invocation was stopped/);
  await assert.rejects(stat(path), { code: 'ENOENT' });
});

test('runner.selection runs only requested, known scenarios', () => {
  assert.deepEqual(selectScenarios('C32').map(s => s.id), ['C32']);
  assert.deepEqual(selectScenarios('C32,C31 C31').map(s => s.id), ['C31', 'C32']);
  assert.deepEqual(selectScenarios('C1,C40').map(s => s.id), ['C1', 'C40']);
  for (const ids of ['', 'C21', 'C31,C99']) assert.throws(() => selectScenarios(ids));
});

test('runner.cli exposes the program, selection and meaningful failure statuses', async () => {
  const driver = [...command, '--fixture=wrong'].map(shellQuote).join(' ');
  const options = { cwd: root, env: { PATH: process.env.PATH }, timeoutMs: 15000 };
  const passed = await invoke([process.execPath, cli], ['--driver', driver, '--only=C31'], options);
  assert.equal(passed.status, 0); assert.match(passed.stdout, /1\/1 scenarios passed/); assert.doesNotMatch(passed.stdout, /C32/);
  const failed = await invoke([process.execPath, cli], ['--driver', driver, '--only', 'C32'], options);
  assert.equal(failed.status, 1); assert.match(failed.stdout, /FAIL C32[\s\S]*Expected: 1[\s\S]*Received: 99/);
  for (const args of [[], ['--driver', driver, '--only', 'C21'], ['--driver', 'missing-driver'], ['--unknown'], ['--driver', driver, '--driver', driver]]) {
    const refused = await invoke([process.execPath, cli], args, options);
    assert.equal(refused.status, 2); assert.match(refused.stderr, /Usage: arbol-conformance/); assert.equal(refused.stdout, '');
  }
});
