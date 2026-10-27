<script lang="ts">
  let {
    label,
    onkeydown,
    value = $bindable(''),
    hint = '',
    error = '',
    required = false,
    placeholder = '',
    type = 'text',
    disabled = false,
  }: {
    label: string;
    onkeydown?: (event: KeyboardEvent) => void;
    value?: string;
    hint?: string;
    error?: string;
    required?: boolean;
    placeholder?: string;
    type?: string;
    disabled?: boolean;
  } = $props();
  const id = $props.id();
</script>

<div class="field">
  <label for={id}
    >{label}{#if required}<span class="muted small"> · Required</span>{/if}</label
  ><input
    {id}
    {onkeydown}
    {type}
    bind:value
    {placeholder}
    {required}
    {disabled}
    aria-invalid={!!error}
    aria-describedby={hint || error ? id + '-help' : undefined}
  />{#if hint || error}<small id={id + '-help'} class:error>{error || hint}</small>{/if}
</div>

<style>
  .field {
    display: grid;
    gap: 6px;
  }
  label {
    font-weight: 600;
  }
  input {
    width: 100%;
    min-height: var(--control-height);
    background: var(--canvas);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 9px;
    padding: 8px 10px;
  }
  input[aria-invalid='true'] {
    border-color: var(--failure);
  }
  small {
    color: var(--muted);
  }
  small.error {
    color: var(--failure);
  }
</style>
