// A synthetic Driver for testing the runner itself, not a vendor stand-in.
import { readFile, writeFile, appendFile, stat, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { execFileSync, spawn } from 'node:child_process';

const args = process.argv.slice(2);
const mode = args[0]?.startsWith('--fixture=') ? args.shift().slice('--fixture='.length) : 'ok';
const home = process.env.HOME;
if (args[0] === 'dev' && args[1] === 'stand-in') {
  const folder = args[2];
  const [scenario, part] = (await readFile(join(folder, 'scenario'), 'utf8')).trim().split(/\s+/);
  const version = part === 'old' ? '0.159.1' : '0.159.2';
  await appendFile(join(folder, 'received.jsonl'), JSON.stringify({
    scenario, part, arguments: args.slice(4), environment: Object.keys(process.env),
    workingDirectory: process.cwd(), checks: {}, toolVersion: version,
  }) + '\n');
  process.stdout.write(version + '\n');
} else if (mode === 'hang') {
  const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });
  await writeFile(join(home, 'pids.json'), JSON.stringify([process.pid, child.pid]));
  setInterval(() => {}, 1000);
} else if (args[0] === 'subscriptions') {
  // Synthetic local account protocol, deliberately independent of either Driver.
  const file = join(home, 'synthetic-subscriptions.json');
  let subscriptions;
  try { subscriptions = JSON.parse(await readFile(file, 'utf8')); }
  catch (error) {
    if (error.code !== 'ENOENT') throw error;
    subscriptions = [{ id: 'chatgpt', family: 'chatgpt', label: 'ChatGPT', auth: 'vendor_login', state: 'signed_out', settings: {}, createdAt: '2026-10-06T00:00:00Z', updatedAt: '2026-10-06T00:00:00Z' }];
  }
  const option = key => args[args.indexOf(`--${key}`) + 1];
  let result;
  const fail = code => { process.exitCode = 1; return { error: { code, message: code, retryable: false } }; };
  switch (args[1]) {
    case 'families': result = [{ id: 'chatgpt', auth: 'vendor_login', settings: {} }]; break;
    case 'list': result = subscriptions; break;
    case 'create': {
      const id = args.includes('--id') ? option('id') : 'chatgpt-2';
      if (subscriptions.some(item => item.id === id)) { result = fail('in_use'); break; }
      result = { ...subscriptions[0], id, label: option('label') };
      subscriptions.push(result);
      await writeFile(file, JSON.stringify(subscriptions));
      break;
    }
    case 'update': {
      result = subscriptions.find(item => item.id === args[2]);
      if (args.includes('--label')) result.label = option('label');
      await writeFile(file, JSON.stringify(subscriptions));
      break;
    }
    case 'check': case 'models': result = fail('not_signed_in'); break;
    case 'usage': result = { outcome: 'needs_sign_in', windows: [], fetchedAt: new Date().toISOString() }; break;
  }
  process.stdout.write(JSON.stringify(result) + '\n');
} else {
  const settingsFile = join(home, '.arbol', 'arbol-codex-driver.json');
  const { toolPath } = JSON.parse(await readFile(settingsFile, 'utf8'));
  const index = args.indexOf('--state-dir');
  const stateDirectory = index >= 0 ? args.splice(index, 2)[1] : join(home, 'Library', 'Application Support', 'Arbol', 'drivers', 'codex');
  await mkdir(stateDirectory, { recursive: true });
  const tool = { name: 'codex', supported: false, oldestSupported: '0.159.2' };
  try {
    await stat(toolPath);
    tool.path = toolPath;
    tool.version = execFileSync(toolPath, ['--version'], { env: process.env, encoding: 'utf8' }).trim();
    tool.supported = tool.version === tool.oldestSupported;
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  let result;
  if (args[0] === 'info') {
    result = { driver: 'codex', version: '4.2.1', build: 'a3', contract: mode === 'wrong' ? 99 : 1, stateDirectory, settingsFile, tool };
    if (mode === 'bad-json') { process.stdout.write('{broken\n'); process.exit(0); }
    process.exitCode = mode === 'wrong-exit' ? 1 : 0;
  } else {
    const code = tool.path ? 'tool_unsupported' : 'tool_missing';
    result = { error: { code, retryable: false, message: `codex ${tool.version ?? 'not found'}; needed ${tool.oldestSupported}`, detail: { neededVersion: tool.oldestSupported, ...(tool.version ? { toolVersion: tool.version } : {}) } } };
    process.exitCode = 1;
  }
  process.stdout.write(JSON.stringify(result) + '\n');
}
