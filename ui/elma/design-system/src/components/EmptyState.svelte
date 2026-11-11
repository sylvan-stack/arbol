<script lang="ts">
  import Button from './Button.svelte';
  let {
    title = 'No items yet',
    description = 'Create the first item to get started.',
    action = 'Create item',
    onclick,
  }: { title?: string; description?: string; action?: string; onclick?: () => void } = $props();
</script>

<div class="empty">
  <span class="icon" aria-hidden="true">◫</span>
  <h3>{title}</h3>
  <p class="muted measure">{description}</p>
  {#if action}<Button label={action} {onclick} />{/if}
</div>
