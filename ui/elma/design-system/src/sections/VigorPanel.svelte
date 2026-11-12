<script lang="ts">
  import Badge from '../components/Badge.svelte';
  import AllowanceMetrics from './AllowanceMetrics.svelte';
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

  function minutesUntil(reset: string | null | undefined, moment: string) {
    const minutes = reset ? (Date.parse(reset) - Date.parse(moment)) / 60_000 : NaN;
    return Number.isFinite(minutes) ? Math.max(0, minutes) : undefined;
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
        {@const { driver, subscription, family, label, result, estimate, unavailable, activity, activityError } = entry}
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
                {#if estimate?.budget}
                  {@const { amount, tokens, currency, rate, referenceTokens, ceiling } = estimate.budget}
                  <p>Estimated output tokens = ({amount} {currency} ÷ {rate} {currency}) × 1,000,000 ≈ <strong>{integer.format(tokens)}</strong></p>
                  <p class="small muted">DeepSeek Flash peak output rate per million tokens.</p>
                  <p>Vigor = {ceiling} × {integer.format(tokens)} ÷ ({integer.format(tokens)} + {integer.format(referenceTokens)}) ≈ <strong>{score.format(estimate.score)}</strong></p>
                {:else if estimate}
                  <p>Vigor = <strong>{score.format(estimate.score)}</strong> · {estimate.reason}</p>
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
                      {@const minutesLeft = minutesUntil(window.resetsAt, result.moment)}
                      <li>
                        <strong>{window.label}</strong>
                        {#if window.predicted}<span class="small muted"> · Predicted</span>{/if}
                        {#if window.loss !== null}
                          {#if window.reached}
                            <p class="small">Loss = 0 · limit reached</p>
                          {:else if window.usedPercent != null && minutesLeft !== undefined && window.windowMinutes}
                            <p class="small">Loss = max(0, 1 − {share.format(window.usedPercent / 100)} − {score.format(minutesLeft)} min ÷ {score.format(window.windowMinutes)} min) ≈ {score.format(window.loss)}</p>
                          {:else}
                            <p class="small">Saved loss {score.format(window.loss)}</p>
                          {/if}
                        {/if}
                        {#if window.contribution !== null && window.weight != null && window.loss !== null}
                          <p class="small muted">Contribution = {score.format(window.loss)} × {score.format(window.weight)} ≈ {score.format(window.contribution)}</p>
                        {:else if window.contribution !== null}
                          <p class="small muted">Saved contribution {score.format(window.contribution)}</p>
                        {/if}
                        {#if window.reason}<p class="small muted">{window.reason}</p>{/if}
                      </li>
                    {/each}
                  </ul>
                {:else if !estimate && !result}
                  <p class="muted">No Vigor record yet.</p>
                {/if}
                {#if !estimate && result?.vigor != null}
                  {@const terms = result.windows.flatMap((window) => window.contribution === null ? [] : [score.format(window.contribution)])}
                  {#if result.exhausted}
                    <p>Vigor = <strong>0</strong> · inference limit reached</p>
                  {:else if terms.length}
                    <p>Vigor = min(1, {terms.join(' + ')}) ≈ <strong>{score.format(result.vigor)}</strong></p>
                  {:else}
                    <p>Saved Vigor = <strong>{score.format(result.vigor)}</strong></p>
                  {/if}
                {/if}
              {/if}
              {#if entry.allowance}<AllowanceMetrics view={entry.allowance} />{/if}
              {#if activity || activityError}
                <p class="small muted">Arbol activity in this Root · Last 30 days</p>
                {#if activity}
                  <p>{integer.format(activity.runCount)} {activity.runCount === 1 ? 'run' : 'runs'} recorded</p>
                  {#if activity.runCount}
                    <p class="small">Input tokens {activity.inputTokens ?? 'unavailable'} · Output tokens {activity.outputTokens ?? 'unavailable'}</p>
                    {#if activity.lastRunAt}
                      <p class="small muted">Last run <time datetime={activity.lastRunAt}>{formatSubscriptionTime(activity.lastRunAt)}</time></p>
                    {/if}
                  {/if}
                {:else}
                  <p class="small muted">{activityError}</p>
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
