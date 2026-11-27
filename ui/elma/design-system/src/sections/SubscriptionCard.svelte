<script lang="ts">
  import { tick } from 'svelte';
  import Button from '../components/Button.svelte';
  import InlineRename from '../patterns/InlineRename.svelte';
  import SubscriptionAllowance from './SubscriptionAllowance.svelte';
  import {
    defaultSubscriptionUserScore, formatSubscriptionCardTime, isSubscriptionUserScore, sortAllowanceWindows,
    subscriptionKey, subscriptionName, subscriptionProviderOrder, subscriptionVendor,
    type OpenSubscriptionUsage, type RenameSubscription, type SubscriptionAvailability, type SubscriptionRecord, type SubscriptionView,
  } from './seqoya-subscriptions';

  let { driver, subscription, view, availability, onOpenUsage, onRename }: {
    driver: string;
    subscription: SubscriptionRecord;
    view: SubscriptionView;
    availability?: SubscriptionAvailability;
    onOpenUsage?: OpenSubscriptionUsage;
    onRename?: RenameSubscription;
  } = $props();
  let draft = $state('');
  let editing = $state<SubscriptionRecord>();
  let saving = $state(false);
  let problem = $state('');
  let scoreDraft = $state<string>();
  let scoreError = $state('');
  let scoreInvalid = $state(false);
  let scoreInput = $state<HTMLInputElement>();
  let scoreButton = $state<HTMLButtonElement>();
  const scoreErrorId = $props.id();
  const userScore = $derived(subscription.userScore ?? defaultSubscriptionUserScore);
  const key = $derived(subscriptionKey(driver, subscription.id));
  const name = $derived(subscriptionName(driver, subscription));
  const metrics = $derived(subscription.metrics);
  const resets = $derived(metrics?.limitResets);
  const payAsYouGo = $derived(driver === 'pi' && ['deepseek', 'minimax'].includes(subscription.family));
  const provider = $derived(subscriptionProviderOrder.has(subscriptionKey(driver, subscription.family))
    ? subscriptionVendor(driver, subscription.family) : undefined);

  async function editUserScore(event: MouseEvent) {
    if (!event.altKey && event.detail !== 0) return;
    scoreDraft = String(userScore);
    await tick();
    scoreInput?.focus();
    scoreInput?.select();
  }

  async function closeUserScore() {
    scoreDraft = undefined;
    scoreError = '';
    scoreInvalid = false;
    await tick();
    scoreButton?.focus();
  }

  function saveUserScore(event: SubmitEvent) {
    event.preventDefault();
    if (availability) return;
    const text = scoreDraft?.trim() ?? '';
    const score = /^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:e[+-]?\d+)?$/i.test(text) ? Number(text.replace(',', '.')) : NaN;
    if (!isSubscriptionUserScore(score)) {
      scoreInvalid = true;
      scoreError = 'Enter a number from 0 to 1.';
      scoreInput?.focus();
      return;
    }
    try {
      view.saveUserScore?.(driver, subscription, score);
      void closeUserScore();
    } catch {
      scoreError = 'Could not save the score. Your edit is still here.';
    }
  }

  function startEdit() {
    editing = subscription;
    draft = name;
    problem = '';
  }
  async function saveName() {
    if (!editing || !onRename || availability || saving) return;
    const value = draft.trim();
    if (!value) { problem = 'Enter a subscription name.'; return; }
    if (Array.from(value).length > 256 || /[\u0000-\u001f\u007f]/.test(value)) {
      problem = 'Use one line with at most 256 characters.'; return;
    }
    saving = true;
    problem = '';
    try {
      await onRename(driver, editing, value);
      editing = undefined;
    } catch (error) {
      problem = error instanceof Error ? error.message : 'Could not save this name. Your text is kept.';
    } finally { saving = false; }
  }
</script>

<li class="panel stack account">
  {#if editing && !availability}
    <InlineRename label="Subscription name" value={draft} max={256} busy={saving} {problem}
      oninput={value => draft = value} onsave={() => void saveName()} oncancel={() => { editing = undefined; problem = ''; }} />
  {:else}
    <div class="subscription-heading">
      <h2>{name}</h2>
      {#if onRename && !availability}
        <button class="edit-name" onclick={startEdit} disabled={!view.connected} aria-label={'Edit ' + name}>Edit</button>
      {/if}
    </div>
  {/if}
  {#if availability === 'unverified'}
    <p class="small warning">Account details unavailable.</p>
  {:else}
    {#if availability === 'stale'}<p class="small warning">Showing last known account details.</p>{/if}
    {#if view.nameNotices?.[key]}<p class="small warning" role="status">{view.nameNotices[key]}</p>{/if}
    {#if subscription.problem}<p class="small warning">{subscription.problem.message}</p>{/if}

    {#if payAsYouGo}
      {#if metrics?.balance}
        <SubscriptionAllowance balance={metrics.balance} />
      {:else}
        <p class="small muted">No saved API balance.</p>
      {/if}
    {/if}
    {#if !payAsYouGo || metrics?.windows.length}
      {#each sortAllowanceWindows(metrics?.windows ?? []) as window}
        <SubscriptionAllowance {window} />
      {:else}
        <p class="small muted">No saved allowance windows.</p>
      {/each}
    {/if}

    {#each metrics?.issues ?? [] as issue}<p class="small warning">{issue}</p>{/each}
    {#if provider && onOpenUsage && !availability}
      <div class="row usage-actions">
        <Button label={view.usageOpening === key ? 'Verifying and opening…' : 'Open in ' + provider} tone="ghost" busy={view.usageOpening === key}
          disabled={!view.connected || (!!view.usageOpening && view.usageOpening !== key)}
          onclick={() => onOpenUsage?.(driver, subscription.id)} />
      </div>
    {/if}
    {#if provider && view.usageOpened?.key === key && view.usageOpened.createdAt === subscription.createdAt
      && view.usageOpened.family === subscription.family && subscription.state === 'signed_in'}
      <p class="small muted" role="status">Opened in Arbol Browser.</p>
    {/if}
    {#if view.usageLinkErrors?.[key]}<p class="small warning" role="status">{view.usageLinkErrors[key]}</p>{/if}

    {#if !payAsYouGo && !metrics?.balance && (view.saveUserScore || subscription.userScore !== undefined)}
      <dl class="metrics user-score">
        <dt>User score</dt>
        <dd>
          {#if scoreDraft !== undefined && !availability}
            <form class="score-editor" onsubmit={saveUserScore}>
              <input type="text" inputmode="decimal" aria-label={'User score for ' + name}
                aria-invalid={scoreInvalid} aria-describedby={scoreError ? scoreErrorId : undefined}
                bind:this={scoreInput} bind:value={scoreDraft}
                oninput={() => { scoreError = ''; scoreInvalid = false; }}
                onkeydown={(event) => {
                  if (event.key === 'Escape' && !event.isComposing) {
                    event.preventDefault();
                    event.stopPropagation();
                    void closeUserScore();
                  }
                }} />
              <button type="submit">Save</button>
              <button type="button" onclick={closeUserScore}>Cancel</button>
              {#if scoreError}<span class="small warning" id={scoreErrorId} role="alert">{scoreError}</span>{/if}
            </form>
          {:else if view.saveUserScore && !availability}
            <button type="button" class="score-value" bind:this={scoreButton} title="Option-click to edit"
              aria-label={'Edit user score for ' + name + ', current score ' + userScore}
              onclick={editUserScore}>{userScore}</button>
          {:else}
            {userScore}
          {/if}
        </dd>
      </dl>
    {/if}

    {#if resets?.count !== undefined && resets.count > 0}
      <div class="reset-section stack">
        <dl class="metrics"><dt>Available limit resets</dt><dd>{resets.count}</dd></dl>
        {#if resets.entries.some(reset => !reset.expired)}
          <ul class="reset-grants">
            {#each resets.entries.filter(reset => !reset.expired) as reset}
              <li>{reset.label}{#if reset.expiresAt === 0} · Never expires
                {:else if reset.expiresAt} · Expires <time datetime={reset.expiresAt}>{formatSubscriptionCardTime(reset.expiresAt)}</time>{/if}</li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}
  {/if}
</li>

<style>
  .account { gap: 16px; padding: 16px; overflow-wrap: anywhere; }
  .subscription-heading { display: flex; align-items: center; gap: 8px; min-height: 30px; }
  h2 { margin: 0; }
  .edit-name { opacity: 0; border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 2px 7px; background: transparent; color: var(--muted); font: inherit; font-size: .8em; }
  .subscription-heading:hover .edit-name, .subscription-heading:focus-within .edit-name { opacity: 1; }
  .edit-name:disabled { color: var(--disabled); }
  @media (hover: none) { .edit-name { opacity: 1; } }
  .usage-actions { flex-wrap: wrap; }
  .reset-section { margin-top: auto; gap: 8px; border-top: 1px solid var(--border); padding-top: 12px; }
  .metrics { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px 16px; margin: 0; }
  .metrics dt { color: var(--muted); }
  .metrics dd { margin: 0; text-align: end; font-variant-numeric: tabular-nums; }
  .user-score { grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); align-items: baseline; }
  .score-value, .score-editor button {
    border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 2px 7px;
    background: transparent; color: var(--text); font: inherit; cursor: pointer;
  }
  .score-value { border-color: transparent; text-decoration: underline dotted var(--muted); }
  .score-value:hover { border-color: var(--border); }
  .score-editor { display: flex; justify-content: end; flex-wrap: wrap; gap: 4px; }
  .score-editor input {
    width: 6ch; max-width: 100%; padding: 2px 5px; border: 1px solid var(--border);
    border-radius: var(--radius-sm); background: var(--inset); color: var(--text); font: inherit;
  }
  .score-editor [role="alert"] { flex-basis: 100%; }
  .reset-grants { margin: 0; padding-left: 20px; }
</style>
