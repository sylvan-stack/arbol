import { inspect } from 'node:util';
import { Mismatch } from './check.js';
import { ScenarioHome } from './harness.js';
import { scenarios } from './scenarios/index.js';
import type { Command } from './command.js';
import type { Scenario } from './scenarios/types.js';

export function selectScenarios(only?: string): Scenario[] {
  if (only === undefined) return [...scenarios];
  const ids = only.split(/[\s,]+/).filter(Boolean);
  if (!ids.length) throw new Error('Give --only at least one scenario identifier.');
  for (const id of ids) if (!scenarios.some(scenario => scenario.id === id)) throw new Error(`Unknown or unimplemented scenario: ${id}. Available: ${scenarios.map(s => s.id).join(', ')}.`);
  return scenarios.filter(scenario => ids.includes(scenario.id));
}

export interface SuiteOptions { timeoutMs?: number; signal?: AbortSignal; write?: (line: string) => void }
export async function runSuite(command: Command, selected: Scenario[], options: SuiteOptions = {}): Promise<number> {
  const write = options.write ?? (line => process.stdout.write(line + '\n'));
  let passed = 0;
  for (const scenario of selected) {
    let fixture: ScenarioHome | undefined;
    try {
      options.signal?.throwIfAborted();
      fixture = await ScenarioHome.create(scenario.id, command, options.timeoutMs, options.signal);
      await scenario.run(fixture);
      await fixture.dispose(); fixture = undefined;
      write(`PASS ${scenario.id} — ${scenario.title} (${scenario.scope})`);
      passed++;
    } catch (error) {
      write(`FAIL ${scenario.id} — ${scenario.title} (${scenario.scope})`);
      write(`  ${error instanceof Error ? error.message : String(error)}`);
      if (error instanceof Mismatch) {
        write(`  Expected: ${inspect(error.expected, { depth: 6, maxArrayLength: 20 })}`);
        write(`  Received: ${inspect(error.actual, { depth: 6, maxArrayLength: 20, maxStringLength: 2048 })}`);
      }
    } finally { if (fixture) await fixture.dispose(); }
    if (options.signal?.aborted) break;
  }
  write(`${passed}/${selected.length} scenarios passed.`);
  return options.signal?.aborted ? 2 : passed === selected.length ? 0 : 1;
}
