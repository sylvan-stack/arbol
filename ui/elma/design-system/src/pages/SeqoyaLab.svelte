<script lang="ts">
  import type { Snippet } from 'svelte';
  import PageHeader from '../patterns/PageHeader.svelte';
  import WorkspaceShell from '../patterns/WorkspaceShell.svelte';
  import type { WorkspaceTrunkSelector } from '../types';

  let {
    trunk, trunkSelector, headerWindowControls, connectionStatus = '', fitted = false,
    theme = $bindable(''), uiScale = $bindable(0), appearanceReady = true, onAppearanceChange,
  }: {
    trunk?: string;
    trunkSelector?: WorkspaceTrunkSelector;
    headerWindowControls?: Snippet;
    connectionStatus?: string;
    fitted?: boolean;
    theme?: string;
    uiScale?: number;
    appearanceReady?: boolean;
    onAppearanceChange?: () => void;
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

<WorkspaceShell workspace="Seqoya" headerTitle="Seqoya Lab" {current} {destinations} {trunk} {trunkSelector} {headerWindowControls}
  headerAppearance={appearanceReady ? 'enabled' : 'disabled'} bind:theme bind:uiScale {onAppearanceChange}
  onnavigate={navigate} status={connectionStatus ? connection : null} navigationFooter={false} {fitted}>
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
