import { readFile, writeFile, readdir, stat, rm, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createServer } from 'node:http';
import { check, equal, object, text } from '../check.js';
import type { Scenario } from './types.js';
import type { ScenarioHome } from '../harness.js';
import { stream } from './runs.js';
const exec = promisify(execFile);
const key = 'fixture-key-SECRET-781';
const delay = async (ms: number): Promise<void> => new Promise(resolve => setTimeout(resolve, ms));
const subscription = async (home: ScenarioHome, id: string): Promise<Record<string, unknown>> => {
  const reply = await home.call(['subscriptions', 'list']); equal('List exit', reply.status, 0);
  return object('Subscription', JSON.parse(reply.stdout).find((value: Record<string, unknown>) => value.id === id));
};
async function families(home: ScenarioHome): Promise<Record<string, unknown>[]> {
  const reply = await home.call(['subscriptions', 'families']); equal('Families exit', reply.status, 0);
  return (JSON.parse(reply.stdout) as unknown[]).map(value => object('Family', value));
}
async function state(home: ScenarioHome): Promise<string> {
  const info = await home.json(['info']); equal('Info exit', info.process.status, 0); return text('State path', info.result.stateDirectory);
}
async function signIn(home: ScenarioHome, id: string, byCode = false) {
  const interaction = home.start(['subscriptions', 'sign-in', id, ...(byCode ? ['--by-code'] : [])]);
  try {
    if (byCode) {
      const family = (await subscription(home, id)).family;
      if (family === 'chatgpt') {
        const step = await interaction.step('open_url'); text('Device user code', step.userCode);
      } else { await interaction.step('enter_code'); interaction.send({ input: 'fixture-code' }); }
    }
    const done = await interaction.step('done');
    const result = await interaction.done; equal('Sign-in exit', result.status, 0);
    equal('Signed in', object('Done Subscription', done.subscription).state, 'signed_in');
    return { done, result, lines: interaction.lines };
  } finally { await interaction.dispose(); }
}
async function gatewayFixture(home: ScenarioHome) {
  let mode = 'ok'; const paths: string[] = [];
  const server = createServer((request, response) => {
    paths.push(request.url ?? '');
    if (request.headers.authorization !== `Bearer ${key}`) { response.writeHead(401); response.end('{}'); return; }
    response.setHeader('Content-Type', 'application/json');
    if (mode === 'rejected') { response.writeHead(403); response.end('{}'); return; }
    if (mode === 'unavailable') { response.writeHead(503); response.end(JSON.stringify({ message: `Temporary outage ${key}` })); return; }
    response.end(JSON.stringify(request.url === '/api/paas/v4/models' ? { data: [{ id: 'fixture-gateway-model', label: 'Fixture gateway' }] } :
      { success: true, data: { planName: 'Fixture plan', limits: [
        { type: 'TOKENS_LIMIT', unit: 3, number: 5, percentage: 99, usage: 100, remaining: 75, nextResetTime: Date.now() + 60000 },
        { type: 'CREDIT_LIMIT', unit: 6, number: 1, percentage: 40 },
        { type: 'TIME_LIMIT', percentage: 7 },
      ] } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); check('Listener address', address !== null && typeof address !== 'string', 'a TCP listener', address);
  const source = join(home.home, 'secret-source');
  await writeFile(source, `#!/bin/sh\nprintf '%s\\n' '${key}'\n`, { mode: 0o700 });
  const settings = { subscriptions: { zai: { secret: { from: 'command', command: [source] }, settings: {
    baseUrl: `http://127.0.0.1:${address.port}/gateway`, modelMap: { haiku: 'fixture-fallback' },
  } } } };
  await home.settings(settings);
  return { paths, settings, mode(value: string) { mode = value; }, async dispose() { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); } };
}
async function keychain(args: string[], instruction?: string): Promise<{ status: number | null; stdout: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn('/usr/bin/security', args, { stdio: 'pipe', env: { PATH: '/usr/bin:/bin' } });
    let stdout = ''; child.stdout.setEncoding('utf8'); child.stdout.on('data', text => { stdout += text; }); child.stderr.resume();
    child.on('error', reject); child.on('close', status => resolve({ status, stdout })); child.stdin.end(instruction);
  });
}
const securityQuote = (value: string): string => '"' + value.replaceAll('\\', '\\\\').replaceAll('"', '\\"') + '"';
async function store(service: string, id: string, value: string): Promise<void> {
  const result = await keychain(['-i'], `add-generic-password -U -s ${securityQuote(service)} -a ${securityQuote(id)} -w ${securityQuote(value)}\n`);
  equal('Synthetic Keychain write', result.status, 0);
}
async function files(directory: string): Promise<string[]> {
  const result: string[] = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) result.push(...await files(path)); else if (entry.isFile()) result.push(path);
  }
  return result;
}

export const c2: Scenario = { id: 'C2', title: 'Sign-in steps, replacement and expiry', scope: 'vendor login, code, command key and Keychain step; replacement and five-minute expiry', covers: ['DRV-1.5', 'DRV-1.6', 'DRV-1.25', 'DRV-6.9'], async run(home) {
  home.env.ARBOL_TEST_TIME_SCALE = '10';
  const vendor = (await families(home)).find(value => value.auth === 'vendor_login'); check('Vendor login family', !!vendor, 'a vendor-login family', vendor);
  const id = text('Family identifier', vendor.id);
  await home.part('success'); const direct = await signIn(home, id);
  const open = object('Open URL', direct.lines.find(value => object('Step', value).step === 'open_url'));
  check('Host list', Array.isArray(open.allowedHosts) && open.allowedHosts.includes(new URL(text('URL', open.url)).hostname), 'URL hostname on allowedHosts', open);
  await home.part('by-code'); await signIn(home, id, true);
  await home.part('waiting'); const first = home.start(['subscriptions', 'sign-in', id]);
  try {
    await first.step('open_url'); equal('Pending state', (await subscription(home, id)).state, 'signing_in');
    const changed = await home.json(['subscriptions', 'update', id, '--label', 'Changed while waiting']); equal('No lock across sign-in', changed.process.status, 0);
    await home.part('success'); await signIn(home, id);
    const replaced = await first.step('failed'); equal('Replacement error', object('Error', replaced.error).code, 'in_use'); equal('Replaced exit', (await first.done).status, 1);
  } finally { await first.dispose(); }
  if (id === 'chatgpt') {
    equal('Create another login home', (await home.json(['subscriptions', 'create', '--family', id, '--label', 'Other login', '--id', 'login-other'])).process.status, 0);
    await home.part('waiting'); const machine = home.start(['subscriptions', 'sign-in', id]);
    try {
      await machine.step('open_url'); await home.part('success'); await signIn(home, 'login-other');
      const replaced = await machine.step('failed'); equal('Machine-wide replacement error', object('Error', replaced.error).code, 'in_use');
      equal('Machine-wide replaced exit', (await machine.done).status, 1); equal('Replaced home signed out', (await subscription(home, id)).state, 'signed_out');
    } finally { await machine.dispose(); }
    await home.part('waiting'); const device = home.start(['subscriptions', 'sign-in', id, '--by-code']);
    try {
      const step = await device.step('open_url'); text('Device code', step.userCode);
      await home.part('success'); await signIn(home, 'login-other');
      equal('Device login is independent of machine login', (await subscription(home, id)).state, 'signing_in');
      device.stop(); equal('Device cancellation exit', (await device.done).status, 2);
    } finally { await device.dispose(); }
  }
  await home.part('waiting'); home.env.ARBOL_TEST_TIME_SCALE = '100';
  const pending = home.start(['subscriptions', 'sign-in', id]);
  try {
    await pending.step('open_url'); const expired = await pending.step('failed', 6000); equal('Timeout code', object('Error', expired.error).code, 'limit_reached');
    equal('Timeout exit', (await pending.done).status, 1); equal('Timeout signed out', (await subscription(home, id)).state, 'signed_out');
  } finally { await pending.dispose(); }
  if ((await families(home)).some(f => f.id === 'zai')) {
    await home.part('success'); const gateway = await gatewayFixture(home);
    let service: string | undefined;
    try {
      const signed = await signIn(home, 'zai'); check('Command key needs no store step', !signed.lines.some(value => object('Step', value).step === 'store_secret'), 'no store_secret', signed.lines);
      const settings = structuredClone(gateway.settings) as any; delete settings.subscriptions.zai.secret; await home.settings(settings);
      const pending = home.start(['subscriptions', 'sign-in', 'zai']);
      try {
        const step = await pending.step('store_secret'); service = text('Service', object('Keychain item', step.keychain).service);
        check('Isolated Keychain service', /\.[a-f0-9]{12}$/.test(service), 'hashed test-directory service', service);
        await store(service, 'zai', key); await pending.step('done'); equal('Keychain sign-in exit', (await pending.done).status, 0);
      } finally { await pending.dispose(); }
      const out = await home.json(['subscriptions', 'sign-out', 'zai']); equal('Key sign-out state', out.result.state, 'signed_out');
      equal('Sign-out removes Keychain item', (await keychain(['find-generic-password', '-s', service, '-a', 'zai', '-w'])).status, 44);
      await store(service, 'zai', key);
      const prefilled = await signIn(home, 'zai'); check('Prefilled item skips prompt', !prefilled.lines.some(value => object('Step', value).step === 'store_secret'), 'no store_secret', prefilled.lines);
      gateway.mode('rejected'); const rejected = home.start(['subscriptions', 'sign-in', 'zai']);
      try { const failed = await rejected.step('failed'); equal('Vendor rejects key', object('Error', failed.error).code, 'credential_rejected'); await rejected.done; }
      finally { await rejected.dispose(); }
      equal('Vendor-rejected key removed', (await keychain(['find-generic-password', '-s', service, '-a', 'zai', '-w'])).status, 44);
      gateway.mode('unavailable'); await store(service, 'zai', key);
      const unreachable = await signIn(home, 'zai'); equal('Unchecked key has no checkedAt', object('Subscription', unreachable.done.subscription).checkedAt, undefined);
      equal('Unreachable vendor keeps key', (await keychain(['find-generic-password', '-s', service, '-a', 'zai', '-w'])).stdout.trim(), key);
    } finally { if (service) await keychain(['delete-generic-password', '-s', service, '-a', 'zai']); await gateway.dispose(); }
  }
} };
export const c3: Scenario = { id: 'C3', title: 'Refusing a malformed Keychain key', scope: 'store_secret, invalid Unicode, deletion and isolated Keychain service; typed refusal where no key family is offered', covers: ['DRV-1.4', 'DRV-1.26'], async run(home) {
  const family = (await families(home)).find(value => value.auth === 'key');
  if (!family) {
    const before = (await home.received()).length;
    const refused = await home.json(['subscriptions', 'create', '--family', 'openai', '--label', 'Unsupported key', '--id', 'key-not-offered']);
    equal('Unavailable key family exit', refused.process.status, 1);
    equal('Unavailable key family refusal', object('Unavailable key family error', refused.result.error).code, 'invalid_input');
    equal('Unavailable key family starts no vendor', (await home.received()).length, before);
    return;
  }
  const id = text('Family id', family.id); const pending = home.start(['subscriptions', 'sign-in', id]); let service: string | undefined;
  try {
    const step = await pending.step('store_secret'); const item = object('Keychain item', step.keychain);
    service = text('Service', item.service); check('Test service is isolated', /\.[a-f0-9]{12}$/.test(service), 'hashed test-directory service', service);
    equal('Item account', item.account, id);
    await store(service, id, 'fixture-key\u201c\u00a0\u201d\u2014');
    const failed = await pending.step('failed'); const error = object('Error', failed.error); equal('Validation error', error.code, 'invalid_input');
    check('Offending characters named', typeof error.message === 'string' && error.message.includes('U+201C') && error.message.includes('U+00A0') && !error.message.includes('U+2014'), 'up to three invalid code points', error);
    equal('Failed sign-in exit', (await pending.done).status, 1);
    equal('Rejected key removed', (await keychain(['find-generic-password', '-s', service, '-a', id, '-w'])).status, 44);
    equal('Failed state', (await subscription(home, id)).state, 'signed_out');
  } finally { await pending.dispose(); if (service) await keychain(['delete-generic-password', '-s', service, '-a', id]); }
} };
export async function checkSubscriptionRejection(home: ScenarioHome, includeRuns = false): Promise<void> {
  await home.part('success'); home.env.ARBOL_TEST_TIME_SCALE = '10';
  for (const family of await families(home)) {
    const id = text('Family id', family.id); let gateway: Awaited<ReturnType<typeof gatewayFixture>> | undefined;
    if (family.auth === 'key') gateway = await gatewayFixture(home);
    try {
      await signIn(home, id);
      if (gateway) gateway.mode('rejected'); else await home.part('rejected');
      const rejected = await home.json(['subscriptions', 'check', id]); equal('Check exit', rejected.process.status, 0); equal('Rejected state', rejected.result.state, 'needs_attention');
      const problem = object('Problem', rejected.result.problem); equal('Credential code', problem.code, 'credential_rejected'); text('Remedy', problem.remedy);
      const before = (await home.received()).length;
      const refused = await home.json(['subscriptions', 'models', id]); equal('Models refuse attention state', object('Error', refused.result.error).code, 'not_signed_in');
      equal('Refused catalog starts no tool', (await home.received()).length, before);
      if (gateway) gateway.mode('ok'); else await home.part('success');
      const recovered = await home.json(['subscriptions', 'check', id]); equal('Check recovers attention state', recovered.result.state, 'signed_in'); equal('Problem cleared', recovered.result.problem, undefined);
      if (includeRuns) {
        const events = stream(await home.call(['run', '--subscription', id, 'answer']), 'failed');
        equal('Run rejected', events.at(-1)!.error.code, 'credential_rejected');
        const marked = await subscription(home, id); equal('Run marks Subscription', marked.state, 'needs_attention'); equal('Run problem stored', marked.problem, events.at(-1)!.error);
      }
    } finally { await gateway?.dispose(); }
  }
}
export const c4: Scenario = { id: 'C4', title: 'Rejected credentials and recovery', scope: 'check and run rejection, all families, and attention-state recovery', covers: ['DRV-1.7', 'DRV-4.7', 'DRV-1.11 (attention check)'], run: home => checkSubscriptionRejection(home, true) };

export async function checkSubscriptionRemoval(home: ScenarioHome): Promise<void> {
  const root = await state(home); home.env.ARBOL_TEST_TIME_SCALE = '10';
  const family = text('Vendor family', (await families(home)).find(f => f.auth === 'vendor_login')?.id);
  for (const operation of ['sign-out', 'remove']) {
    const id = operation === 'remove' ? 'removable' : family;
    if (operation === 'remove') equal('Create removable account', (await home.json(['subscriptions', 'create', '--family', family, '--label', 'Removable', '--id', id])).process.status, 0);
    await home.part('success'); await signIn(home, id);
    const out = await home.call(['subscriptions', operation, id]); equal('Subscription operation exit', out.status, 0);
    if (operation === 'sign-out') {
      const record = object('Signed-out record', JSON.parse(out.stdout)); equal('Signed-out state', record.state, 'signed_out');
      equal('Account removed', record.account, undefined); equal('Cached usage removed', record.lastUsage, undefined);
    } else {
      equal('Removal returns no document', out.stdout, '');
      equal('Removed Subscription absent', (JSON.parse((await home.call(['subscriptions', 'list'])).stdout) as any[]).some(value => value.id === id), false);
      equal('Home removed', await stat(join(root, 'subscriptions', id, 'home')).then(() => false).catch(() => true), true);
    }
  }
}
export const c5: Scenario = { id: 'C5', title: 'Sign-out and removal while a real run uses the account', scope: 'live run refusal, forced cancellation, shell cleanup and account removal', covers: ['DRV-1.12'], async run(home) {
  const root = await state(home); home.env.ARBOL_TEST_TIME_SCALE = '10';
  const id = text('Vendor family', (await families(home)).find(f => f.auth === 'vendor_login')?.id);
  for (const operation of ['sign-out', 'remove']) {
    await home.part('success'); await signIn(home, id); await home.part('hold');
    const active = home.start(['run', '--subscription', id, '--tools', 'all', '--cwd', home.home, '--control', 'answer']);
    try {
      const deadline = performance.now() + 5000;
      while (!active.lines.some((event: any) => event.type === 'started')) { check('Run starts', performance.now() < deadline, 'within five seconds', active.lines); await delay(10); }
      const refused = await home.json(['subscriptions', operation, id]); equal('Busy refusal', object('Error', refused.result.error).code, 'in_use'); equal('Busy exit', refused.process.status, 1);
      equal('Refusal retains login', (await subscription(home, id)).state, 'signed_in');
      const forced = await home.call(['subscriptions', operation, id, '--force']); equal('Forced exit', forced.status, 0);
      stream(await active.done, 'cancelled');
      equal('Run record removed', await readdir(join(root, 'runs')), []);
      equal('Run folder removed', await readdir(join(root, 'tmp')), []);
      const seen = (await home.received()).filter(record => record.stage === 'input').at(-1)!;
      for (const pid of [seen.checks.toolPid, seen.checks.backgroundPid]) if (typeof pid === 'number') {
        equal('Tool and shell leftovers ended', await exec('/bin/ps', ['-p', String(pid), '-o', 'stat=']).then(reply => !reply.stdout.trim().startsWith('Z')).catch(() => false), false);
      }
      equal('Credential removed', (await subscription(home, id)).state, 'signed_out');
      if (operation === 'remove') equal('Home removed', await stat(join(root, 'subscriptions', id, 'home')).then(() => false).catch(() => true), true);
    } finally { await active.dispose(); }
  }
} };
export const c6: Scenario = { id: 'C6', title: 'Cancelling and killing a pending sign-in', scope: 'signal cancellation, dead-owner recovery and orphaned login child', covers: ['DRV-1.24', 'DRV-1.25', 'DRV-0.8'], async run(home) {
  const root = await state(home); await home.part('waiting'); home.env.ARBOL_TEST_TIME_SCALE = '10';
  const id = text('Vendor family', (await families(home)).find(f => f.auth === 'vendor_login')?.id);
  for (const signal of ['SIGTERM', 'SIGKILL'] as const) {
    const pending = home.start(['subscriptions', 'sign-in', id]);
    try {
      await pending.step('open_url');
      const progress = JSON.parse(await readFile(join(root, 'subscriptions', id, 'sign-in.json'), 'utf8'));
      pending.stop(signal); const result = await pending.done;
      if (signal === 'SIGTERM') { equal('Cancelled exit', result.status, 2); check('Failed final step', pending.lines.some(value => object('Step', value).step === 'failed'), 'failed step', pending.lines); }
      equal('Dead sign-in is signed out', (await subscription(home, id)).state, 'signed_out');
      await home.json(['subscriptions', 'update', id, '--label', 'After cancellation']);
      equal('Progress removed', await stat(join(root, 'subscriptions', id, 'sign-in.json')).then(() => false).catch(() => true), true);
      const alive = await exec('/bin/ps', ['-p', String(progress.tool.pid), '-o', 'stat=']).then(r => !r.stdout.trim().startsWith('Z')).catch(() => false);
      equal('Login child is gone', alive, false);
    } finally { await pending.dispose(); }
  }
} };
export async function checkSubscriptionCredentials(home: ScenarioHome, includeRuns = false): Promise<void> {
  const root = await state(home); await home.part('success'); home.env.ARBOL_TEST_TIME_SCALE = '10';
  const allFamilies = await families(home);
  const gateway = allFamilies.some(f => f.id === 'zai') ? await gatewayFixture(home) : undefined; const outputs: string[] = [];
  const codex = (await home.json(['info'])).result.driver === 'codex';
  try {
    for (const family of allFamilies) {
      const id = text('Family identifier', family.id);
      const signed = await signIn(home, id); outputs.push(signed.result.stdout, signed.result.stderr);
      for (const command of ['check', 'usage', 'models']) { const result = await home.call(['subscriptions', command, id]); equal('Subscription operation exit', result.status, 0); outputs.push(result.stdout, result.stderr); }
    }
    if (includeRuns && codex) {
      await mkdir(join(home.home, '.codex'), { mode: 0o700 });
      await writeFile(join(home.home, '.codex/config.toml'), '[mcp_servers.fixture]\ncommand = "fixture-server"\n[mcp_servers.fixture.env]\nFIXTURE_TOKEN = "' + key + '"\n', { mode: 0o600 });
    }
    if (includeRuns) for (const part of ['plain', 'failed', 'stderr']) {
      await home.part(part); if (gateway) await home.settings(gateway.settings);
      const id = text('Run family', allFamilies.find(f => f.auth === 'key')?.id ?? allFamilies[0]?.id);
      const extra = codex ? ['--tools', 'all', '--cwd', home.home] : [];
      const result = await home.call(['run', '--subscription', id, ...extra, 'answer']);
      const events = stream(result, part === 'plain' ? 'completed' : 'failed'); outputs.push(result.stdout, result.stderr);
      if (codex) {
        equal('Answer private literal scrubbed', events.find(event => event.type === 'text')!.text, 'answer [redacted]');
        equal('Reasoning private literal scrubbed', events.find(event => event.type === 'thinking')!.text, 'thinking [redacted]');
        equal('Split answer deltas scrubbed', events.filter(event => event.type === 'text_delta').map(event => event.text).join(''), 'answer [redacted]');
        equal('Split reasoning deltas scrubbed', events.filter(event => event.type === 'thinking_delta').map(event => event.text).join(''), 'thinking [redacted]');
        equal('Split tool deltas scrubbed', events.filter(event => event.type === 'tool_output_delta').map(event => event.text).join(''), 'output [redacted]');
        equal('Shell private literal scrubbed', events.find(event => event.type === 'tool_started' && event.name === 'shell')!.input.command, 'echo [redacted]');
        equal('Shell output private literal scrubbed', events.find(event => event.type === 'tool_finished' && event.callId === 'fixture-call')!.result.output, 'output [redacted]');
        equal('Structured tool argument private literal scrubbed', events.find(event => event.type === 'tool_started' && event.name === 'mcpToolCall')!.input.arguments.private, '[redacted]');
        equal('Structured tool result private literal scrubbed', events.find(event => event.type === 'tool_finished' && event.callId === 'credential-mcp')!.result.structuredContent.private, '[redacted]');
        equal('Notice private literal scrubbed', events.find(event => event.type === 'notice')!.message, 'Private diagnostic [redacted]');
        equal('Credential fixture actually emitted', (await home.received()).filter(record => record.stage === 'credential-output' && record.part === part).length, 1);
      }
      if (part === 'plain') {
        const text = await home.call(['run', '--subscription', id, ...extra, '--output', 'text', 'answer']);
        equal('Text run completes', text.status, 0); outputs.push(text.stdout, text.stderr);
      }
    }
    for (const path of await files(root)) {
      const content = await readFile(path, 'utf8'); check('No gateway key in state', !content.includes(key), 'no key value', path);
      if (!path.includes('/home/')) check('No copied vendor credential', !content.includes('fixture-vendor-secret'), 'credential only in vendor home', path);
    }
    outputs.push(await readFile(join(home.tool, 'received.jsonl'), 'utf8'));
    for (const output of outputs) check('No credential in outputs or arguments', !output.includes(key) && !output.includes('fixture-vendor-secret'), 'no credential values', 'output checked');
  } finally { await gateway?.dispose(); }
}
export const c7: Scenario = { id: 'C7', title: 'Credentials stay out of Driver data and output', scope: 'subscription operations, streamed text/thinking, tools, errors, stderr, text output and tool-owned login', covers: ['DRV-0.3', 'DRV-1.3', 'DRV-1.8'], run: home => checkSubscriptionCredentials(home, true) };
export async function checkSubscriptionEnvironments(home: ScenarioHome, includeRun = false): Promise<void> {
  await home.part('success'); home.env.ARBOL_TEST_TIME_SCALE = '10';
  Object.assign(home.env, { ANTHROPIC_API_KEY: key, CLAUDECODE: '1', CLAUDE_SESSION_ID: key, OPENAI_API_KEY: key, OPENAI_BASE_URL: 'http://127.0.0.1:9', CODEX_HOME: '/wrong-home', CODEX_API_KEY: key });
  const id = text('Vendor family', (await families(home)).find(f => f.auth === 'vendor_login')?.id);
  await signIn(home, id);
  for (const command of ['check', 'usage', 'models']) equal('Subscription operation exit', (await home.call(['subscriptions', command, id])).status, 0);
  if (includeRun) stream(await home.call(['run', '--subscription', id, 'answer']));
  for (const received of (await home.received()).filter(record => record.stage !== 'input')) { equal('No inherited selectors', received.checks.injectedVariablesAbsent, true); if (received.arguments[0] !== '--version' && !received.arguments.includes('--input-format')) equal('Both homes private', received.checks.privateHome, true); }
}
export const c8: Scenario = { id: 'C8', title: 'Clean environments for every tool child', scope: 'sign-in, status, catalog and inference children', covers: ['DRV-0.5'], run: home => checkSubscriptionEnvironments(home, true) };
export const c39: Scenario = { id: 'C39', title: 'Two accounts of one family stay independent', scope: 'independent login, homes and sign-out; conversation separation covered by C14', covers: ['DRV-1.2 (subscriptions)'], async run(home) {
  await home.part('success'); home.env.ARBOL_TEST_TIME_SCALE = '10';
  const family = text('Vendor family', (await families(home)).find(f => f.auth === 'vendor_login')?.id);
  const created = await home.json(['subscriptions', 'create', '--family', family, '--label', 'Second', '--id', 'second']); equal('Creation exit', created.process.status, 0);
  await signIn(home, family); await signIn(home, 'second');
  const homes = new Set((await home.received()).filter(r => r.arguments[0] !== '--version').map(r => r.checks.home)); equal('Distinct vendor homes', homes.size, 2);
  await home.call(['subscriptions', 'sign-out', family]); equal('First is out', (await subscription(home, family)).state, 'signed_out');
  equal('Second still works', (await home.json(['subscriptions', 'check', 'second'])).result.state, 'signed_in');
} };
async function checkChatgptUsage(home: ScenarioHome): Promise<void> {
  await home.part('success'); home.env.ARBOL_TEST_TIME_SCALE = '10';
  const id = 'chatgpt';
  equal('Unsigned usage', (await home.json(['subscriptions', 'usage', id])).result.outcome, 'needs_sign_in');
  await signIn(home, id);
  const account = object('Vendor account', (await subscription(home, id)).account);
  equal('Vendor email', account.email, 'fixture@example.invalid'); equal('Vendor plan', account.plan, 'fixture');
  const before = (await home.received()).length; await home.call(['subscriptions', 'list']);
  equal('List does not poll', (await home.received()).length, before);
  const catalog = await home.json(['subscriptions', 'models', id]); equal('Catalog exit', catalog.process.status, 0); equal('Catalog source', catalog.result.source, 'tool');
  const catalogActivity = (await home.received()).slice(before).filter(value => value.stage === 'request' && value.checks.operation !== 'setup');
  equal('Only catalog pages requested', catalogActivity.map(value => value.checks.operation), ['models', 'models']);
  const models = (catalog.result.models as unknown[]).map(value => object('Model', value));
  equal('Every model page read', models.map(value => value.id), ['gpt-6.1-sol', 'gpt-6-astra']);
  equal('Vendor model label', models[0]?.label, 'GPT-6.1-Sol');
  equal('Vendor effort words', models[0]?.efforts, ['low', 'medium', 'high', 'xhigh', 'max', 'ultra']);
  equal('Default effort', models[0]?.defaultEffort, 'low'); equal('Service tiers', models[0]?.serviceTiers, ['priority']); equal('Default model', models[0]?.isDefault, true);
  const beforeUsage = (await home.received()).length;
  const usage = await home.json(['subscriptions', 'usage', id]); equal('Usage exit', usage.process.status, 0); equal('Usage outcome', usage.result.outcome, 'ok'); equal('Usage plan', usage.result.plan, 'fixture');
  equal('Only requested usage', (await home.received()).slice(beforeUsage).filter(value => value.stage === 'request' && value.checks.operation !== 'setup').map(value => value.checks.operation), ['usage']);
  const windows = (usage.result.windows as unknown[]).map(value => object('Window', value));
  equal('Window kind follows duration', windows.map(value => value.kind), ['weekly', 'session']);
  equal('Window labels', windows.map(value => value.label), ['Weekly window', '5-hour window']);
  equal('Used percentage', windows[0]?.usedPercent, 25); equal('Weekly length', windows[0]?.windowMinutes, 10080);
  equal('Vendor reset in UTC', windows[0]?.resetsAt, new Date(1791640848 * 1000).toISOString());
  equal('Unknown reset absent', windows[1]?.resetsAt, undefined); equal('Exhausted window', windows[1]?.limitReached, true);
  equal('Vendor details URL', usage.result.detailsUrl, 'https://chatgpt.com/codex/settings/usage');
  equal('Good usage cached', (await subscription(home, id)).lastUsage, usage.result);
  await home.part('unavailable'); const unavailable = await home.json(['subscriptions', 'usage', id]); equal('Unavailable usage', unavailable.result.outcome, 'unavailable');
  equal('Unavailable windows empty', unavailable.result.windows, []); text('Unavailable reason', unavailable.result.message);
  equal('Last good report preserved', (await subscription(home, id)).lastUsage, usage.result);
  const fallback = await home.json(['subscriptions', 'models', id]); equal('Fallback source', fallback.result.source, 'builtin');
  check('Fallback remains in ChatGPT family', Array.isArray(fallback.result.models) && fallback.result.models.length > 0 && fallback.result.models.every(value => text('Model', object('Model entry', value).id).startsWith('gpt-')), 'ChatGPT models', fallback.result.models);
  await home.part('unknown-windows'); const unknown = await home.json(['subscriptions', 'usage', id]); equal('Unknown-window usage', unknown.result.outcome, 'ok');
  const other = (unknown.result.windows as unknown[]).map(value => object('Window', value));
  equal('Unknown length is absent', other[0]?.windowMinutes, undefined); equal('Unknown length kind', other[0]?.kind, 'other');
  equal('Unknown reset is absent', other[0]?.resetsAt, undefined); equal('Other duration kind', other[1]?.kind, 'other'); equal('Other duration', other[1]?.windowMinutes, 1440);
  await home.part('rejected'); equal('Rejected usage', (await home.json(['subscriptions', 'usage', id])).result.outcome, 'needs_sign_in');
  const rejected = await subscription(home, id); equal('Rejected login needs attention', rejected.state, 'needs_attention'); equal('Rejected credential code', object('Problem', rejected.problem).code, 'credential_rejected');
  await home.part('success'); equal('Recovery check', (await home.json(['subscriptions', 'check', id])).result.state, 'signed_in');
  const out = await home.json(['subscriptions', 'sign-out', id]); equal('Sign-out exit', out.process.status, 0); equal('Account gone', out.result.account, undefined); equal('Cached usage gone', out.result.lastUsage, undefined);
}
export const c41: Scenario = { id: 'C41', title: 'Usage, model catalogs and vendor account details', scope: 'available usage outcomes, cached reports, unknown fields, family fallback and account clearing; run-derived usage covered by C30', covers: ['DRV-1.16', 'DRV-1.17', 'DRV-1.18', 'DRV-1.19', 'DRV-1.20', 'DRV-1.21', 'DRV-1.22'], async run(home) {
  if ((await families(home)).some(value => value.id === 'chatgpt')) return checkChatgptUsage(home);
  await home.part('success'); home.env.ARBOL_TEST_TIME_SCALE = '10'; const gateway = await gatewayFixture(home);
  try {
    equal('Unsigned usage', (await home.json(['subscriptions', 'usage', 'zai'])).result.outcome, 'needs_sign_in');
    await signIn(home, 'zai'); gateway.paths.length = 0;
    await home.call(['subscriptions', 'list']); equal('List does not poll', gateway.paths, []);
    const catalog = await home.json(['subscriptions', 'models', 'zai']); equal('Vendor source', catalog.result.source, 'vendor'); equal('Only models request', gateway.paths, ['/api/paas/v4/models']);
    gateway.paths.length = 0;
    const usage = await home.json(['subscriptions', 'usage', 'zai']); equal('Usage outcome', usage.result.outcome, 'ok'); equal('Only requested usage', gateway.paths, ['/api/monitor/usage/quota/limit']);
    const windows = usage.result.windows as Record<string, unknown>[]; equal('Computed percentage', windows[0]?.usedPercent, 25); equal('Unknown reset absent', windows[1]?.resetsAt, undefined); equal('Unknown length absent', windows[2]?.windowMinutes, undefined);
    equal('Good usage cached', (await subscription(home, 'zai')).lastUsage, usage.result);
    gateway.mode('unavailable'); const unavailable = await home.json(['subscriptions', 'usage', 'zai']); equal('Unavailable usage', unavailable.result.outcome, 'unavailable'); check('Error redacted', !unavailable.process.stdout.includes(key), 'no key', 'output checked');
    equal('Last good report preserved', (await subscription(home, 'zai')).lastUsage, usage.result);
    const fallback = await home.json(['subscriptions', 'models', 'zai']); equal('Fallback source', fallback.result.source, 'builtin'); equal('Own family only', fallback.result.models, [{ id: 'fixture-fallback', label: 'fixture-fallback' }]);
    await signIn(home, 'anthropic'); const account = object('Vendor account', (await subscription(home, 'anthropic')).account); equal('Vendor plan', account.plan, 'fixture');
    equal('Anthropic usage unsupported before run', (await home.json(['subscriptions', 'usage', 'anthropic'])).result.outcome, 'unsupported');
    equal('Tool catalog source', (await home.json(['subscriptions', 'models', 'anthropic'])).result.source, 'tool');
    await home.part('unavailable'); await home.settings(gateway.settings);
    const toolFallback = await home.json(['subscriptions', 'models', 'anthropic']); equal('Tool fallback marked builtin', toolFallback.result.source, 'builtin');
    check('Tool fallback is its own family', Array.isArray(toolFallback.result.models) && toolFallback.result.models.every(value => !text('Model', object('Model entry', value).id).startsWith('fixture-')), 'Anthropic names', toolFallback.result.models);
    await home.part('success'); await home.settings(gateway.settings);
    const out = await home.json(['subscriptions', 'sign-out', 'anthropic']); equal('Account gone', out.result.account, undefined); equal('Cached usage gone', out.result.lastUsage, undefined);
    gateway.mode('rejected'); equal('Rejected usage', (await home.json(['subscriptions', 'usage', 'zai'])).result.outcome, 'needs_sign_in'); equal('Rejected key needs attention', (await subscription(home, 'zai')).state, 'needs_attention');
  } finally { await gateway.dispose(); }
} };
