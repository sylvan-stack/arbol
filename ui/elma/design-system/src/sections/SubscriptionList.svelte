<script lang="ts">
  import Badge from '../components/Badge.svelte';
  import Button from '../components/Button.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import Meter from '../components/Meter.svelte';
  import Notice from '../patterns/Notice.svelte';
  import PageHeader from '../patterns/PageHeader.svelte';
  import type { SubscriptionView } from './seqoya-subscriptions';

  let {
    view = { connected: false },
    onRefresh,
  }: { view?: SubscriptionView; onRefresh?: () => void } = $props();

  const vendors = new Map([
    ['anthropic', 'Claude Code'],
    ['chatgpt', 'ChatGPT'],
    ['kimi-coding', 'Kimi Code'],
    ['zai', 'z.ai'],
    ['deepseek', 'DeepSeek'],
    ['xiaomi', 'MiMo'],
  ]);
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
  const dateTime = new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    timeZoneName: 'short',
  });
  function formatTime(value: string) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Time unavailable' : dateTime.format(date);
  }

  const failures = $derived(view.listing?.drivers.filter((entry) => entry.error) ?? []);
  const rows = $derived((view.listing?.drivers ?? []).flatMap(({ driver, subscriptions }) =>
    (subscriptions ?? []).map((subscription) => ({
      driver,
      subscription,
      vendor: driver === 'codex' && subscription.family === 'chatgpt'
        ? 'Codex' : (vendors.get(subscription.family) ?? subscription.family),
    })),
  ).sort((left, right) =>
    left.vendor.localeCompare(right.vendor) ||
    left.subscription.label.localeCompare(right.subscription.label) ||
    left.driver.localeCompare(right.driver) ||
    left.subscription.id.localeCompare(right.subscription.id),
  ));
</script>

<section class="stack" aria-label="Subscriptions">
  <div class="row spread">
    <PageHeader title="Subscriptions" description="Accounts reported by this Root’s drivers." count={view.listing && (!failures.length || rows.length) ? rows.length : undefined} />
    <Button label="Refresh" onclick={onRefresh} busy={view.loading} disabled={!view.connected || !onRefresh}
      title="Reread stored accounts and usage" />
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
      {#each rows as { driver, subscription, vendor } (JSON.stringify([driver, subscription.id]))}
        {@const status = states.get(subscription.state)}
        {@const usage = subscription.lastUsage}
        <li class="panel stack account">
          <div class="row spread">
            <h2>{vendor}</h2>
            <Badge label={status?.label ?? 'Sign-in state unknown'} tone={status?.tone} />
          </div>
          <div class="stack identity">
            {#if subscription.label !== vendor}<p>{subscription.label}</p>{/if}
            <p class="small muted"><code>{driver}/{subscription.id}</code> · {authModes.get(subscription.auth) ?? subscription.auth}</p>
          </div>
          {#if subscription.problem}
            <p class="small warning">{subscription.problem.message}</p>
          {/if}
          {#if usage}
            <div class="stack usage">
              <p class="small muted">Usage recorded <time datetime={usage.fetchedAt}>{formatTime(usage.fetchedAt)}</time>{#if usage.plan} · {usage.plan}{/if}</p>
              {#each usage.windows as window}
                <div class="stack usage-window">
                  <Meter label={window.label + (window.resource ? ` · ${window.resource}` : '')} value={window.usedPercent} unknown={window.usedPercent === undefined} />
                  {#if window.limitReached || window.resetsAt}
                    <p class="small muted">
                      {#if window.limitReached}<span class="warning">Limit reached</span>{/if}
                      {#if window.limitReached && window.resetsAt} · {/if}
                      {#if window.resetsAt}Resets <time datetime={window.resetsAt}>{formatTime(window.resetsAt)}</time>{/if}
                    </p>
                  {/if}
                </div>
              {:else}
                <p class="small muted">No usage limits reported.</p>
              {/each}
            </div>
          {:else}
            <p class="small muted">No saved usage.</p>
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
  .usage {
    gap: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }
</style>
