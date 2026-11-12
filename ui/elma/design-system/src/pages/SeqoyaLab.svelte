<script lang="ts">
  import type { Snippet } from 'svelte';
  import WorkspaceShell from '../patterns/WorkspaceShell.svelte';
  import type { SubscriptionView, UsageDestination } from '../sections/seqoya-subscriptions';
  import type { VigorView } from '../sections/seqoya-vigor';
  import type { WorkspaceTrunkSelector } from '../types';
  import IntelligenceProviders from './IntelligenceProviders.svelte';

  let {
    trunk, trunkSelector, headerWindowControls, connectionStatus = '', fitted = false,
    theme = $bindable(''), uiScale = $bindable(0), appearanceReady = true, onAppearanceChange,
    subscriptions, vigor, onRefreshSubscriptions, onRefreshVigor, onTabChange,
    onRefreshUsage, onOpenUsage,
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
    subscriptions?: SubscriptionView;
    vigor?: VigorView;
    onRefreshSubscriptions?: () => void;
    onRefreshVigor?: () => void;
    onTabChange?: (tab: string) => void;
    onRefreshUsage?: (driver: string, subscription: string) => void;
    onOpenUsage?: (destination: UsageDestination) => void;
  } = $props();
</script>

{#snippet connection()}<span role="status">{connectionStatus}</span>{/snippet}

<WorkspaceShell workspace="Seqoya" headerTitle="Seqoya Lab" current="Intelligence Providers"
  destinations={['Intelligence Providers']} {trunk} {trunkSelector} {headerWindowControls}
  headerAppearance={appearanceReady ? 'enabled' : 'disabled'} bind:theme bind:uiScale {onAppearanceChange}
  status={connectionStatus ? connection : null} navigationFooter={false} {fitted}>
  <div class="page-content seqoya-page">
    <IntelligenceProviders {subscriptions} {vigor} {onRefreshSubscriptions} {onRefreshVigor}
      {onTabChange} {onRefreshUsage} {onOpenUsage} />
  </div>
</WorkspaceShell>

<style>
  .seqoya-page { min-height: 0; overflow: auto; }
</style>
