import { mkdir, readFile, readdir, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { check, equal, object, text } from '../check.js';
import type { Scenario } from './types.js';
import type { ScenarioHome } from '../harness.js';
import type { ProcessResult } from '../process.js';
const delay = async (ms: number): Promise<void> => new Promise(resolve => setTimeout(resolve, ms));
export function events(reply: ProcessResult): Record<string, any>[] {
  return reply.stdout.trim().split('\n').filter(Boolean).map(line => object('Run event', JSON.parse(line)));
}
export function stream(reply: ProcessResult, outcome = 'completed'): Record<string, any>[] {
  const records = events(reply);
  check('Nonempty event stream', records.length > 0, 'at least a final event', reply);
  records.forEach((event, index) => {
    equal('Gapless sequence', event.seq, index + 1); equal('Run identifier', event.runId, records[0]!.runId);
    check('Timestamp', typeof event.at === 'string' && Number.isFinite(Date.parse(event.at)), 'UTC timestamp', event);
  });
  equal('One final event', records.filter(event => event.type === 'finished').length, 1);
  equal('Last event', records.at(-1)!.type, 'finished'); equal('Outcome', records.at(-1)!.outcome, outcome);
  equal('Outcome exit status', reply.status, outcome === 'completed' ? 0 : outcome === 'failed' ? 1 : 2);
  return records;
}
export async function signed(home: ScenarioHome): Promise<string> {
  home.env.ARBOL_TEST_TIME_SCALE = '10';
  await home.part('success');
  const families = JSON.parse((await home.call(['subscriptions', 'families'])).stdout) as Record<string, any>[];
  const id = text('Vendor login family', families.find(family => family.auth === 'vendor_login')?.id);
  const result = await home.call(['subscriptions', 'sign-in', id]); equal('Sign-in exit', result.status, 0);
  await home.part('plain'); return id;
}
const start = (home: ScenarioHome, id: string, message = 'answer', extra: string[] = []) => home.call(['run', '--subscription', id, ...extra, message]);
const calls = async (home: ScenarioHome) => (await home.received()).filter(record => record.arguments.includes('--input-format') && record.stage !== 'input');
export const c10: Scenario = { id: 'C10', title: 'Fresh run and request defaults', scope: 'fresh runs, whole blocks, options, defaults and unreadable settings; history covered by C14',
  covers: ['DRV-2.1', 'DRV-2.3', 'DRV-2.4', 'DRV-0.2', 'DRV-0.16'], async run(home) {
    const id = await signed(home);
    const records = stream(await start(home, id, 'answer', ['--label', 'exchange=41']));
    equal('First event', records[0]!.type, 'started'); equal('Fresh conversation', records[0]!.continuity, 'fresh');
    check('Actual model', typeof records[0]!.model === 'string', 'model from tool', records[0]);
    for (const event of records) equal('Echoed labels', event.labels, { exchange: '41' });
    equal('Whole answer despite partial delta', records.filter(event => event.type === 'text').map(event => event.text), ['answer']);
    const info = await home.json(['info']); equal('Build identity', records[0]!.driverBuild, info.result.build);
    await home.settings({ defaultSubscription: id, subscriptions: { [id]: { defaultModel: 'sonnet', defaultEffort: 'low' } } });
    const defaults = stream(await home.call(['run', 'answer'])); equal('Default subscription', defaults[0]!.subscriptionId, id); equal('Default effort', defaults[0]!.effort, 'low');
    const received = (await calls(home)).at(-1)!; check('Default model passed', received.arguments.includes('sonnet'), 'sonnet', received);
    const path = join(home.home, 'request.json');
    await writeFile(path, JSON.stringify({ subscriptionId: id, tools: 'none', history: [], input: { role: 'user', text: 'file message' },
      model: 'opus', effort: 'high', systemPrompt: 'Keep this exact.\nSecond line.', labels: { source: 'file' } }));
    stream(await home.call(['run', '--request', path, '--model', 'sonnet', '--effort', 'low', 'override']));
    const input = (await home.received()).filter(record => record.stage === 'input').at(-1)!;
    equal('Option replaces message', object('Message', object('Input', input.checks.input).message).content, [{ type: 'text', text: 'override' }]);
    const before = await readFile(path, 'utf8'); stream(await home.call(['run', '--request', path])); equal('Request unchanged', await readFile(path, 'utf8'), before);
    const settings = join(home.home, '.arbol', 'arbol-' + String(info.result.driver) + '-driver.json'); await writeFile(settings, '{');
    const refused = stream(await start(home, id), 'failed'); equal('Unreadable settings only final', refused.length, 1); equal('Settings refusal', refused[0]!.error.code, 'invalid_input');
  } };
export const c11: Scenario = { id: 'C11', title: 'Text before and after a shell call', scope: 'live block ordering and call pairing; history mapping covered by C14', covers: ['DRV-2.5', 'DRV-2.6', 'DRV-3.19 (events)'], async run(home) {
  const id = await signed(home); const records = stream(await start(home, id, 'answer', ['--tools', 'all', '--cwd', home.home]));
  const begun = records.findIndex(event => event.type === 'tool_started'); const ended = records.findIndex(event => event.type === 'tool_finished');
  check('Text before call', records.findIndex(event => event.type === 'text') < begun, 'text before tool_started', records);
  check('Text after call', records.findIndex((event, index) => index > ended && event.type === 'text') > ended, 'text after call', records);
  equal('Normalized command', records[begun]!.name, 'shell'); equal('Command input', records[begun]!.input, { command: 'printf fixture-output' });
  equal('One matching finish', records.filter(event => event.type === 'tool_finished' && event.callId === records[begun]!.callId).length, 1);
  equal('Shell output', records[ended]!.result, { output: 'fixture-output' });
} };
export const c12: Scenario = { id: 'C12', title: 'Error flag under a success subtype', scope: 'vendor error result', covers: ['DRV-2.7'], async run(home) {
  const records = stream(await start(home, await signed(home)), 'failed'); equal('Failure code', records.at(-1)!.error.code, 'vendor_error');
} };
export const c13: Scenario = { id: 'C13', title: 'Usage totals and absent values', scope: 'intermediate request sums replaced by result totals', covers: ['DRV-2.15'], async run(home) {
  const records = stream(await start(home, await signed(home))); const usage = records.filter(event => event.type === 'usage').map(event => event.usage);
  equal('Input totals', usage.map(item => item.inputTokens), [3, 7, 7]); equal('Output totals', usage.map(item => item.outputTokens), [2, 5, 5]);
  for (const item of usage) for (const field of ['cachedInputTokens', 'reasoningTokens', 'costUsd']) equal('Unreported ' + field, field in item, false);
  equal('Final usage', records.at(-1)!.usage, usage.at(-1));
} };
export const c18: Scenario = { id: 'C18', title: 'Concurrent runs stay independent', scope: 'failed and malformed peers, slow consumer', covers: ['DRV-2.21', 'CLD-0.5'], async run(home) {
  const id = await signed(home);
  const [good, bad] = await Promise.all([start(home, id, 'hold'), start(home, id, 'fail')]); stream(good); stream(bad, 'failed');
  await home.part('malformed'); const malformed = await start(home, id); stream(malformed, 'failed');
  await home.part('plain'); stream(await start(home, id));
  const slow = home.start(['run', '--subscription', id, 'slow']); slow.child.stdout.pause();
  try { await delay(300); const began = performance.now(); stream(await start(home, id)); check('Peer completes while output blocked', performance.now() - began < 5000, 'under 5 seconds', performance.now() - began); }
  finally { slow.child.stdout.resume(); await slow.dispose(); }
} };
export const c19: Scenario = { id: 'C19', title: 'No tools and no leftover work folder', scope: 'no tools, no session persistence, fresh scratch cleanup', covers: ['DRV-2.20'], async run(home) {
  const records = stream(await start(home, await signed(home))); equal('One whole text', records.filter(event => event.type === 'text').length, 1);
  equal('No calls', records.filter(event => event.type === 'tool_started').length, 0);
  const received = (await calls(home)).at(-1)!; check('Tools off', received.arguments.includes('--tools') && received.arguments[received.arguments.indexOf('--tools') + 1] === '', 'empty tool list', received);
  check('No persistence', received.arguments.includes('--no-session-persistence'), '--no-session-persistence', received);
  equal('Work folder removed', await stat(received.workingDirectory).then(() => false).catch(() => true), true);
  const info = await home.json(['info']); equal('No temporary run folders', await readdir(join(String(info.result.stateDirectory), 'tmp')), []);
} };
export const c20: Scenario = { id: 'C20', title: 'Large tool results are cut', scope: 'text and structure, UTF-8 boundary', covers: ['DRV-2.22'], async run(home) {
  const id = await signed(home);
  for (const part of ['text', 'structure']) {
    await home.part(part); const records = stream(await start(home, id, 'answer', ['--tools', 'all', '--cwd', home.home]));
    const result = records.find(event => event.type === 'tool_finished')!; equal('Cut flag', result.truncated, true);
    check('Result length', Buffer.byteLength(typeof result.result === 'string' ? result.result : JSON.stringify(result.result)) <= 200 * 1024, 'at most 200 KiB', result);
    check('Whole UTF-8 characters', !JSON.stringify(result.result).includes('�'), 'valid UTF-8', result.result);
  }
} };
export const c33: Scenario = { id: 'C33', title: 'Run input and active records', scope: 'no control, stdin request, malformed control and runs list; questions and runs stop pending', covers: ['DRV-2.25', 'DRV-2.27', 'DRV-2.28', 'DRV-6.7'], async run(home) {
  const id = await signed(home); stream(await start(home, id));
  const active = home.start(['run', '--subscription', id, '--run-id', 'visible-run', '--control', 'hold']);
  try {
    active.child.stdin.write('not-json\n'); active.send({ type: 'answer', askId: 'missing', answer: {} });
    let listed: Record<string, any>[] = [];
    for (let n = 0; n < 100; n++) { listed = JSON.parse((await home.call(['runs', 'list'])).stdout); if (listed.some(r => r.runId === 'visible-run')) break; await delay(10); }
    check('Active run listed', listed.some(r => r.runId === 'visible-run' && r.subscriptionId === id), 'visible-run', listed);
    const records = stream(await active.done); equal('Control refusals', records.filter(event => event.type === 'control_refused').length, 2);
  } finally { await active.dispose(); }
  const request = home.start(['run', '--request', '-']);
  try { request.send({ subscriptionId: id, history: [], tools: 'none', input: { role: 'user', text: 'stdin' } }); request.child.stdin.end(); stream(await request.done); }
  finally { await request.dispose(); }
  equal('No ended runs listed', JSON.parse((await home.call(['runs', 'list'])).stdout), []);
} };
export const c42: Scenario = { id: 'C42', title: 'Failure preserves output and unfinished calls', scope: 'unexpected exit with output and known usage; no retry', covers: ['DRV-2.8', 'DRV-2.9', 'DRV-2.10'], async run(home) {
  const id = await signed(home); const records = stream(await start(home, id), 'failed'); const final = records.at(-1)!;
  equal('Output retained', records.filter(event => event.type === 'text').map(event => event.text), ['answer']); equal('Produced output', final.producedOutput, true);
  equal('Unfinished call named', final.unfinishedCalls, ['fixture-call']); equal('Usage retained', final.usage.inputTokens, 3);
  equal('Call closed once', records.filter(event => event.type === 'tool_finished').length, 1); equal('No retry', (await calls(home)).length, 1);
} };
export const c43: Scenario = { id: 'C43', title: 'State failure has one final event', scope: 'state path is an unwritable regular file', covers: ['DRV-4.15'], async run(home) {
  const path = join(home.home, 'blocked-state'); await writeFile(path, 'file');
  const records = stream(await home.call(['run', '--state-dir', path, 'answer']), 'failed'); equal('Only final event', records.length, 1); equal('Internal failure', records[0]!.error.code, 'internal');
} };
export async function runRefusals(home: ScenarioHome): Promise<void> {
  const id = await signed(home);
  for (const args of [['--cwd', join(home.home, 'gone')], ['--model', 'unknown-model'], ['--model', 'haiku', '--effort', 'high'], ['--service-tier', 'fast']]) {
    const records = stream(await start(home, id, 'answer', args), 'failed'); equal('Only final refusal', records.length, 1); equal('Invalid request', records[0]!.error.code, 'invalid_input');
  }
  await home.part('dropped-effort'); stream(await start(home, id, 'answer', ['--model', 'sonnet', '--effort', 'low']), 'failed');
  await home.part('plain'); const first = home.start(['run', '--subscription', id, '--run-id', 'same-id', 'hold']);
  try {
    for (let n = 0; n < 100; n++) { if (JSON.parse((await home.call(['runs', 'list'])).stdout).some((r: any) => r.runId === 'same-id')) break; await delay(10); }
    const refused = stream(await start(home, id, 'answer', ['--run-id', 'same-id']), 'failed'); equal('Duplicate identifier', refused[0]!.error.code, 'in_use'); stream(await first.done);
  } finally { await first.dispose(); }
  const input = (await home.received()).filter(record => record.stage === 'input'); equal('Only accepted run reached inference', input.length, 1);
}
