<script lang="ts">
  import Badge from '../components/Badge.svelte';
  import Button from '../components/Button.svelte';
  import Notice from '../patterns/Notice.svelte';
  import { formatSubscriptionTime, subscriptionKey, subscriptionVendor } from './seqoya-subscriptions';
  import type { VigorView } from './seqoya-vigor';

  let { view = {}, onRefresh }: { view?: VigorView; onRefresh?: () => void } = $props();
  const rollup = $derived(view.rollup);
  const failures = $derived(Object.entries(rollup?.failures ?? {}));
  const score = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
  const share = new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 1 });

  function reportAge(minutes: number) {
    const rounded = Math.round(minutes);
    const hours = Math.floor(rounded / 60);
    return hours ? `${hours} h ${rounded % 60} min` : `${rounded} min`;
  }
</script>

<section class="stack" aria-label="Subscriptions Vigor">
  <div class="row spread">
    <div class="stack heading">
      <p class="muted">Vigor estimates the share of allowance that could expire unused.</p>
      {#if rollup}
        <p class="small muted">Read <time datetime={rollup.moment}>{formatSubscriptionTime(rollup.moment)}</time></p>
      {/if}
    </div>
    <Button label="Refresh" busy={view.loading} disabled={!onRefresh} onclick={onRefresh}
      title="Reread saved Vigor results" />
  </div>

  {#if view.loading}
    <Notice message={rollup ? 'Refreshing Vigor…' : 'Loading Vigor…'} />
  {:else if view.error}
    <Notice role="alert" tone="warning"
      message={(rollup ? 'Showing the last saved results. ' : '') + view.error} />
  {/if}

  {#each failures as [source, reason] (source)}
    <Notice tone="warning" message={`${source} · ${reason}`} />
  {/each}

  {#if rollup?.headline}
    {@const { vigor, driver, subscription, label } = rollup.headline}
    {@const entry = rollup.subscriptions.find((row) => row.driver === driver && row.subscription === subscription)}
    <div class="panel row spread">
      <div class="stack heading">
        <h2>Highest recorded Vigor</h2>
        <p>{entry ? subscriptionVendor(driver, entry.family) : label} · <code>{driver}/{subscription}</code></p>
      </div>
      <strong class="score">{score.format(vigor)}</strong>
    </div>
  {/if}

  {#if rollup?.subscriptions.length}
    <ol class="ranked" aria-label="Subscriptions ranked by Vigor">
      {#each rollup.subscriptions as { driver, subscription, family, label, result } (subscriptionKey(driver, subscription))}
        {@const vendor = subscriptionVendor(driver, family)}
        <li class="panel stack account">
          <div class="row spread">
            <div class="stack heading">
              <h2>{vendor}</h2>
              <p class="small muted">{#if label !== vendor}{label} · {/if}<code>{driver}/{subscription}</code></p>
            </div>
            {#if result && result.vigor !== null}
              <p><span class="small muted">Vigor</span> <strong class="score">{score.format(result.vigor)}</strong></p>
            {:else}
              <p class="small muted">Vigor unavailable</p>
            {/if}
          </div>

          {#if result}
            {#if result.vigor === null && result.unknown}<p class="muted">{result.unknown}</p>{/if}
            {#if result.exhausted || result.predicted || result.stale}
              <div class="row">
                {#if result.exhausted}<Badge label="Exhausted" tone="warning" />{/if}
                {#if result.predicted}<Badge label="Predicted" />{/if}
                {#if result.stale}<Badge label={`Stale · report ${reportAge(result.stale.reportAgeMinutes)} old`} tone="warning" />{/if}
              </div>
            {/if}
            {#if result.nextChange}
              <p>{result.exhausted ? 'Recovery' : 'Next reset'}
                <time datetime={result.nextChange.at}>{formatSubscriptionTime(result.nextChange.at)}</time>
                {#if result.nextChange.vigor !== null} · projected Vigor {score.format(result.nextChange.vigor)}{/if}
              </p>
            {/if}
            <p class="small muted">Recorded <time datetime={result.moment}>{formatSubscriptionTime(result.moment)}</time></p>
            {#if result.windows.length}
              <details>
                <summary>Allowance by window</summary>
                <ul class="windows">
                  {#each result.windows as window}
                    <li>
                      <strong>{window.label}</strong>
                      {#if window.predicted}<span class="small muted"> · Predicted</span>{/if}
                      {#if window.loss !== null}<p class="small">{share.format(window.loss)} may expire unused</p>{/if}
                      {#if window.contribution !== null}<p class="small muted">Vigor contribution {score.format(window.contribution)}</p>{/if}
                      {#if window.reason}<p class="small muted">{window.reason}</p>{/if}
                    </li>
                  {/each}
                </ul>
              </details>
            {/if}
          {:else}
            <p class="muted">No Vigor record yet.</p>
          {/if}
        </li>
      {/each}
    </ol>
  {:else if rollup && !failures.length}
    <p class="panel muted">No subscriptions found.</p>
  {/if}
</section>

<style>
  .heading { gap: 4px; }
  .score {
    font-size: calc(22px * var(--font-scale));
    font-variant-numeric: tabular-nums;
  }
  .ranked {
    display: grid;
    gap: 12px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .account {
    gap: 10px;
    overflow-wrap: anywhere;
  }
  summary { cursor: pointer; }
  .windows {
    display: grid;
    gap: 8px;
    margin: 8px 0 0;
    padding-inline-start: 20px;
  }
</style>
