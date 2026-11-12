<script lang="ts">
  import { formatSubscriptionTime, type AllowanceView } from './seqoya-subscriptions';

  let { view }: { view: AllowanceView } = $props();
  const percent = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
  const integer = new Intl.NumberFormat();
  const estimate = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 3 });
  const quota = $derived(view.quota);
  const capacity = $derived(view.capacity);
</script>

{#if quota}
  <p class="small muted">
    {quota.source}{#if quota.plan} · {quota.plan}{/if}
    {#if quota.observedAt} · <time datetime={quota.observedAt}>{formatSubscriptionTime(quota.observedAt)}</time>{/if}
  </p>
  {#if quota.credits}
    <p><strong>{integer.format(BigInt(quota.credits.remaining))}</strong> of {integer.format(BigInt(quota.credits.total))} credits {quota.windows.some((window) => window.elapsed) ? 'left at reading' : 'left'}</p>
  {/if}
  {#if quota.note}<p class="small">{quota.note}</p>{/if}
  {#each quota.windows as window}
    <div class="stack quota-window">
      <p>{window.label}{#if window.remainingPercent !== undefined} · <strong>{percent.format(window.remainingPercent)}% {window.elapsed ? 'left at reading' : 'left'}</strong>{/if}</p>
      {#if window.resetsAt}
        <p class:warning={window.elapsed} class="small muted">{window.elapsed ? 'Reading expired at reset' : 'Resets'}
          <time datetime={window.resetsAt}>{formatSubscriptionTime(window.resetsAt)}</time>
        </p>
      {:else}
        <p class="small warning">Reset time unavailable.</p>
      {/if}
    </div>
  {/each}
{/if}
{#if capacity}
  <p>Estimated {capacity.model} output-token equivalents ·
    {#if capacity.remaining !== undefined}<strong>{estimate.format(capacity.remaining)}</strong> left of {/if}
    {estimate.format(capacity.total)} total
  </p>
  <p class="small muted">{capacity.source}</p>
  <p class="small muted">{capacity.calculation}</p>
{/if}
{#each view.issues ?? [] as issue}
  <p class="small warning">{issue}</p>
{/each}

<style>
  .quota-window { gap: 4px; }
</style>
