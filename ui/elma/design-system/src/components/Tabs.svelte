<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    label = 'View',
    items = ['Overview', 'Activity', 'Settings'],
    value = $bindable('Overview'),
    panel,
    onChange,
  }: {
    label?: string;
    items?: string[];
    value?: string;
    panel?: Snippet<[string]>;
    onChange?: (value: string) => void;
  } = $props();
  const id = $props.id();

  function select(item: string) {
    if (value === item) return;
    value = item;
    onChange?.(item);
  }

  function move(event: KeyboardEvent, i: number) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? items.length - 1
          : (i + (event.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
    select(items[next]);
    ((event.currentTarget as HTMLElement).parentElement?.children[next] as HTMLElement)?.focus();
  }
</script>

<div class="tabs" role={panel ? 'tablist' : 'group'} aria-label={label}>
  {#each items as item, i}<button
      type="button"
      id={panel ? `${id}-tab-${i}` : undefined}
      role={panel ? 'tab' : undefined}
      aria-controls={panel ? `${id}-panel-${i}` : undefined}
      aria-selected={panel ? item === value : undefined}
      aria-pressed={panel ? undefined : item === value}
      tabindex={item === value ? 0 : -1}
      onclick={() => select(item)}
      onkeydown={(e) => move(e, i)}>{item}</button
    >{/each}
</div>

{#if panel}
  {#each items as item, i}
    <div role="tabpanel" id={`${id}-panel-${i}`} aria-labelledby={`${id}-tab-${i}`}
      hidden={item !== value} tabindex="0">
      {#if item === value}{@render panel(item)}{/if}
    </div>
  {/each}
{/if}

<style>
  .tabs {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
  }
  button {
    min-height: var(--control-height);
    padding: 7px 12px;
    border: 1px solid transparent;
    background: transparent;
    color: var(--muted);
    border-radius: 9px;
  }
  button[aria-pressed='true'],
  button[aria-selected='true'] {
    background: var(--selected);
    border-color: var(--border);
    color: var(--text);
    font-weight: 600;
  }
</style>
