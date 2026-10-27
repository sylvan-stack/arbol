<script lang="ts">
  import { onMount } from 'svelte';
  import type { Snippet } from 'svelte';
  import IconButton from '../components/IconButton.svelte';
  let {
    title = 'Dialog',
    description = '',
    children,
    footer,
    onclose = () => {},
    width = 640,
    initialFocus = 'input,textarea,select',
  }: {
    title?: string;
    description?: string;
    children?: Snippet;
    footer?: Snippet;
    onclose?: () => void;
    width?: number;
    initialFocus?: string;
  } = $props();
  let dialog: HTMLDialogElement;
  const id = $props.id();
  onMount(() => {
    const previous = document.activeElement as HTMLElement;
    dialog.showModal();
    dialog.querySelector<HTMLElement>(initialFocus)?.focus();
    return () => {
      dialog?.close();
      if (previous?.isConnected) previous.focus();
    };
  });
  function containFocus(event: KeyboardEvent) {
    if (event.key !== 'Tab') return;
    const dialogs = [...document.querySelectorAll('dialog[open]')];
    if (dialogs.at(-1) !== dialog) return;
    const focusable = [
      ...dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]),a[href],input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])',
      ),
    ].filter((element) => element.getClientRects().length > 0);
    const first = focusable[0],
      last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
</script>

<dialog
  onkeydown={containFocus}
  bind:this={dialog}
  aria-labelledby={id}
  aria-describedby={description ? id + '-description' : undefined}
  style:max-width={width + 'px'}
  oncancel={(e) => {
    e.preventDefault();
    onclose();
  }}
>
  <header>
    <div class="stack" style="gap:6px">
      <h2 {id}>{title}</h2>
      {#if description}<p class="small muted" id={id + '-description'}>{description}</p>{/if}
    </div>
    <IconButton label="Close dialog" icon="×" onclick={onclose} />
  </header>
  <div class="body">
    {#if children}{@render children()}{/if}
  </div>
  {#if footer}<footer>{@render footer()}</footer>{/if}
</dialog>

<style>
  dialog {
    width: calc(100vw - 32px);
    max-height: calc(100dvh - 32px);
    padding: 0;
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 16px;
    box-shadow: var(--shadow);
  }
  dialog::backdrop {
    background: #080605aa;
    backdrop-filter: blur(3px);
  }
  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    padding: 24px;
    border-bottom: 1px solid var(--border);
  }
  .body {
    padding: 24px;
    overflow: auto;
  }
  footer {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    padding: 16px 24px;
    border-top: 1px solid var(--border);
    position: sticky;
    bottom: 0;
    background: var(--panel);
  }
</style>
