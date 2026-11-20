<script module lang="ts">
  import type { StationData } from './StationSummary.svelte';

  export type StationEntry = StationData & { id: string; drafted?: boolean };
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import StationSummary from './StationSummary.svelte';
  import TextField from '../components/TextField.svelte';
  import Tabs from '../components/Tabs.svelte';

  let {
    stations, agentic = false, compact = false, readOnly = false,
  }: {
    stations: StationEntry[];
    agentic?: boolean;
    compact?: boolean;
    readOnly?: boolean;
  } = $props();
  let query = $state('');
  let density = $state(untrack(() => (compact ? 'Compact' : 'Full')));

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
    const term = query.trim().toLowerCase();
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
  <div class="row spread">
    <TextField label={readOnly ? 'Search loaded Chat Sessions' : 'Search this sample page'}
      bind:value={query} type="search" />
    <Tabs label="Station density" items={['Full', 'Compact', 'Minimal']} bind:value={density} />
  </div>
  {#each groups as category (category)}
    {@const entries = visible.get(category)}
    {#if entries}
      <section class="stack" aria-label={category} style="gap:8px">
        <h2 class="eyebrow">{category}{agentic ? ' · Agent-origin' : ''}</h2>
        {#each entries as station (station.id)}
          <StationSummary {...station} density={density.toLowerCase()} {readOnly} />
        {/each}
      </section>
    {/if}
  {/each}
  {#if !visible.size && query.trim() && stations.length}
    <p class="muted" role="status">No matching Chat Sessions.</p>
  {/if}
</div>
