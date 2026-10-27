<script lang="ts">
  import type { Snippet } from 'svelte';
  let {
    label = '',
    children,
    tone = 'secondary',
    disabled = false,
    busy = false,
    type = 'button',
    onclick,
    title,
  }: {
    label?: string;
    children?: Snippet;
    tone?: 'primary' | 'secondary' | 'ghost' | 'danger';
    disabled?: boolean;
    busy?: boolean;
    type?: 'button' | 'submit' | 'reset';
    onclick?: (event: MouseEvent) => void;
    title?: string;
  } = $props();
</script>

<button class="button {tone}" {type} disabled={disabled || busy} aria-busy={busy} {onclick} {title}
  >{#if busy}<span aria-hidden="true">◌</span
    >{/if}{#if children}{@render children()}{:else}{label}{/if}</button
>

<style>
  .button {
    min-height: var(--control-height);
    padding: 7px 13px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--inset);
    color: var(--text);
    font-weight: 600;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    transition: background var(--motion-fast);
    white-space: normal;
  }
  .button:hover:enabled {
    border-color: var(--muted);
  }
  .primary {
    background: var(--accent);
    color: var(--action-ink);
    border-color: transparent;
  }
  .ghost {
    background: transparent;
  }
  .danger {
    background: var(--failure);
    color: var(--canvas);
    border-color: transparent;
  }
  .button:disabled {
    color: var(--disabled);
    background: var(--inset);
  }
</style>
