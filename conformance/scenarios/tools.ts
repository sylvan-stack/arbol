import { mkdir, readFile, readdir, readlink, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { check, equal, object } from '../check.js';
import { signed, stream } from './runs.js';
import type { Scenario } from './types.js';
import type { ScenarioHome } from '../harness.js';

async function wait(label: string, condition: () => boolean, timeout = 5000): Promise<void> {
  const deadline = performance.now() + timeout;
  while (!condition()) { check(label, performance.now() < deadline, 'arrives before deadline', false); await new Promise(resolve => setTimeout(resolve, 10)); }
}
const runArgs = (home: ScenarioHome, id: string): string[] => ['run', '--subscription', id, '--tools', 'all', '--cwd', home.home, 'answer'];
export const c25: Scenario = { id: 'C25', title: 'Unexpected permission requests', scope: 'automatic allow, malformed deny, missing identifier fails only its own run', covers: ['DRV-3.22', 'DRV-0.7'], async run(home) {
  const id = await signed(home);
  const records = stream(await home.call(runArgs(home, id)));
  equal('Permission notices', records.filter(event => event.type === 'notice' && event.code === 'permission_answered').length, 2);
  equal('No ask', records.filter(event => event.type === 'ask_opened').length, 0);
  const responses = (await home.received()).filter(record => record.stage === 'response');
  const answer = (n: number) => object('Response', object('Envelope', responses[n]!.checks.input).response);
  equal('Permission allowed', object('Allow', answer(0).response), { behavior: 'allow', updatedInput: { file_path: 'fixture', content: 'value' } });
  equal('Permission declined', object('Deny', answer(1).response).behavior, 'deny'); check('Deny has reason', typeof object('Deny', answer(1).response).message === 'string', 'message', answer(1));
  await home.part('missing-id'); const failed = stream(await home.call(runArgs(home, id)), 'failed'); equal('Malformed protocol fails', failed.at(-1)!.error.code, 'tool_unsupported');
  await home.part('plain'); stream(await home.call(runArgs(home, id)));
} };
export const c35: Scenario = { id: 'C35', title: 'Tools and completed background work', scope: 'all tools, refusal reason, shell shape, sub-agent attribution, three result parts and text output; idle-limit integration covered by C29',
  covers: ['DRV-3.19', 'DRV-3.20', 'DRV-3.21', 'DRV-3.23', 'DRV-3.24', 'DRV-3.25', 'DRV-3.32'], async run(home) {
    const id = await signed(home); const records = stream(await home.call(runArgs(home, id)));
    equal('Refused call reason', records.find(event => event.type === 'tool_finished' && event.callId === 'refused')!.error, 'Claude refused this command.');
    equal('Refused call failed', records.find(event => event.type === 'tool_finished' && event.callId === 'refused')!.ok, false);
    equal('Shell input', records.find(event => event.type === 'tool_started' && event.callId === 'refused')!.input, { command: 'rejected-command', cwd: home.home });
    equal('Main answer', records.filter(event => event.type === 'text' && !event.parentCallId).map(event => event.text), ['main-before', 'main-after-agent', 'main-after-command']);
    for (const event of records.filter(event => event.callId === 'subcall' || event.text === 'sub-agent-only')) equal('Sub-agent parent', event.parentCallId, 'agent');
    for (const event of records.filter(event => event.type === 'tool_started')) equal('Call paired', records.filter(result => result.type === 'tool_finished' && result.callId === event.callId).length, 1);
    const input = (await home.received()).find(record => record.stage === 'input')!;
    for (const option of ['--tools', '--allowedTools', '--disallowedTools', '--setting-sources', '--strict-mcp-config']) equal('No restrictive ' + option, input.arguments.includes(option), false);
    equal('Trusted mode', input.arguments[input.arguments.indexOf('--permission-mode') + 1], 'bypassPermissions'); equal('Memory disabled', input.checks.memoryOff, true);
    equal('Background completed', (await home.received()).filter(record => record.stage === 'background-ended').length, 1);
    const text = await home.call([...runArgs(home, id), '--output', 'text']); equal('Text output completed', text.status, 0); equal('Sub-agent excluded', text.stdout, 'main-beforemain-after-agentmain-after-command');
    await home.part('early-exit'); const failed = stream(await home.call(runArgs(home, id)), 'failed'); equal('Premature exit refused', failed.at(-1)!.error.code, 'tool_failed');
} };
export const c36: Scenario = { id: 'C36', title: 'Questions and their answers', scope: 'concurrent questions, reversed answers, multiple labels, duplicate, invalid and withdrawn answers, decline and cancellation',
  covers: ['DRV-3.26', 'DRV-3.27', 'DRV-3.28', 'DRV-3.29'], async run(home) {
    const id = await signed(home); const info = await home.json(['info']);
    if (info.result.driver === 'codex') { const records = stream(await home.call(runArgs(home, id))); equal('Codex carries no questions', records.filter(event => event.type === 'ask_opened').length, 0); return; }
    const active = home.start([...runArgs(home, id), '--control']);
    try {
      await wait('Three questions open', () => active.lines.filter((event: any) => event.type === 'ask_opened').length === 3);
      await new Promise(resolve => setTimeout(resolve, 150)); equal('No question timeout', active.lines.filter((event: any) => event.type === 'finished').length, 0);
      const answers = (askId: string, choices: unknown) => active.send({ type: 'answer', askId, answer: { type: 'answers', answers: choices } });
      for (const invalid of [{}, { 'Choose first': ['Green'] }, { 'Choose first': ['Blue', 'Red'] }, { 'Choose first': [] }, { 'Choose first': ['Blue'], extra: ['Red'] }]) answers('first', invalid);
      answers('withdrawn', { 'Choose withdrawn': ['Blue'] }); answers('unknown', {});
      answers('second', { 'Choose second': ['Blue', 'Blue'] });
      await wait('All invalid answers refused', () => active.lines.filter((event: any) => event.type === 'control_refused').length === 8);
      answers('second', { 'Choose second': ['Red', 'Blue'] });
      await wait('Second answered', () => active.lines.some((event: any) => event.type === 'ask_closed' && event.askId === 'second'));
      active.send({ type: 'answer', askId: 'second', answer: {} }); answers('first', { 'Choose first': ['Blue'] });
      const records = stream(await active.done);
      equal('Refusal codes', records.filter(event => event.type === 'control_refused').map(event => event.error.code), ['invalid_input', 'invalid_input', 'invalid_input', 'invalid_input', 'invalid_input', 'not_found', 'not_found', 'invalid_input']);
      equal('Answered order', records.filter(event => event.type === 'ask_closed' && event.reason === 'answered').map(event => event.askId), ['second', 'first']);
      for (const ask of records.filter(event => event.type === 'ask_opened')) {
        check('Call starts before ask', records.findIndex(event => event.type === 'tool_started' && event.callId === ask.ask.callId) < records.indexOf(ask), 'tool_started before ask_opened', records);
        equal('Ask closes once', records.filter(event => event.type === 'ask_closed' && event.askId === ask.askId).length, 1);
      }
      const responses = (await home.received()).filter(record => record.stage === 'response'); equal('Exactly two delivered answers', responses.length, 2);
      equal('Multiple choices mapped', (responses[0]!.checks.input as any).response.response.updatedInput.answers, { 'Choose second': 'Red, Blue' });
    } finally { await active.dispose(); }
    await home.part('decline'); const declined = home.start([...runArgs(home, id), '--control']);
    try {
      await wait('Decline question opens', () => declined.lines.some((event: any) => event.type === 'ask_opened'));
      declined.send({ type: 'answer', askId: 'decline', answer: { type: 'decline' } }); const records = stream(await declined.done, 'cancelled');
      equal('Decline closes question', records.find(event => event.type === 'ask_closed')!.reason, 'answered');
      const response = (await home.received()).filter(record => record.stage === 'response').at(-1)!;
      equal('Decline interrupts', (response.checks.input as any).response.response.interrupt, true);
    } finally { await declined.dispose(); }
} };
async function ownerScenario(home: ScenarioHome, configured: boolean): Promise<void> {
  const id = await signed(home);
  await mkdir(join(home.home, '.claude/skills/fixture-skill'), { recursive: true });
  await mkdir(join(home.home, '.claude/skills/synced/test-account'), { recursive: true });
  const files = ['.claude/CLAUDE.md', '.claude/settings.json', '.claude/skills/fixture-skill/SKILL.md', '.claude.json', '.claude/skills/synced/test-account/sentinel'];
  const values = ['owner instructions sentinel', '{"ownerSettingsSentinel":true}', '---\nname: fixture-skill\ndescription: A sentinel skill\n---\nSkill sentinel\n', JSON.stringify({ mcpServers: { fixture: { command: 'fixture-server', args: ['sentinel'] } }, ownerStateSentinel: true }), 'owner account skill'];
  for (let i = 0; i < files.length; i++) await writeFile(join(home.home, files[i]!), values[i]!);
  const before = await Promise.all(files.map(async file => ({ file, content: await readFile(join(home.home, file), 'utf8'), modified: (await stat(join(home.home, file))).mtimeMs })));
  stream(await home.call(runArgs(home, id)));
  const seen = (await home.received()).find(record => record.stage === 'input')!;
  equal('Owner skill path', seen.checks.skills, join(home.home, '.claude/skills/fixture-skill')); equal('Skill reaches tool', seen.checks.skill, values[2]);
  equal('MCP servers reach tool', seen.checks.mcp, { fixture: { command: 'fixture-server', args: ['sentinel'] } });
  const configHome = String(seen.checks.configHome); equal('Skill symlink', await readlink(join(configHome, 'skills/fixture-skill')), join(home.home, '.claude/skills/fixture-skill'));
  equal('Account sync stays private', await readFile(join(configHome, 'skills/synced/test-account/sentinel'), 'utf8'), 'private account skill');
  for (const file of ['settings.json', 'CLAUDE.md', 'plugins', 'hooks']) equal('Owner ' + file + ' absent in private home', (await readdir(configHome)).includes(file), false);
  equal('Owner files unchanged', await Promise.all(files.map(async file => ({ file, content: await readFile(join(home.home, file), 'utf8'), modified: (await stat(join(home.home, file))).mtimeMs }))), before);
  if (configured) {
    const text = stream(await home.call(['run', '--subscription', id, 'answer'])); equal('No-tool run completes', text.at(-1)!.outcome, 'completed');
    const noTools = (await home.received()).filter(record => record.stage === 'input').at(-1)!; equal('No-tool MCP argument omitted', noTools.arguments.includes('--mcp-config'), false);
  }
}
export const c9: Scenario = { id: 'C9', title: 'Owner setup stays unchanged', scope: 'sentinel settings, instructions, skills and MCP list; only skills and MCP paths supplied to the tool', covers: ['DRV-0.4'], run: home => ownerScenario(home, false) };
export const c37: Scenario = { id: 'C37', title: 'Owner skills and MCP servers', scope: 'owner skill link, MCP configuration argument and private home, including no-tool MCP omission', covers: ['DRV-3.31', 'DRV-0.4'], run: home => ownerScenario(home, true) };
