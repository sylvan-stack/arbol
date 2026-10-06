import { spawn } from 'node:child_process';
import type { Command } from './command.js';
import type { ProcessResult, ProcessOptions } from './process.js';
import { Mismatch } from './check.js';

export function startInteraction(command: Command, args: string[], options: ProcessOptions) {
  const child = spawn(command[0], [...command.slice(1), ...args], { cwd: options.cwd, env: options.env, detached: true, stdio: 'pipe' });
  let stdout = '', stderr = '', closed = false;
  const lines: unknown[] = []; let rest = '';
  const kill = (signal: NodeJS.Signals): void => { if (child.pid) { try { process.kill(-child.pid, signal); } catch { /* gone */ } } };
  const timer = setTimeout(() => kill('SIGKILL'), options.timeoutMs);
  const done = new Promise<ProcessResult>((resolve, reject) => {
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8'); child.stdin.on('error', () => {});
    child.stdout.on('data', (text: string) => {
      stdout += text; rest += text;
      let end: number;
      while ((end = rest.indexOf('\n')) >= 0) { const line = rest.slice(0, end); rest = rest.slice(end + 1); try { lines.push(JSON.parse(line)); } catch { lines.push({ invalidLine: line }); } }
      if (Buffer.byteLength(stdout) > 4 * 1024 * 1024) kill('SIGKILL');
    });
    child.stderr.on('data', (text: string) => { stderr += text; if (Buffer.byteLength(stderr) > 4 * 1024 * 1024) kill('SIGKILL'); });
    child.on('error', reject); child.on('exit', () => kill('SIGKILL'));
    child.on('close', (status, signal) => { closed = true; clearTimeout(timer); resolve({ status, signal, stdout, stderr }); });
  });
  void done.catch(() => {});
  return { child, done, lines, send(value: unknown) { child.stdin.write(JSON.stringify(value) + '\n'); },
    stop(signal: NodeJS.Signals = 'SIGTERM') { kill(signal); },
    async step(name: string, timeout = 5000): Promise<Record<string, unknown>> {
      const deadline = performance.now() + timeout;
      while (true) {
        const value = lines.find(value => value !== null && typeof value === 'object' && 'step' in value && value.step === name);
        if (value) return value as Record<string, unknown>;
        if (closed || performance.now() >= deadline) throw new Mismatch(`Sign-in did not return ${name}`, name, { args, lines, stdout, stderr });
        await new Promise(resolve => setTimeout(resolve, 10));
      }
    }, async dispose() { kill('SIGKILL'); await done.catch(() => {}); } };
}
