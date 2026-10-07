import { mkdirSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';

interface Writer { pid: number; choosing: boolean; ticket: string }

// Lamport's bakery lock: each invocation owns a unique file, so reclaiming a dead
// writer cannot remove a new writer's reservation. It needs no resident process.
export function withMutationLock<T>(componentFolder: string, action: () => T): T {
  const folder = join(componentFolder, '.writers');
  mkdirSync(folder, { recursive: true, mode: 0o700 });
  const name = `${process.pid}-${randomUUID()}.json`;
  const path = join(folder, name);
  const writer: Writer = { pid: process.pid, choosing: true, ticket: '0' };
  const waiting = new Int32Array(new SharedArrayBuffer(4));
  const started = performance.now();
  const pause = () => {
    if (performance.now() - started > 30000) throw new Error('Another invocation is still changing this component; try again when it finishes.');
    Atomics.wait(waiting, 0, 0, 10);
  };
  const publish = () => {
    const temp = `${path}.tmp`;
    try { writeFileSync(temp, JSON.stringify(writer), { mode: 0o600 }); renameSync(temp, path); }
    finally { rmSync(temp, { force: true }); }
  };
  const readers = (): Array<{ name: string; writer: Writer }> => {
    const found: Array<{ name: string; writer: Writer }> = [];
    for (const item of readdirSync(folder)) {
      if (!/^\d+-[0-9a-f-]+\.json$/.test(item) || item === name) continue;
      const otherPath = join(folder, item);
      let other: Writer;
      try { other = JSON.parse(readFileSync(otherPath, 'utf8')) as Writer; }
      catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') continue; throw error; }
      if (!Number.isSafeInteger(other.pid) || other.pid < 1 || typeof other.choosing !== 'boolean' || !/^\d+$/.test(other.ticket)) throw new Error(`Damaged writer reservation: ${otherPath}`);
      try { process.kill(other.pid, 0); }
      catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ESRCH') { rmSync(otherPath, { force: true }); continue; }
        if ((error as NodeJS.ErrnoException).code !== 'EPERM') throw error;
      }
      found.push({ name: item, writer: other });
    }
    return found;
  };
  try {
    publish();
    writer.ticket = (readers().reduce((max, other) => BigInt(other.writer.ticket) > max ? BigInt(other.writer.ticket) : max, 0n) + 1n).toString();
    writer.choosing = false; publish();
    while (readers().some(other => other.writer.choosing || (BigInt(other.writer.ticket) > 0n
      && (BigInt(other.writer.ticket) < BigInt(writer.ticket) || (other.writer.ticket === writer.ticket && other.name < name))))) pause();
    return action();
  } finally { rmSync(path, { force: true }); }
}
