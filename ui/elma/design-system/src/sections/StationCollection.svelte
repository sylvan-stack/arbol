<script module lang="ts">
  import type { StationData } from './StationSummary.svelte';

  export type StationEntry = StationData & { id: string };
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import StationSummary from './StationSummary.svelte';
  import TextField from '../components/TextField.svelte';
  import Tabs from '../components/Tabs.svelte';

  let {
    stations, agentic = false, compact = false, readOnly = false, showControls = true,
  }: {
    stations: StationEntry[];
    agentic?: boolean;
    compact?: boolean;
    readOnly?: boolean;
    showControls?: boolean;
  } = $props();
  let query = $state('');
  let density = $state(untrack(() => (compact ? 'Compact' : 'Full')));
  const visibleDensity = $derived(showControls ? density : 'Full');

  const groups = ['Drafted', 'Running', 'Unread', 'Other on-going', 'Other chats'] as const;
  type Group = (typeof groups)[number];

  function group(station: StationEntry): Group {
    if (station.status === 'Running') return 'Running';
    if (station.drafted || station.status === 'Draft') return 'Drafted';
    if (station.unread) return 'Unread';
    return station.ongoing ? 'Other on-going' : 'Other chats';
  }

  const visible = $derived.by(() => {
    const result = new Map<Group, StationEntry[]>();
    const term = showControls ? query.trim().toLowerCase() : '';
    for (const station of stations) {
      if (agentic && station.status === 'Draft') continue;
      if (term && !station.title.toLowerCase().includes(term)) continue;
      const category = group(station);
      const entries = result.get(category);
      if (entries) entries.push(station);
      else result.set(category, [station]);
    }
    return result;
  });
</script>

<div class="stack">
  {#if showControls}
    <div class="row spread">
      <TextField label={readOnly ? 'Search loaded Chat Sessions' : 'Search this sample page'}
        bind:value={query} type="search" />
      <Tabs label="Station density" items={['Full', 'Compact', 'Minimal']} bind:value={density} />
    </div>
  {/if}
  {#each groups as category (category)}
    {@const entries = visible.get(category)}
    {#if entries}
      {@const condensed = visibleDensity === 'Full' && category === 'Other chats'}
      <section class="group" aria-label={category}>
        <h2 class="eyebrow">{category}{agentic ? ' · Agent-origin' : ''}</h2>
        <div class="cards" class:full={visibleDensity === 'Full'} class:condensed>
          {#each entries as station (station.id)}
            <StationSummary {...station} density={visibleDensity.toLowerCase()} {condensed} {readOnly} />
          {/each}
        </div>
      </section>
    {/if}
  {/each}
  {#if showControls && !visible.size && query.trim() && stations.length}
    <p class="muted" role="status">No matching Chat Sessions.</p>
  {/if}
</div>

<style>
  .group {
    display: grid;
    gap: 8px;
    min-width: 0;
  }
  .group + .group {
    border-top: 1px solid var(--border);
    padding-top: 16px;
  }
  .cards {
    display: grid;
    gap: 8px;
    grid-template-columns: minmax(0, 1fr);
  }
  .cards.full {
    gap: 16px;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
  }
  .cards.condensed {
    gap: 12px;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 210px), 1fr));
  }
</style>
