import { createHash } from 'node:crypto';
import { readFile, readdir, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { check, equal, object, text } from '../check.js';
import { signed, stream } from './runs.js';
import type { Scenario } from './types.js';
import type { ScenarioHome } from '../harness.js';
const delay = async (ms: number): Promise<void> => new Promise(resolve => setTimeout(resolve, ms));
const alive = (pid: number): boolean => { try { process.kill(pid, 0); return true; } catch { return false; } };
export async function waitFor(checkName: string, predicate: () => Promise<boolean>, timeout = 5000): Promise<void> {
  const deadline = performance.now() + timeout;
  while (!await predicate()) { check(checkName, performance.now() < deadline, 'within deadline', timeout); await delay(10); }
}
async function input(home: ScenarioHome, part: string, after = 0) {
  await waitFor('Tool accepts message', async () => (await home.received()).slice(after).some(record => record.stage === 'input' && record.part === part));
  return (await home.received()).slice(after).filter(record => record.stage === 'input' && record.part === part).at(-1)!;
}
async function gone(pid: unknown): Promise<void> {
  if (typeof pid === 'number') await waitFor('Background process ended', async () => !alive(pid));
}
export const c15: Scenario = { id: 'C15', title: 'Stop closes partial output, calls, questions and sub-agents', scope: 'interrupt, cancellation ordering, 2/15 second limits, ignored interrupt and peer isolation',
  covers: ['DRV-2.3', 'DRV-2.8', 'DRV-2.16', 'DRV-2.17', 'DRV-2.19', 'DRV-2.21', 'DRV-2.25'], async run(home) {
    const id = await signed(home); home.env.ARBOL_TEST_TIME_SCALE = '1';
    for (const part of ['text', 'tool', 'question', 'subagent', 'stubborn']) {
      if (part === 'question' && (await home.json(['info'])).result.driver === 'codex') continue;
      await home.part(part); const active = home.start(['run', '--subscription', id, '--tools', 'all', '--cwd', home.home, '--control', 'answer']);
      try {
        const seen = await input(home, part);
        await waitFor('Partial output arrives', async () => active.lines.some((event: any) => event.type === 'text_delta'));
        if (part === 'question') await waitFor('Question is open', async () => active.lines.some((event: any) => event.type === 'ask_opened'));
        if (part === 'subagent') {
          await waitFor('Sub-agent is working', async () => active.lines.some((event: any) => event.parentCallId));
          await waitFor('Sub-agent records active work', async () => (await home.received()).some(record => record.stage === 'subagent-tick'));
        }
        const start = performance.now(); active.send({ type: 'stop' }); const records = stream(await active.done, 'cancelled');
        const elapsed = performance.now() - start;
        check('Stop finishes within fifteen seconds', elapsed < 15000, '< 15 seconds', elapsed);
        check('Tool asked to interrupt', (await home.received()).some(record => record.stage === 'interrupt' && record.part === part), 'interrupt request', await home.received());
        if (part === 'stubborn') check('Escalation after two seconds', elapsed >= 1900 && elapsed < 5000, 'about two seconds', elapsed);
        equal('Earlier delta preserved', records.find(event => event.type === 'text_delta')!.text, 'partial');
        equal('Output reported', records.at(-1)!.producedOutput, true);
        for (const call of records.filter(event => event.type === 'tool_started')) equal('Every call closed once', records.filter(event => event.type === 'tool_finished' && event.callId === call.callId).length, 1);
        if (part === 'tool') equal('Running call interrupted', records.find(event => event.type === 'tool_finished')!.interrupted, true);
        if (part === 'question') equal('Question withdrawn', records.find(event => event.type === 'ask_closed')!.reason, 'withdrawn');
        await gone(seen.checks.backgroundPid); await gone(seen.checks.toolPid);
        const before = (await home.received()).filter(record => record.stage === 'subagent-tick').length;
        await delay(100); equal('No sub-agent activity after final', (await home.received()).filter(record => record.stage === 'subagent-tick').length, before);
      } finally { await active.dispose(); }
    }
    await home.part('hold'); const held = home.start(['run', '--subscription', id, '--control', 'answer']);
    try { await input(home, 'hold'); await home.part('plain'); stream(await home.call(['run', '--subscription', id, 'peer'])); held.send({ type: 'stop' }); stream(await held.done, 'cancelled'); }
    finally { await held.dispose(); }
    const early = home.start(['run', '--subscription', id, '--control', 'answer']);
    try { early.send({ type: 'stop' }); stream(await early.done, 'cancelled'); }
    finally { await early.dispose(); }
  } };
export const c16: Scenario = { id: 'C16', title: 'Stopping ended or unknown runs succeeds', scope: 'idempotent runs stop', covers: ['DRV-2.18'], async run(home) {
  const id = await signed(home); stream(await home.call(['run', '--subscription', id, '--run-id', 'ended', 'answer']));
  for (const run of ['ended', 'unknown']) { const reply = await home.call(['runs', 'stop', run]); equal('Successful stop', reply.status, 0); equal('No output', reply.stdout, ''); }
} };
export const c17: Scenario = { id: 'C17', title: 'Every end path clears shell process groups', scope: 'normal result, hanging exit, SIGINT, SIGTERM, input EOF, broken event pipe',
  covers: ['DRV-0.10', 'DRV-2.19', 'DRV-2.26'], async run(home) {
    const id = await signed(home);
    for (const path of ['normal', 'linger', 'SIGINT', 'SIGTERM', 'input', 'output']) {
      const part = path === 'normal' ? 'background' : path === 'linger' ? 'linger' : 'hold'; await home.part(part);
      const after = (await home.received()).length;
      const active = home.start(['run', '--subscription', id, '--tools', 'all', '--cwd', home.home, '--control', 'answer']);
      try {
        const seen = await input(home, part, after); const pid = seen.checks.backgroundPid;
        check('Background child was alive', typeof pid === 'number' && seen.checks.backgroundWasAlive === true, 'live background process before final', pid);
        if (path === 'SIGINT' || path === 'SIGTERM') active.child.kill(path);
        if (path === 'input') active.child.stdin.end();
        if (path === 'output') { active.child.stdout.destroy(); active.child.kill('SIGCONT'); }
        // Closing a pipe is observed when the next event is written.
        if (path === 'output') active.send({ type: 'unrecognized' });
        const reply = await active.done;
        if (path !== 'output') stream(reply, path === 'normal' || path === 'linger' ? 'completed' : 'cancelled');
        else equal('Broken output cancels', reply.status, 2);
        await gone(pid); await gone(seen.checks.toolPid);
      } finally { await active.dispose(); }
    }
} };
export const c38: Scenario = { id: 'C38', title: 'Recover a killed Driver and protect durable state', scope: 'orphan tool and shell groups, resumed map removal, concurrent recovery, format, empty state and concurrent subscription creation; sign-in independence covered by C6',
  covers: ['DRV-6.1', 'DRV-6.3', 'DRV-6.10', 'DRV-0.9', 'DRV-1.10'], async run(home) {
    const id = await signed(home); const info = await home.json(['info']); const state = text('State directory', info.result.stateDirectory);
    const key = createHash('sha256').update('recovery-chat').digest('hex'); const mapPath = join(state, 'subscriptions', id, 'chats', key + '.json');
    const request = { subscriptionId: id, tools: 'all', workingDirectory: home.home, chatSessionId: 'recovery-chat', history: [] as object[], input: { role: 'user', text: 'answer' } };
    const file = join(home.home, 'request.json'); await writeFile(file, JSON.stringify(request));
    await home.part('plain'); const first = stream(await home.call(['run', '--request', file]));
    request.history = [{ type: 'message', role: 'user', text: 'answer' }, ...first.filter(event => event.type === 'text').map(event => ({ type: 'message', role: 'assistant', text: event.text }))];
    await writeFile(file, JSON.stringify({ ...request, runId: 'killed-run' })); await home.part('hold');
    const active = home.start(['run', '--request', file]);
    try {
      const seen = await input(home, 'hold');
      await waitFor('Native resume began', async () => active.lines.some((event: any) => event.type === 'started' && event.continuity === 'resumed'));
      active.child.kill('SIGKILL'); await active.done;
      const replies = await Promise.all([home.call(['runs', 'list']), home.call(['runs', 'list'])]);
      for (const reply of replies) { equal('Recovery succeeded', reply.status, 0); equal('No orphan run listed', JSON.parse(reply.stdout), []); }
      await gone(seen.checks.toolPid); await gone(seen.checks.backgroundPid);
      equal('Run folder gone', await stat(join(state, 'tmp', 'killed-run')).then(() => false).catch(() => true), true);
      equal('Continued map gone', await stat(mapPath).then(() => false).catch(() => true), true);
      equal('Run record gone', await stat(join(state, 'runs', 'killed-run.json')).then(() => false).catch(() => true), true);
    } finally { await active.dispose(); }
    const created = await Promise.all(['One', 'Two'].map(label => home.json(['subscriptions', 'create', '--family', id, '--label', label])));
    for (const reply of created) equal('Concurrent change succeeds', reply.process.status, 0);
    check('Distinct creations kept', created[0]!.result.id !== created[1]!.result.id, 'different identifiers', created.map(reply => reply.result.id));
    const listed = JSON.parse((await home.call(['subscriptions', 'list'])).stdout) as Record<string, unknown>[];
    for (const reply of created) equal('Both creations persisted', listed.find(item => item.id === reply.result.id)?.label, reply.result.label);
    const empty = join(home.home, 'empty-state'); equal('Empty state works', (await home.call(['info', '--state-dir', empty])).status, 0);
    await writeFile(join(empty, 'format'), '999\n'); const newer = await home.json(['info', '--state-dir', empty]);
    equal('Newer format refused', newer.process.status, 1); equal('Format refusal', object('Error', newer.result.error).code, 'state_newer');
    equal('Newer format unchanged', await readFile(join(empty, 'format'), 'utf8'), '999\n');
    equal('No recovered scratch files', await readdir(join(state, 'tmp')), []);
} };
