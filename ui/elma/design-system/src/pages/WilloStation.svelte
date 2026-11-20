<script module lang="ts">
  export interface ChatSessionRow {
    id: string;
    title: string;
    activityAt: string;
  }
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import Button from '../components/Button.svelte';
  import Notice from '../patterns/Notice.svelte';
  import WorkspaceShell from '../patterns/WorkspaceShell.svelte';

  let {
    rows = [],
    loading = false,
    more = false,
    problem = '',
    onRetry,
    onLoadOlder,
    headerWindowControls,
  }: {
    rows?: ChatSessionRow[];
    loading?: boolean;
    more?: boolean;
    problem?: string;
    onRetry?: () => void;
    onLoadOlder?: () => void;
    headerWindowControls?: Snippet;
  } = $props();

  const localTime = new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
</script>

<WorkspaceShell
  workspace="Willo"
  headerTitle="Willo Station"
  {headerWindowControls}
  showNavigation={false}
  status={null}
  fitted
>
  <div class="page">
    <section class="collection" aria-labelledby="recent-chat-sessions">
      <h2 id="recent-chat-sessions">Recent Chat Sessions</h2>

      {#if rows.length}
        <ol class="rows" role="list">
          {#each rows as row (row.id)}
            <li>
              <span class="title">{row.title}</span>
              <time datetime={row.activityAt}>{localTime.format(new Date(row.activityAt))}</time>
            </li>
          {/each}
        </ol>
      {/if}

      {#if problem}
        <Notice message={problem} tone="warning" role="alert">
          {#if onRetry}<Button label="Retry" onclick={onRetry} />{/if}
        </Notice>
      {:else if loading}
        <p class="muted" role="status">
          {rows.length ? 'Loading Chat Sessions…' : 'Loading recent Chat Sessions…'}
        </p>
      {:else if !rows.length}
        <p class="muted" role="status">No recent Chat Sessions.</p>
      {/if}

      {#if more && onLoadOlder && !problem}
        <div><Button label="Load older" tone="ghost" disabled={loading} onclick={onLoadOlder} /></div>
      {/if}
    </section>
  </div>
</WorkspaceShell>

<style>
  .page {
    flex: 1;
    min-block-size: 0;
    overflow: auto;
    padding: clamp(var(--space-4), 4vw, var(--space-6));
  }
  .collection {
    display: grid;
    gap: var(--space-4);
    max-inline-size: 58rem;
    margin-inline: auto;
  }
  .collection h2 {
    font-size: 1.25em;
    font-weight: 600;
  }
  .rows {
    padding: 0;
    margin: 0;
    list-style: none;
    border-block-start: 1px solid var(--border);
  }
  .rows li {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    flex-wrap: wrap;
    column-gap: var(--space-5);
    row-gap: var(--space-1);
    padding: var(--space-3) 0;
    border-block-end: 1px solid var(--border);
  }
  .title {
    flex: 1 1 16rem;
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  time {
    color: var(--muted);
    font-size: .9em;
    font-variant-numeric: tabular-nums;
  }
</style>
