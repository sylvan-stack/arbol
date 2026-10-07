import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { check, equal, object, text } from '../check.js';
import { signed, stream } from './runs.js';
import type { Scenario } from './types.js';
const delay = async (ms: number): Promise<void> => new Promise(resolve => setTimeout(resolve, ms));
export const c14: Scenario = { id: 'C14', title: 'Resume or rebuild the caller conversation', scope: 'continuity, reasons, history, map privacy, competing and failed runs',
  covers: ['DRV-2.11', 'DRV-2.12', 'DRV-2.13', 'DRV-2.34', 'DRV-2.35', 'DRV-6.11', 'DRV-6.12', 'DRV-6.14', 'DRV-6.15'], async run(home) {
    const subscriptionId = await signed(home); const info = await home.json(['info']); const state = text('State folder', info.result.stateDirectory);
    const codex = info.result.driver === 'codex';
    const savedFiles = async (folder: string): Promise<string[]> => {
      const entries = await readdir(folder, { withFileTypes: true }).catch(error => {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') return []; throw error;
      });
      const paths: string[] = [];
      for (const entry of entries) {
        const path = join(folder, entry.name);
        if (entry.isDirectory()) paths.push(...await savedFiles(path)); else if (entry.isFile()) paths.push(path);
      }
      return paths;
    };
    const chatSessionId = 'opaque/../chat'; const key = createHash('sha256').update(chatSessionId).digest('hex');
    const mapPath = (id = subscriptionId) => join(state, 'subscriptions', id, 'chats', key + '.json');
    const map = async () => object('Chat map', JSON.parse(await readFile(mapPath(), 'utf8')));
    const image = { mediaType: 'image/png', data: 'aQ==' };
    const firstMessage = { type: 'message', role: 'user', text: 'history-user-secret', images: [image] };
    const shell = { type: 'tool_call', name: 'shell', input: { command: 'printf history-shell-output', cwd: '/ignored' },
      ok: false, result: { output: 'history-shell-output', exitCode: 2 }, error: 'history-error' };
    const foreign = { type: 'tool_call', name: 'foreign_tool', input: { value: 'foreign-input' }, ok: true, result: { value: 'foreign-value' } };
    const base = { subscriptionId, chatSessionId, workingDirectory: home.home, tools: 'none', history: [] as object[],
      input: { role: 'user', text: 'history-user-secret', images: [image] } };
    let counter = 0;
    const requestFile = async (request: object): Promise<string> => {
      const file = join(home.home, `request-${++counter}.json`); await writeFile(file, JSON.stringify(request)); return file;
    };
    const invoke = async (request: object, continuity: string, reason?: string, part = 'plain', outcome = 'completed') => {
      await home.part(part); const records = stream(await home.call(['run', '--request', await requestFile(request)]), outcome);
      const started = records.filter(event => event.type === 'started'); equal('One started event', started.length, 1);
      equal('Continuity', started[0]!.continuity, continuity); equal('First rebuild reason', started[0]!.rebuildReason, reason);
      return records;
    };
    const append = (history: object[], input: { text: string; images?: object[] }, records: Record<string, any>[]) => [...history,
      { type: 'message', role: 'user', ...input }, ...records.filter(event => event.type === 'text' && !event.parentCallId).map(event => ({ type: 'message', role: 'assistant', text: event.text }))];
    const inputSeen = async () => (await home.received()).filter(record => record.stage === 'input').at(-1)!.checks;
    const checkNative = async () => {
      const seen = await inputSeen(); equal('Native shell tool', seen.nativeShellCall, true);
      equal('Native failed result', seen.nativeShellResult, 'history-shell-output\nexit code: 2\nhistory-error'); equal('Native error flag', seen.nativeShellFailed, true);
      equal('Foreign tool and JSON result', seen.nativeForeignCall, true); equal('Earlier images', seen.historyImages, [image]);
      if (codex) {
        const received = await home.received(); const input = object('Codex turn request', received.filter(record => record.stage === 'input').at(-1)!.request);
        const turn = object('Codex turn parameters', input.params);
        const injections = received.filter(record => record.stage === 'request' && (record.request as any)?.method === 'thread/inject_items' &&
          (record.request as any)?.params?.threadId === turn.threadId);
        equal('One Codex native injection', injections.length, 1); const injection = injections[0]!;
        check('Codex native injection precedes turn', received.indexOf(injection) < received.findLastIndex(record => record.stage === 'input'),
          'thread/inject_items before turn/start', turn);
        const items = (injection!.request as any).params.items as Record<string, any>[];
        const call = items.find(item => item.type === 'function_call' && item.name === 'shell');
        check('Codex shell has a made-up call identifier', typeof call?.call_id === 'string' && /^call_[a-zA-Z0-9]{24}$/.test(call.call_id), 'call_ and 24 letters/digits', call);
        equal('Codex shell arguments', JSON.parse(call!.arguments), { command: 'printf history-shell-output', cwd: '/ignored' });
        equal('Codex shell result follows call', items[items.indexOf(call!) + 1], { type: 'function_call_output', call_id: call!.call_id,
          output: 'history-shell-output\nexit code: 2\nhistory-error' });
      }
    };
    const first = await invoke(base, 'fresh'); const initial = await map(); equal('Map chat identifier', initial.chatSessionId, chatSessionId); equal('Map count', initial.messages, 2);
    equal('Map filename', (await readdir(join(state, 'subscriptions', subscriptionId, 'chats'))), [key + '.json']);
    check('Private map', ((await stat(mapPath())).mode & 0o777) === 0o600, '0600', await stat(mapPath()));
    let history = append([], base.input, first);
    const nextInput = { role: 'user', text: 'second' };
    const second = await invoke({ ...base, history, input: nextInput }, 'resumed'); equal('Same saved conversation', (await map()).conversation, initial.conversation);
    history = append(history, nextInput, second);
    const changedPrompt = await invoke({ ...base, history, systemPrompt: 'changed-system', input: { role: 'user', text: 'third' } },
      info.result.driver === 'claude' ? 'resumed' : 'rebuilt', info.result.driver === 'claude' ? undefined : 'system_prompt_changed');
    const prompt = await inputSeen(); equal('New prompt reached tool', prompt.systemPrompt, 'changed-system');
    if (info.result.driver === 'claude') equal('Prompt snapshot disabled', prompt.promptSnapshotOff, true);
    history = append(history, { text: 'third' }, changedPrompt);
    const edited = [{ ...firstMessage, text: 'edited-user-secret' }, shell, foreign, ...history.slice(1)];
    const rebuilt = await invoke({ ...base, history: edited, input: { role: 'user', text: 'after edit' } }, 'rebuilt', 'history_differs'); await checkNative();
    check('New native conversation', (await map()).conversation !== initial.conversation, 'new identifier', await map());
    history = append(edited, { text: 'after edit' }, rebuilt);
    // Splitting replies and changing tool records alone leave the message digest unchanged.
    const split = history.flatMap((item: any) => item.type === 'message' && item.role === 'assistant' ?
      [{ ...item, text: item.text.slice(0, 2) }, { ...item, text: item.text.slice(2) }] : [item]);
    const splitRun = await invoke({ ...base, history: [...split, { type: 'tool_call', name: 'ignored_tool_change', input: {}, ok: true, result: 'changed-tool-record' }], input: { role: 'user', text: 'split reply' } }, 'resumed');
    history = append(split, { text: 'split reply' }, splitRun);
    const replaced = history.map((item: any, index) => index === history.length - 1 ? { ...item, text: 'replaced-reply-secret' } : item);
    const replacement = await invoke({ ...base, history: replaced, input: { role: 'user', text: 'replacement' } }, 'rebuilt', 'history_differs'); await checkNative();
    history = append(replaced, { text: 'replacement' }, replacement);
    const otherFolder = join(home.home, 'other'); await mkdir(otherFolder);
    const moved = await invoke({ ...base, history, workingDirectory: otherFolder, input: { role: 'user', text: 'moved' } }, 'rebuilt', 'working_folder_changed');
    history = append(history, { text: 'moved' }, moved);
    const current = await map(); const toolHome = join(state, 'subscriptions', subscriptionId, 'home'); const projects = join(toolHome, 'projects');
    if (codex) {
      for (const root of ['sessions', 'archived_sessions']) for (const file of await savedFiles(join(toolHome, root))) {
        if (file.endsWith('-' + String(current.conversation) + '.jsonl')) await rm(file);
      }
    } else for (const folder of await readdir(projects)) await rm(join(projects, folder, String(current.conversation) + '.jsonl'), { force: true });
    const gone = await invoke({ ...base, history, workingDirectory: otherFolder, input: { role: 'user', text: 'gone' } }, 'rebuilt', 'conversation_gone');
    history = append(history, { text: 'gone' }, gone);
    const original = await map();
    await home.part('hold'); const heldFile = await requestFile({ ...base, history, workingDirectory: otherFolder, runId: 'held-chat', input: { role: 'user', text: 'held' } });
    const held = home.start(['run', '--request', heldFile]);
    try {
      let live = false;
      for (let i = 0; i < 100; i++) { if ((await home.received()).some(record => record.stage === 'input' && record.part === 'hold')) { live = true; break; } await delay(10); }
      check('Resume reserved before peer', live, 'active held-chat', held.lines);
      equal('Original map kept during run', (await map()).conversation, original.conversation);
      const peer = await invoke({ ...base, history, workingDirectory: otherFolder, input: { role: 'user', text: 'peer' } }, 'rebuilt', 'in_use');
      stream(await held.done); history = append(history, { text: 'held' }, held.lines as Record<string, any>[]);
      equal('Last completed writer wins', (await map()).conversation, original.conversation);
      equal('Independent peer completed', peer.at(-1)!.outcome, 'completed');
    } finally { await held.dispose(); }
    const failed = await invoke({ ...base, history, workingDirectory: otherFolder, input: { role: 'user', text: 'fail' } }, 'resumed', undefined, 'fail', 'failed');
    equal('Failed map removed', await stat(mapPath()).then(() => false).catch(() => true), true);
    // Failed replies are caller-owned too; their next use has no saved entry.
    history = append(history, { text: 'fail' }, failed);
    const firstAgain = await invoke({ ...base, history, workingDirectory: otherFolder, input: { role: 'user', text: 'again' } }, 'rebuilt', 'first_run');
    history = append(history, { text: 'again' }, firstAgain);
    for (const part of ['refuse', 'refuse-stderr']) {
      const fallback = await invoke({ ...base, history, workingDirectory: otherFolder, input: { role: 'user', text: 'fallback' } }, 'rebuilt', 'resume_refused', part);
      equal('One text fallback notice', fallback.filter(event => event.type === 'notice' && event.code === 'history_as_text').length, 1);
      equal('Labelled history reaches tool', (await inputSeen()).labelledHistory, true);
      history = append(history, { text: 'fallback' }, fallback);
    }
    await invoke({ ...base, history, chatSessionId: undefined, input: { role: 'user', text: 'anonymous' } }, 'rebuilt', 'no_chat_session'); await checkNative();
    const refusedRebuild = await invoke({ ...base, history, chatSessionId: undefined, input: { role: 'user', text: 'refused rebuild' } }, 'rebuilt', 'no_chat_session', 'refuse');
    equal('Refused synthetic session uses text', refusedRebuild.filter(event => event.type === 'notice' && event.code === 'history_as_text').length, 1);
    const oneOff = await invoke({ ...base, history, workingDirectory: undefined, input: { role: 'user', text: 'one off' } }, 'rebuilt', 'no_chat_session');
    equal('One-off completed', oneOff.at(-1)!.outcome, 'completed');
    const oneOffSeen = (await home.received()).filter(record => record.stage === 'input').at(-1)!;
    if (codex) {
      const params = (oneOffSeen.request as any).params; const records = await home.received();
      const start = records.filter(record => (record.request as any)?.method === 'thread/start').at(-1)!;
      equal('One-off thread is ephemeral', (start.request as any).params.ephemeral, true);
      for (const root of ['sessions', 'archived_sessions']) equal('One-off has no saved rollout',
        (await savedFiles(join(toolHome, root))).some(file => file.endsWith('-' + params.threadId + '.jsonl')), false);
    } else {
      const oneOffArgs = oneOffSeen.arguments; const oneOffId = oneOffArgs[oneOffArgs.indexOf('--resume') + 1];
      for (const folder of await readdir(projects)) equal('One-off synthetic file removed', await stat(join(projects, folder, oneOffId + '.jsonl')).then(() => false).catch(() => true), true);
    }
    equal('No temporary runs', await readdir(join(state, 'tmp')), []);
    await home.part('plain'); const id = 'other-login'; await home.json(['subscriptions', 'create', '--family', subscriptionId, '--label', 'Other', '--id', id]);
    await home.part('success'); equal('Other account signed in', (await home.call(['subscriptions', 'sign-in', id])).status, 0);
    await invoke({ ...base, history, subscriptionId: id, input: { role: 'user', text: 'other subscription' } }, 'rebuilt', 'first_run'); await checkNative();
    check('Separate subscription map', !!await readFile(mapPath(id), 'utf8'), 'map under other account', id);
    const mapText = await readFile(mapPath(), 'utf8');
    for (const secret of ['history-user-secret', 'edited-user-secret', 'history-shell-output', 'replaced-reply-secret']) check('Map has no message or tool text', !mapText.includes(secret), 'identifiers and digests only', mapText);
  } };
