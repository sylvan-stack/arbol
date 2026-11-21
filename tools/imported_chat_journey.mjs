/** SIM-17 browser half of the private packaged Backend and Elma qualification. */
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const [playwright, target] = process.argv.slice(2);
const destination = new URL(target);
assert.equal(destination.protocol, 'http:');
assert.equal(destination.hostname, '127.0.0.1');
assert(destination.port && destination.searchParams.has('token'));

const { chromium } = await import(pathToFileURL(playwright).href);
const ordinary = '00000000-0000-0000-0000-00000000000a';
const imported = '00000000-0000-0000-0000-00000000000b';
const race = '00000000-0000-0000-0000-00000000000c';
const raceTitle = 'Fictional race target';
const draft = 'Fictional ordinary Draft preserved across archive playback.';
const name = (value) => ({ name: value, exact: true });
const words = (value) => ({ name: value });

const browser = await chromium.launch({ headless: true });
const terminal = createInterface({ input: process.stdin, terminal: false });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 840 } });
  page.setDefaultTimeout(12_000);
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const archiveRequests = new Set();
  const draftRequests = [];
  let raceArmed = false;
  let observedUnarchive = false;
  let held;
  let markReceived;
  let firstPageHeld;
  const canonicalMark = new Promise((resolve) => { markReceived = resolve; });
  const heldArchive = new Promise((resolve) => { firstPageHeld = resolve; });

  // Hold an actual reply from the packaged Bridge. Forward the real mark publication
  // and all later replies in wire order without editing their fields.
  await page.routeWebSocket('**/bridge', (client) => {
    const server = client.connectToServer();
    client.onMessage((message) => {
      const value = JSON.parse(message.toString());
      if (value.method === 'chats.page' && value.params.archived === true) archiveRequests.add(value.id);
      if (value.topic === 'draft' || value.method === 'draft.save') draftRequests.push(value.params);
      server.send(message);
    });
    server.onMessage((message) => {
      const value = JSON.parse(message.toString());
      if (value.type === 'event' && value.event.kind === 'changed'
          && value.event.chats?.some((chat) => chat.chat === race && chat.archived !== true)) {
        observedUnarchive = true;
        markReceived();
      }
      if (value.type === 'reply' && archiveRequests.delete(value.id) && raceArmed && !held
          && value.result?.chats.some((chat) => chat.chat === race)) {
        held = { client, message, id: value.id };
        firstPageHeld();
        return;
      }
      client.send(message);
    });
  });

  // Record receipt at the actual browser socket to make the post-release assertion
  // independent of host-to-browser scheduling.
  await page.addInitScript(() => {
    const NativeWebSocket = window.WebSocket;
    window.sim17SeenReplies = new Set();
    window.WebSocket = class ObservedWebSocket extends NativeWebSocket {
      constructor(...args) {
        super(...args);
        this.addEventListener('message', (event) => {
          const value = JSON.parse(event.data);
          if (value.type === 'reply') window.sim17SeenReplies.add(value.id);
        });
      }
    };
  });

  const navigation = page.getByRole('navigation', name('Elma navigation'));
  const archive = navigation.getByRole('button', name('Archived chats'));
  const dialog = page.getByRole('dialog', name('Archived chats'));
  const composer = page.getByLabel('Message composer', { exact: true });
  await page.goto(destination.href);
  await page.getByLabel('Message', { exact: true }).waitFor();
  assert.equal(await navigation.getByText('Imported from Codex', { exact: true }).count(), 0);
  await archive.click();
  const picked = dialog.getByRole('button', words(/Fictional archive example/));
  assert.match(await picked.innerText(), /Imported from Codex/);
  await picked.click();
  await dialog.waitFor({ state: 'hidden' });
  await navigation.getByText('Imported from Codex', { exact: true }).waitFor();
  await page.getByText('Fictional saved prompt', { exact: true }).waitFor();
  await page.getByText('Fictional saved response', { exact: true }).waitFor();
  await page.getByText('fixture-parent', { exact: true }).waitFor();
  await page.getByText(/codex.*fictional-saved-model.*high/).waitFor();
  assert.equal(await page.getByText('fixture-child', { exact: true }).count(), 0);
  assert.equal(await composer.count(), 0);
  assert.equal(await page.getByRole('button', words(/^(Retry|Continue)$/)).count(), 0);

  await navigation.getByRole('button', words(/Quick actions/)).click();
  await page.getByRole('dialog', name('Quick actions')).getByRole('button', words(/Unarchive/)).click();
  await page.getByText('Chat unarchived', { exact: true }).waitFor();
  await navigation.getByText('Imported from Codex', { exact: true }).waitFor();
  assert.equal(await composer.count(), 0);

  await page.keyboard.press('Control+Shift+Meta+c');
  const latest = page.getByRole('dialog', name('Latest chats'));
  await latest.getByRole('button', words(/Fictional ordinary chat/)).click();
  await page.getByText('Fictional ordinary prompt', { exact: true }).waitFor();
  const message = page.getByLabel('Message', { exact: true });
  await message.waitFor();
  assert.equal(await message.inputValue(), draft);
  assert(draftRequests.some((params) => params.chat === ordinary));

  const control = once(terminal, 'line');
  raceArmed = true;
  await archive.click();
  await heldArchive;
  assert.equal(await dialog.getByRole('button', words(new RegExp(raceTitle))).count(), 0);
  console.log('held archive reply');
  const [action] = await control;
  assert.equal(action, 'unarchived');
  await canonicalMark;
  assert(observedUnarchive);
  await dialog.getByText('No archived chats.', { exact: true }).waitFor();
  held.client.send(held.message);
  await page.waitForFunction((id) => window.sim17SeenReplies.has(id), held.id);
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await dialog.getByRole('button', words(new RegExp(raceTitle))).count(), 0);
  await dialog.getByText('No archived chats.', { exact: true }).waitFor();
  assert(!draftRequests.some((params) => params.chat === imported || params.chat === race));
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ archivedPlayback: 'passed', unarchive: 'passed', ordinaryDraft: 'passed', race: 'passed' }));
} finally {
  terminal.close();
  await browser.close();
}
