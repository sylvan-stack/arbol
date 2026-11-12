<script lang="ts">
  import Badge from '../components/Badge.svelte';
  import Button from '../components/Button.svelte';
  import Notice from '../patterns/Notice.svelte';
  import { formatSubscriptionTime, subscriptionKey, subscriptionVendor } from './seqoya-subscriptions';
  import { displayedVigor, type VigorEntry, type VigorView } from './seqoya-vigor';

  let { view = {}, onRefresh }: { view?: VigorView; onRefresh?: () => void } = $props();
  const rollup = $derived(view.rollup);
  const entries = $derived<VigorEntry[] | undefined>(view.entries ?? rollup?.subscriptions);
  const failures = $derived(Object.entries(rollup?.failures ?? {}));
  const score = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 });
  const share = new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 1 });
  const integer = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });

  function reportAge(minutes: number) {
    const rounded = Math.round(minutes);
    const hours = Math.floor(rounded / 60);
    return hours ? hours + ' h ' + rounded % 60 + ' min' : rounded + ' min';
  }
</script>

<section class="stack" aria-label="Subscriptions Vigor">
  <div class="row spread">
    <p class="small muted">
      {#if rollup}Read <time datetime={rollup.moment}>{formatSubscriptionTime(rollup.moment)}</time>{/if}
    </p>
    <Button label="Refresh" busy={view.loading} disabled={!onRefresh} onclick={onRefresh}
      title="Reread saved Vigor and account data" />
  </div>

  {#if view.loading}
    <Notice message={entries?.length ? 'Refreshing Vigor…' : 'Loading Vigor…'} />
  {:else if view.error}
    <Notice role="alert" tone="warning"
      message={(rollup ? 'Showing the last saved results. ' : '') + view.error} />
  {/if}

  {#each failures as [source, reason] (source)}
    <Notice tone="warning" message={source + ' · ' + reason} />
  {/each}
  {#each view.accountIssues ?? [] as issue}
    <Notice tone="warning" message={issue} />
  {/each}

  {#if entries?.length}
    <ol class="ranked" aria-label="Subscriptions ranked by Vigor">
      {#each entries as entry (subscriptionKey(entry.driver, entry.subscription))}
        {@const { driver, subscription, family, label, result, estimate, unavailable } = entry}
        {@const vendor = subscriptionVendor(driver, family)}
        {@const value = displayedVigor(entry)}
        <li>
          <details>
            <summary>
              <span class="identity">
                <strong>{vendor}</strong>
                <span class="small muted">{#if label !== vendor}{label} · {/if}<code>{driver}/{subscription}</code></span>
              </span>
              {#if !unavailable}
                {#if result?.exhausted || estimate?.exhausted}<Badge label="Exhausted" tone="warning" />{/if}
                {#if estimate}<Badge label="Estimated" />{/if}
                {#if result?.predicted}<Badge label="Predicted" />{/if}
                {#if result?.stale}<Badge label="Stale" tone="warning" />{/if}
              {/if}
              <span class="score">{value === null ? 'Unavailable' : score.format(value)}</span>
            </summary>
            <div class="stack details">
              {#if unavailable}
                <p>{unavailable}</p>
              {:else}
                {#if estimate}
                  <p>{estimate.reason}</p>
                  {#if estimate.budget}
                    {@const { tokens, currency, rate, referenceTokens, ceiling } = estimate.budget}
                    <p><strong>{integer.format(tokens)}</strong> estimated output tokens at {currency} {rate} per million for DeepSeek Flash.</p>
                    <p class="small muted">{ceiling} × tokens ÷ (tokens + {integer.format(referenceTokens)}) = {score.format(estimate.score)}</p>
                  {/if}
                {/if}
                {#if result?.vigor === null && result.unknown}<p class="muted">{result.unknown}</p>{/if}
                {#if result?.stale}<p class="small muted">Usage report is {reportAge(result.stale.reportAgeMinutes)} old.</p>{/if}
                {#if result?.nextChange}
                  <p>{result.exhausted ? 'Recovery' : 'Next reset'}
                    <time datetime={result.nextChange.at}>{formatSubscriptionTime(result.nextChange.at)}</time>
                    {#if result.nextChange.vigor !== null} · projected Vigor {score.format(result.nextChange.vigor)}{/if}
                  </p>
                {/if}
                {#if result?.windows.length}
                  <ul class="windows">
                    {#each result.windows as window}
                      <li>
                        <strong>{window.label}</strong>
                        {#if window.predicted}<span class="small muted"> · Predicted</span>{/if}
                        {#if window.loss !== null}<p class="small">{share.format(window.loss)} may expire unused</p>{/if}
                        {#if window.weight != null}<p class="small muted">Weight {score.format(window.weight)}</p>{/if}
                        {#if window.contribution !== null}<p class="small muted">Vigor contribution {score.format(window.contribution)}</p>{/if}
                        {#if window.reason}<p class="small muted">{window.reason}</p>{/if}
                      </li>
                    {/each}
                  </ul>
                {:else if !estimate && !result}
                  <p class="muted">No Vigor record yet.</p>
                {/if}
              {/if}
            </div>
          </details>
        </li>
      {/each}
    </ol>
  {:else if entries && !failures.length}
    <p class="muted">No subscriptions found.</p>
  {/if}
</section>

<style>
  .ranked {
    margin: 0;
    padding: 0;
    list-style: none;
    border-top: 1px solid var(--border);
  }
  .ranked > li { border-bottom: 1px solid var(--border); }
  summary {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding: 10px 8px;
    cursor: pointer;
    list-style: none;
  }
  summary::-webkit-details-marker { display: none; }
  summary::before {
    content: '';
    width: 6px;
    height: 6px;
    border-right: 1px solid var(--muted);
    border-bottom: 1px solid var(--muted);
    transform: rotate(-45deg);
  }
  details[open] > summary::before { transform: rotate(45deg); }
  summary:hover { background: var(--inset); }
  .identity {
    flex: 1;
    display: grid;
    gap: 2px;
    min-width: min(140px, 100%);
    overflow-wrap: anywhere;
  }
  .score {
    margin-inline-start: auto;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .details { gap: 8px; padding: 0 8px 12px 22px; }
  .windows { display: grid; gap: 8px; margin: 0; padding-inline-start: 18px; }
</style>
