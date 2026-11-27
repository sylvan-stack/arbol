<script lang="ts">
  import { untrack } from 'svelte';
  import Button from '../components/Button.svelte';
  import Modal from '../patterns/Modal.svelte';
  import Notice from '../patterns/Notice.svelte';
  import { isMonthlyEtcForecast, vigorCurrencies, type MonthlyEtcForecast, type VigorCurrency } from './seqoya-vigor-priority';

  let { name, forecast, currency, now, onSave, onClose }: {
    name: string;
    forecast?: MonthlyEtcForecast;
    currency: VigorCurrency;
    now: number;
    onSave: (forecast?: MonthlyEtcForecast) => void;
    onClose: () => void;
  } = $props();
  const initial = untrack(() => ({ forecast, currency }));
  let start = $state(localInput(initial.forecast?.start));
  let end = $state(localInput(initial.forecast?.end));
  let charge = $state(initial.forecast?.charge);
  let billingCurrency = $state(initial.forecast?.currency ?? initial.currency);
  let used = $state(initial.forecast?.used);
  let expected = $state(initial.forecast?.expected);
  let problem = $state('');

  function localInput(time?: number) {
    if (time === undefined) return '';
    const date = new Date(time);
    return new Date(time - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 19);
  }

  function apply(value?: MonthlyEtcForecast) {
    try {
      onSave(value);
      onClose();
    } catch {
      problem = 'Could not save the monthly ETC forecast.';
    }
  }

  function submit(event: SubmitEvent) {
    event.preventDefault();
    const value = { start: new Date(start).getTime(), end: new Date(end).getTime(),
      charge, currency: billingCurrency, used, expected, recordedAt: now };
    if (!isMonthlyEtcForecast(value)) {
      problem = 'Enter the current billing period dates, a charge, and nonnegative usage and forecast amounts.';
      return;
    }
    apply(value);
  }
</script>

<Modal title="Monthly ETC forecast" description={name} width={570} onclose={onClose}>
  <form class="stack" novalidate onsubmit={submit}>
    <div class="fields">
      <label><span>Billing period starts</span><input type="datetime-local" step="1" bind:value={start} /></label>
      <label><span>Next billing date</span><input type="datetime-local" step="1" bind:value={end} /></label>
      <label><span>Charge for the full period</span><input type="number" min="0" step="any" bind:value={charge} /></label>
      <label><span>Billing currency</span><select bind:value={billingCurrency}>
        {#each vigorCurrencies as option (option)}<option value={option}>{option}</option>{/each}
      </select></label>
      <label><span>Equivalents used so far</span><input type="number" min="0" step="any" bind:value={used} /></label>
      <label><span>Expected additional equivalents</span><input type="number" min="0" step="any" bind:value={expected} /></label>
    </div>
    <p class="small muted">Use the actual billing dates and your expected usage through renewal. Dates use local time.</p>
    {#if problem}<Notice role="alert" tone="warning" message={problem} />{/if}
    <div class="row spread">
      <div>{#if forecast}<Button label="Clear forecast" tone="ghost" onclick={() => apply()} />{/if}</div>
      <div class="row"><Button label="Cancel" onclick={onClose} /><Button label="Save" tone="primary" type="submit" /></div>
    </div>
  </form>
</Modal>

<style>
  .fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(210px, 100%), 1fr)); gap: var(--space-3); }
  label { display: grid; gap: var(--space-1); }
  input, select {
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
