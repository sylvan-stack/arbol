<script module lang="ts">
  export const phaseOrder = ['intake', 'planning', 'execution', 'finalization'] as const;
  export type PhaseName = (typeof phaseOrder)[number];
  export const phaseLabel = (phase: PhaseName) => phase[0].toUpperCase() + phase.slice(1);
</script>

<script lang="ts">
  import { isLosslessNumber } from 'lossless-json';
  import { stringifyJson } from '../json';

  type Path = (string | number)[];
  let { data, phases = [], phase, onphase, onclose, busy = false, problem = '', onretry }: {
    data: Record<string, unknown> | null;
    phases?: readonly PhaseName[];
    phase?: PhaseName;
    onphase?: (phase: PhaseName) => void;
    onclose: () => void;
    busy?: boolean;
    problem?: string;
    onretry?: () => void;
  } = $props();
  let dialog = $state<HTMLDialogElement>();

  function object(value: unknown): Record<string, unknown> | undefined {
    return value !== null && typeof value === 'object' && !Array.isArray(value) && !isLosslessNumber(value)
      ? value as Record<string, unknown> : undefined;
  }

  function preview(text: string): string {
    if (text.length <= 1000) return text;
    let characters = 0;
    let offset = 0;
    for (const character of text) {
      if (characters === 1000) return text.slice(0, offset) + '…';
      characters++;
      offset += character.length;
    }
    return text;
  }

  function textPayload(path: Path): boolean {
    const [section, key, index, member, field, item, property] = path;
    if (section !== 'privatePhase' || key !== 'commands') return true;
    const commands = object(data?.privatePhase)?.commands;
    const command = Array.isArray(commands) && typeof index === 'number' ? object(commands[index]) : undefined;
    if (command?.kind === 'subprocess') return member === 'input';
    if (command?.kind !== 'provider' || member !== 'parameters') return false;
    if (field === 'systemPrompt' || field === 'cueContext') return path.length === 5;
    if (field === 'input') return item === 'text' && path.length === 6;
    const history = object(command.parameters)?.history;
    return field === 'history' && Array.isArray(history) && typeof item === 'number'
      && object(history[item])?.type === 'message' && property === 'text' && path.length === 7;
  }

  function display(value: unknown, path: Path): string {
    return stringifyJson(typeof value === 'string' && textPayload(path) ? preview(value) : value ?? null);
  }

  $effect(() => { if (dialog && !dialog.open) dialog.showModal(); });
</script>

{#snippet jsonKey(name: string | number)}
  <span class="json-key">{JSON.stringify(name)}</span>{': '}
{/snippet}

{#snippet jsonNode(name: string | number, value: unknown, path: Path)}
  {#if Array.isArray(value) || object(value)}
    {@const entries = Object.entries(value as object) as [string, unknown][]}
    {@const array = Array.isArray(value)}
    {@const opening = array ? '[' : '{'}
    {@const closing = array ? ']' : '}'}
    {#if entries.length}
      <details class="json-branch" open={path.length === 1}>
        <summary>
          {@render jsonKey(name)}{opening}<span class="json-fold">…{closing}
            <span class="json-count">({entries.length})</span>
          </span>
        </summary>
        <div class="json-children">
          {#each entries as [key, child] (key)}
            {@const childName = array ? Number(key) : key}
            {@render jsonNode(childName, child, [...path, childName])}
          {/each}
        </div>
        <div>{closing}</div>
      </details>
    {:else}
      <div>{@render jsonKey(name)}{opening}{closing}</div>
    {/if}
  {:else}
    <div>{@render jsonKey(name)}{display(value, path)}</div>
  {/if}
{/snippet}

<dialog class="inspector" aria-label="Exchange Details" bind:this={dialog} {onclose}>
  <button type="button" class="inspector-close" aria-label="Close Exchange Details" onclick={() => dialog?.close()}>×</button>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex (Long data stays keyboard scrollable.) -->
  <div class="json-data" tabindex="0" role="region" aria-label="Exchange and phase JSON">
    {#if onphase && phases.length}
      <select aria-label="Exchange phase" value={phase} onchange={(event) => onphase?.(event.currentTarget.value as PhaseName)}>
        {#each phases as name (name)}
          <option value={name}>{phaseLabel(name)}</option>
        {/each}
      </select>
    {/if}
    {#if problem}
      <p role="alert">{problem} {#if onretry}<button type="button" onclick={onretry}>Retry</button>{/if}</p>
    {:else if busy && !data}
      <p role="status">Loading phase details…</p>
    {:else if !data}
      <p>No phase details recorded.</p>
    {/if}
    {#if data}
      {#each Object.entries(data) as [key, value] (key)}
        {@render jsonNode(key, value, [key])}
      {/each}
    {/if}
  </div>
</dialog>

<style>
  .inspector {
    width: min(560px, calc(100vw - 24px));
    max-height: calc(100dvh - 24px);
    margin: auto;
    padding: 0;
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow);
  }
  .inspector::backdrop { background: #08060555; }
  .inspector-close {
    position: absolute;
    z-index: 1;
    inset-block-start: 4px;
    inset-inline-end: 4px;
    width: 26px;
    height: 26px;
    padding: 0;
    background: var(--panel);
    color: var(--muted);
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
  }
  .inspector-close:hover { border-color: var(--border); color: var(--text); }
  .json-data {
    max-height: min(70dvh, calc(100dvh - 26px));
    padding: 7px 32px 7px 9px;
    overflow: auto;
    overflow-wrap: anywhere;
    font: calc(12px * var(--font-scale))/1.55 var(--font-mono);
  }
  .json-data:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
  .json-data > p { margin: 0; }
  .json-data select { margin: 0 0 3px; font: inherit; color: inherit; background: var(--panel); }
  .json-branch summary { cursor: pointer; }
  .json-children { margin-inline-start: 5px; padding-inline-start: 10px; border-inline-start: 1px solid var(--border); }
  .json-branch[open] > summary > .json-fold { display: none; }
  .json-key { color: var(--link); }
  .json-count { color: var(--muted); font-size: 0.9em; }
</style>
