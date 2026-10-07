import { resolve } from 'node:path';
import { componentName, locations } from './config.js';
import { buildComponent, listBuilds, pruneBuilds, showBuild, withdrawBuild } from './service.js';

export const usage = 'arbol-builds build <component> [--repo <folder>] | list [<component>] | show <component>[@<build>] | withdraw <component>@<build> --reason <text> | prune <component> --keep <n> [--registry-dir <folder>] [--bin-dir <folder>]';

export function options(args: string[], allowed: string[]): { words: string[]; values: Map<string, string> } {
  const words: string[] = [];
  const values = new Map<string, string>();
  for (let index = 0; index < args.length; index++) {
    const arg = args[index]!;
    if (!arg.startsWith('-')) { words.push(arg); continue; }
    const equals = arg.indexOf('=');
    const key = equals === -1 ? arg : arg.slice(0, equals);
    if (!allowed.includes(key) || values.has(key)) throw new Error(`Unknown or repeated option: ${key}.`);
    const value = equals === -1 ? args[++index] : arg.slice(equals + 1);
    if (value === undefined || value === '' || (equals === -1 && value.startsWith('--'))) throw new Error(`Option ${key} needs a value.`);
    values.set(key, value);
  }
  return { words, values };
}

export async function main(args: string[]): Promise<number> {
  const print = (value: unknown) => process.stdout.write(JSON.stringify(value) + '\n');
  try {
    if (Number(process.versions.node.split('.')[0]) < 24) throw new Error('arbol-builds requires Node.js 24 or later.');
    if (args.length === 1 && args[0] === '--help') { print({ usage }); return 0; }
    const { words, values } = options(args, ['--registry-dir', '--bin-dir', '--repo', '--reason', '--keep']);
    const [command, target, ...extra] = words;
    if (extra.length || !command || !['build', 'list', 'show', 'withdraw', 'prune'].includes(command) || (command !== 'list' && !target)) throw new Error(usage);
    for (const [key] of values) {
      if ((key === '--repo' && command !== 'build') || (key === '--reason' && command !== 'withdraw') || (key === '--keep' && command !== 'prune')) throw new Error(`Option ${key} does not apply to ${command}.`);
    }
    const paths = locations();
    if (values.has('--registry-dir')) paths.registry = resolve(values.get('--registry-dir')!);
    if (values.has('--bin-dir')) paths.bin = resolve(values.get('--bin-dir')!);
    if (values.has('--repo')) paths.repo = resolve(values.get('--repo')!);
    const [component, number, ...rest] = (target ?? '').split('@');
    if (target) componentName(component!);
    if (rest.length || (number !== undefined && !['show', 'withdraw'].includes(command))) throw new Error('This command takes a component without a build number.');
    if (command === 'list') print(listBuilds(paths.registry, target));
    else if (command === 'show') print(showBuild(paths.registry, component!, number));
    else if (command === 'withdraw') {
      const reason = values.get('--reason');
      if (!number || !reason?.trim()) throw new Error('withdraw requires component@build and --reason <text>.');
      print(withdrawBuild(paths.registry, component!, number, reason));
    } else if (command === 'prune') {
      const keep = values.get('--keep');
      if (!keep || !/^[1-9][0-9]*$/.test(keep) || !Number.isSafeInteger(Number(keep))) throw new Error('--keep must be a positive whole number.');
      print(pruneBuilds(paths.registry, component!, Number(keep)));
    } else {
      const controller = new AbortController();
      const stop = () => controller.abort();
      process.on('SIGINT', stop); process.on('SIGTERM', stop);
      try {
        const record = await buildComponent(component!, paths, controller.signal);
        print(record);
        return record.status === 'working' ? 0 : 1;
      } finally { process.off('SIGINT', stop); process.off('SIGTERM', stop); }
    }
    return 0;
  } catch (error) { print({ error: { code: 'builds_failed', message: (error as Error).message } }); return 1; }
}
