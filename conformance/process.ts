import { spawn } from 'node:child_process';
import { Mismatch } from './check.js';
import type { Command } from './command.js';

export interface ProcessResult { status: number | null; signal: string | null; stdout: string; stderr: string }
export interface ProcessOptions { cwd: string; env: NodeJS.ProcessEnv; timeoutMs: number; signal?: AbortSignal }

export function invoke(command: Command, args: string[], options: ProcessOptions): Promise<ProcessResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(command[0], [...command.slice(1), ...args], {
      cwd: options.cwd, env: options.env, detached: true, stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '', stderr = '', bytes = 0;
    let failure: Error | undefined;
    const killGroup = (): void => {
      if (child.pid) {
        try { process.kill(-child.pid, 'SIGKILL'); }
        catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ESRCH') failure ??= error as Error; }
      }
    };
    const stop = (error: Error): void => { failure ??= error; killGroup(); };
    const abort = (): void => stop(new Mismatch('Driver invocation was stopped', 'a completed invocation', { args, stdout, stderr }));
    const timer = setTimeout(() => stop(new Mismatch('Driver invocation timed out', `completion within ${options.timeoutMs} ms`, { args, stdout, stderr })), options.timeoutMs);
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    const collect = (chunk: string, stream: 'stdout' | 'stderr'): void => {
      bytes += Buffer.byteLength(chunk);
      if (bytes > 4 * 1024 * 1024) { stop(new Mismatch('Driver output exceeded the runner limit', 'at most 4 MiB per invocation', { args, bytes })); return; }
      if (stream === 'stdout') stdout += chunk;
      else stderr += chunk;
    };
    child.stdout.on('data', (chunk: string) => collect(chunk, 'stdout'));
    child.stderr.on('data', (chunk: string) => collect(chunk, 'stderr'));
    child.on('error', error => { failure ??= new Mismatch('Driver could not start', 'an executable Driver', { args, message: error.message }); });
    // End descendants even when the Driver exits without closing their inherited pipes.
    child.on('exit', killGroup);
    child.on('close', (status, signal) => {
      clearTimeout(timer);
      options.signal?.removeEventListener('abort', abort);
      if (failure) reject(failure);
      else resolve({ status, signal, stdout, stderr });
    });
    options.signal?.addEventListener('abort', abort, { once: true });
    if (options.signal?.aborted) abort();
  });
}
