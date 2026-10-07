import { readFile, writeFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { check, equal, object } from '../check.js';
import { signed, stream, events as parseEvents } from './runs.js';
import type { ScenarioHome } from '../harness.js';
import type { Scenario } from './types.js';
const run = (home: ScenarioHome, id: string) => home.call(['run', '--subscription', id, 'answer']);
const subscription = async (home: ScenarioHome, id: string): Promise<Record<string, any>> => object('Subscription', JSON.parse((await home.call(['subscriptions', 'list'])).stdout).find((value: any) => value.id === id));
const inputs = async (home: ScenarioHome) => (await home.received()).filter(record => record.stage === 'input');
const codex = async (home: ScenarioHome) => (await home.json(['info'])).result.driver === 'codex';
const limitReads = (records: Awaited<ReturnType<ScenarioHome['received']>>) => records.filter(record => record.stage === 'request' && object('Vendor request', record.request).method === 'account/rateLimits/read');
export const c26: Scenario = { id: 'C26', title: 'Every error mapping row', scope: 'field precedence, wording fallback, absent result, unknown failures and retry policy', covers: ['DRV-4.1', 'DRV-4.4'], async run(home) {
  const isCodex = await codex(home);
  const rows = isCodex ? [
    ['unauthorized', 'credential_rejected'], ['usageLimitExceeded', 'rate_limited'], ['rateLimitExceeded', 'rate_limited'], ['contextWindowExceeded', 'context_exceeded'],
    ...['serverOverloaded', 'internalServerError', 'flexUnavailable'].map(part => [part, 'vendor_unavailable']),
    ...['httpConnectionFailed', 'responseStreamConnectionFailed', 'responseStreamDisconnected', 'responseTooManyFailedAttempts'].flatMap(part => [
      ['401', 'credential_rejected'], ['403', 'credential_rejected'], ['500', 'vendor_unavailable'], ['none', 'vendor_unavailable'], ['400', 'vendor_error'],
    ].map(([status, code]) => [part + '-' + status, code!])),
    ...['cyberPolicy', 'misalignmentPolicyViolation', 'tooManyDenials', 'badRequest', 'sessionBudgetExceeded'].map(part => [part, 'vendor_error']),
    ...['sandboxError', 'threadRollbackFailed', 'activeTurnNotSteerable'].map(part => [part, 'tool_failed']),
    ['model', 'invalid_input'], ['effort', 'invalid_input'], ['tool-newer', 'tool_unsupported'],
    ['wording-rate', 'rate_limited'], ['wording-auth', 'credential_rejected'], ['missing-class-rate', 'rate_limited'], ['missing-class-auth', 'credential_rejected'],
    ['unknown-class', 'vendor_error'], ['unknown', 'vendor_error'], ['bare-fragments', 'vendor_error'], ['exit', 'tool_failed'],
  ] : [ ['authentication', 'credential_rejected'], ['401', 'credential_rejected'], ['403', 'credential_rejected'], ['model', 'invalid_input'], ['404', 'invalid_input'],
    ['rate', 'rate_limited'], ['429', 'rate_limited'], ['server', 'vendor_unavailable'], ['503', 'vendor_unavailable'], ['context', 'context_exceeded'],
    ['400', 'vendor_error'], ['418', 'vendor_error'], ['other-code', 'vendor_error'], ['turns', 'limit_reached'], ['missing', 'tool_missing'], ['argument', 'tool_unsupported'],
    ['exit', 'tool_failed'], ['wording-rate', 'rate_limited'], ['wording-auth', 'credential_rejected'], ['unknown', 'vendor_error'] ];
  for (const [part, code] of rows) {
    const id = await signed(home); await home.part(part!); const before = (await inputs(home)).length;
    const events = stream(await run(home, id), 'failed'), error = events.at(-1)!.error;
    equal('Code for ' + part, error.code, code); equal('Retryable ' + part, error.retryable, ['rate_limited', 'vendor_unavailable'].includes(code!));
    const wording = part!.startsWith('wording') || part!.startsWith('missing-class') || part === 'tool-newer' || part === 'bare-fragments' || part === 'unknown' || part === 'argument';
    equal('Classification basis ' + part, error.detail.basis, wording ? 'wording' : 'fields');
    equal('No Driver retry ' + part, (await inputs(home)).length - before, 1);
    if (code === 'credential_rejected') { const record = await subscription(home, id); equal('Attention state', record.state, 'needs_attention'); equal('Stored problem', record.problem, error); }
    if (['missing', 'argument', 'exit'].includes(part!)) { check('Exit detail', Number.isInteger(error.detail.toolExit), 'tool exit code', error); check('Bounded excerpt', Buffer.byteLength(error.detail.excerpt) <= 1024, '<= 1 KiB', error); }
  }
  if (isCodex) {
    const id = await signed(home); await home.part('old-handshake');
    const error = stream(await run(home, id), 'failed').at(-1)!.error;
    equal('Handshake version rejected', error.code, 'tool_unsupported'); equal('Handshake found version', error.detail.toolVersion, '0.159.1'); equal('Handshake needed version', error.detail.neededVersion, '0.159.2');
    equal('Old handshake starts no turn', (await inputs(home)).filter(record => record.part === 'old-handshake').length, 0);
  }
} };
export const c27: Scenario = { id: 'C27', title: 'Rate limit waits', scope: 'seconds, minutes, omitted wait and limiting-window reset; no Driver retry', covers: ['DRV-4.5', 'DRV-4.6'], async run(home) {
  const isCodex = await codex(home), id = await signed(home);
  for (const [part, wait] of [['seconds', 8], ['minutes', 300], ['none', undefined], ['reset', 'reset']] as const) {
    await home.part(part); const before = (await inputs(home)).length, beforeReads = limitReads(await home.received()).length;
    const error = stream(await run(home, id), 'failed').at(-1)!.error;
    equal('Rate limit', error.code, 'rate_limited');
    if (wait === 'reset') check('Reset wait', typeof error.retryAfterSeconds === 'number' && error.retryAfterSeconds > 0, 'positive vendor reset wait', error);
    else equal('Named wait ' + part, error.retryAfterSeconds, wait);
    equal('Still signed in', (await subscription(home, id)).state, 'signed_in'); equal('No Driver retry', (await inputs(home)).length - before, 1);
    if (isCodex) equal('One post-limit read', limitReads(await home.received()).length - beforeReads, 1);
  }
} };
export const c28: Scenario = { id: 'C28', title: 'Stop rejected retries', scope: 'first retry ends run and marks the account before any later retry', covers: ['DRV-4.7', 'DRV-4.8', 'DRV-4.12'], async run(home) {
  const isCodex = await codex(home), id = await signed(home); const events = stream(await run(home, id), 'failed');
  equal('Credential refusal', events.at(-1)!.error.code, 'credential_rejected'); equal('One retry notice', events.filter(event => event.type === 'notice' && event.code === (isCodex ? 'retrying' : 'api_retry')).length, 1);
  equal('No second retry', (await home.received()).filter(record => record.stage === 'second-retry').length, 0);
  equal('Cleanup requested', (await home.received()).filter(record => record.stage === 'interrupt').length, 1);
  if (isCodex) equal('Codex has no retry-count setting', (await inputs(home))[0]!.checks.retryBoundSupported, false);
  else equal('Retry bound', (await inputs(home))[0]!.checks.maxRetries, '3');
  equal('Account marked', (await subscription(home, id)).state, 'needs_attention');
  if (isCodex) equal('Stored retry problem', (await subscription(home, id)).problem, events.at(-1)!.error);
} };
export const c29: Scenario = { id: 'C29', title: 'Run clocks and waiting work', scope: 'start, silent idle, heartbeats, idle off, tool call, background command, question and total while busy', covers: ['DRV-4.9', 'DRV-4.10', 'DRV-4.11', 'DRV-3.27', 'DRV-3.32'], async run(home) {
  const isCodex = await codex(home), id = await signed(home); home.env.ARBOL_TEST_TIME_SCALE = '100';
  const info = await home.json(['info']), root = String(info.result.stateDirectory);
  // Codex explicitly refuses caller questions (C25); it cannot open one for an idle-clock check.
  for (const part of ['start', 'idle', 'call', 'background', 'heartbeat', 'idle-off', 'total', ...isCodex ? [] : ['question']]) {
    await home.part(part);
    const request = { subscriptionId: id, runId: 'clock-' + part, tools: 'all', history: [], workingDirectory: home.home, input: { role: 'user', text: 'answer' },
      limits: { idleSeconds: part === 'idle-off' ? 0 : 0.15, ...(part === 'total' ? { totalSeconds: 0.3 } : {}) } };
    const file = join(home.home, 'request.json'); await writeFile(file, JSON.stringify(request));
    let reply;
    if (part === 'question') {
      const active = home.start(['run', '--request', file, '--control']);
      try {
        const deadline = performance.now() + 5000;
        while (!active.lines.some((event: any) => event.type === 'ask_opened')) { check('Question opens', performance.now() < deadline, 'before deadline', active.lines); await new Promise(resolve => setTimeout(resolve, 10)); }
        await new Promise(resolve => setTimeout(resolve, 450)); equal('No idle timeout for question', active.lines.some((event: any) => event.type === 'finished'), false);
        const ask = active.lines.find((event: any) => event.type === 'ask_opened') as any;
        active.send({ type: 'answer', askId: ask.askId, answer: { type: 'answers', answers: { [ask.ask.questions[0].id]: ['Blue'] } } }); reply = await active.done;
      } finally { await active.dispose(); }
    } else reply = await home.call(['run', '--request', file]);
    const limit = ['start', 'idle', 'total'].includes(part);
    check('Clock outcome ' + part, parseEvents(reply).at(-1)?.outcome === (limit ? 'failed' : 'completed'), limit ? 'failed' : 'completed', reply);
    const events = stream(reply, limit ? 'failed' : 'completed');
    if (limit) { equal('Limit code', events.at(-1)!.error.code, 'limit_reached'); equal('Named limit', events.at(-1)!.error.detail.limit, part); }
    for (const call of events.filter(event => event.type === 'tool_started')) {
      const finished = events.filter(event => event.type === 'tool_finished' && event.callId === call.callId);
      equal('Call closed once', finished.length, 1);
      if (isCodex && ['call', 'background'].includes(part)) equal('Busy command completes', finished[0]!.ok, true);
      if (isCodex && part === 'total') equal('Total limit interrupts busy command', finished[0]!.interrupted, true);
    }
    equal('Scratch removed', await stat(join(root, 'tmp', request.runId)).then(() => false).catch(() => true), true);
    equal('Run record removed', await stat(join(root, 'runs', request.runId + '.json')).then(() => false).catch(() => true), true);
  }
} };
export const c30: Scenario = { id: 'C30', title: 'Latest run limit information', scope: 'latest report stored at completion and read without a tool invocation', covers: ['DRV-4.13', 'DRV-1.18'], async run(home) {
  const isCodex = await codex(home), id = await signed(home);
  if (isCodex) equal('Seed rich usage', (await home.json(['subscriptions', 'usage', id])).result.outcome, 'ok');
  const beforeRunReads = limitReads(await home.received()).length;
  stream(await run(home, id)); const record = await subscription(home, id);
  equal('Usage outcome', record.lastUsage.outcome, 'ok'); equal('Latest shares', record.lastUsage.windows.map((window: any) => window.usedPercent), [25, 100]);
  equal('Window durations', record.lastUsage.windows.map((window: any) => window.windowMinutes), [300, 10080]);
  equal('Exhausted window', record.lastUsage.windows.map((window: any) => window.limitReached), [false, true]);
  if (isCodex) {
    equal('Normal run does not poll limits', limitReads(await home.received()).length, beforeRunReads);
    equal('Sparse update keeps reached reason', record.lastUsage.extra.rateLimitReachedType, 'rate_limit_reached');
    equal('Sparse update keeps false value', record.lastUsage.extra.spendControlReached, false);
  }
  const before = (await home.received()).length;
  // Codex's explicit usage command refreshes account limits; list exposes its stored report.
  const cached = isCodex ? (await subscription(home, id)).lastUsage : (await home.json(['subscriptions', 'usage', id])).result;
  equal('Cached report', cached, record.lastUsage);
  equal('No tool for cached usage', (await home.received()).length, before);
} };
