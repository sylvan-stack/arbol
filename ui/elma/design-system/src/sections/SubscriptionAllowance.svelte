<script lang="ts">
  import Tooltip from '../components/Tooltip.svelte';
  import {
    allowanceWindowLabel, allowanceWindowType, formatSubscriptionCardTime,
    type SubscriptionWindow,
  } from './seqoya-subscriptions';

  let { window, apiAccess = false }: { window: SubscriptionWindow; apiAccess?: boolean } = $props();
  const percent = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
  const significant = new Intl.NumberFormat('en-GB', { maximumSignificantDigits: 3, useGrouping: false });
  const remaining = $derived(window.next === 'awaitingRenewal' ? undefined : share(window.remainingPercent));
  const used = $derived(remaining === undefined ? undefined : 100 - remaining);
  const unknown = $derived(apiAccess ? 'Unavailable' : 'Awaiting reading');
  const timeLeft = $derived(window.next === 'awaitingRenewal' ? 'Awaiting next allowance'
    : window.pendingStart ? 'Starts with next use' : window.resetsAt === null ? 'No scheduled end'
    : duration(window.remainingMinutes));
  const resetTip = $derived([
    window.resetsAt ? 'Resets at ' + formatSubscriptionCardTime(window.resetsAt)
      : window.pendingStart ? 'Resets at: five hours after the next use'
      : window.resetsAt === null ? 'No scheduled reset' : 'Reset time awaits a provider reading.',
    window.expiresAt === 0 ? 'Never expires.'
      : window.expiresAt ? 'Allowance expires ' + formatSubscriptionCardTime(window.expiresAt) + '.' : '',
  ].filter(Boolean).join('\n'));
  const estimateTip = $derived([window.model, window.estimateBasis,
    window.terminal && window.expiresAt ? 'Allowance expires ' + formatSubscriptionCardTime(window.expiresAt) : '',
  ].filter(Boolean).join(' · ') || undefined);

  function share(value?: number): number | undefined {
    return value !== undefined && Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : undefined;
  }
  function duration(value?: number) {
    if (value === undefined) return unknown;
    if (value < 1) return 'Under 1 min';
    const minutes = Math.floor(value);
    const days = Math.floor(minutes / 1440);
    const hours = Math.floor(minutes / 60) % 24;
    return [days ? days + ' d' : '', hours ? hours + ' h' : '',
      minutes % 60 ? minutes % 60 + ' min' : ''].filter(Boolean).join(' ');
  }
  function amount(value?: number, rate = false) {
    if (value === undefined) return apiAccess ? 'Unavailable' : 'Needs estimate';
    const rounded = Number(value.toPrecision(3));
    const tokens = rounded >= 1e6 ? significant.format(rounded / 1e6) + 'M'
      : rounded >= 1e3 ? significant.format(rounded / 1e3) + 'k' : significant.format(rounded);
    return '≈ ' + tokens + (rate ? '/hour' : '');
  }
</script>

<section class="allowance stack" aria-label={window.label} data-window-type={allowanceWindowType(window)}>
  <h3 class="window-divider" title={window.label}>
    <span>{allowanceWindowLabel(window)}</span>
  </h3>
  <div class="allowance-progress">
    <div class="bar" role="progressbar" aria-label={window.label + ' remaining allowance'}
      aria-valuemin="0" aria-valuemax="100" aria-valuenow={remaining}
      aria-valuetext={remaining === undefined ? unknown : percent.format(remaining) + '% remaining'}>
      {#if remaining !== undefined}
        <span class="remaining" style:width={remaining + '%'}></span>
      {/if}
    </div>
    <div class="bar-labels">
      <span>Remaining <strong>{remaining === undefined ? '—' : percent.format(remaining) + '%'}</strong></span>
      <span>Used <strong>{used === undefined ? '—' : percent.format(100 - remaining!) + '%'}</strong></span>
    </div>
  </div>
  {#if window.next === 'projected'}<p class="small muted">Estimated next allowance</p>{/if}
  <div class="time-row">
    <span class="time-label">Time remaining</span>
    <Tooltip text={resetTip}>
      <button class="time-remaining" aria-label={'Time remaining: ' + timeLeft + '. ' + resetTip}>
        {timeLeft}
      </button>
    </Tooltip>
  </div>
  {#if window.next !== 'awaitingRenewal'}
    <dl class="metrics">
      <dt>Output-token equivalents used</dt><dd title={estimateTip}>{amount(window.outputTokensUsed)}</dd>
      <dt>Output-token equivalents remaining</dt><dd title={estimateTip}>{amount(window.outputTokensRemaining)}</dd>
      <dt>Remaining equivalents per hour</dt>
      <dd title={estimateTip}>{window.pendingStart ? 'After first use' : amount(window.outputTokensPerHour, true)}</dd>
    </dl>
  {/if}
</section>

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
