import { closeSync, mkdirSync, openSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync, writeSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { description } from './config.js';
import type { Locations } from './config.js';
import { buildPattern, defaultRecord, executableEntry, numberedFolders, readRecords, runnable } from './records.js';
import type { BuildRecord } from './records.js';
import { withMutationLock } from './mutation.js';

function atomicWrite(path: string, contents: string, mode = 0o600): void {
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try { writeFileSync(temporary, contents, { mode, flag: 'wx' }); renameSync(temporary, path); }
  finally { rmSync(temporary, { force: true }); }
}
function saveUnlocked(folder: string, record: BuildRecord): void {
  atomicWrite(join(folder, 'build.json'), JSON.stringify(record, null, 2) + '\n');
}
export function saveRecord(folder: string, record: BuildRecord): void {
  withMutationLock(dirname(folder), () => saveUnlocked(folder, record));
}
export function reserve(registry: string, component: string): { folder: string; build: string } {
  const root = join(registry, component);
  mkdirSync(root, { recursive: true, mode: 0o700 });
  let number = numberedFolders(root).reduce((max, item) => BigInt(`0x${item}`) > max ? BigInt(`0x${item}`) : max, 0n) + 1n;
  for (;;) {
    const build = number.toString(16);
    const folder = join(root, build);
    try { mkdirSync(folder, { mode: 0o700 }); return { folder, build }; }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error; number++; }
  }
}

export function writeLauncher(bin: string, registry: string, component: string): void {
  mkdirSync(bin, { recursive: true });
  const runtime = readFileSync(join(import.meta.dirname, 'records.js'), 'utf8')
    .replace(/^export /gm, '').replace(/^\/\/# sourceMappingURL=.*$/gm, '');
  const source = `#!/usr/bin/env node\n${runtime}\nlaunch(${JSON.stringify(resolve(registry))}, ${JSON.stringify(component)}, process.argv.slice(2));\n`;
  atomicWrite(join(bin, component), source, 0o755);
}

async function command(command: string, repo: string, folder: string, number: string, fd: number, signal?: AbortSignal): Promise<boolean> {
  if (signal?.aborted) return false;
  writeSync(fd, `\n$ ${command}\n`);
  return new Promise(resolveResult => {
    const child = spawn('/bin/sh', ['-c', command], { cwd: repo, env: { ...process.env, ARBOL_BUILD_DIR: folder, ARBOL_BUILD_NUMBER: number }, detached: true, stdio: ['ignore', fd, fd] });
    let timer: ReturnType<typeof setTimeout> | undefined;
    const kill = (name: NodeJS.Signals) => { if (child.pid) { try { process.kill(-child.pid, name); } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error; } } };
    const stop = () => { kill('SIGTERM'); timer = setTimeout(() => kill('SIGKILL'), 2000); };
    signal?.addEventListener('abort', stop, { once: true });
    child.on('error', error => writeSync(fd, `Command could not start: ${error.message}\n`));
    child.on('close', (code, endedBy) => {
      if (signal?.aborted) kill('SIGKILL');
      if (timer) clearTimeout(timer);
      signal?.removeEventListener('abort', stop);
      writeSync(fd, `Exit: ${code ?? endedBy ?? 'failed'}${signal?.aborted ? ' (stopped by caller)' : ''}\n`);
      resolveResult(code === 0 && !signal?.aborted);
    });
    if (signal?.aborted) stop();
  });
}

export async function buildComponent(component: string, paths: Locations, signal?: AbortSignal): Promise<BuildRecord> {
  const repo = resolve(paths.repo ?? join(homedir(), 'repos/sylvan-stack', component));
  const { config, version, source } = description(repo, component);
  const { folder, build } = reserve(paths.registry, component);
  const record: BuildRecord = { component, build, packageVersion: version, status: 'building', startedAt: new Date().toISOString(), source, entry: config.entry, checks: [] };
  if (config.contract !== undefined) record.contract = config.contract;
  if (config.dataFormat !== undefined) record.dataFormat = config.dataFormat;
  saveRecord(folder, record);
  const fd = openSync(join(folder, 'build.log'), 'a', 0o600);
  let stage: NonNullable<BuildRecord['failure']>['stage'] = 'launcher';
  let name = 'launcher';
  try {
    writeLauncher(paths.bin, paths.registry, component);
    stage = 'build';
    for (const [index, text] of config.build.entries()) {
      name = `build-${index + 1}`;
      if (!await command(text, repo, folder, build, fd, signal)) throw new Error(signal?.aborted ? 'Build stopped by the caller.' : 'Build command failed; see build.log.');
    }
    stage = 'entry'; name = config.entry;
    if (!executableEntry(folder, config.entry)) throw new Error('The entry must be an executable file within the Build folder.');
    stage = 'check';
    for (const check of config.checks) {
      name = check.name;
      const passed = await command(check.command, repo, folder, build, fd, signal);
      record.checks.push({ name, passed });
      saveRecord(folder, record);
      if (!passed) throw new Error(signal?.aborted ? 'Check stopped by the caller.' : 'Check failed; see build.log.');
    }
    stage = 'entry'; name = config.entry;
    if (!executableEntry(folder, config.entry)) throw new Error('A check removed the Build entry.');
    record.status = 'working';
  } catch (error) {
    record.status = 'failed';
    record.failure = { stage, name, message: (error as Error).message };
    writeSync(fd, `\nFAILED ${stage} ${name}: ${(error as Error).message}\n`);
  } finally {
    closeSync(fd);
    record.finishedAt = new Date().toISOString();
    saveRecord(folder, record);
  }
  return record;
}

export function listBuilds(registry: string, component?: string): Array<BuildRecord & { default: boolean }> {
  let components: string[];
  if (component) components = [component];
  else {
    try { components = readdirSync(registry, { withFileTypes: true }).filter(item => item.isDirectory()).map(item => item.name).sort(); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; components = []; }
  }
  return components.flatMap(name => {
    const records = readRecords(registry, name);
    const selected = defaultRecord(registry, records)?.build;
    return records.map(record => ({ ...record, default: record.build === selected }));
  });
}
export function showBuild(registry: string, component: string, number?: string): BuildRecord {
  if (number !== undefined && !buildPattern.test(number)) throw new Error('A build number is lower-case hexadecimal, without leading zero.');
  const records = readRecords(registry, component);
  const record = number === undefined ? defaultRecord(registry, records) : records.find(record => record.build === number);
  if (!record) throw new Error(`No ${number === undefined ? 'default' : number} Build of ${component}.`);
  return record;
}
export function withdrawBuild(registry: string, component: string, number: string, reason: string): BuildRecord {
  return withMutationLock(join(registry, component), () => {
    const record = showBuild(registry, component, number);
    if (record.status !== 'working' || !runnable(registry, record)) throw new Error('Only a working, unpruned Build can be withdrawn.');
    record.status = 'withdrawn';
    record.withdrawn = { at: new Date().toISOString(), reason };
    saveUnlocked(join(registry, component, number), record);
    return record;
  });
}
export function pruneBuilds(registry: string, component: string, keep: number): { component: string; pruned: string[] } {
  return withMutationLock(join(registry, component), () => {
    const working = readRecords(registry, component).filter(record => record.status === 'working' && !record.prunedAt);
    const selected = defaultRecord(registry, working)?.build;
    const pruned: string[] = [];
    for (const record of working.slice(keep)) {
      if (record.build === selected) continue;
      const folder = join(registry, component, record.build);
      // Mark unavailable before removing files: a partial prune cannot be launched.
      record.prunedAt = new Date().toISOString();
      saveUnlocked(folder, record);
      for (const item of readdirSync(folder)) if (item !== 'build.json' && item !== 'build.log') rmSync(join(folder, item), { recursive: true, force: true });
      pruned.push(record.build);
    }
    return { component, pruned };
  });
}
