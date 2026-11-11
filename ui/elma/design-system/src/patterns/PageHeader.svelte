<script lang="ts">
  import Button from '../components/Button.svelte';
  let {
    title = 'Repositories',
    description = 'Code, knowledge and indexing in one place.',
    count,
    action = '',
    onaction,
  }: {
    title?: string;
    description?: string;
    count?: number;
    action?: string;
    onaction?: () => void;
  } = $props();
</script>

<header class="row spread">
  <div class="stack" style="gap:8px">
    <div class="row">
      <h1>{title}</h1>
      {#if count !== undefined}<span class="pill">{count}</span>{/if}
    </div>
    {#if description}<p class="muted measure">{description}</p>{/if}
  </div>
  {#if action}<Button label={action} tone="primary" onclick={onaction} />{/if}
</header>
