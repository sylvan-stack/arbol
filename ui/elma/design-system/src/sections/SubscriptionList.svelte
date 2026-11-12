<script lang="ts">
  import Button from '../components/Button.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import Notice from '../patterns/Notice.svelte';
  import PageHeader from '../patterns/PageHeader.svelte';
  import {
    canRefreshSubscriptionUsage, formatSubscriptionCardTime, subscriptionKey, subscriptionVendor,
    type OpenSubscriptionUsage, type SubscriptionView, type SubscriptionWindow,
  } from './seqoya-subscriptions';

  let {
    view = { connected: false },
    embedded = false,
    onRefresh,
    onRefreshUsage,
    onOpenUsage,
  }: {
    view?: SubscriptionView;
    embedded?: boolean;
    onRefresh?: () => void;
    onRefreshUsage?: (driver: string, subscription: string) => void;
    onOpenUsage?: OpenSubscriptionUsage;
  } = $props();

  const integer = new Intl.NumberFormat();
  const percent = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
  const estimated = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 3 });

  function duration(value?: number) {
    if (value === undefined) return 'Unavailable';
    if (value > 0 && value < 1) return 'Under 1 min';
    const minutes = Math.floor(value);
    const days = Math.floor(minutes / 1440);
    const hours = Math.floor(minutes / 60) % 24;
    return [
      days ? `${days} d` : '', hours ? `${hours} h` : '',
      minutes % 60 || !minutes ? `${minutes % 60} min` : '',
    ].filter(Boolean).join(' ');
  }

  function percentValue(value?: number) {
    return value === undefined ? 'Unavailable' : percent.format(value) + '%';
  }

  function estimateValue(value: number | undefined, missing: string, suffix = '') {
    if (value === undefined) return missing;
    const rounded = Number(value.toPrecision(3));
    const amount = rounded >= 1e6 ? estimated.format(rounded / 1e6) + 'M'
      : rounded >= 1e3 ? estimated.format(rounded / 1e3) + 'k' : estimated.format(rounded);
    return '≈ ' + amount + suffix;
  }

  function estimateTitle(window: SubscriptionWindow) {
    return [window.model, window.estimateBasis].filter(Boolean).join(' · ') || undefined;
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

{#snippet expiration(value: string | 0 | undefined)}
  {#if value === 0}Never
  {:else if value}<time datetime={value}>{formatSubscriptionCardTime(value)}</time>
  {:else}Unavailable{/if}
{/snippet}

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

  {#if view.evidenceError}
    <Notice tone="warning" message={view.evidenceError} />
  {/if}
  {#each failures as failure (failure.driver)}
    <Notice tone="warning" message={`Could not read the ${failure.driver} driver. ${failure.error?.message ?? ''}`} />
  {/each}

  {#if rows.length}
    <ul class="accounts" aria-label="Subscription accounts">
      {#each rows as { driver, subscription, vendor } (subscriptionKey(driver, subscription.id))}
        {@const key = subscriptionKey(driver, subscription.id)}
        {@const metrics = subscription.metrics}
        {@const resets = metrics?.limitResets}
        {@const deepseek = subscription.family === 'deepseek'}
        {@const mimo = subscription.family === 'xiaomi' && driver === 'mimo'}
        {@const chatgpt = subscription.family === 'chatgpt' && (driver === 'pi' || driver === 'codex')}
        {@const destination = mimo ? 'mimo' : chatgpt ? 'chatgpt' : undefined}
        {@const linkError = destination && view.usageLinkErrors?.[key]}
        {@const refreshable = canRefreshSubscriptionUsage(driver, subscription) && onRefreshUsage}
        {@const usageRequest = view.usageRequests?.[key]}
        <li class="panel stack account">
          <h2>{vendor}</h2>
          {#if subscription.label !== vendor}
            <p class="small muted">{subscription.label}</p>
          {/if}
          {#if subscription.problem}
            <p class="small warning">{subscription.problem.message}</p>
          {/if}

          {#each metrics?.windows ?? [] as window}
            <section class="stack metric-section" aria-label={window.label}>
              <h3>{window.label}</h3>
              {#if window.next === 'awaitingRenewal'}
                <p class="small muted">Awaiting the next allowance reading.</p>
              {:else}
                {@const missingEstimate = deepseek ? 'Unavailable' : 'Needs estimate'}
                {@const missingReading = deepseek ? 'Unavailable' : 'Awaiting reading'}
                {#if window.next === 'projected'}
                  <p class="small muted">Estimated next allowance</p>
                {/if}
                <dl class="metrics">
                  <dt>Window length</dt><dd>{window.resetsAt === null ? 'No fixed window' : window.windowMinutes === undefined ? missingReading : duration(window.windowMinutes)}</dd>
                  <dt>Resets</dt>
                  <dd>
                    {#if window.resetsAt}<time datetime={window.resetsAt}>{formatSubscriptionCardTime(window.resetsAt)}</time>
                    {:else if window.pendingStart}Starts with next use
                    {:else if window.resetsAt === null}No scheduled reset
                    {:else}{missingReading}{/if}
                  </dd>
                  {#if !window.pendingStart}
                    <dt>Time remaining</dt><dd>{window.resetsAt === null ? 'No scheduled end' : window.remainingMinutes === undefined ? missingReading : duration(window.remainingMinutes)}</dd>
                  {/if}
                  <dt>Allowance expires</dt><dd>{#if !window.terminal && (window.resetsAt || window.pendingStart) && window.expiresAt === undefined}No separate expiry{:else if !deepseek && window.expiresAt === undefined}{missingReading}{:else}{@render expiration(window.expiresAt)}{/if}</dd>
                  <dt>Allowance used</dt><dd>{window.usedPercent === undefined ? missingReading : percentValue(window.usedPercent)}</dd>
                  <dt>Allowance remaining</dt><dd>{window.remainingPercent === undefined ? missingReading : percentValue(window.remainingPercent)}</dd>
                  <dt>Output-token equivalents used</dt><dd title={estimateTitle(window)}>{estimateValue(window.outputTokensUsed, missingEstimate)}</dd>
                  <dt>Output-token equivalents remaining</dt><dd title={estimateTitle(window)}>{estimateValue(window.outputTokensRemaining, missingEstimate)}</dd>
                  {#if !window.pendingStart}
                    <dt>Remaining equivalents per hour</dt><dd title={estimateTitle(window)}>{estimateValue(window.outputTokensPerHour, window.outputTokensRemaining === undefined ? missingEstimate : missingReading, '/hour')}</dd>
                  {/if}
                </dl>
              {/if}
            </section>
          {:else}
            <p class="small muted">No saved allowance windows.</p>
          {/each}

          {#each metrics?.issues ?? [] as issue}
            <p class="small warning">{issue}</p>
          {/each}
          {#if deepseek && subscription.lastUsage?.extra?.apiAvailable === false}
            <p class="small warning">The balance is insufficient for API calls.</p>
          {/if}
          {#if refreshable || destination && onOpenUsage}
            <div class="row usage-actions">
              {#if refreshable}
                <Button label="Refresh usage" onclick={() => onRefreshUsage?.(driver, subscription.id)}
                  busy={usageRequest?.pending} disabled={!view.connected} />
              {/if}
              {#if destination && onOpenUsage}
                <Button label={mimo ? 'Open MiMo console' : 'Open ChatGPT Usage'} tone="ghost"
                  disabled={chatgpt && !view.connected} onclick={() => onOpenUsage?.(destination, driver, subscription.id)} />
              {/if}
            </div>
          {/if}
          {#if usageRequest?.error}<p class="small warning" role="status">{usageRequest.error}</p>{/if}
          {#if linkError}<p class="small warning" role="status">{linkError}</p>{/if}

          {#if resets?.count !== undefined && resets.count > 0}
            <div class="stack metric-section">
              <dl class="metrics">
                <dt>Available limit resets</dt><dd>{integer.format(resets.count)}</dd>
              </dl>
              {#if resets.entries.some((reset) => !reset.expired)}
                <ul class="reset-grants">
                  {#each resets.entries.filter((reset) => !reset.expired) as reset}
                    <li>{reset.label}{#if reset.expiresAt === 0} · Never expires{:else if reset.expiresAt} · Expires
                      {@render expiration(reset.expiresAt)}{/if}</li>
                  {/each}
                </ul>
              {/if}
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
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr));
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
  .metric-section {
    gap: 8px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }
  .metrics {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, auto);
    gap: 6px 16px;
    margin: 0;
  }
  .metrics dt { color: var(--muted); }
  .metrics dd {
    margin: 0;
    text-align: end;
    font-variant-numeric: tabular-nums;
  }
  .reset-grants { margin: 0; padding-inline-start: 20px; }
  .usage-actions { flex-wrap: wrap; }
</style>
