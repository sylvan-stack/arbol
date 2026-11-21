<script lang="ts" module>
  export type ElmaStatusActions = {
    onStartMessage: () => void;
    busy?: boolean;
    onScrollToEdge?: (edge: 'top' | 'bottom') => void;
  };
</script>

<script lang="ts">
  import type { ElmaRoute } from './elma-types';

  let { repository, route, actions }: {
    repository: string;
    route: ElmaRoute;
    actions?: ElmaStatusActions;
  } = $props();
</script>

<div class="status">
  <span class="context">{repository} – {route.driver || '—'} · {route.subscription || '—'} – {route.model || '—'}::{route.effort || '—'}</span>
  {#if actions}
    {@const { onStartMessage, busy, onScrollToEdge } = actions}
    <div class="actions">
      <button class="start-message" disabled={busy} onclick={onStartMessage}
        >Press Enter to start new message ⏎</button>
      <button class="scroll" aria-label="Scroll to top" title="Scroll to top"
        disabled={!onScrollToEdge} onclick={() => onScrollToEdge?.('top')}>↑</button>
      <button class="scroll" aria-label="Scroll to bottom" title="Scroll to bottom"
        disabled={!onScrollToEdge} onclick={() => onScrollToEdge?.('bottom')}>↓</button>
    </div>
  {/if}
</div>

<style>
  .status {
    display: flex;
    flex: 1;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 12px;
    min-width: 0;
  }
  .context {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-inline-start: auto;
    max-width: 100%;
    font: calc(13.5px * var(--font-scale))/1.25 var(--font-ui);
  }
  .start-message {
    min-width: 0;
    min-height: 27px;
    padding: 2px 4px;
    border: 0;
    background: transparent;
    color: var(--muted);
    text-align: left;
  }
  .scroll {
    flex-shrink: 0;
    min-width: 30px;
    min-height: 27px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--panel);
    color: var(--text);
  }
  button:disabled {
    color: var(--disabled);
  }
  button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
  }
</style>
