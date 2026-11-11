<script lang="ts">
  let {
    label = 'Weekly usage',
    value = 42,
    max = 100,
    unknown = false,
  }: { label?: string; value?: number; max?: number; unknown?: boolean } = $props();
  const id = $props.id();
</script>

<div class="stack" style="gap:8px">
  <div class="row spread">
    <label for={id}>{label}</label><small class="mono muted"
      >{unknown ? 'Unavailable' : Math.round((value / max) * 100) + '%'}</small
    >
  </div>
  {#if !unknown}<meter {id} min="0" {max} {value}>{value}/{max}</meter>{:else}<div
      class="unknown"
      aria-hidden="true"
    ></div>{/if}
</div>

<style>
  meter,
  .unknown {
    width: 100%;
    height: 10px;
    accent-color: var(--accent);
  }
  meter::-webkit-meter-bar {
    background: var(--canvas);
    border: 0;
  }
  meter::-webkit-meter-optimum-value {
    background: var(--accent);
  }
  .unknown {
    background: repeating-linear-gradient(120deg, var(--inset) 0 8px, var(--border) 8px 10px);
    border-radius: 5px;
  }
</style>
