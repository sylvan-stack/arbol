import { mkdtemp, mkdir, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, isAbsolute, join, relative } from 'node:path';
import { check, object, Mismatch } from './check.js';
import { shellQuote } from './command.js';
import { invoke } from './process.js';
import type { Command } from './command.js';
import type { ProcessResult } from './process.js';

export interface Received {
  scenario: string;
  part: string;
  arguments: string[];
  environment: string[];
  workingDirectory: string;
  checks: Record<string, unknown>;
  [key: string]: unknown;
}

export class ScenarioHome {
  readonly tool: string;
  readonly toolPath: string;
  readonly env: NodeJS.ProcessEnv;
  private constructor(readonly home: string, readonly id: string, readonly command: Command, readonly timeoutMs: number, readonly signal?: AbortSignal) {
    this.tool = join(home, 'tool');
    this.toolPath = join(this.tool, 'vendor-tool');
    this.env = {
      HOME: home, PATH: `${dirname(process.execPath)}:${dirname(command[0])}:/usr/bin:/bin`,
      LANG: 'C', TMPDIR: home, TMP: home, TEMP: home, ARBOL_TEST_TIME_SCALE: '100',
    };
  }

  static async create(id: string, command: Command, timeoutMs = 15000, signal?: AbortSignal): Promise<ScenarioHome> {
    const home = await realpath(await mkdtemp(join(tmpdir(), `arbol-conformance-${id}-`)));
    const fixture = new ScenarioHome(home, id, command, timeoutMs, signal);
    try {
      await mkdir(fixture.tool, { mode: 0o700 });
      await mkdir(join(home, '.arbol'), { mode: 0o700 });
      const words = [...command, 'dev', 'stand-in', fixture.tool, '--'].map(shellQuote).join(' ');
      await writeFile(fixture.toolPath, `#!/bin/sh\nexec ${words} "$@"\n`, { mode: 0o700 });
      await fixture.part('supported');
      return fixture;
    } catch (error) { await fixture.dispose(); throw error; }
  }

  async part(part: string, missing = false): Promise<void> {
    await writeFile(join(this.tool, 'scenario'), `${this.id} ${part}\n`, { mode: 0o600 });
    const settings = JSON.stringify({ toolPath: missing ? join(this.tool, 'nonexistent') : this.toolPath });
    // Both contract filenames are installed before discovering the Driver with info.
    for (const driver of ['claude', 'codex']) await writeFile(join(this.home, '.arbol', `arbol-${driver}-driver.json`), settings, { mode: 0o600 });
  }

  call(args: string[]): Promise<ProcessResult> {
    return invoke(this.command, args, { cwd: this.home, env: this.env, timeoutMs: this.timeoutMs, ...(this.signal ? { signal: this.signal } : {}) });
  }

  async json(args: string[]): Promise<{ process: ProcessResult; result: Record<string, unknown> }> {
    const process = await this.call(args);
    let parsed: unknown;
    try { parsed = JSON.parse(process.stdout); }
    catch { throw new Mismatch(`Invalid JSON from ${args.join(' ')}`, 'one JSON result', process); }
    return { process, result: object(`Result of ${args.join(' ')}`, parsed) };
  }

  async received(): Promise<Received[]> {
    let content: string;
    try { content = await readFile(join(this.tool, 'received.jsonl'), 'utf8'); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return []; throw error; }
    const records: Received[] = [];
    for (const [index, line] of content.trim().split('\n').entries()) {
      if (!line) continue;
      let parsed: unknown;
      try { parsed = JSON.parse(line); }
      catch { throw new Mismatch(`received.jsonl line ${index + 1}`, 'a JSON record', line); }
      const entry = object('Stand-in record', parsed);
      for (const field of ['scenario', 'part', 'workingDirectory']) check(`Stand-in ${field}`, typeof entry[field] === 'string', 'a string', entry[field]);
      for (const field of ['arguments', 'environment']) check(`Stand-in ${field}`, Array.isArray(entry[field]) && entry[field].every(value => typeof value === 'string'), 'an array of strings', entry[field]);
      object('Stand-in checks', entry.checks);
      records.push(entry as unknown as Received);
    }
    return records;
  }

  contains(path: string): boolean {
    const rel = relative(this.home, path);
    return isAbsolute(path) && rel !== '..' && !rel.startsWith('../') && !isAbsolute(rel);
  }

  dispose(): Promise<void> { return rm(this.home, { recursive: true, force: true }); }
}
