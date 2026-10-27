<script lang="ts">
  let {
    label,
    onkeydown,
    value = $bindable(''),
    hint = '',
    rows = 4,
    placeholder = '',
  }: {
    label: string;
    onkeydown?: (event: KeyboardEvent) => void;
    value?: string;
    hint?: string;
    rows?: number;
    placeholder?: string;
  } = $props();
  const id = $props.id();
</script>

<div class="stack" style="gap:6px">
  <label for={id}><strong>{label}</strong></label><textarea
    {id}
    {onkeydown}
    {rows}
    {placeholder}
    bind:value
    aria-describedby={hint ? id + '-hint' : undefined}></textarea>{#if hint}<small
      id={id + '-hint'}
      class="muted">{hint}</small
    >{/if}
</div>

<style>
  textarea {
    width: 100%;
    resize: vertical;
    background: var(--canvas);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 9px;
    padding: 12px;
  }
</style>
