<script lang="ts">
  let {
    label,
    icon = '＋',
    onclick,
    disabled = false,
  }: { label: string; icon?: string; onclick?: () => void; disabled?: boolean } = $props();
</script>

<button class="icon-button" aria-label={label} title={label} {onclick} {disabled}
  ><span aria-hidden="true">{icon}</span></button
>

<style>
  .icon-button {
    min-width: var(--control-height);
    min-height: var(--control-height);
    border: 1px solid var(--border);
    border-radius: 9px;
    background: var(--inset);
    color: var(--text);
    font-size: 18px;
  }
</style>
