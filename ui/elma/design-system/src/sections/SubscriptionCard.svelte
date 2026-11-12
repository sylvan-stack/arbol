<script lang="ts">
  import Button from '../components/Button.svelte';
  import InlineRename from '../patterns/InlineRename.svelte';
  import SubscriptionAllowance from './SubscriptionAllowance.svelte';
  import {
    canRefreshSubscriptionUsage, formatSubscriptionCardTime, sortAllowanceWindows, subscriptionKey, subscriptionName,
    type OpenSubscriptionUsage, type RenameSubscription, type SubscriptionRecord, type SubscriptionView,
  } from './seqoya-subscriptions';

  let { driver, subscription, view, onRefreshUsage, onOpenUsage, onRename }: {
    driver: string;
    subscription: SubscriptionRecord;
    view: SubscriptionView;
    onRefreshUsage?: (driver: string, subscription: string) => void;
    onOpenUsage?: OpenSubscriptionUsage;
    onRename?: RenameSubscription;
  } = $props();
  let draft = $state('');
  let editing = $state<SubscriptionRecord>();
  let saving = $state(false);
  let problem = $state('');
  const key = $derived(subscriptionKey(driver, subscription.id));
  const name = $derived(subscriptionName(driver, subscription));
  const metrics = $derived(subscription.metrics);
  const resets = $derived(metrics?.limitResets);
  const deepseek = $derived(subscription.family === 'deepseek');
  const mimo = $derived(subscription.family === 'xiaomi' && driver === 'mimo');
  const destination = $derived(mimo ? 'mimo' : subscription.family === 'chatgpt' && ['pi', 'codex'].includes(driver) ? 'chatgpt' : undefined);
  const refreshable = $derived(canRefreshSubscriptionUsage(driver, subscription) && onRefreshUsage);
  const request = $derived(view.usageRequests?.[key]);

  function startEdit() {
    editing = subscription;
    draft = name;
    problem = '';
  }
  async function saveName() {
    if (!editing || !onRename || saving) return;
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
  {#if editing}
    <InlineRename label="Subscription name" value={draft} max={256} busy={saving} {problem}
      oninput={value => draft = value} onsave={() => void saveName()} oncancel={() => { editing = undefined; problem = ''; }} />
  {:else}
    <div class="subscription-heading">
      <h2>{name}</h2>
      {#if onRename}
        <button class="edit-name" onclick={startEdit} disabled={!view.connected} aria-label={'Edit ' + name}>Edit</button>
      {/if}
    </div>
  {/if}
  {#if view.nameNotices?.[key]}<p class="small warning" role="status">{view.nameNotices[key]}</p>{/if}
  {#if subscription.problem}<p class="small warning">{subscription.problem.message}</p>{/if}

  {#each sortAllowanceWindows(metrics?.windows ?? []) as window}
    <SubscriptionAllowance {window} apiAccess={deepseek} />
  {:else}
    <p class="small muted">No saved allowance windows.</p>
  {/each}

  {#each metrics?.issues ?? [] as issue}<p class="small warning">{issue}</p>{/each}
  {#if deepseek && subscription.lastUsage?.extra?.apiAvailable === false}
    <p class="small warning">The balance is insufficient for API calls.</p>
  {/if}
  {#if refreshable || destination && onOpenUsage}
    <div class="row usage-actions">
      {#if refreshable}
        <Button label="Refresh usage" onclick={() => onRefreshUsage?.(driver, subscription.id)}
          busy={request?.pending} disabled={!view.connected} />
      {/if}
      {#if destination && onOpenUsage}
        <Button label={mimo ? 'Open MiMo console' : 'Open ChatGPT Usage'} tone="ghost"
          disabled={destination === 'chatgpt' && !view.connected}
          onclick={() => onOpenUsage?.(destination, driver, subscription.id)} />
      {/if}
    </div>
  {/if}
  {#if request?.error}<p class="small warning" role="status">{request.error}</p>{/if}
  {#if view.usageLinkErrors?.[key]}<p class="small warning" role="status">{view.usageLinkErrors[key]}</p>{/if}

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
  .reset-grants { margin: 0; padding-left: 20px; }
</style>
