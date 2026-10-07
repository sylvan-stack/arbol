import { join } from 'node:path';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { check, equal, object, text } from '../check.js';
import { inspectInfo, versionOrder, versionRecords } from './info.js';
import type { Scenario } from './types.js';
import type { ScenarioHome } from '../harness.js';
import { signed, stream } from './runs.js';

export const c32: Scenario = {
  id: 'C32', title: 'Command line, identity and development checks', scope: 'all commands and options, JSON/file/stdin requests, text output, unknown input, exit codes, secret-input refusal and build/probe commands; Keychain steps also checked by C2/C3',
  covers: ['DRV-0.1', 'DRV-0.11', 'DRV-0.12', 'DRV-0.13', 'DRV-0.14', 'DRV-0.15', 'DRV-1.23', 'DRV-1.26', 'DRV-5.3', 'DRV-5.4', 'DRV-5.6', 'DRV-5.8', 'DRV-5.10'],
  async run(home) {
    await checkDriverInfo(home);
    const id = await signed(home);
    const info = await home.json(['info']), root = text('State directory', info.result.stateDirectory);
    const codex = info.result.driver === 'codex';
    const catalog = await home.json(['subscriptions', 'models', id]);
    const models = (catalog.result.models as unknown[]).map(value => object('Catalog model', value));
    const model = codex ? text('Model with low effort', models.find(value => Array.isArray(value.efforts) && value.efforts.includes('low'))?.id) : 'sonnet';
    const textModel = codex ? text('Text model', models.at(-1)?.id) : 'haiku';
    const system = join(home.home, 'system'), request = join(home.home, 'request.json'), extra = join(home.home, 'extra');
    await mkdir(extra); await writeFile(system, 'Caller system prompt.');
    await writeFile(request, JSON.stringify({ subscriptionId: id, tools: 'none', history: [], input: { role: 'user', text: 'ready' } }));
    const args = ['run', '--state-dir', root, '--request', request, '--subscription', id, '--model', model, '--effort', 'low',
      '--system-prompt-file', system, '--cwd', home.home, '--add-dir', extra, '--add-dir=' + home.home,
      '--tools', 'all', '--chat-session', 'cli-chat', '--run-id', 'cli-run', '--output', 'events', '--label', 'one=1', '--label=two=2', 'ready'];
    const events = stream(await home.call(args)); equal('Run build matches info', events[0]!.driverBuild, info.result.build);
    equal('Repeated labels', events[0]!.labels, { one: '1', two: '2' });
    const input = (await home.received()).filter(record => record.stage === 'input').at(-1)!;
    if (codex) {
      const thread = (await home.received()).find(record => record.stage === 'request' && object('Thread request', record.request).method === 'thread/start')!;
      const parameters = object('Thread params', object('Thread request', thread.request).params);
      const turn = object('Turn params', object('Turn request', input.request).params);
      equal('Prompt file delivered', parameters.developerInstructions, 'Caller system prompt.');
      equal('Model option delivered to thread', parameters.model, model); equal('Model option delivered to turn', turn.model, model);
      equal('Effort option delivered', turn.effort, 'low');
      equal('Working directory delivered', parameters.cwd, home.home);
      equal('Repeated directories accepted in unrestricted run', parameters.sandbox, 'danger-full-access');
      equal('Run identifier option delivered', events[0]!.runId, 'cli-run');
      equal('Chat session selects durable vendor conversation', parameters.ephemeral === true, false);
      const mapDirectory = join(root, 'subscriptions', id, 'chats');
      const mapped = await Promise.all((await readdir(mapDirectory)).filter(file => file.endsWith('.json')).map(async file => JSON.parse(await readFile(join(mapDirectory, file), 'utf8'))));
      equal('Chat session option is mapped', mapped.map(entry => entry.chatSessionId), ['cli-chat']);
    } else {
      equal('Prompt file delivered', input.arguments[input.arguments.indexOf('--append-system-prompt') + 1], 'Caller system prompt.');
      equal('Model option delivered', input.arguments[input.arguments.indexOf('--model') + 1], 'sonnet');
      equal('Effort option delivered', input.arguments[input.arguments.indexOf('--effort') + 1], 'low');
      equal('Repeated directories delivered', input.arguments.filter(value => value === '--add-dir').length, 2);
    }
    const stdin = home.start(['run', '--request', '-', '--subscription', id]);
    try { stdin.send(JSON.parse(await readFile(request, 'utf8'))); stream(await stdin.done); } finally { await stdin.dispose(); }
    const output = await home.call(['run', '--subscription=' + id, '--model=' + textModel, '--tools=none', '--output=text', 'ready']);
    equal('Text exit', output.status, 0); equal('Plain text result', output.stdout, 'ready');
    const tier = stream(await home.call(['run', '--subscription', id, '--service-tier', 'unsupported-tier', 'ready']), 'failed');
    equal('Unavailable tier is typed', tier.at(-1)!.error.code, 'invalid_input');
    for (const bad of [['unknown'], ['info', '--unknown'], ['info', '--state-dir'], ['run', '--unknown', 'ready'],
      ['subscriptions', 'sign-in', id, '--secret=fixture-secret'], ['subscriptions', 'sign-in', id, '--key-file', request]]) {
      const reply = await home.call(bad); equal('Invalid input exit', reply.status, 1);
      const record = JSON.parse(reply.stdout); equal('Invalid input code', record.error.code, 'invalid_input');
      check('Secret option not echoed', !reply.stdout.includes('fixture-secret'), 'no secret value', reply.stdout);
    }
    // All subscription commands are executed in C1-C6/C41; this confirms their command frame here.
    for (const command of [['subscriptions', 'families'], ['subscriptions', 'list'], ['subscriptions', 'check', id],
      ['subscriptions', 'usage', id], ['subscriptions', 'models', id], ['runs', 'list'], ['runs', 'stop', 'unknown']]) {
      equal('Command accepted: ' + command.join(' '), (await home.call(command)).status, 0);
    }
    const imported = await home.json(['subscriptions', 'import', 'unknown', '--from', request]);
    check('Import frame accepted', ['not_found', 'invalid_input', ...(codex ? ['unsupported'] : [])].includes((imported.result.error as any).code), 'typed import refusal', imported.result);
    for (const command of ['build-check', 'live-check']) {
      const refused = await home.json(['dev', command]); equal('Absent test account refused', refused.process.status, 1);
      equal('Absent test account code', (refused.result.error as any).code, 'not_found');
    }
    await home.json(['subscriptions', 'create', '--family', id, '--label', 'Test', '--id', 'test-' + id]);
    const testId = 'test-' + id;
    equal('Signed-out build check refuses', (await home.json(['dev', 'build-check'])).process.status, 1);
    equal('Test sign-in', (await home.call(['subscriptions', 'sign-in', testId])).status, 0);
    const before = (await home.received()).filter(record => record.stage === 'input').length;
    const build = await home.json(['dev', 'build-check']); equal('Build check passes', build.process.status, 0);
    equal('One real message', build.result.inferenceRequests, 1);
    equal('Exactly one stand-in prompt', (await home.received()).filter(record => record.stage === 'input').length, before + 1);
    const recordFile = join(root, 'subscriptions', testId, 'record.json'), account = JSON.parse(await readFile(recordFile, 'utf8'));
    account.lastUsage = { outcome: 'ok', fetchedAt: new Date().toISOString(), windows: [{ kind: 'weekly', label: 'Weekly', usedPercent: 100 }] };
    await writeFile(recordFile, JSON.stringify(account));
    for (const command of ['build-check', 'live-check']) {
      const refused = await home.json(['dev', command]); equal('Full account refused', (refused.result.error as any).code, 'rate_limited');
    }
    const probe = await home.json(['dev', 'probe']); equal('Probe command passes', probe.process.status, 0); equal('Probe sends no prompt', probe.result.inferenceRequests, 0);
    equal('Probe makes no inference', (await home.received()).filter(record => record.stage === 'input').length, before + 1);
    const active = home.start(['run', '--subscription', id, '--control', 'ready']);
    try { active.send({ type: 'stop' }); stream(await active.done, 'cancelled'); } finally { await active.dispose(); }
  },
};

export async function checkDriverInfo(home: ScenarioHome): Promise<void> {
    await home.part('info');
    let identity: unknown;
    for (const override of [false, true]) {
      const state = override ? join(home.home, 'explicit-state') : undefined;
      const reply = await home.json(override ? ['--state-dir', state!, 'info'] : ['info']);
      equal('info exit status', reply.process.status, 0);
      const { info, tool, name } = inspectInfo(reply.result);
      equal('Contract version', info.contract, 1);
      const version = text('Package version', info.version);
      check('Package version format', /^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$/.test(version), 'a semantic package version', version);
      const build = text('Build number', info.build);
      check('Build number format', /^(?:0|[1-9a-f][0-9a-f]*)$/.test(build), 'a hexadecimal Build number, or 0 for a source checkout', build);
      equal('State directory', info.stateDirectory, state ?? join(home.home, 'Library', 'Application Support', 'Arbol', 'drivers', name));
      equal('Settings filename', info.settingsFile, join(home.home, '.arbol', `arbol-${name}-driver.json`));
      equal('Supported tool path', tool.path, home.toolPath);
      equal('Supported tool version', tool.supported, true);
      const found = text('Reported tool version', tool.version);
      const needed = text('Oldest supported tool version', tool.oldestSupported);
      check('Supported version meets the support boundary', versionOrder(found, needed) >= 0, `a version at least ${needed}`, found);
      const current = { driver: name, version, build, contract: info.contract };
      if (identity === undefined) identity = current;
      else equal('Identity is stable with a state override', current, identity);
      await versionRecords(home, 'info');
      for (const record of await home.received()) equal('Reported version matches the stand-in', tool.version, record.toolVersion);
    }
}
