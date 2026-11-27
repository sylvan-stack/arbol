<script lang="ts">
  import Button from '../components/Button.svelte';
  import Modal from '../patterns/Modal.svelte';
  import Notice from '../patterns/Notice.svelte';
  import VigorEtcEditor from './VigorEtcEditor.svelte';
  import { formatAllowanceTokenTotal } from './seqoya-subscriptions';
  import { formatVigorNumber, formatVigorTokens } from './seqoya-vigor-format';
  import {
    defaultVigorSettings, isVigorSettings, quotaDashRules, vigorCurrencies, vigorFactors, vigorPriorityRows,
    type MonthlyEtcForecast, type MonthlyEtcForecasts, type QuotaDashMatch,
    type QuotaDashChoice, type QuotaDashChoices, type VigorCalculation, type VigorPriorityView, type VigorSettings,
  } from './seqoya-vigor-priority';

  let { view = {}, onRefresh }: { view?: VigorPriorityView; onRefresh?: () => void } = $props();
  let previewChoices = $state<QuotaDashChoices>({});
  let previewForecasts = $state<MonthlyEtcForecasts>({});
  let previewSettings = $state(defaultVigorSettings);
  let dashProblem = $state('');
  let settingsProblem = $state('');
  let expanded = $state<string>();
  let configuring = $state(false);
  let editingForecast = $state<string>();
  type SettingsDraft = Partial<Omit<VigorSettings, 'weights' | 'dashThresholds'>> & {
    weights: Partial<VigorSettings['weights']>;
    dashThresholds: NonNullable<VigorSettings['dashThresholds']>;
  };
  let draft = $state<SettingsDraft>({ weights: {}, dashThresholds: {} });
  const panelId = $props.id();
  const settings = $derived(view.priority?.settings ?? previewSettings);
  const forecasts = $derived(view.priority?.monthlyForecasts ?? previewForecasts);
  const rows = $derived(vigorPriorityRows(view, view.priority?.choices ?? previewChoices, settings, forecasts));
  const forecastRow = $derived(rows?.find(row => row.key === editingForecast));
  const issues = $derived([...new Set([...Object.entries(view.rollup?.failures ?? {}).map(([source, reason]) =>
    source + ' · ' + reason), ...(view.accountIssues ?? [])])]);
  const variableFormula = 'Vigor = ' + vigorFactors.map(({ coefficient, variable }) => `${coefficient} × ${variable}`).join(' + ');
  const score = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const timestamp = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

  function configure() {
    draft = { ...settings, weights: { ...settings.weights }, dashThresholds: { ...settings.dashThresholds } };
    settingsProblem = '';
    configuring = true;
  }

  function useDefaults() {
    draft = { ...defaultVigorSettings, weights: { ...defaultVigorSettings.weights }, dashThresholds: {} };
    settingsProblem = '';
  }

  function saveSettings(event: SubmitEvent) {
    event.preventDefault();
    if (!isVigorSettings(draft)) {
      settingsProblem = 'Use nonnegative weights with a positive total, positive scales, and nonnegative thresholds or blank fields.';
      return;
    }
    const next = { ...draft, weights: { ...draft.weights }, dashThresholds: { ...draft.dashThresholds } };
    try {
      if (view.priority?.setSettings) view.priority.setSettings(next);
      else previewSettings = next;
      configuring = false;
    } catch {
      settingsProblem = 'Could not save the Vigor settings.';
    }
  }

  function mark(key: string, choice: QuotaDashChoice) {
    dashProblem = '';
    try {
      if (view.priority?.setChoice) view.priority.setChoice(key, choice);
      else previewChoices[key] = choice;
    } catch {
      dashProblem = 'Could not save the Quota Dash choice.';
    }
  }

  function toggle(key: string) {
    expanded = expanded === key ? undefined : key;
  }

  function rowClick(event: MouseEvent, key: string) {
    const target = event.target;
    if (target instanceof Element && target.closest('button')) return;
    toggle(key);
  }

  function money(amount: number, currency: string) {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 2 }).format(amount);
  }

  function timeLeft(hours: number) {
    const minutes = Math.max(0, Math.floor(hours * 60));
    if (minutes >= 1_440) return `${Math.floor(minutes / 1_440)}d ${Math.floor(minutes / 60) % 24}h`;
    return minutes > 0 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : '<1m';
  }

  function saveForecast(key: string, forecast?: MonthlyEtcForecast) {
    if (view.priority?.setMonthlyForecast) view.priority.setMonthlyForecast(key, forecast);
    else if (forecast) previewForecasts[key] = forecast;
    else delete previewForecasts[key];
  }

  function etcLabel(value: number, currency: string) {
    return value === Infinity ? 'Unbounded (zero projected usage)' : `${money(value, currency)} per million`;
  }

  function shortRule(match: QuotaDashMatch) {
    return match.kind === 'reset' ? 'Reset expiry' : quotaDashRules.find(rule => rule.key === match.kind)?.short;
  }

  function describeMatch(match: QuotaDashMatch) {
    if (match.kind === 'reset') return 'Weekly reset expires ' + timestamp.format(match.deadline);
    const label = quotaDashRules.find(rule => rule.key === match.kind)?.label;
    if (match.kind === 'requiredPace') {
      return `${label} · weekly Mach ${formatVigorNumber(match.value)} ≥ weekly Mach ${formatVigorNumber(match.threshold)}`;
    }
    if (match.kind === 'projectedEtc') {
      return `${label} · ${etcLabel(match.value, settings.lossCurrency)} ≥ ${etcLabel(match.threshold, settings.lossCurrency)}`;
    }
    return `${label} · ≈${money(match.value, settings.lossCurrency)} ≥ ${money(match.threshold, settings.lossCurrency)}`;
  }

  function values(calculation: VigorCalculation, weekly: boolean) {
    const { dash, hoursLeft, windowHours, tokens, loss, userScore } = calculation;
    const time = hoursLeft === undefined ? 'Unavailable'
      : windowHours === undefined ? `${formatVigorNumber(hoursLeft)} h left · duration unavailable`
      : `${formatVigorNumber(hoursLeft)} h left of ${formatVigorNumber(windowHours)} h`;
    return [
      weekly ? (dash ? 'On (1)' : 'Off (0)') : 'Weekly windows only (0)',
      time,
      tokens === undefined ? 'Unavailable' : `${formatVigorTokens(tokens)} equivalents · scale ${formatVigorTokens(settings.tokenScale)}`,
      loss === undefined ? 'Unavailable' : `≈${money(loss.amount, loss.currency)} · scale ${money(settings.lossScale, settings.lossCurrency)}`,
      formatVigorNumber(userScore),
    ];
  }

  function arithmetic(calculation: VigorCalculation) {
    return calculation.terms.map(({ weight, factor }) =>
      `${formatVigorNumber(weight)} × ${formatVigorNumber(factor ?? 0)}`).join(' + ');
  }
</script>

{#snippet breakdown(calculation: VigorCalculation, weekly: boolean)}
  {@const inputs = values(calculation, weekly)}
  <table class="breakdown" aria-label="Vigor calculation inputs">
    <thead><tr><th scope="col">Input</th><th scope="col">Value</th><th scope="col" class="numeric">Factor</th><th scope="col" class="numeric">Weight</th><th scope="col" class="numeric">Contribution</th></tr></thead>
    <tbody>
      {#each vigorFactors as metric, index (metric.key)}
        {@const term = calculation.terms[index]}
        <tr>
          <th scope="row">{metric.label} <code>({metric.variable})</code></th>
          <td>{inputs[index]}</td>
          <td class="numeric">{term.factor === undefined ? 'Unavailable' : formatVigorNumber(term.factor)}</td>
          <td class="numeric">{formatVigorNumber(term.weight)}</td>
          <td class="numeric">{formatVigorNumber(term.contribution)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if calculation.loss && calculation.tokens !== undefined}
    <div class="stack price-basis">
      <strong>Estimated token cost · {money(calculation.loss.perMillion, calculation.loss.currency)} per million</strong>
      <p class="small muted">{calculation.loss.basis}</p>
      <p class="small">Estimated loss =
        <code>{formatVigorTokens(calculation.tokens)} ÷ 1M × {money(calculation.loss.perMillion, calculation.loss.currency)}
          ≈ {money(calculation.loss.amount, calculation.loss.currency)}</code>
      </p>
    </div>
  {/if}
  {#if calculation.partial}
    <p class="small muted">Unavailable factors contribute zero.{#if calculation.loss && calculation.loss.currency !== settings.lossCurrency} The monetary factor uses {settings.lossCurrency}.{/if}</p>
  {/if}
  <p class="arithmetic">
    <code>{arithmetic(calculation)} ≈ {formatVigorNumber(calculation.sum)}</code>
    {#if calculation.exhausted}
      <span>Vigor = <strong>0</strong> while the allowance is exhausted.</span>
    {:else}
      <span>Vigor ≈ <strong>{formatVigorNumber(calculation.score)}</strong></span>
    {/if}
  </p>
{/snippet}

<section class="stack" aria-label="Subscriptions Vigor">
  <div class="row spread toolbar">
    <code class="formula">{variableFormula}</code>
    <div class="row">
      <Button label="Configure formula" onclick={configure} />
      <Button label="Refresh" busy={view.loading} disabled={!onRefresh} onclick={onRefresh}
        title="Reread subscription usage and account data" />
    </div>
  </div>
  {#if view.loading}
    <Notice message={rows?.length ? 'Refreshing Vigor…' : 'Loading Vigor…'} />
  {/if}
  {#if view.error}<Notice role="alert" tone="warning" message={view.error} />{/if}
  {#if dashProblem}<Notice role="alert" tone="warning" message={dashProblem} />{/if}
  {#each issues as issue (issue)}
    <Notice tone="warning" message={issue} />
  {/each}

  {#if rows?.length}
    <div class="table-scroll">
      <table class="ranking" aria-label="Subscriptions ranked by Vigor">
        <thead>
          <tr>
            <th scope="col">Subscription</th>
            <th scope="col">Quota Dash</th>
            <th scope="col" class="numeric">User Score</th>
            <th scope="col" class="numeric">Time Left</th>
            <th scope="col" class="numeric">Potential Loss</th>
            <th scope="col" class="numeric" title="Available output-token equivalents in thousands (K) or millions (M)">Available Tokens</th>
            <th scope="col" class="numeric">Vigor</th>
          </tr>
        </thead>
        <tbody>
          {#each rows as row, index (row.key)}
            {@const windowEnd = row.windowEnd}
            {@const open = expanded === row.key}
            {@const detailsId = panelId + '-details-' + index}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions (The disclosure button is the row's keyboard action.) -->
            <tr class="overview" onclick={(event) => rowClick(event, row.key)}>
              <th scope="row">
                <button class="disclosure" type="button" aria-expanded={open}
                  aria-controls={open ? detailsId : undefined} onclick={() => toggle(row.key)}>
                  <span class="chevron" class:open aria-hidden="true">›</span>
                  <span>
                    {row.name}
                    {#if row.windowLabel}<small class="window-label">{row.windowLabel}</small>{/if}
                  </span>
                </button>
              </th>
              <td class="dash-cell">
                {#if row.weekly && windowEnd !== undefined}
                  <button type="button" class="dash" class:marked={row.dash} aria-pressed={row.dash}
                    aria-label={`Quota Dash for ${row.name}`}
                    title={row.reason ?? (row.matches?.length ? row.matches.map(describeMatch).join('\n') : 'Mark the current weekly window as Quota Dash')}
                    onclick={() => mark(row.key, { windowEnd, marked: !row.dash })}>
                    {row.dash ? 'Dash activated!' : 'Off'}
                  </button>
                  {#if row.reason}
                    <small>{row.dash ? 'Manual' : 'Dismissed'}</small>
                  {:else if row.matches?.length}
                    <small>{row.matches.map(shortRule).join(' · ')}</small>
                  {/if}
                {:else}
                  <span class="muted" title="Quota Dash applies to weekly windows">—</span>
                {/if}
              </td>
              <td class="numeric">{row.userScore === undefined ? '—' : score.format(row.userScore)}</td>
              <td class="numeric">{row.current?.hoursLeft === undefined ? '—' : timeLeft(row.current.hoursLeft)}</td>
              <td class="numeric">
                {#if row.current?.loss?.currency === settings.lossCurrency}
                  <span title={`Estimated potential loss in ${settings.lossCurrency}`}>
                    ≈{money(row.current.loss.amount, settings.lossCurrency)}</span>
                {:else if row.current?.loss}
                  <span class="muted" title={`Estimate is in ${row.current.loss.currency}. The configured currency is ${settings.lossCurrency}.`}>—</span>
                {:else}
                  <span class="muted" title="Available equivalents or matching reference cost unavailable">—</span>
                {/if}
              </td>
              <td class="numeric">
                {row.current?.tokens === undefined ? '—' : formatVigorTokens(row.current.tokens)}
              </td>
              <td class="numeric vigor">
                <span class="vigor-score">{row.current === undefined ? '—' : score.format(row.current.score)}</span>
                {#if row.resetReady}<small>Reset ready</small>{/if}
                {#if row.next && windowEnd !== undefined}
                  <small title={row.next.partial ? 'Some projection inputs are unavailable.' : undefined}>
                    Next available ≈{score.format(row.next.score)}
                    <time datetime={new Date(windowEnd).toISOString()}>{timestamp.format(windowEnd)}</time>
                  </small>
                {/if}
              </td>
            </tr>
            {#if open}
              <tr class="detail" id={detailsId}>
                <td colspan="7">
                  {#if row.current && windowEnd !== undefined}
                    <div class="stack calculation">
                      <div class="row spread">
                        <strong>{row.windowLabel}</strong>
                        <span class="small muted">
                          {row.expires ? 'Expires' : 'Renews'}
                          {row.approximate ? ' around ' : ' '}
                          <time datetime={new Date(windowEnd).toISOString()}>{timestamp.format(windowEnd)}</time>
                        </span>
                      </div>
                      {#if row.reason || row.matches?.length}
                        <div class="stack dash-reasons">
                          {#if row.reason}<p class="small muted">{row.reason}</p>{/if}
                          {#if row.matches?.length}
                            <ul aria-label="Matching Quota Dash rules">
                              {#each row.matches as match (match.kind)}<li>{describeMatch(match)}</li>{/each}
                            </ul>
                          {/if}
                        </div>
                      {/if}
                      {#if row.weekly && (settings.dashThresholds?.projectedEtc !== undefined || row.monthlyForecast)}
                        <div class="row spread monthly-etc">
                          <div>
                            <strong>Projected monthly ETC</strong>
                            {#if row.monthlyForecast && row.projectedEtc !== undefined}
                              <p class="small muted">
                                {etcLabel(row.projectedEtc, row.monthlyForecast.currency)} ·
                                {timestamp.format(row.monthlyForecast.start)} to {timestamp.format(row.monthlyForecast.end)}
                              </p>
                              <p class="small muted">
                                {money(row.monthlyForecast.charge, row.monthlyForecast.currency)} ÷
                                ({formatVigorTokens(row.monthlyForecast.used)} used + {formatVigorTokens(row.monthlyForecast.expected)} expected) × 1M
                                · saved {timestamp.format(row.monthlyForecast.recordedAt)}
                              </p>
                            {:else}
                              <p class="small muted">Current billing period forecast unavailable.</p>
                            {/if}
                          </div>
                          <Button label="Edit forecast" onclick={() => (editingForecast = row.key)} />
                        </div>
                      {/if}
                      <dl class="window-total small">
                        <dt>Total tokens per window</dt>
                        <dd>{formatAllowanceTokenTotal(row.totalTokens)}</dd>
                      </dl>
                      {@render breakdown(row.current, row.weekly === true)}
                      {#if row.next}
                        <strong>Next available · {timestamp.format(windowEnd)}</strong>
                        <p class="small muted">Projected at the scheduled renewal.</p>
                        {@render breakdown(row.next, row.weekly === true)}
                      {/if}
                    </div>
                  {:else}
                    <p class="muted">{row.status ?? 'Current timed allowance unavailable.'}</p>
                  {/if}
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
  {:else if !view.loading && !view.error}
    <p class="muted">No subscriptions to rank.</p>
  {/if}
</section>

{#if configuring}
  <Modal title="Configure Vigor formula" width={560} onclose={() => (configuring = false)}>
    <form class="stack" novalidate onsubmit={saveSettings}>
      <p class="small muted">Each coefficient is its weight divided by the total weight.</p>
      <div class="settings-grid">
        {#each vigorFactors as factor (factor.key)}
          <label>
            <span>{factor.label} weight ({factor.coefficient})</span>
            <input type="number" min="0" step="any" bind:value={draft.weights[factor.key]} />
          </label>
        {/each}
        <label><span>Token scale (equivalents)</span><input type="number" min="0" step="any" bind:value={draft.tokenScale} /></label>
        <label><span>Loss scale</span><input type="number" min="0" step="any" bind:value={draft.lossScale} /></label>
        <label><span>Loss currency</span>
          <select bind:value={draft.lossCurrency}>
            {#each vigorCurrencies as currency (currency)}<option value={currency}>{currency}</option>{/each}
          </select>
        </label>
      </div>
      <fieldset>
        <legend>Automatic Quota Dash</legend>
        <p class="small muted">Leave a threshold blank to turn off its rule.</p>
        <div class="settings-grid">
          <label><span>Weekly required pace (Mach)</span><input type="number" min="0" step="any" bind:value={draft.dashThresholds.requiredPace} /></label>
          <label><span>Potential weekly loss ({draft.lossCurrency})</span><input type="number" min="0" step="any" bind:value={draft.dashThresholds.potentialLoss} /></label>
          <label><span>Projected monthly ETC ({draft.lossCurrency} per million)</span><input type="number" min="0" step="any" bind:value={draft.dashThresholds.projectedEtc} /></label>
        </div>
      </fieldset>
      {#if settingsProblem}<Notice role="alert" tone="warning" message={settingsProblem} />{/if}
      <div class="row spread">
        <Button label="Use defaults" tone="ghost" onclick={useDefaults} />
        <div class="row">
          <Button label="Cancel" onclick={() => (configuring = false)} />
          <Button label="Save" tone="primary" type="submit" />
        </div>
      </div>
    </form>
  </Modal>
{/if}

{#if forecastRow}
  <VigorEtcEditor name={forecastRow.name} forecast={forecastRow.monthlyForecast} currency={settings.lossCurrency}
    now={view.priority?.now ?? Date.now()} onSave={forecast => saveForecast(forecastRow.key, forecast)}
    onClose={() => (editingForecast = undefined)} />
{/if}

<style>
  .toolbar { gap: var(--space-3); }
  .formula { padding-block: var(--space-2); font-weight: 650; }
  .table-scroll {
    overflow-x: auto;
    inline-size: fit-content;
    max-inline-size: 100%;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--panel);
  }
  table { width: 100%; border-collapse: collapse; }
  .ranking { inline-size: max-content; }
  .ranking > thead th, .ranking > tbody > .overview > td { white-space: nowrap; }
  th, td { padding: var(--space-3) var(--space-4); text-align: start; }
  thead th { color: var(--muted); font-size: .85em; }
  tbody th { font-weight: 650; }
  tbody tr { border-top: 1px solid var(--border); }
  .numeric { text-align: end; font-variant-numeric: tabular-nums; }
  .vigor-score { font-size: 1.25em; font-weight: 750; }
  .vigor small { display: block; margin-top: 2px; color: var(--muted); font-weight: 600; }
  .vigor small time { display: block; }
  .dash-cell small { display: block; max-inline-size: 18ch; margin-top: 4px; color: var(--muted); white-space: normal; }
  .dash-reasons ul { margin-block: 0; padding-inline-start: var(--space-4); }
  .monthly-etc { padding-block: var(--space-2); }
  .overview, .disclosure, .dash { cursor: pointer; }
  .overview:hover, .detail { background: var(--inset); }
  .disclosure {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: 3px 0;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: start;
    max-inline-size: 34ch;
    overflow-wrap: anywhere;
  }
  .chevron { color: var(--accent); font-size: 1.2em; line-height: 1; }
  .chevron.open { transform: rotate(90deg); }
  .window-label { display: block; color: var(--muted); font-weight: 400; }
  .dash {
    min-height: 28px;
    padding: 2px 0;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    font-weight: 400;
  }
  .dash:hover { text-decoration: underline; }
  .dash.marked { color: var(--success); font-weight: 750; }
  .calculation { contain: inline-size; gap: var(--space-3); }
  .window-total { display: flex; flex-wrap: wrap; gap: var(--space-2); margin: 0; }
  .window-total dt { color: var(--muted); }
  .window-total dd { margin: 0; font-variant-numeric: tabular-nums; }
  .price-basis { gap: var(--space-1); }
  .breakdown th, .breakdown td { padding: var(--space-2); }
  .breakdown code { color: var(--muted); }
  .arithmetic { display: grid; gap: var(--space-1); }
  .settings-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(180px, 100%), 1fr)); gap: var(--space-3); }
  .settings-grid label { display: grid; gap: var(--space-1); }
  fieldset { display: grid; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-md); }
  legend { padding-inline: var(--space-1); font-weight: 650; }
  .settings-grid input, .settings-grid select {
    width: 100%;
    min-width: 0;
    min-height: var(--control-height);
    padding-inline: var(--space-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--inset);
    color: var(--text);
  }
</style>
