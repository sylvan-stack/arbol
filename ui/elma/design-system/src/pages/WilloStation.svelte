<script module lang="ts">
  import type { StationEntry } from '../sections/StationCollection.svelte';

  export type ChatSessionRow = StationEntry & { activityAt: string };
  export type WilloTab = 'Live Stations' | 'Imported Chat Sessions';
  type StationView = {
    rows?: ChatSessionRow[];
    loading?: boolean;
    more?: boolean;
    problem?: string;
    onRetry?: () => void;
    onLoadOlder?: () => void;
  };
  const destinations: WilloTab[] = ['Live Stations', 'Imported Chat Sessions'];
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
  import Tabs from '../components/Tabs.svelte';
  import WorkspaceShell from '../patterns/WorkspaceShell.svelte';
  import StationCollection from '../sections/StationCollection.svelte';

  let {
    rows = [],
    loading = false,
    more = false,
    problem = '',
    onRetry,
    onLoadOlder,
    tab = $bindable('Live Stations'),
    importedView = {},
    onTabChange,
    headerWindowControls,
  }: StationView & {
    tab?: WilloTab;
    importedView?: StationView;
    onTabChange?: (tab: WilloTab) => void;
    headerWindowControls?: Snippet;
  } = $props();

  let order = $state('Most recent');
  const imported = $derived(tab === 'Imported Chat Sessions');
  const view = $derived(imported ? importedView : { rows, loading, more, problem, onRetry, onLoadOlder });

  function select(destination: string) {
    if (destination === tab || (destination !== 'Live Stations' && destination !== 'Imported Chat Sessions')) return;
    tab = destination;
    onTabChange?.(destination);
  }
</script>

<div class="willo">
  <WorkspaceShell
    workspace="Willo"
    headerTitle="Willo Station"
    current={tab}
    {destinations}
    onnavigate={select}
    insignia={{ label: 'Station', hue: 104 }}
    {headerWindowControls}
    navigationFooter={false}
    status={null}
    fitted
  >
    <div class="page-content">
      {#if imported}
        <Tabs label="Imported Chat Session order" items={['Most recent', 'By harness']} bind:value={order} />
      {/if}
      <StationCollection stations={view.rows ?? []} readOnly showControls={false}
        groupBy={imported ? (order === 'By harness' ? 'harness' : 'recent') : 'status'} />

      {#if view.problem}
        <Notice message={view.problem} tone="warning" role="alert">
          {#if view.onRetry}<Button label="Retry" onclick={view.onRetry} />{/if}
        </Notice>
      {:else if view.loading}
        <p class="muted" role="status">
          {imported ? 'Loading imported Chat Sessions…' : 'Loading Chat Sessions…'}
        </p>
      {:else if !view.rows?.length}
        <p class="muted" role="status">
          {imported ? 'No imported Chat Sessions.' : 'No live Chat Sessions.'}
        </p>
      {/if}

      {#if view.more && view.onLoadOlder && !view.problem}
        <div><Button label="Load older" tone="ghost" disabled={view.loading} onclick={view.onLoadOlder} /></div>
      {/if}
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
