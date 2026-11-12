<script lang="ts">
  import type { Snippet } from 'svelte';
  let {
    text = 'Copy the entity reference',
    label = 'Copy reference',
    children,
  }: { text?: string; label?: string; children?: Snippet } = $props();
  const id = $props.id();
</script>

<span class="tooltip-wrap"
  >{#if children}{@render children()}{:else}<button aria-describedby={id}>{label}</button>{/if}<span
    {id}
    class="tooltip-text"
    role="tooltip">{text}</span
  ></span
>

<style>
  button {
    min-height: 36px;
    padding: 8px 12px;
    background: var(--inset);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 9px;
  }
</style>
