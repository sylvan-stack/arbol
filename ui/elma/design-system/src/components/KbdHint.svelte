<script lang="ts">
  let { keys = ['⌘', '↵'], label = 'Send message' }: { keys?: string[]; label?: string } = $props();
</script>

<span class="row small muted"
  >{#each keys as key}<kbd>{key}</kbd>{/each}{label}</span
>

<style>
  kbd {
    border: 1px solid var(--border);
    border-bottom-width: 2px;
    border-radius: 5px;
    padding: 2px 6px;
    background: var(--inset);
  }
</style>
