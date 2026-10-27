<script lang="ts">
  import TextField from '../components/TextField.svelte';
  import Button from '../components/Button.svelte';
  import EntitySummary from './EntitySummary.svelte';
  import type { RecordItem } from '../types';
  let {
    items = [
      { id: '1', title: 'Design System', kind: 'artifact', subtitle: 'Arbol artifacts' },
      { id: '2', title: 'Restore shared interactions', kind: 'graft', subtitle: 'Oaken · Planned' },
      { id: '3', title: 'Chat continuity', kind: 'living_topic', subtitle: 'Elma · Active' },
    ],
    multiple = false,
    onselect = () => {},
  }: { items?: RecordItem[]; multiple?: boolean; onselect?: (ids: string[]) => void } = $props();
  let query = $state('');
  let selected = $state<string[]>([]);
  let visible = $derived(items.filter((x) => x.title.toLowerCase().includes(query.toLowerCase())));
  function select(id: string) {
    selected = multiple
      ? selected.includes(id)
        ? selected.filter((x) => x !== id)
        : [...selected, id]
      : [id];
    if (!multiple) onselect(selected);
  }
</script>

<section class="stack" aria-label="Entity picker">
  <TextField
    label="Search all sample entities"
    bind:value={query}
    type="search"
    placeholder="Name, reference or kind…"
  />
  <ul class="clean stack">
    {#each visible as item}<li class="inset">
        <EntitySummary
          {...item}
          status={selected.includes(item.id) ? 'Selected' : ''}
          onclick={() => select(item.id)}
        />
      </li>{:else}<li class="empty">No matching entities. Try another name.</li>{/each}
  </ul>
  {#if multiple}<Button
      label={'Use ' + selected.length + ' selected'}
      disabled={!selected.length}
      onclick={() => onselect(selected)}
    />{/if}
</section>
