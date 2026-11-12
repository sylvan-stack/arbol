<script lang="ts">
  import Button from '../components/Button.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import Notice from '../patterns/Notice.svelte';
  import PageHeader from '../patterns/PageHeader.svelte';
  import SubscriptionCard from './SubscriptionCard.svelte';
  import { subscriptionKey, subscriptionVendor,
    type OpenSubscriptionUsage, type RenameSubscription, type SubscriptionView,
  } from './seqoya-subscriptions';

  let {
    view = { connected: false }, embedded = false,
    onRefresh, onRefreshUsage, onOpenUsage, onRenameSubscription,
  }: {
    view?: SubscriptionView;
    embedded?: boolean;
    onRefresh?: () => void;
    onRefreshUsage?: (driver: string, subscription: string) => void;
    onOpenUsage?: OpenSubscriptionUsage;
    onRenameSubscription?: RenameSubscription;
  } = $props();
  const failures = $derived(view.listing?.drivers.filter(entry => entry.error) ?? []);
  const rows = $derived((view.listing?.drivers ?? []).flatMap(({ driver, subscriptions }) =>
    (subscriptions ?? []).map(subscription => ({
      driver, subscription, vendor: subscriptionVendor(driver, subscription.family),
    })),
  ).sort((a, b) => a.vendor.localeCompare(b.vendor) || a.subscription.label.localeCompare(b.subscription.label)
    || a.driver.localeCompare(b.driver) || a.subscription.id.localeCompare(b.subscription.id)));
  const count = $derived(view.listing && (!failures.length || rows.length) ? rows.length : undefined);
</script>

<section class="stack" aria-label="Subscriptions">
  <div class="row spread">
    {#if !embedded}
      <PageHeader title="Subscriptions" description="Accounts reported by the installation’s drivers." {count} />
    {:else if count !== undefined}
      <p class="small muted">{count} {count === 1 ? 'subscription' : 'subscriptions'}</p>
    {/if}
    <div class="subscription-actions">
      <Button label="Refresh" onclick={onRefresh} busy={view.loading} disabled={!view.connected || !onRefresh}
        title="Reread stored accounts and usage" />
    </div>
  </div>
  {#if !view.connected}
    <Notice message={view.listing ? 'Showing the last account list while disconnected.' : 'Waiting for the installation connection…'} tone={view.listing ? 'warning' : 'info'} />
  {:else if view.loading}
    <Notice message={view.listing ? 'Refreshing subscriptions…' : 'Loading subscriptions…'} />
  {:else if view.error}
    <Notice role="alert" tone="warning" message={(view.listing ? 'Refresh failed. Showing the last account list. ' : 'Could not load subscriptions. ') + view.error} />
  {/if}
  {#if view.evidenceError}<Notice tone="warning" message={view.evidenceError} />{/if}
  {#each failures as failure (failure.driver)}
    <Notice tone="warning" message={`Could not read the ${failure.driver} driver. ${failure.error?.message ?? ''}`} />
  {/each}
  {#if rows.length}
    <ul class="accounts" aria-label="Subscription accounts">
      {#each rows as { driver, subscription } (subscriptionKey(driver, subscription.id))}
        <SubscriptionCard {driver} {subscription} {view} {onRefreshUsage} {onOpenUsage} onRename={onRenameSubscription} />
      {/each}
    </ul>
  {:else if view.listing && !failures.length}
    <div class="panel">
      <EmptyState title="No subscriptions found" action="" description={view.listing.drivers.length ? 'The available drivers reported no subscriptions.' : 'The installation’s backend found no installed drivers.'} />
    </div>
  {/if}
</section>

<style>
  .subscription-actions { margin-inline-start: auto; }
  .accounts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr)); gap: 12px; list-style: none; margin: 0; padding: 0; }
</style>
