<script lang="ts">
  import type { Snippet } from 'svelte';
  import WorkspaceGlyph from '../components/WorkspaceGlyph.svelte';
  import PageHeader from '../patterns/PageHeader.svelte';
  import WorkspaceShell from '../patterns/WorkspaceShell.svelte';
  import type { WorkspaceRoot, WorkspaceRootSelector } from '../types';

  let { root, rootSelector, headerWindowControls, connectionStatus = '', fitted = false }: {
    root?: WorkspaceRoot;
    rootSelector?: WorkspaceRootSelector;
    headerWindowControls?: Snippet;
    connectionStatus?: string;
    fitted?: boolean;
  } = $props();

  const sections = {
    'Intelligence Providers': 'Provider configuration will appear here.',
    Subscriptions: 'Subscription management will appear here.',
    Usage: 'Usage and limits will appear here.',
  };
  type Section = keyof typeof sections;
  const destinations = Object.keys(sections) as Section[];
  let current = $state<Section>('Intelligence Providers');

  function navigate(page: string) {
    if (Object.hasOwn(sections, page)) current = page as Section;
  }
</script>

{#snippet connection()}<span role="status">{connectionStatus}</span>{/snippet}

<WorkspaceShell workspace="Seqoya" {current} {destinations} {root} {rootSelector} {headerWindowControls}
  onnavigate={navigate} status={connectionStatus ? connection : null} navigationFooter={false} {fitted}>
  {#snippet headerLead()}
    <WorkspaceGlyph workspace="Seqoya" size={24} />
    <strong>Seqoya Lab</strong>
  {/snippet}
  <div class="page-content seqoya-page">
    <PageHeader title={current} description="" />
    <div class="panel seqoya-empty"><p class="muted">{sections[current]}</p></div>
  </div>
</WorkspaceShell>

<style>
  .seqoya-page { min-height: 0; overflow: auto; }
  .seqoya-empty { padding: 24px; }
  .seqoya-empty p { margin: 0; }
</style>
