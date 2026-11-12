<script lang="ts">
  import Tabs from '../components/Tabs.svelte';
  import PageHeader from '../patterns/PageHeader.svelte';
  import SubscriptionList from '../sections/SubscriptionList.svelte';
  import type { SubscriptionView } from '../sections/seqoya-subscriptions';

  let {
    subscriptions, onRefreshSubscriptions, onTabChange, onRefreshUsage, onOpenMiMo,
  }: {
    subscriptions?: SubscriptionView;
    onRefreshSubscriptions?: () => void;
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
        <div class="panel"><p class="muted">Vigor rankings will appear here.</p></div>
      {:else}
        <div class="panel"><p class="muted">Routing controls will appear here.</p></div>
      {/if}
    {/snippet}
  </Tabs>
</div>
