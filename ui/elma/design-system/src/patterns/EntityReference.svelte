<script lang="ts">
  import { KINDS, type EntityKind } from '../entities';
  let {
    title = 'Design System',
    kind = 'artifact',
    onclick,
  }: { title?: string; kind?: string; onclick?: () => void } = $props();
  let meta = $derived(KINDS[kind as EntityKind] || { glyph: '◫', label: 'Entity', hue: 42 });
</script>

<button class="reference" {onclick} title={'Open ' + title}
  ><span aria-hidden="true" style:color={'oklch(0.75 0.09 ' + meta.hue + ')'}>{meta.glyph}</span
  ><span class="sr-only">{meta.label}: </span>{title}</button
>

<style>
  .reference {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 100%;
    background: var(--inset);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 9px;
    min-height: 32px;
    text-align: left;
    overflow-wrap: anywhere;
    font-size: 12px;
  }
</style>
