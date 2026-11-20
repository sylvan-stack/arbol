<script module lang="ts">
  import type { StationEntry } from '../sections/StationCollection.svelte';

  export type ChatSessionRow = StationEntry & { activityAt: string };
  export const willoDestinations = [
    'Stations', 'Agentic Stations', 'Action Items', 'Spotlight', 'Comunicados',
    'Slack', 'Telegram', 'Emails', 'Blueprint Runs', 'Run Details', 'Email Signal Rules',
    'Compact Stations',
  ];
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import Button from '../components/Button.svelte';
  import Notice from '../patterns/Notice.svelte';
  import PageHeader from '../patterns/PageHeader.svelte';
  import WorkspaceShell from '../patterns/WorkspaceShell.svelte';
  import AttentionColumn from '../sections/AttentionColumn.svelte';
  import StationCollection from '../sections/StationCollection.svelte';

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

  const inactiveDestinations = willoDestinations.slice(1);
</script>

<div class="willo">
  <WorkspaceShell
    workspace="Willo"
    headerTitle="Willo Station"
    current="Stations"
    destinations={willoDestinations}
    disabledDestinations={inactiveDestinations}
    {headerWindowControls}
    navigationFooter={false}
    status={null}
    fitted
  >
    <div class="page-content">
      <PageHeader title="Stations" description="Recent Chat Sessions in this installation." />
      <div class="split">
        <div class="stack">
          <StationCollection stations={rows} readOnly />

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
        </div>
        <AttentionColumn unavailable />
      </div>
    </div>
  </WorkspaceShell>
</div>

<style>
  .willo {
    height: 100dvh;
  }
  .willo :global(.workspace.fitted) {
    height: 100%;
    min-height: 0;
  }
  .page-content {
    overflow: auto;
  }
</style>
