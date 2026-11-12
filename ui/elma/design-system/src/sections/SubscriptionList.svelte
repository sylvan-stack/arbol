<script lang="ts">
  import Badge from '../components/Badge.svelte';
  import Button from '../components/Button.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import Meter from '../components/Meter.svelte';
  import Notice from '../patterns/Notice.svelte';
  import PageHeader from '../patterns/PageHeader.svelte';
  import { formatSubscriptionTime, subscriptionKey, subscriptionVendor, type SubscriptionView } from './seqoya-subscriptions';

  let {
    view = { connected: false },
    embedded = false,
    onRefresh,
    onRefreshUsage,
    onOpenMiMo,
  }: {
    view?: SubscriptionView;
    embedded?: boolean;
    onRefresh?: () => void;
    onRefreshUsage?: (driver: string, subscription: string) => void;
    onOpenMiMo?: () => void;
  } = $props();

  const states = new Map<string, { label: string; tone: string }>([
    ['signed_in', { label: 'Signed in', tone: 'success' }],
    ['signed_out', { label: 'Signed out', tone: 'neutral' }],
    ['signing_in', { label: 'Signing in', tone: 'working' }],
    ['needs_attention', { label: 'Needs attention', tone: 'warning' }],
  ]);
  const authModes = new Map([
    ['vendor_login', 'Vendor sign-in'],
    ['oauth', 'OAuth'],
    ['key', 'API key'],
    ['api_key', 'API key'],
    ['token', 'Token'],
  ]);
  const integer = new Intl.NumberFormat();
  function tokens(value?: string) {
    return typeof value === 'string' && /^[0-9]+$/.test(value) ? integer.format(BigInt(value)) : 'Unavailable';
  }

  const failures = $derived(view.listing?.drivers.filter((entry) => entry.error) ?? []);
  const rows = $derived((view.listing?.drivers ?? []).flatMap(({ driver, subscriptions }) =>
    (subscriptions ?? []).map((subscription) => ({
      driver,
      subscription,
      vendor: subscriptionVendor(driver, subscription.family),
    })),
  ).sort((left, right) =>
    left.vendor.localeCompare(right.vendor) ||
    left.subscription.label.localeCompare(right.subscription.label) ||
    left.driver.localeCompare(right.driver) ||
    left.subscription.id.localeCompare(right.subscription.id),
  ));
  const accountCount = $derived(view.listing && (!failures.length || rows.length) ? rows.length : undefined);
</script>

<section class="stack" aria-label="Subscriptions">
  <div class="row spread">
    {#if !embedded}
      <PageHeader title="Subscriptions" description="Accounts reported by this Root’s drivers." count={accountCount} />
    {:else if accountCount !== undefined}
      <p class="small muted">{accountCount} {accountCount === 1 ? 'subscription' : 'subscriptions'}</p>
    {/if}
    <div class="subscription-actions">
      <Button label="Refresh" onclick={onRefresh} busy={view.loading} disabled={!view.connected || !onRefresh}
        title="Reread stored accounts and usage" />
    </div>
  </div>

  {#if !view.connected}
    <Notice message={view.listing ? 'Showing the last account list while disconnected.' : 'Waiting for the Root connection…'} tone={view.listing ? 'warning' : 'info'} />
  {:else if view.loading}
    <Notice message={view.listing ? 'Refreshing subscriptions…' : 'Loading subscriptions…'} />
  {:else if view.error}
    <Notice role="alert" tone="warning"
      message={(view.listing ? 'Refresh failed. Showing the last account list. ' : 'Could not load subscriptions. ') + view.error} />
  {/if}

  {#each failures as failure (failure.driver)}
    <Notice tone="warning" message={`Could not read the ${failure.driver} driver. ${failure.error?.message ?? ''}`} />
  {/each}

  {#if rows.length}
    <ul class="accounts" aria-label="Subscription accounts">
      {#each rows as { driver, subscription, vendor } (subscriptionKey(driver, subscription.id))}
        {@const status = states.get(subscription.state)}
        {@const usage = subscription.lastUsage}
        {@const deepseek = subscription.family === 'deepseek'}
        {@const zai = subscription.family === 'zai'}
        {@const mimo = subscription.family === 'xiaomi' && driver === 'mimo'}
        {@const refreshable = (deepseek || zai) && subscription.state === 'signed_in' && onRefreshUsage}
        {@const usageRequest = view.usageRequests?.[subscriptionKey(driver, subscription.id)]}
        {@const balances = deepseek && Array.isArray(usage?.extra?.balances) ? usage.extra.balances : []}
        {@const insufficient = deepseek && usage?.extra?.apiAvailable === false}
        <li class="panel stack account">
          <div class="row spread">
            <h2>{vendor}</h2>
            <Badge label={status?.label ?? 'Sign-in state unknown'} tone={status?.tone} />
          </div>
          <div class="stack identity">
            {#if subscription.label !== vendor}<p>{subscription.label}</p>{/if}
            <p class="small muted"><code>{driver}/{subscription.id}</code> · {authModes.get(subscription.auth) ?? subscription.auth}</p>
          </div>
          {#if subscription.modelLabels}
            <dl class="model-labels">
              {#each subscription.modelLabels as label, index}
                <div>
                  <dt>{label.model ?? 'Default model'}{#if index === 0 && label.model}<span class="small muted"> · Default</span>{/if}</dt>
                  <dd class="small muted">{label.performance} performance · {label.cost}</dd>
                </div>
              {/each}
            </dl>
          {/if}
          {#if subscription.problem}
            <p class="small warning">{subscription.problem.message}</p>
          {/if}
          {#if usage}
            <div class="stack usage">
              <p class="small muted">Usage recorded <time datetime={usage.fetchedAt}>{formatSubscriptionTime(usage.fetchedAt)}</time>{#if usage.plan} · {usage.plan}{/if}</p>
              {#each balances as balance (balance.currency)}
                <p>API balance <strong>{balance.amount} {balance.currency}</strong></p>
              {/each}
              {#if insufficient}<p class="small warning">The balance is insufficient for API calls.</p>{/if}
              {#each usage.windows as window}
                <div class="stack usage-window">
                  <Meter label={window.label + (window.resource ? ` · ${window.resource}` : '')} value={window.usedPercent} unknown={window.usedPercent === undefined} />
                  {#if window.limitReached || window.resetsAt}
                    <p class="small muted">
                      {#if window.limitReached}<span class="warning">Limit reached</span>{/if}
                      {#if window.limitReached && window.resetsAt} · {/if}
                      {#if window.resetsAt}Resets <time datetime={window.resetsAt}>{formatSubscriptionTime(window.resetsAt)}</time>{/if}
                    </p>
                  {/if}
                </div>
              {:else}
                {#if !balances.length && !insufficient}<p class="small muted">No usage limits reported.</p>{/if}
              {/each}
            </div>
          {:else if !mimo}
            <p class="small muted">
              {refreshable ? (deepseek ? 'Refresh usage to check your API balance.' : 'Refresh usage to check your Coding Plan quota.') : 'No saved usage.'}
            </p>
          {/if}
          {#if refreshable}
            <div>
              <Button label="Refresh usage" onclick={() => onRefreshUsage?.(driver, subscription.id)}
                busy={usageRequest?.pending} disabled={!view.connected} />
            </div>
          {/if}
          {#if usageRequest?.error}<p class="small warning" role="status">{usageRequest.error}</p>{/if}
          {#if mimo}
            <div class="stack usage">
              <p class="small muted">Arbol activity in this Root · Last 30 days</p>
              {#if subscription.activity}
                {@const activity = subscription.activity}
                <p>{integer.format(activity.runCount)} {activity.runCount === 1 ? 'run' : 'runs'} recorded</p>
                {#if activity.runCount}
                  <p class="small">Input tokens: {tokens(activity.inputTokens)} · Output tokens: {tokens(activity.outputTokens)}</p>
                  {#if activity.lastRunAt}
                    <p class="small muted">Last run <time datetime={activity.lastRunAt}>{formatSubscriptionTime(activity.lastRunAt)}</time></p>
                  {/if}
                {/if}
              {:else if subscription.activityError}
                <p class="small warning" role="status">{subscription.activityError}</p>
              {:else}
                <p class="small muted">{view.connected ? 'Reading Root activity…' : 'Root activity unavailable while disconnected.'}</p>
              {/if}
              {#if onOpenMiMo}
                <div><Button label="Open MiMo console" tone="ghost" onclick={onOpenMiMo} /></div>
              {/if}
              {#if view.consoleError}<p class="small warning" role="status">{view.consoleError}</p>{/if}
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {:else if view.listing && !failures.length}
    <div class="panel">
      <EmptyState title="No subscriptions found" action=""
        description={view.listing.drivers.length ? 'The available drivers reported no subscriptions.' : 'This Root’s backend found no installed drivers.'} />
    </div>
  {/if}
</section>

<style>
  .subscription-actions { margin-inline-start: auto; }
  .accounts {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 20rem), 1fr));
    gap: 12px;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .account {
    gap: 12px;
    padding: 16px;
    overflow-wrap: anywhere;
  }
  .identity, .usage-window { gap: 4px; }
  .model-labels {
    display: grid;
    gap: 8px;
    margin: 0;
  }
  .model-labels dd { margin: 0; }
  .usage {
    gap: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }
</style>
