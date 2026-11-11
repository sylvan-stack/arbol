<script lang="ts">
  import type { Snippet } from 'svelte';
  import WorkspaceGlyph from '../components/WorkspaceGlyph.svelte';
  import IconButton from '../components/IconButton.svelte';
  import Button from '../components/Button.svelte';
  import type { WorkspaceRoot, WorkspaceRootChoice, WorkspaceRootSelector } from '../types';

  let {
    workspace, title, titleDetail, titleEditor, busy = false, content, lead, extras, windowControls,
    root, rootSelector, onToggleNavigation,
  }: {
    workspace: string;
    title?: string;
    titleDetail?: Snippet;
    titleEditor?: Snippet;
    busy?: boolean;
    content?: Snippet;
    lead?: Snippet;
    extras?: Snippet;
    windowControls?: Snippet;
    root?: WorkspaceRoot;
    rootSelector?: WorkspaceRootSelector;
    onToggleNavigation: () => void;
  } = $props();
  const surfaceHeader = $derived(Boolean(title || lead || extras || root));

  const rootPickerId = $props.id();
  let rootTrigger = $state<HTMLButtonElement>();
  let rootPicker = $state<HTMLDivElement>();
  let loadingRoots = $state(false);
  let openingRoot = $state<string>();
  let rootChoices = $state<WorkspaceRootChoice[]>([]);
  let rootProblem = $state('');
  let readGeneration = 0;

  function positionRootPicker() {
    if (!rootTrigger || !rootPicker) return;
    const anchor = rootTrigger.getBoundingClientRect();
    const width = Math.max(0, Math.min(320, window.innerWidth - 16));
    const below = window.innerHeight - anchor.bottom - 12;
    const above = anchor.top - 12;
    const openAbove = below < 180 && above > below;
    rootPicker.style.left = Math.max(8, Math.min(anchor.left, window.innerWidth - width - 8)) + 'px';
    rootPicker.style.width = width + 'px';
    rootPicker.style.top = openAbove ? 'auto' : anchor.bottom + 4 + 'px';
    rootPicker.style.bottom = openAbove ? window.innerHeight - anchor.top + 4 + 'px' : 'auto';
    rootPicker.style.maxHeight = Math.max(0, openAbove ? above : below) + 'px';
  }

  function rootPickerToggling(event: ToggleEvent) {
    if (event.newState === 'open') {
      positionRootPicker();
      if (!openingRoot) void loadRoots();
    } else {
      readGeneration += 1;
    }
  }

  function repositionOpenPicker() {
    if (rootPicker?.matches(':popover-open')) positionRootPicker();
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
      rootPicker?.hidePopover();
    } catch (error) {
      rootProblem = error instanceof Error ? error.message : 'Could not open the selected Root.';
    } finally {
      openingRoot = undefined;
    }
  }
</script>

<svelte:window onresize={repositionOpenPicker} onscroll={repositionOpenPicker} />
<header class="chrome" class:surface-header={surfaceHeader} data-arbol-window-header data-arbol-window-drag
  data-arbol-native-controls={windowControls ? '' : undefined}>
  {#if windowControls}<div class="window-controls" data-arbol-no-drag>{@render windowControls()}</div>{/if}
  {#if content}{@render content()}
  {:else if surfaceHeader}
    <div class="header-lead">
      {#if lead}{@render lead()}
      {:else}
        <span class="workspace-mark" class:busy><WorkspaceGlyph {workspace} size={21} /></span>
        <div class="title-area">
          <h1 class:editing={!!titleEditor}>
            {title ?? workspace}{#if titleDetail}{' · '}{@render titleDetail()}{/if}
          </h1>
          {@render titleEditor?.()}
        </div>
      {/if}
    </div>
    {#if root}
      <div class="window-root" data-arbol-no-drag>
        {#if rootSelector && root.root}
          <button type="button" class="root-trigger" popovertarget={rootPickerId} bind:this={rootTrigger}
            title="Open this UI in another Root">
            <span class="sr-only">Root </span>{root.name}<span aria-hidden="true">▾</span>
          </button>
          <div id={rootPickerId} popover="auto" class="root-picker" role="group" aria-label="Open in Root"
            bind:this={rootPicker} onbeforetoggle={rootPickerToggling}>
            {#if loadingRoots}<p role="status">Loading Roots…</p>{/if}
            {#if openingRoot}<p role="status">Opening Root…</p>{/if}
            {#if rootProblem}<p class="root-state" role="alert">{rootProblem}</p>{/if}
            {#if rootChoices.length}
              <ul class="clean root-choices">
                {#each rootChoices as choice (choice.root)}
                  <li>
                    <button type="button" class="root-option" aria-current={choice.root === root.root ? 'true' : undefined}
                      disabled={choice.root === root.root || !!choice.unavailable} aria-disabled={openingRoot ? 'true' : undefined}
                      onclick={() => void chooseRoot(choice)}>
                      <span>{choice.name}</span>
                      {#if choice.root === root.root}<span class="small muted">This window</span>{/if}
                      {#if choice.status !== 'working'}<span class="small muted">{choice.status}</span>{/if}
                      {#if choice.unavailable}<span class="small root-state">{choice.unavailable}</span>{/if}
                    </button>
                  </li>
                {/each}
              </ul>
            {:else if !loadingRoots}
              {#if rootProblem}<Button label="Retry" onclick={() => void loadRoots()} />
              {:else}<p class="muted">No Roots available.</p>{/if}
            {/if}
          </div>
        {:else}
          <span><span class="sr-only">Root </span>{root.name}</span>
        {/if}
        {#if root.status !== 'working'}
          <span class="root-state">{root.status}{root.failed ? ': ' + root.failed.reason : ''}</span>
        {/if}
      </div>
    {/if}
    {#if extras}{@render extras()}{/if}
  {:else}
    <div class="brand"><WorkspaceGlyph {workspace} size={24} /><strong>{workspace}</strong></div>
    <span class="small muted">Arbol / Design system</span>
    <div class="grow"></div>
  {/if}
  <IconButton label="Toggle navigation" icon="☰" onclick={onToggleNavigation} />
  {#if !content && !surfaceHeader}<span class="pill">Sample workspace</span>{/if}
</header>

<style>
  .chrome {
    position: relative;
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
  .chrome.surface-header {
    min-height: 40px;
    padding: 4px 12px;
    gap: 8px;
    flex-wrap: wrap;
    font: calc(13.5px * var(--font-scale))/1.5 var(--font-ui);
  }
  .chrome[data-arbol-native-controls] { padding-inline-start: 96px; }
  .window-controls {
    position: absolute;
    inset: 0 auto auto 12px;
    height: 40px;
    display: flex;
    align-items: center;
  }
  .header-lead { display: flex; align-items: center; gap: 8px; flex: 1 1 10rem; min-width: 0; }
  .workspace-mark { display: flex; flex-shrink: 0; color: var(--accent); }
  .workspace-mark.busy { animation: breathe 1.6s ease-in-out infinite; }
  @keyframes breathe { 50% { opacity: .4; transform: rotate(-12deg); } }
  .title-area { min-width: 0; flex: 1; }
  .title-area h1 {
    margin: 0;
    font: 600 calc(13.5px * var(--font-scale))/1.4 var(--font-ui);
    overflow-wrap: anywhere;
  }
  .title-area h1.editing { font-size: 12px; color: var(--muted); }
  .window-root { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; overflow-wrap: anywhere; }
  .root-state { color: var(--warning); overflow-wrap: anywhere; }
  .root-trigger {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 30px;
    max-width: min(100%, 18rem);
    padding: 3px 9px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--inset);
    color: var(--text);
    font-weight: 600;
    text-align: start;
  }
  .root-trigger:hover, .root-trigger:has(+ :popover-open) { border-color: var(--muted); }
  .root-picker {
    position: fixed;
    inset: auto;
    box-sizing: border-box;
    margin: 0;
    padding: 6px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--panel);
    color: var(--text);
    box-shadow: var(--shadow);
    overflow: auto;
    overflow-wrap: anywhere;
  }
  .root-picker p { margin: 6px 8px; }
  .root-choices { display: grid; gap: 2px; }
  .root-option {
    display: grid;
    gap: 2px;
    width: 100%;
    min-height: 34px;
    padding: 5px 8px;
    border: 0;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text);
    text-align: start;
    overflow-wrap: anywhere;
  }
  .root-option:disabled, .root-option[aria-disabled='true'] { color: var(--muted); }
  .root-option[aria-current], .root-option:hover:enabled { background: var(--selected); }
  @media (prefers-reduced-motion: reduce) {
    .workspace-mark.busy { animation: none; }
  }
  @media (max-width: 800px) {
    .chrome { gap: 8px; }
    .brand { min-width: 0; }
    .chrome > .muted, .chrome > .pill, .workspace-mark { display: none; }
  }
</style>
