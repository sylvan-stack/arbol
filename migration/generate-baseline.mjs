// Generate immutable compatibility vectors from separately retained baseline commits.
import { pathToFileURL } from 'node:url';
import { resolve, join } from 'node:path';
import { readFile, writeFile, mkdir, mkdtemp, realpath, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
const baseline = resolve(process.argv[2]);
const destination = resolve(process.argv[3]);
const message = (role, text, images) => ({ type: 'message', role, text, ...(images ? { images } : {}) });
const tool = { type: 'tool_call', name: 'shell', input: { command: 'printf fixture' }, ok: true, result: { output: 'fixture', exitCode: 0 } };
const vectors = [
  ['empty', []],
  ['ascii', [message('user', 'hello'), message('assistant', 'world')]],
  ['unicode-and-controls', [message('user', 'Quote " slash \\\n\r\t\b\f\u0000 café 中文 😀 \u2028\u2029'), message('assistant', '¿sí?')]],
  ['images-decoded-bytes', [message('user', 'picture', [{ mediaType: 'image/png', data: 'aQ==' }, { mediaType: 'image/jpeg', data: 'AAECA//+' }])]],
  ['image-base64-pad-bits', [message('user', 'same bytes', [{ mediaType: 'image/png', data: 'aR==' }])]],
  ['assistant-blocks', [message('user', 'prompt'), message('assistant', 'first'), message('assistant', 'second')]],
  ['assistant-across-tool', [message('user', 'prompt'), message('assistant', 'before'), tool, message('assistant', 'after')]],
  ['consecutive-users', [message('user', 'one'), message('user', 'two'), message('assistant', '')]],
  ['empty-assistant', [message('assistant', ''), message('assistant', '')]],
  ['lone-high-surrogate', [message('user', '\ud83d'), message('assistant', '\ud83d')]],
  ['lone-low-surrogate', [message('user', '\ude00'), message('assistant', '\ude00')]],
  ['split-surrogate-pair', [message('user', 'prompt'), message('assistant', '\ud83d'), tool, message('assistant', '\ude00')]],
  ['paired-surrogates-in-one-block', [message('assistant', '\ud83d\ude00')]],
  ['high-surrogate-followed-by-user', [message('assistant', '\ud83d'), message('user', 'next')]],
];
const chats = ['opaque/../chat', 'café/中文/😀', 'quote"\ncontrol\u0000', '\ud83d', '\ude00', ''];
const folders = ['/space dir/_a.b+@ü', '/中文/😀/é', '/a\\b:c', '/' + 'x'.repeat(210), '/a\n\u0000b'];
const sha = value => createHash('sha256').update(value).digest('hex');
function canonical(history) {
  const tuples = [];
  for (const item of history) {
    if (item.type !== 'message') continue;
    if (item.role === 'assistant' && tuples.at(-1)?.[0] === 'assistant') tuples.at(-1)[1] += item.text;
    else if (item.role === 'assistant') tuples.push(['assistant', item.text]);
    else tuples.push(['user', item.text, (item.images ?? []).map(image => [image.mediaType, sha(Buffer.from(image.data, 'base64'))])]);
  }
  return { messages: tuples.length, digest: sha(JSON.stringify(tuples)), json: JSON.stringify(tuples) };
}
const record = { issue: 'SYL-95', date: '2026-10-07', node: process.version, drivers: {}, histories: vectors.map(([name, history]) => ({ name, history, canonical: canonical(history), expected: {} })), chats: [], folders: [] };
for (const driver of ['claude', 'codex']) {
  const repo = join(baseline, `arbol-${driver}-driver`);
  const history = await import(pathToFileURL(join(repo, 'dist/src', driver === 'claude' ? 'history.js' : 'continuity.js')));
  record.drivers[driver] = { commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(), worktree: execFileSync('git', ['status', '--porcelain'], { cwd: repo, encoding: 'utf8' }).trim() };
  for (const vector of record.histories) {
    const digest = new history.MessageDigest();
    const snapshots = [digest.snapshot()];
    for (const item of vector.history) { digest.add(item); snapshots.push(digest.snapshot()); }
    vector.expected[driver] = { ...history.messageDigest(vector.history), snapshots };
  }
  for (const chat of chats) {
    const entry = record.chats.find(entry => entry.chat === chat) ?? { chat, expected: {} };
    entry.expected[driver] = history.chatKey(chat);
    if (!record.chats.includes(entry)) record.chats.push(entry);
  }
}
const continuity = await import(pathToFileURL(join(baseline, 'arbol-claude-driver/dist/src/continuity.js')));
record.folders = folders.map(folder => ({ folder, expected: continuity.encodeFolder(folder) }));
const secrets = await import(pathToFileURL(join(baseline, 'arbol-claude-driver/dist/src/secrets.js')));
const temporary = await mkdtemp(join(tmpdir(), 'syl95-keychain-'));
try {
  const custom = join(temporary, 'custom'); await mkdir(custom);
  const customReal = await realpath(custom);
  const normal = join(temporary, 'Library/Application Support/Arbol/drivers/claude'); await mkdir(normal, { recursive: true });
  record.keychain = { defaultService: await secrets.keychainService(normal, temporary), customServicePrefix: secrets.KEYCHAIN_SERVICE, customSuffixLength: 12, customExample: { realPath: customReal, service: await secrets.keychainService(custom, temporary), sha256: sha(customReal) } };
} finally { await rm(temporary, { recursive: true, force: true }); }
await mkdir(destination, { recursive: true });
await writeFile(join(destination, 'baseline-vectors.json'), JSON.stringify(record, null, 2) + '\n');
const differences = record.histories.filter(vector => vector.expected.claude.digest !== vector.canonical.digest).map(vector => vector.name);
console.log(JSON.stringify({ output: join(destination, 'baseline-vectors.json'), histories: record.histories.length, knownClaudeDifferences: differences }));
