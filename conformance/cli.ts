import { resolveCommand } from './command.js';
import { runSuite, selectScenarios } from './runner.js';
import { scenarios } from './scenarios/index.js';

const usage = `Usage: arbol-conformance --driver <command> [--only <scenario ids>]\nAvailable: ${scenarios.map(scenario => scenario.id).join(', ')}. Quote commands with fixed arguments and paths with spaces.\nExit status: 0 passed; 1 scenario failed; 2 invalid input or stopped.`;

export async function main(args: string[]): Promise<number> {
  const cancellation = new AbortController();
  const stop = (): void => cancellation.abort();
  process.on('SIGINT', stop); process.on('SIGTERM', stop);
  try {
    if (Number(process.versions.node.split('.')[0]) < 24) throw new Error('The conformance suite needs Node.js 24 or later.');
    if (args.length === 1 && args[0] === '--help') { process.stdout.write(usage + '\n'); return 0; }
    const values: Record<string, string> = {};
    for (let i = 0; i < args.length; i++) {
      const arg = args[i]!;
      const index = arg.indexOf('=');
      const name = index < 0 ? arg : arg.slice(0, index);
      if (!['--driver', '--only'].includes(name)) throw new Error(`Unknown suite option: ${arg}`);
      const value = index < 0 ? args[++i] : arg.slice(index + 1);
      if (value === undefined || !value.trim() || value.startsWith('--') || name in values) throw new Error(`Give ${name} exactly one value.`);
      values[name] = value;
    }
    if (!values['--driver']) throw new Error('Give --driver a command.');
    const selected = selectScenarios(values['--only']);
    const command = await resolveCommand(values['--driver']);
    return await runSuite(command, selected, { signal: cancellation.signal });
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n${usage}\n`);
    return 2;
  } finally { process.off('SIGINT', stop); process.off('SIGTERM', stop); }
}
