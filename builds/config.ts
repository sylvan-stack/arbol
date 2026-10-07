import { readFileSync, realpathSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { componentPattern, entryPath } from './records.js';
import type { BuildRecord } from './records.js';

export interface BuildDescription {
  component: string;
  build: string[];
  entry: string;
  checks: Array<{ name: string; command: string; kind?: 'unit' | 'contract' | 'live' }>;
  contract?: number;
  dataFormat?: number;
}

export interface Locations { registry: string; bin: string; repo?: string }
export function locations(): Locations {
  return { registry: join(homedir(), 'Library/Application Support/Arbol/builds'), bin: join(homedir(), '.local/bin') };
}
export function componentName(name: string): string {
  if (!componentPattern.test(name)) throw new Error('A component name must contain lower-case letters, digits and separating hyphens.');
  return name;
}

export function description(repo: string, component: string): { config: BuildDescription; version: string; source: BuildRecord['source'] } {
  const config = JSON.parse(readFileSync(join(repo, 'arbol-build.json'), 'utf8')) as BuildDescription;
  if (!config || config.component !== component || !Array.isArray(config.build) || config.build.length === 0
    || config.build.some(command => typeof command !== 'string' || command.trim() === '')
    || !entryPath('/build', config.entry) || !Array.isArray(config.checks) || config.checks.length === 0) {
    throw new Error('Invalid arbol-build.json: expected this component, nonempty build commands, a relative executable entry and named checks.');
  }
  const names = new Set<string>();
  for (const check of config.checks) {
    if (!check || typeof check.name !== 'string' || check.name.trim() === '' || names.has(check.name)
      || typeof check.command !== 'string' || check.command.trim() === ''
      || (check.kind !== undefined && !['unit', 'contract', 'live'].includes(check.kind))) throw new Error('Invalid or duplicate check in arbol-build.json.');
    names.add(check.name);
  }
  for (const value of [config.contract, config.dataFormat]) {
    if (value !== undefined && (!Number.isSafeInteger(value) || value < 1)) throw new Error('contract and dataFormat must be positive whole numbers.');
  }
  if (component.endsWith('-driver')) {
    if (config.contract === undefined || config.dataFormat === undefined
      || ['unit', 'contract', 'live'].some(kind => !config.checks.some(check => check.kind === kind))) {
      throw new Error('A Driver requires contract, dataFormat and unit, contract and live checks.');
    }
  }
  const pkg = JSON.parse(readFileSync(join(repo, 'package.json'), 'utf8')) as { version?: unknown };
  if (typeof pkg.version !== 'string' || !pkg.version.trim()) throw new Error('package.json must name the package version.');
  const git = (...args: string[]) => execFileSync('git', args, { cwd: repo, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  return { config, version: pkg.version, source: {
    repository: realpathSync(resolve(repo)), branch: git('rev-parse', '--abbrev-ref', 'HEAD'),
    commit: git('rev-parse', 'HEAD'), uncommittedChanges: git('status', '--porcelain').length > 0,
  } };
}
