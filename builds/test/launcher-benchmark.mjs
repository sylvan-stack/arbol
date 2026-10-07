#!/usr/bin/env node
// Local sample only: no vendor executable, account or quota is involved.
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
import { buildComponent } from '../../dist/builds/service.js';

const home = mkdtempSync(join(tmpdir(), 'arbol-launcher-benchmark-'));
const repo = join(home, 'repository'); const registry = join(home, 'registry'); const bin = join(home, 'bin');
const env = { HOME: home, PATH: `${dirname(process.execPath)}:/usr/bin:/bin` };
function invoke(file, args = [], cwd = repo) {
  const start = performance.now(); const result = spawnSync(file, args, {env, cwd, encoding:'utf8'});
  if (result.status !== 0) throw new Error(`${file} failed: ${result.stdout}${result.stderr}`);
  return performance.now() - start;
}
try {
  mkdirSync(repo);
  writeFileSync(join(repo, 'package.json'), '{"version":"1.0.0"}');
  writeFileSync(join(repo, 'program.mjs'), '#!/usr/bin/env node\nprocess.stdout.write("ready\\n");\n');
  writeFileSync(join(repo, 'arbol-build.json'), JSON.stringify({component: 'sample', build: ['cp program.mjs "$ARBOL_BUILD_DIR/program.mjs"; chmod +x "$ARBOL_BUILD_DIR/program.mjs"'], entry: 'program.mjs', checks: [{name:'ready', command:'"$ARBOL_BUILD_DIR/program.mjs"'}]}));
  invoke('git', ['init', '-q', '-b', 'main']); invoke('git', ['add', '.']);
  invoke('git', ['-c', 'user.name=Build Benchmark', '-c', 'user.email=builds@example.invalid', 'commit', '-qm', 'Sample']);
  // Build commands get this script's Node runtime while vendor/session settings stay out.
  for (const key of Object.keys(process.env)) delete process.env[key];
  Object.assign(process.env, env);
  for (let i=0; i<2; i++) {
    const record = await buildComponent('sample', {registry, bin, repo});
    if (record.status !== 'working') throw new Error(JSON.stringify(record));
  }
  const entry = join(registry, 'sample/2/program.mjs'); const launcher = join(bin, 'sample');
  for (let i=0; i<5; i++) { invoke(entry); invoke(launcher); }
  const direct = []; const launched = []; const added = [];
  for (let i=0; i<30; i++) {
    // Alternate order to reduce systematic warm-cache bias.
    let a, b;
    if (i % 2) { b = invoke(launcher); a = invoke(entry); } else { a = invoke(entry); b = invoke(launcher); }
    direct.push(a); launched.push(b); added.push(b-a);
  }
  function stats(values) {
    values.sort((a,b) => a-b);
    return {medianMs: Number(((values[14]+values[15])/2).toFixed(2)), p95Ms: Number(values[28].toFixed(2))};
  }
  const record = {date: new Date().toISOString(), platform: process.platform, arch: process.arch, node: process.version, pairs: 30, workingBuilds: 2, launcherBytes: statSync(launcher).size, direct: stats(direct), launched: stats(launched), added: stats(added)};
  if (process.argv[2]) writeFileSync(process.argv[2], JSON.stringify(record, null, 2)+'\n');
  process.stdout.write(JSON.stringify(record, null, 2)+'\n');
} finally { rmSync(home, {recursive:true, force:true}); }
