<script lang="ts">
  import type { Snippet } from 'svelte';
  import WorkspaceGlyph from '../components/WorkspaceGlyph.svelte';
  import IconButton from '../components/IconButton.svelte';
  import Button from '../components/Button.svelte';
  import type { WorkspaceTrunkSelector } from '../types';

  let {
    workspace, title, titleDetail, titleEditor, busy = false, content, lead, extras, windowControls,
    trunk, trunkSelector, onToggleNavigation,
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
    trunk?: string;
    trunkSelector?: WorkspaceTrunkSelector;
    onToggleNavigation: () => void;
  } = $props();
  const surfaceHeader = $derived(Boolean(title || lead || extras || trunk || trunkSelector));

  const trunkPickerId = $props.id();
  let trunkTrigger = $state<HTMLButtonElement>();
  let trunkPicker = $state<HTMLDivElement>();
  let loadingTrunks = $state(false);
  let selectingTrunk = $state<string>();
  let trunkChoices = $state<string[]>([]);
  let trunkProblem = $state('');
  let readGeneration = 0;

  function positionTrunkPicker() {
    if (!trunkTrigger || !trunkPicker) return;
    const anchor = trunkTrigger.getBoundingClientRect();
    const width = Math.max(0, Math.min(320, window.innerWidth - 16));
    const below = window.innerHeight - anchor.bottom - 12;
    const above = anchor.top - 12;
    const openAbove = below < 180 && above > below;
    trunkPicker.style.left = Math.max(8, Math.min(anchor.left, window.innerWidth - width - 8)) + 'px';
    trunkPicker.style.width = width + 'px';
    trunkPicker.style.top = openAbove ? 'auto' : anchor.bottom + 4 + 'px';
    trunkPicker.style.bottom = openAbove ? window.innerHeight - anchor.top + 4 + 'px' : 'auto';
    trunkPicker.style.maxHeight = Math.max(0, openAbove ? above : below) + 'px';
  }

  function trunkPickerToggling(event: ToggleEvent) {
    if (event.newState === 'open') {
      positionTrunkPicker();
      if (!selectingTrunk) void loadTrunks();
    } else {
      readGeneration += 1;
    }
  }

  function repositionOpenPicker() {
    if (trunkPicker?.matches(':popover-open')) positionTrunkPicker();
  }

  async function loadTrunks() {
    if (!trunkSelector) return;
    const generation = ++readGeneration;
    trunkChoices = [];
    trunkProblem = '';
    loadingTrunks = true;
    try {
      const choices = await trunkSelector.load();
      if (generation === readGeneration) trunkChoices = choices;
    } catch (error) {
      if (generation === readGeneration) {
        trunkProblem = error instanceof Error ? error.message : 'Could not read Trunks.';
      }
    } finally {
      if (generation === readGeneration) loadingTrunks = false;
    }
  }

  async function chooseTrunk(choice: string) {
    if (!trunkSelector || selectingTrunk || choice === trunk) return;
    selectingTrunk = choice;
    trunkProblem = '';
    try {
      await trunkSelector.select(choice);
      trunkPicker?.hidePopover();
    } catch (error) {
      trunkProblem = error instanceof Error ? error.message : 'Could not select the Trunk.';
    } finally {
      selectingTrunk = undefined;
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
    {#if trunk || trunkSelector}
      <div class="window-trunk" data-arbol-no-drag>
        {#if trunkSelector}
          <button type="button" class="trunk-trigger" popovertarget={trunkPickerId} bind:this={trunkTrigger}
            title="Choose a Trunk for this window">
            <span class="sr-only">Trunk </span>{trunk || 'Select Trunk'}<span aria-hidden="true">▾</span>
          </button>
          <div id={trunkPickerId} popover="auto" class="trunk-picker" role="group" aria-label="Choose a Trunk"
            bind:this={trunkPicker} onbeforetoggle={trunkPickerToggling}>
            {#if loadingTrunks}<p role="status">Loading Trunks…</p>{/if}
            {#if selectingTrunk}<p role="status">Selecting Trunk…</p>{/if}
            {#if trunkProblem}<p class="trunk-state" role="alert">{trunkProblem}</p>{/if}
            {#if trunkChoices.length}
              <ul class="clean trunk-choices">
                {#each trunkChoices as choice (choice)}
                  <li>
                    <button type="button" class="trunk-option" aria-current={choice === trunk ? 'true' : undefined}
                      disabled={choice === trunk} aria-disabled={selectingTrunk ? 'true' : undefined}
                      onclick={() => void chooseTrunk(choice)}>
                      <span>{choice}</span>
                      {#if choice === trunk}<span class="small muted">This window</span>{/if}
                    </button>
                  </li>
                {/each}
              </ul>
            {:else if !loadingTrunks}
              {#if trunkProblem}<Button label="Retry" onclick={() => void loadTrunks()} />
              {:else}<p class="muted">No compatible Trunks available.</p>{/if}
            {/if}
          </div>
        {:else}
          <span><span class="sr-only">Trunk </span>{trunk}</span>
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
  .window-trunk { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; overflow-wrap: anywhere; }
  .trunk-state { color: var(--warning); overflow-wrap: anywhere; }
  .trunk-trigger {
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
  .trunk-trigger:hover, .trunk-trigger:has(+ :popover-open) { border-color: var(--muted); }
  .trunk-picker {
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
  .trunk-picker p { margin: 6px 8px; }
  .trunk-choices { display: grid; gap: 2px; }
  .trunk-option {
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
  .trunk-option:disabled, .trunk-option[aria-disabled='true'] { color: var(--muted); }
  .trunk-option[aria-current], .trunk-option:hover:enabled { background: var(--selected); }
  @media (prefers-reduced-motion: reduce) {
    .workspace-mark.busy { animation: none; }
  }
  @media (max-width: 800px) {
    .chrome { gap: 8px; }
    .brand { min-width: 0; }
    .chrome > .muted, .chrome > .pill, .workspace-mark { display: none; }
  }
</style>
