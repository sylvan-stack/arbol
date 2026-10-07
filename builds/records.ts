import { accessSync, constants, readFileSync, readdirSync, realpathSync, statSync, writeSync } from 'node:fs';
import { isAbsolute, join, relative, resolve, sep } from 'node:path';

export interface BuildRecord {
  component: string;
  build: string;
  packageVersion: string;
  status: 'building' | 'failed' | 'working' | 'withdrawn';
  startedAt: string;
  finishedAt?: string;
  source: { repository: string; branch: string; commit: string; uncommittedChanges: boolean };
  entry?: string;
  checks: Array<{ name: string; passed: boolean }>;
  contract?: number;
  dataFormat?: number;
  withdrawn?: { at: string; reason: string };
  prunedAt?: string;
  failure?: { stage: 'build' | 'entry' | 'check' | 'launcher'; name: string; message: string };
}

export const componentPattern = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/;
export const buildPattern = /^[1-9a-f][0-9a-f]*$/;

export function inside(folder: string, path: string): boolean {
  const rel = relative(folder, path);
  return rel !== '' && rel !== '..' && !rel.startsWith(`..${sep}`) && !isAbsolute(rel);
}

export function entryPath(folder: string, entry: unknown): string | undefined {
  if (typeof entry !== 'string' || entry === '' || isAbsolute(entry)) return undefined;
  const path = resolve(folder, entry);
  return inside(folder, path) ? path : undefined;
}

function text(value: unknown): value is string { return typeof value === 'string' && value.length > 0; }
function date(value: unknown): boolean { return text(value) && Number.isFinite(Date.parse(value)); }
function positive(value: unknown): boolean { return Number.isSafeInteger(value) && (value as number) > 0; }
function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function validRecord(value: unknown, component: string, build: string): value is BuildRecord {
  if (!object(value) || value.component !== component || value.build !== build || !buildPattern.test(build)
    || !text(value.packageVersion) || !date(value.startedAt)
    || !['building', 'failed', 'working', 'withdrawn'].includes(String(value.status))) return false;
  const source = value.source;
  if (!object(source) || !text(source.repository) || !text(source.branch) || !text(source.commit)
    || typeof source.uncommittedChanges !== 'boolean') return false;
  if (!Array.isArray(value.checks) || !value.checks.every(check => object(check) && text(check.name) && typeof check.passed === 'boolean')) return false;
  for (const key of ['contract', 'dataFormat']) if (value[key] !== undefined && !positive(value[key])) return false;
  for (const key of ['finishedAt', 'prunedAt']) if (value[key] !== undefined && !date(value[key])) return false;
  if (value.entry !== undefined && entryPath('/build', value.entry) === undefined) return false;
  if (value.status === 'working' || value.status === 'withdrawn') {
    if (!date(value.finishedAt) || !text(value.entry) || value.checks.length === 0 || value.checks.some(check => check.passed !== true)) return false;
  }
  if (value.status === 'withdrawn' && (!object(value.withdrawn) || !date(value.withdrawn.at) || !text(value.withdrawn.reason))) return false;
  return true;
}

export function numberedFolders(folder: string): string[] {
  try { return readdirSync(folder, { withFileTypes: true }).filter(item => item.isDirectory() && buildPattern.test(item.name)).map(item => item.name); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return []; throw error; }
}

export function readRecords(registry: string, component: string): BuildRecord[] {
  const folder = join(registry, component);
  const records: BuildRecord[] = [];
  for (const build of numberedFolders(folder)) {
    try {
      const record: unknown = JSON.parse(readFileSync(join(folder, build, 'build.json'), 'utf8'));
      if (validRecord(record, component, build)) records.push(record);
    } catch { /* One damaged or missing record affects only this Build. */ }
  }
  return records.sort((a, b) => BigInt(`0x${a.build}`) > BigInt(`0x${b.build}`) ? -1 : 1);
}

export function executableEntry(folder: string, entry: unknown): string | undefined {
  const path = entryPath(folder, entry);
  if (!path) return undefined;
  try {
    if (!inside(realpathSync(folder), realpathSync(path)) || !statSync(path).isFile()) return undefined;
    accessSync(path, constants.X_OK);
    return path;
  } catch { return undefined; }
}

export function runnable(registry: string, record: BuildRecord): boolean {
  return !record.prunedAt && (record.status === 'working' || record.status === 'withdrawn')
    && executableEntry(join(registry, record.component, record.build), record.entry) !== undefined;
}

export function defaultRecord(registry: string, records: BuildRecord[]): BuildRecord | undefined {
  return records.find(record => record.status === 'working' && runnable(registry, record));
}

// This module is also copied into each standalone launcher. It has only built-in imports.
export function launch(registry: string, component: string, args: string[]): void {
  try {
    const records = readRecords(registry, component);
    const available = records.filter(record => runnable(registry, record)).map(record => record.build);
    let selected: BuildRecord | undefined;
    if (args[0] === '-v') {
      const number = args[1];
      if (number && buildPattern.test(number)) selected = records.find(record => record.build === number && runnable(registry, record));
      args = args.slice(2);
    } else selected = defaultRecord(registry, records);
    if (!selected) {
      writeSync(1, JSON.stringify({ error: { code: 'build_unavailable', message: `No runnable Build selected for ${component}. Available Builds: ${available.join(', ') || 'none'}.`, available } }) + '\n');
      process.exitCode = 1;
      return;
    }
    if (!process.execve) throw new Error('Launchers require Node.js 24 or later on a POSIX system.');
    if (selected.status === 'withdrawn') writeSync(2, `${component}@${selected.build} is withdrawn: ${selected.withdrawn!.reason}\n`);
    const entry = executableEntry(join(registry, component, selected.build), selected.entry)!;
    process.execve(entry, [entry, ...args], process.env);
  } catch (error) {
    writeSync(1, JSON.stringify({ error: { code: 'launch_failed', message: (error as Error).message } }) + '\n');
    process.exitCode = 1;
  }
}
