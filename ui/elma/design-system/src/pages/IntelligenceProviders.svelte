<script module lang="ts">
  export const providerTabInsignia: Record<string, string> = {
    Subscriptions: 'Providers Subscriptions Metrics',
    Vigor: 'Subscriptions Vigor Pressure',
    Routing: 'Subscription and Model routing',
  };
  const providerTabs = Object.keys(providerTabInsignia);
</script>

<script lang="ts">
  import Tabs from '../components/Tabs.svelte';
  import SubscriptionList from '../sections/SubscriptionList.svelte';
  import VigorPanel from '../sections/VigorPanel.svelte';
  import type { SubscriptionView, OpenSubscriptionUsage, RenameSubscription } from '../sections/seqoya-subscriptions';
  import type { VigorView } from '../sections/seqoya-vigor';

  let {
    tab = $bindable('Subscriptions'), subscriptions, vigor, onRefreshSubscriptions, onRefreshVigor,
    onTabChange, onRefreshUsage, onOpenUsage, onRenameSubscription,
  }: {
    tab?: string;
    subscriptions?: SubscriptionView;
    vigor?: VigorView;
    onRefreshSubscriptions?: () => void;
    onRefreshVigor?: () => void;
    onTabChange?: (tab: string) => void;
    onRefreshUsage?: (driver: string, subscription: string) => void;
    onOpenUsage?: OpenSubscriptionUsage;
    onRenameSubscription?: RenameSubscription;
  } = $props();
</script>

<div class="stack">
  <Tabs label="Intelligence Providers" items={providerTabs} bind:value={tab} onChange={onTabChange}>
    {#snippet panel(tab)}
      {#if tab === 'Subscriptions'}
        <SubscriptionList embedded view={subscriptions} onRefresh={onRefreshSubscriptions}
          {onRefreshUsage} {onOpenUsage} {onRenameSubscription} />
      {:else if tab === 'Vigor'}
        <VigorPanel view={vigor} onRefresh={onRefreshVigor} />
      {:else}
        <div class="panel"><p class="muted">Routing controls will appear here.</p></div>
      {/if}
    {/snippet}
  </Tabs>
</div>
