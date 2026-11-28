<script lang="ts">
  import Tooltip from '../components/Tooltip.svelte';
  import {
    allowanceTokenTotal, allowanceWindowLabel, allowanceWindowType, formatAllowanceTokenTotal, formatSubscriptionCardTime,
    type SubscriptionBalance, type SubscriptionWindow,
  } from './seqoya-subscriptions';

  let { window, balance }: { window: SubscriptionWindow; balance?: never } | {
    window?: never; balance: SubscriptionBalance;
  } = $props();
  const percent = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
  const significant = new Intl.NumberFormat('en-GB', { maximumSignificantDigits: 3, useGrouping: false });
  const date = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  const quotaRemaining = $derived(window?.next === 'awaitingRenewal' ? undefined : share(window?.remainingPercent));
  const balanceUsed = $derived(share(balance?.usedPercent));
  const remaining = $derived(balanceUsed === undefined ? quotaRemaining : 100 - balanceUsed);
  const used = $derived(remaining === undefined ? undefined : 100 - remaining);
  const timeLeft = $derived(window?.next === 'awaitingRenewal' ? 'Awaiting next allowance'
    : window?.pendingStart ? 'Starts with next use' : window?.resetsAt === null ? 'No scheduled end'
    : (window?.approximateReset ? '≈ ' : '') + duration(window?.remainingMinutes));
  const resetTip = $derived(window ? [
    window.resetsAt ? (window.approximateReset ? 'Resets around ' : 'Resets at ') + formatSubscriptionCardTime(window.resetsAt)
      : window.pendingStart ? 'Resets at: five hours after the next use'
      : window.resetsAt === null ? 'No scheduled reset' : 'Reset time awaits a provider reading.',
    window.expiresAt === 0 ? 'Never expires.'
      : window.expiresAt ? 'Allowance expires ' + formatSubscriptionCardTime(window.expiresAt) + '.' : '',
    window.source && window.observedAt
      ? window.source + ' · Read ' + formatSubscriptionCardTime(window.observedAt) : '',
  ].filter(Boolean).join('\n') : '');
  const estimateTip = $derived([window?.model, window?.estimateBasis,
    window?.savedEstimateAt ? 'Last successful estimate from ' + formatSubscriptionCardTime(window.savedEstimateAt) : '',
    window?.terminal && window.expiresAt ? 'Allowance expires ' + formatSubscriptionCardTime(window.expiresAt) : '',
  ].filter(Boolean).join(' · ') || undefined);

  function share(value?: number): number | undefined {
    return value !== undefined && Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : undefined;
  }
  function duration(value?: number) {
    if (value === undefined) return 'Awaiting reading';
    if (value < 1) return 'Under 1 min';
    const minutes = Math.floor(value);
    const days = Math.floor(minutes / 1440);
    const hours = Math.floor(minutes / 60) % 24;
    return [days ? days + ' d' : '', hours ? hours + ' h' : '',
      minutes % 60 ? minutes % 60 + ' min' : ''].filter(Boolean).join(' ');
  }
  function amount(value?: number, rate = false, empty = 'Unavailable') {
    if (value === undefined) return empty;
    const rounded = Number(value.toPrecision(3));
    const tokens = rounded >= 1e6 ? significant.format(rounded / 1e6) + 'M'
      : rounded >= 1e3 ? significant.format(rounded / 1e3) + 'k' : significant.format(rounded);
    return '≈ ' + tokens + (rate ? '/hour' : '');
  }
</script>

{#snippet progress(label: string, availableLabel: string)}
  <div class="allowance-progress">
    <div class="bar" role="progressbar" aria-label={label}
      aria-valuemin="0" aria-valuemax="100" aria-valuenow={remaining}
      aria-valuetext={remaining === undefined ? 'Unavailable' : percent.format(remaining) + '% ' + availableLabel.toLowerCase()}>
      {#if remaining !== undefined}
        <span class="remaining" style:width={remaining + '%'}></span>
      {/if}
    </div>
    <div class="bar-labels">
      <span>{availableLabel} <strong>{remaining === undefined ? '—' : percent.format(remaining) + '%'}</strong></span>
      <span>Used <strong>{used === undefined ? '—' : percent.format(used) + '%'}</strong></span>
    </div>
  </div>
{/snippet}

{#if balance}
  <section class="allowance stack" aria-label="API token balance">
    {#if balance.paymentDate}
      <div class="small muted">Since top-up on <time datetime={balance.paymentDate}>{date.format(new Date(`${balance.paymentDate}T00:00:00Z`))}</time></div>
    {:else}
      <div class="small muted">Top-up history unavailable</div>
    {/if}
    {@render progress('Available API balance since top-up', 'Available')}
    <dl class="metrics">
      <dt>Output tokens used</dt><dd title={balance.estimateBasis}>{amount(balance.usedTokens)}</dd>
      <dt>Output tokens available</dt>
      <dd><Tooltip text={balance.estimateBasis}>
        <button class="time-remaining" aria-label={'Output tokens available: ' + amount(balance.availableTokens) + '. ' + balance.estimateBasis}>
          {amount(balance.availableTokens)}
        </button>
      </Tooltip></dd>
    </dl>
  </section>
{:else if window}
<section class="allowance stack" aria-label={window.label} data-window-type={allowanceWindowType(window)}>
  <h3 class="window-divider" title={window.label}>
    <span>{allowanceWindowLabel(window)}</span>
  </h3>
  {@render progress(window.label + ' remaining allowance', 'Remaining')}
  {#if window.next === 'projected'}<p class="small muted">Estimated next allowance</p>{/if}
  <div class="time-row">
    <span class="time-label">Time remaining</span>
    <Tooltip text={resetTip}>
      <button class="time-remaining" aria-label={'Time remaining: ' + timeLeft + '. ' + resetTip}>
        {timeLeft}
      </button>
    </Tooltip>
  </div>
  {#if window.savedEstimateAt}
    <p class="small muted">Last token estimate · <time datetime={window.savedEstimateAt}>{formatSubscriptionCardTime(window.savedEstimateAt)}</time></p>
  {/if}
  {#if window.calibrationDetail}<p class="small muted">{window.calibrationDetail}</p>{/if}
  <dl class="metrics">
    <dt>Total tokens per window</dt><dd title={estimateTip}>{formatAllowanceTokenTotal(allowanceTokenTotal(window))}</dd>
    {#if window.next !== 'awaitingRenewal' || window.savedEstimateAt}
      <dt>Output-token equivalents used</dt><dd title={estimateTip}>{amount(window.outputTokensUsed, false, 'Awaiting first estimate')}</dd>
      <dt>Output-token equivalents remaining</dt><dd title={estimateTip}>{amount(window.outputTokensRemaining, false, 'Awaiting first estimate')}</dd>
      <dt>Remaining equivalents per hour</dt>
      <dd title={estimateTip}>{window.pendingStart && window.outputTokensPerHour === undefined
        ? 'After first use' : amount(window.outputTokensPerHour, true, 'Awaiting first estimate')}</dd>
    {/if}
  </dl>
</section>
{/if}

<style>
  .allowance { gap: 10px; }
  .window-divider { display: flex; align-items: center; gap: 10px; margin: 2px 0; font-size: .85em; font-weight: 500; color: var(--muted); }
  .window-divider::before, .window-divider::after { content: ''; flex: 1; height: 1px; background: var(--border); }
  .window-divider span { flex: 0 0 auto; }
  .bar { height: 10px; border-radius: 999px; background: var(--border); display: flex; justify-content: flex-start; overflow: hidden; }
  .remaining { display: block; height: 100%; background: var(--accent); border-radius: 999px 0 0 999px; }
  .bar-labels { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 5px 12px; margin-top: 5px; font-size: .85em; color: var(--muted); }
  .bar-labels strong { margin-left: 4px; font-weight: 500; color: var(--text); font-variant-numeric: tabular-nums; }
  .time-row { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; }
  .time-label { color: var(--muted); }
  .time-row :global(.tooltip-wrap) { min-width: 0; text-align: end; }
  .time-remaining { padding: 0; border: 0; background: transparent; color: var(--text); font: inherit; text-align: end; font-variant-numeric: tabular-nums; text-decoration: underline dotted var(--muted); text-underline-offset: 4px; cursor: help; }
  .metrics { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px 16px; margin: 0; }
  .metrics dt { color: var(--muted); }
  .metrics dd { margin: 0; text-align: end; font-variant-numeric: tabular-nums; }
</style>
