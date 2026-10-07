import { lstat, mkdir, readFile, readdir, readlink, stat, writeFile } from 'node:fs/promises';
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
const isCodex = async (home: ScenarioHome): Promise<boolean> => (await home.json(['info'])).result.driver === 'codex';
async function codexPermissions(home: ScenarioHome): Promise<void> {
  const id = await signed(home); const records = stream(await home.call(runArgs(home, id)));
  equal('Unexpected request notices', records.filter(event => event.type === 'notice' && event.code === 'unexpected_request').length, 7);
  equal('No caller questions', records.filter(event => event.type === 'ask_opened' || event.type === 'ask_closed').length, 0);
  const responses = (await home.received()).filter(record => record.stage === 'response');
  equal('Every vendor request answered', responses.length, 7);
  for (let index = 0; index < responses.length; index++) {
    const response = object('Codex response', responses[index]!.request);
    equal('Response identifier', response.id, 'fixture-request-' + index);
    if (index < 2) equal('Approval accepted', response.result, { decision: 'accept' });
    else { equal('Unsupported request rejected', object('Request error', response.error).code, -32601); check('Rejection explains why', typeof object('Request error', response.error).message === 'string', 'message', response); }
  }
  await home.part('malformed'); const malformed = stream(await home.call(runArgs(home, id)), 'failed'); equal('Malformed vendor protocol fails its run', malformed.at(-1)!.error.code, 'tool_failed');
  await home.part('no-requests'); stream(await home.call(runArgs(home, id)));
  equal('No responses in next run', (await home.received()).filter(record => record.stage === 'response' && record.part === 'no-requests').length, 0);
}
async function codexCompletedTools(home: ScenarioHome): Promise<void> {
  const id = await signed(home);
  for (const part of ['plain', 'collaboration', 'nested']) {
    await home.part(part); const records = stream(await home.call(runArgs(home, id)));
    const begun = (callId: string) => records.find(event => event.type === 'tool_started' && event.callId === callId)!;
    const ended = (callId: string) => records.find(event => event.type === 'tool_finished' && event.callId === callId)!;
    equal('Refused call reason', ended('refused').error, 'Codex refused this command.'); equal('Refused call failed', ended('refused').ok, false);
    equal('Shell input', begun('refused').input, { command: 'rejected-command', cwd: home.home });
    equal('Main answer', records.filter(event => event.type === 'text' && !event.parentCallId).map(event => event.text), ['main-before', 'main-answer']);
    const parent = part === 'collaboration' ? 'agent-spawn' : 'agent';
    const childEvents = records.filter(event => event.callId === 'subcall' || event.text === 'sub-agent-only' || event.text === 'child-thinking' || event.type === 'usage');
    check('Child event coverage', childEvents.length >= 7, 'tool start/result/delta, text/delta, reasoning/delta and usage', childEvents);
    for (const event of childEvents) equal('Sub-agent parent', event.parentCallId, parent);
    const childNotices = records.filter(event => event.type === 'notice' && (event.code === 'unexpected_request' || event.message === 'Fixture child warning.'));
    equal('Child request and warning both carried', childNotices.length, 2);
    for (const event of childNotices) equal('Child notice parent', event.parentCallId, parent);
    equal('Child elicitation rejected', (await home.received()).filter(record => record.part === part && record.stage === 'response' && object('Response', record.request).id === 'fixture-child-request').length, 1);
    equal('Child tool result', ended('subcall').result, { output: 'child-output', exitCode: 0 });
    if (part === 'nested') {
      equal('Nested spawn parent', begun('nested-agent').parentCallId, 'agent');
      for (const event of records.filter(event => event.callId === 'nested-call' || event.text === 'nested-only')) equal('Nested child parent', event.parentCallId, 'nested-agent');
    }
    for (const event of records.filter(event => event.type === 'tool_started')) equal('Call paired once', records.filter(result => result.type === 'tool_finished' && result.callId === event.callId).length, 1);
    equal('Patch input', begun('patch').input, [{ path: join(home.home, 'fixture-patch.txt'), kind: { type: 'add' }, content: 'fixture patch\n' }]);
    equal('Patch succeeds', ended('patch').ok, true); equal('Web tool name', begun('search').name, 'webSearch');
    equal('Web shape retained', object('Web result', ended('search').result).action, { type: 'search', query: 'fixture query', queries: null });
    equal('MCP tool name', begun('mcp').name, 'mcpToolCall'); equal('MCP arguments retained', object('MCP input', begun('mcp').input).arguments, { value: 'fixture-value' });
    equal('MCP result retained', ended('mcp').result, { content: [{ type: 'text', text: 'fixture-value' }], structuredContent: { value: 'fixture-value' } });
    equal('MCP failure reason', ended('mcp-failed').error, 'Fixture MCP refusal.'); equal('MCP failure', ended('mcp-failed').ok, false);
    equal('Background result', ended('background').result, { output: 'background-output\n', exitCode: 0 });
    check('Final after late child', records.indexOf(ended('subcall')) < records.length - 1, 'child completes before finished', records);
    check('Final after background', records.indexOf(ended('background')) < records.length - 1, 'background completes before finished', records);
    const received = (await home.received()).filter(record => record.part === part);
    const mainEnd = received.find(record => record.stage === 'main-ended')!;
    equal('Main ends with child active', mainEnd.checks.childWasActive, true); equal('Main ends with command active', mainEnd.checks.backgroundWasAlive, true);
    equal('Child completed', received.filter(record => record.stage === 'child-ended').length, 1); equal('Background completed', received.filter(record => record.stage === 'background-ended').length, 1);
    const thread = object('Thread params', object('Thread request', received.find(record => record.stage === 'request' && object('Request', record.request).method === 'thread/start')!.request).params);
    equal('Trusted sandbox', thread.sandbox, 'danger-full-access'); equal('No approval', thread.approvalPolicy, 'never');
    equal('Single app-server argument', received.find(record => record.stage === 'input')!.arguments, ['app-server']);
    const turn = object('Turn params', object('Turn request', received.find(record => record.stage === 'input')!.request).params);
    equal('Turn trusted sandbox', turn.sandboxPolicy, { type: 'dangerFullAccess' }); equal('Turn no approval', turn.approvalPolicy, 'never');
    const config = await readFile(join(String(mainEnd.checks.home), 'config.toml'), 'utf8');
    equal('Only memory feature disabled', config.match(/\[features\]\s*([^[]*)/)![1]!.trim(), 'memories = false'); check('Live web search', config.includes('web_search = "live"'), 'live web', config);
  }
  await home.part('plain'); const text = await home.call([...runArgs(home, id), '--output', 'text']); equal('Text output completed', text.status, 0); equal('Child text excluded', text.stdout, 'main-beforemain-answer');
  await home.part('early-exit'); const failed = stream(await home.call(runArgs(home, id)), 'failed'); equal('Premature exit refused', failed.at(-1)!.error.code, 'tool_failed');
  await home.part('unexpected-tool'); const without = stream(await home.call(['run', '--subscription', id, 'answer']));
  equal('Unexpected tool in no-tool run reported', without.filter(event => event.type === 'tool_started' && event.name === 'shell').length, 1);
  equal('Unexpected tool leaves run completed', without.at(-1)!.outcome, 'completed');
}
export const c25: Scenario = { id: 'C25', title: 'Unexpected permission requests', scope: 'automatic allow, malformed deny, missing identifier fails only its own run', covers: ['DRV-3.22', 'DRV-0.7'], async run(home) {
  if (await isCodex(home)) return codexPermissions(home);
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
    if (await isCodex(home)) return codexCompletedTools(home);
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
    if (info.result.driver === 'codex') {
      const records = stream(await home.call(runArgs(home, id)));
      equal('Codex carries no questions', records.filter(event => event.type === 'ask_opened' || event.type === 'ask_closed').length, 0);
      equal('Every unsupported question gives notice', records.filter(event => event.type === 'notice' && event.code === 'unexpected_request').length, 2);
      const responses = (await home.received()).filter(record => record.stage === 'response');
      equal('Both questions settled', responses.length, 2);
      for (const response of responses) {
        const error = object('Unsupported question error', object('Question response', response.request).error);
        equal('Codex question refusal', error.code, -32601);
        check('Question refusal explains why', typeof error.message === 'string' && /not supported|unsupported/i.test(error.message), 'unsupported question message', error);
      }
      return;
    }
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
  if (await isCodex(home)) return codexOwnerScenario(home, configured);
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
async function ownerTree(root: string): Promise<unknown[]> {
  const result: unknown[] = [];
  async function visit(folder: string): Promise<void> {
    for (const name of (await readdir(folder)).sort()) {
      const path = join(folder, name); const metadata = await lstat(path);
      result.push({ path, modified: metadata.mtimeMs, mode: metadata.mode,
        content: metadata.isSymbolicLink() ? await readlink(path) : metadata.isFile() ? (await readFile(path)).toString('base64') : null });
      if (metadata.isDirectory()) await visit(path);
    }
  }
  await visit(root); return result;
}
async function codexOwnerScenario(home: ScenarioHome, configured: boolean): Promise<void> {
  const id = await signed(home);
  const secret = 'fixture-owner-mcp-private-credential-12345'; const header = 'fixture-owner-mcp-private-header-67890';
  const ownerConfig = '[mcp_servers.fixture]\ncommand = "fixture-server"\nargs = ["sentinel"]\nenabled = true\nstartup_timeout_sec = 12\n[mcp_servers.fixture.env]\nFIXTURE_TOKEN = "' + secret + '"\n[mcp_servers.remote]\nurl = "https://example.invalid/mcp"\n[mcp_servers.remote.http_headers]\nAuthorization = "' + header + '"\n';
  const paths = ['.codex/skills/sentinel', '.codex/plugins/sentinel', '.codex/hooks/sentinel', '.agents/skills/fixture-skill'];
  for (const path of paths) await mkdir(join(home.home, path), { recursive: true });
  const files: Record<string, string> = {
    '.codex/config.toml': 'model = "ownerModelSentinel"\ndeveloper_instructions = "ownerInstructionsSentinel"\n[features]\nmemories = true\nshell_tool = false\n' + ownerConfig,
    '.codex/auth.json': '{"ownerCredentialSentinel":true}', '.codex/AGENTS.md': 'Owner instructions sentinel',
    '.codex/skills/sentinel/SKILL.md': 'Owner .codex skill is outside this driver scope',
    '.codex/plugins/sentinel/owner.txt': 'Owner plugin sentinel', '.codex/hooks/sentinel/owner.txt': 'Owner hook sentinel',
    '.agents/skills/fixture-skill/SKILL.md': '---\nname: fixture-skill\ndescription: A sentinel skill\n---\nSkill sentinel\n',
  };
  for (const [file, value] of Object.entries(files)) await writeFile(join(home.home, file), value, { mode: 0o600 });
  const before = [await ownerTree(join(home.home, '.codex')), await ownerTree(join(home.home, '.agents'))];
  const reply = await home.call(runArgs(home, id)); stream(reply);
  const seen = (await home.received()).filter(record => record.stage === 'input').at(-1)!;
  equal('Owner MCP tables reach tool intact', seen.checks.ownerMcpCorrect, true); equal('MCP config supplied', seen.checks.ownerMcpOmitted, false);
  equal('Owner skill reaches tool naturally', seen.checks.ownerSkillCorrect, true); equal('Owner skill path', seen.checks.ownerSkillPath, join(home.home, '.agents/skills/fixture-skill/SKILL.md'));
  equal('Only memory feature switched off', seen.checks.onlyMemoryFeature, true); equal('Live web search', seen.checks.liveWebSearch, true); equal('Owner settings excluded', seen.checks.ownerSettingsAbsent, true);
  const privateHome = String(seen.checks.home);
  for (const name of ['AGENTS.md', 'plugins', 'hooks', 'skills']) equal('Owner ' + name + ' not copied', (await readdir(privateHome)).includes(name), false);
  const privateConfig = await readFile(join(privateHome, 'config.toml'), 'utf8');
  for (const marker of [secret, header, 'ownerModelSentinel', 'ownerInstructionsSentinel', 'ownerCredentialSentinel']) {
    equal('Owner marker absent in output', (reply.stdout + reply.stderr).includes(marker), false);
    equal('Owner marker absent in private config', privateConfig.includes(marker), false);
    equal('Owner marker absent in fixture ledger', (await readFile(join(home.tool, 'received.jsonl'), 'utf8')).includes(marker), false);
    for (const folder of [privateHome, join(home.home, '.arbol')]) {
      for (const entry of await ownerTree(folder)) {
        const content = object('Private file snapshot', entry).content;
        equal('Owner marker absent in saved files', typeof content === 'string' && Buffer.from(content, 'base64').toString('utf8').includes(marker), false);
      }
    }
  }
  equal('Owner trees unchanged', [await ownerTree(join(home.home, '.codex')), await ownerTree(join(home.home, '.agents'))], before);
  if (configured) {
    const without = stream(await home.call(['run', '--subscription', id, 'answer'])); equal('No-tool run completes', without.at(-1)!.outcome, 'completed');
    const noTools = (await home.received()).filter(record => record.stage === 'input').at(-1)!;
    equal('No-tool MCP config omitted', noTools.checks.ownerMcpOmitted, true); equal('No-tool MCP verified', noTools.checks.ownerMcpCorrect, true);
    equal('Owner trees unchanged after no-tool run', [await ownerTree(join(home.home, '.codex')), await ownerTree(join(home.home, '.agents'))], before);
  }
}
export const c9: Scenario = { id: 'C9', title: 'Owner setup stays unchanged', scope: 'sentinel settings, instructions, skills and MCP list; only skills and MCP paths supplied to the tool', covers: ['DRV-0.4'], run: home => ownerScenario(home, false) };
export const c37: Scenario = { id: 'C37', title: 'Owner skills and MCP servers', scope: 'owner skill link, MCP configuration argument and private home, including no-tool MCP omission', covers: ['DRV-3.31', 'DRV-0.4'], run: home => ownerScenario(home, true) };
