<script lang="ts">
  import Tabs from '../components/Tabs.svelte';
  import PageHeader from '../patterns/PageHeader.svelte';
  import SubscriptionList from '../sections/SubscriptionList.svelte';
  import VigorPanel from '../sections/VigorPanel.svelte';
  import type { SubscriptionView } from '../sections/seqoya-subscriptions';
  import type { VigorView } from '../sections/seqoya-vigor';

  let {
    subscriptions, vigor, onRefreshSubscriptions, onRefreshVigor, onTabChange, onRefreshUsage, onOpenMiMo,
  }: {
    subscriptions?: SubscriptionView;
    vigor?: VigorView;
    onRefreshSubscriptions?: () => void;
    onRefreshVigor?: () => void;
    onTabChange?: (tab: string) => void;
    onRefreshUsage?: (driver: string, subscription: string) => void;
    onOpenMiMo?: () => void;
  } = $props();
</script>

<div class="stack">
  <PageHeader title="Intelligence Providers" description="" />
  <Tabs label="Intelligence Providers" items={['Subscriptions', 'Vigor', 'Routing']}
    value="Subscriptions" onChange={onTabChange}>
    {#snippet panel(tab)}
      {#if tab === 'Subscriptions'}
        <SubscriptionList embedded view={subscriptions} onRefresh={onRefreshSubscriptions}
          {onRefreshUsage} {onOpenMiMo} />
      {:else if tab === 'Vigor'}
        <VigorPanel view={vigor} onRefresh={onRefreshVigor} />
      {:else}
        <div class="panel"><p class="muted">Routing controls will appear here.</p></div>
      {/if}
    {/snippet}
  </Tabs>
</div>
