<script lang="ts">
  import type { Snippet } from 'svelte';
  import WorkspaceGlyph from '../components/WorkspaceGlyph.svelte';
  import IconButton from '../components/IconButton.svelte';
  import Button from '../components/Button.svelte';
  import Modal from './Modal.svelte';
  import type { WorkspaceRoot, WorkspaceRootChoice, WorkspaceRootSelector } from '../types';
  let {
    workspace = 'Seqoya',
    current = 'Dashboard',
    destinations = [
      'Dashboard',
      'Intelligence Providers',
      'Brain Recipes',
      'Organizations',
      'Repos',
      'Quick Text',
      'Living Topics',
      'Blueprints',
      'Stewardship',
      'Artifacts',
      'Monitoring',
    ],
    children,
    headerContent, headerLead, headerExtras, root, rootSelector, navigation, status, fitted = false, elma = false,
    onnavigate = () => {},
  }: {
    workspace?: string;
    current?: string;
    destinations?: string[];
    children?: Snippet;
    headerContent?: Snippet;
    headerLead?: Snippet;
    headerExtras?: Snippet;
    root?: WorkspaceRoot;
    rootSelector?: WorkspaceRootSelector;
    navigation?: Snippet; status?: Snippet; fitted?: boolean; elma?: boolean;
    onnavigate?: (page: string) => void;
  } = $props();
  let expanded = $state(false);
  let pickerOpen = $state(false);
  let loadingRoots = $state(false);
  let openingRoot = $state<string>();
  let rootChoices = $state<WorkspaceRootChoice[]>([]);
  let rootProblem = $state('');
  let readGeneration = 0;

  function closeRootSelector() {
    if (openingRoot) return;
    pickerOpen = false;
    readGeneration += 1;
  }

  async function loadRoots() {
    if (!rootSelector) return;
    const generation = ++readGeneration;
    rootChoices = [];
    rootProblem = '';
    loadingRoots = true;
    try {
      const choices = await rootSelector.load();
      if (generation === readGeneration) rootChoices = choices;
    } catch (error) {
      if (generation === readGeneration) {
        rootProblem = error instanceof Error ? error.message : 'Could not read Roots.';
      }
    } finally {
      if (generation === readGeneration) loadingRoots = false;
    }
  }

  async function chooseRoot(choice: WorkspaceRootChoice) {
    if (!rootSelector || openingRoot || choice.root === root?.root || choice.unavailable) return;
    openingRoot = choice.root;
    rootProblem = '';
    try {
      await rootSelector.open(choice.root);
      pickerOpen = false;
    } catch (error) {
      rootProblem = error instanceof Error ? error.message : 'Could not open the selected Root.';
    } finally {
      openingRoot = undefined;
    }
  }
</script>

<div class="workspace" class:fitted class:elma>
  <header class="chrome" class:with-slots={!!(headerLead || headerExtras || root)}>
    {#if headerContent}{@render headerContent()}
      <IconButton label="Toggle navigation" icon="☰" onclick={() => (expanded = !expanded)} />
    {:else if headerLead || headerExtras || root}
      <div class="header-lead">
        {#if headerLead}{@render headerLead()}
        {:else}<WorkspaceGlyph {workspace} size={24} /><strong>{workspace}</strong>{/if}
      </div>
      {#if root}
        <div class="window-root">
          {#if rootSelector && root.root}
            <Button title="Open this UI in another Root" onclick={() => { pickerOpen = true; void loadRoots(); }}>
              <span class="sr-only">Root </span>{root.name}<span aria-hidden="true">▾</span>
            </Button>
          {:else}
            <span><span class="sr-only">Root </span>{root.name}</span>
          {/if}
          {#if root.status !== 'working'}
            <span class="root-state">{root.status}{root.failed ? ': ' + root.failed.reason : ''}</span>
          {/if}
        </div>
      {/if}
      {#if headerExtras}{@render headerExtras()}{/if}
      <IconButton label="Toggle navigation" icon="☰" onclick={() => (expanded = !expanded)} />
    {:else}
    <div class="brand"><WorkspaceGlyph {workspace} size={24} /><strong>{workspace}</strong></div>
    <span class="small muted">Arbol / Design system</span>
    <div class="grow"></div>
    <IconButton label="Toggle navigation" icon="☰" onclick={() => (expanded = !expanded)} /><span
      class="pill">Sample workspace</span
    >
    {/if}
  </header>
  <div class="layout" class:expanded>
    <nav aria-label={workspace + ' navigation'}>
      {#if navigation}{@render navigation()}{:else}
      <p class="eyebrow">Workspace</p>
      {#each destinations as destination}<button
          aria-current={current === destination ? 'page' : undefined}
          onclick={() => {
            onnavigate(destination);
            expanded = false;
          }}>{destination}</button
        >{/each}
      <div class="nav-foot">
        <span class="small muted">Connected knowledge.<br />Thoughtful work.</span>
      </div>
      {/if}
    </nav>
    <main>
      {#if children}{@render children()}{:else}<div class="page-content">
          <h1>{current}</h1>
          <p class="muted">
            The shared shell provides navigation, main content and persistent status.
          </p>
        </div>{/if}
    </main>
  </div>
  <footer>{#if status}{@render status()}{:else}<span>● Fixture mode</span><span>Local sample data · No native services</span>{/if}</footer>
  {#if pickerOpen}
    <Modal title="Open in Root" width={460} onclose={closeRootSelector}>
      {#if loadingRoots}<p role="status">Loading Roots…</p>{/if}
      {#if rootProblem}<p class="root-state" role="alert">{rootProblem}</p>{/if}
      {#if rootChoices.length}
        <ul class="clean root-choices">
          {#each rootChoices as choice (choice.root)}
            <li class="root-choice">
              <Button
                label={choice.name}
                busy={openingRoot === choice.root}
                disabled={choice.root === root?.root || !!choice.unavailable || !!openingRoot}
                onclick={() => void chooseRoot(choice)}
              />
              {#if choice.root === root?.root}<span class="small muted">This window</span>{/if}
              {#if choice.status !== 'working'}<span class="small muted">{choice.status}</span>{/if}
              {#if choice.unavailable}<span class="small root-state">{choice.unavailable}</span>{/if}
            </li>
          {/each}
        </ul>
      {:else if !loadingRoots}
        {#if rootProblem}<Button label="Retry" onclick={() => void loadRoots()} />
        {:else}<p class="muted">No Roots available.</p>{/if}
      {/if}
    </Modal>
  {/if}
</div>

<style>
  .fitted { height: 100dvh; min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; border: 0; border-radius: 0; }
  .fitted .layout { min-height: 0; }
  .fitted main { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
  .fitted nav { min-height: 0; overflow: auto; }
  .elma .chrome { min-height: 40px; padding: 4px 12px; gap: 8px; flex-wrap: wrap; }
  .elma nav { padding: 12px; }
  .elma footer { min-height: 40px; padding: 6px 12px; }
  .elma .layout { grid-template-columns: 248px minmax(0, 1fr); }
  @media (max-width: 800px) { .elma .layout { grid-template-columns: 1fr; } }

  .workspace {
    min-height: 720px;
    background: var(--canvas);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }
  .chrome {
    min-height: 48px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 8px 20px;
    background: var(--panel);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 208px;
  }
  .chrome.with-slots { gap: 8px; flex-wrap: wrap; }
  .header-lead { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; }
  .window-root { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; overflow-wrap: anywhere; }
  .root-state { color: var(--warning); overflow-wrap: anywhere; }
  .root-choices { display: grid; gap: 12px; }
  .root-choice { display: grid; justify-items: start; gap: 4px; overflow-wrap: anywhere; }
  .layout {
    display: grid;
    grid-template-columns: 248px minmax(0, 1fr);
    min-height: 624px;
  }
  nav {
    padding: 24px 12px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    background: var(--panel);
    border-right: 1px solid var(--border);
  }
  nav p {
    padding: 0 12px 12px;
  }
  nav button {
    color: var(--muted);
    background: none;
    border: 1px solid transparent;
    border-radius: 9px;
    text-align: left;
    padding: 8px 12px;
    min-height: 36px;
  }
  nav button[aria-current='page'] {
    background: var(--selected);
    border-color: var(--border);
    color: var(--text);
    font-weight: 600;
  }
  .nav-foot {
    margin-top: auto;
    padding: 32px 12px 0;
  }
  main {
    min-width: 0;
  }
  footer {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    min-height: 40px;
    padding: 10px 20px;
    border-top: 1px solid var(--border);
    font: 11px var(--font-mono);
    color: var(--muted);
  }
  @media (max-width: 1100px) {
    .layout {
      grid-template-columns: 208px minmax(0, 1fr);
    }
  }
  @media (max-width: 800px) {
    .layout {
      grid-template-columns: 1fr;
    }
    nav {
      display: none;
    }
    .expanded nav {
      display: flex;
    }
    .chrome {
      gap: 8px;
    }
    .brand {
      min-width: 0;
    }
    .chrome > .muted,
    .chrome > .pill {
      display: none;
    }
    .workspace {
      border-radius: 0;
    }
    .expanded main {
      display: none;
    }
  }
</style>
