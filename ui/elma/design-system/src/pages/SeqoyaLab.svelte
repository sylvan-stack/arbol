<script lang="ts">
  import type { Snippet } from 'svelte';
  import WorkspaceShell from '../patterns/WorkspaceShell.svelte';
  import type { SubscriptionView } from '../sections/seqoya-subscriptions';
  import type { WorkspaceTrunkSelector } from '../types';
  import IntelligenceProviders from './IntelligenceProviders.svelte';

  let {
    trunk, trunkSelector, headerWindowControls, connectionStatus = '', fitted = false,
    theme = $bindable(''), uiScale = $bindable(0), appearanceReady = true, onAppearanceChange,
    subscriptions, onRefreshSubscriptions, onTabChange,
    onRefreshUsage, onOpenMiMo,
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
    onRefreshSubscriptions?: () => void;
    onTabChange?: (tab: string) => void;
    onRefreshUsage?: (driver: string, subscription: string) => void;
    onOpenMiMo?: () => void;
  } = $props();
</script>

{#snippet connection()}<span role="status">{connectionStatus}</span>{/snippet}

<WorkspaceShell workspace="Seqoya" headerTitle="Seqoya Lab" current="Intelligence Providers"
  destinations={['Intelligence Providers']} {trunk} {trunkSelector} {headerWindowControls}
  headerAppearance={appearanceReady ? 'enabled' : 'disabled'} bind:theme bind:uiScale {onAppearanceChange}
  status={connectionStatus ? connection : null} navigationFooter={false} {fitted}>
  <div class="page-content seqoya-page">
    <IntelligenceProviders {subscriptions} {onRefreshSubscriptions} {onTabChange} {onRefreshUsage} {onOpenMiMo} />
  </div>
</WorkspaceShell>

<style>
  .seqoya-page { min-height: 0; overflow: auto; }
</style>
