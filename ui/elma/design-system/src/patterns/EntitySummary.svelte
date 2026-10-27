<script lang="ts">
  import { KINDS, type EntityKind } from '../entities';
  import Badge from '../components/Badge.svelte';
  let {
    title = 'Restore shared interactions',
    subtitle = 'Arbol · Design system',
    kind = 'graft',
    status = 'Planned',
    onclick,
  }: {
    title?: string;
    subtitle?: string;
    kind?: string;
    status?: string;
    onclick?: () => void;
  } = $props();
  const meta = $derived(KINDS[kind as EntityKind] || KINDS.artifact);
</script>

<div class="row">
  <span class="icon" aria-hidden="true">{meta.glyph}</span>
  <div class="grow">
    <button class="link-button" {onclick}>{title}</button>
    <p class="small muted">{subtitle}</p>
  </div>
  {#if status}<Badge
      label={status}
      tone={status === 'Failed'
        ? 'failure'
        : status === 'Complete' || status === 'Done'
          ? 'success'
          : status === 'Running'
            ? 'working'
            : 'neutral'}
    />{/if}
</div>
