<script lang="ts">
  let { label = 'Running', tone = 'neutral' }: { label?: string; tone?: string } = $props();
</script>

<span class="badge {tone}"
  ><span aria-hidden="true"
    >{tone === 'success'
      ? '✓'
      : tone === 'failure'
        ? '!'
        : tone === 'warning'
          ? '◷'
          : tone === 'working'
            ? '◌'
            : '•'}</span
  >{label}</span
>

<style>
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font: 12px var(--font-mono);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 4px 7px;
    color: var(--text);
    white-space: nowrap;
  }
  .success {
    color: var(--success);
  }
  .failure {
    color: var(--failure);
  }
  .warning {
    color: var(--warning);
  }
  .working {
    color: var(--link);
  }
</style>
