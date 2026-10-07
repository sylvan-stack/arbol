import { chmodSync, copyFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { locations } from './config.js';
import { options } from './cli.js';

export function install(args: string[]): { bin: string; program: string } {
  if (Number(process.versions.node.split('.')[0]) < 24) throw new Error('arbol-builds requires Node.js 24 or later.');
  const { words, values } = options(args, ['--bin-dir']);
  if (words.length) throw new Error('Usage: npm run install:builds -- [--bin-dir <folder>]');
  const bin = resolve(values.get('--bin-dir') ?? locations().bin);
  const library = join(bin, '.arbol-builds');
  mkdirSync(library, { recursive: true });
  for (const name of ['cli', 'config', 'records', 'service', 'mutation']) copyFileSync(join(import.meta.dirname, `${name}.js`), join(library, `${name}.js`));
  writeFileSync(join(library, 'package.json'), '{"type":"module"}\n');
  const program = join(bin, 'arbol-builds');
  writeFileSync(program, `#!/usr/bin/env node\nimport { main } from ${JSON.stringify(pathToFileURL(join(library, 'cli.js')).href)};\nprocess.exitCode = await main(process.argv.slice(2));\n`, { mode: 0o755 });
  chmodSync(program, 0o755);
  return { bin, program };
}
try { process.stdout.write(JSON.stringify(install(process.argv.slice(2))) + '\n'); }
catch (error) { process.stdout.write(JSON.stringify({ error: { code: 'install_failed', message: (error as Error).message } }) + '\n'); process.exitCode = 1; }
