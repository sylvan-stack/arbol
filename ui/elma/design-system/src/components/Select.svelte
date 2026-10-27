<script lang="ts">
  let {
    label,
    options = ['All', 'Active', 'Archived'],
    value = $bindable('All'),
  }: { label: string; options?: string[]; value?: string } = $props();
  const id = $props.id();
</script>

<label for={id} class="stack" style="gap:6px"
  ><span class="small muted">{label}</span><select {id} bind:value
    >{#each options as option}<option>{option}</option>{/each}</select
  ></label
>

<style>
  select {
    min-height: var(--control-height);
    background: var(--canvas);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 9px;
    padding: 6px 30px 6px 10px;
    max-width: 100%;
  }
</style>
