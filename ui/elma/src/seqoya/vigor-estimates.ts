import {
  subscriptionKey, type SubscriptionListing, type SubscriptionRecord,
} from '../../design-system/src/sections/seqoya-subscriptions';
import {
  displayedVigor, type VigorEntry, type VigorRollup,
} from '../../design-system/src/sections/seqoya-vigor';

const provisional = 0.05;
const tokensPerRate = 1_000_000;
const capacityCeiling = 0.5;
// Peak output price per million tokens for deepseek-flash, checked 2026-11-12.
// https://api-docs.deepseek.com/quick_start/pricing/
// https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
const deepSeekRates = { USD: 1.2, CNY: 8 };
const inactiveStates = new Map([
  ['signed_out', 'Signed out.'],
  ['needs_attention', 'This account needs attention before it can be used.'],
  ['signing_in', 'Sign-in is still in progress.'],
]);

type Estimate = NonNullable<VigorEntry['estimate']>;

function deepSeekEstimate(account: SubscriptionRecord, entry: VigorEntry): Estimate | undefined {
  const usage = account.lastUsage;
  if (account.family !== 'deepseek' || account.auth !== 'key' && account.auth !== 'api_key'
    || entry.result?.nextChange || usage?.windows.some((window) => window.resetsAt)) return undefined;

  let largest: { amount: string; currency: 'USD' | 'CNY'; tokens: number; rate: number } | undefined;
  for (const { currency, amount } of usage?.extra?.balances ?? []) {
    const rate = deepSeekRates[currency];
    const balance = Number(amount);
    if (!rate || !Number.isFinite(balance)) continue;
    const tokens = Math.max(0, balance) / rate * tokensPerRate;
    if (!largest || tokens > largest.tokens) largest = { amount, currency, tokens, rate };
  }
  if (!largest) return undefined;

  const { amount, currency, tokens, rate } = largest;
  return {
    score: capacityCeiling * tokens / (tokens + tokensPerRate),
    exhausted: tokens === 0,
    reason: 'Saved balance ' + amount + ' ' + currency + '.',
    budget: { amount, tokens, currency, rate, referenceTokens: tokensPerRate, ceiling: capacityCeiling },
  };
}

function scoreEntry(entry: VigorEntry, account: SubscriptionRecord | undefined): VigorEntry {
  const inactive = account && inactiveStates.get(account.state);
  if (inactive) return { ...entry, unavailable: account?.problem?.message || inactive };
  if (entry.result?.vigor != null) return entry;
  if (entry.result?.exhausted || account?.lastUsage?.extra?.apiAvailable === false) {
    return { ...entry, estimate: { score: 0, exhausted: true, reason: 'The reported allowance is exhausted.' } };
  }
  if (account?.state !== 'signed_in') {
    return { ...entry, estimate: { score: provisional, reason: 'Provisional score. Sign-in status could not be confirmed.' } };
  }
  const estimate = deepSeekEstimate(account, entry) ?? {
    score: provisional,
    reason: 'Provisional score while usable allowance data is missing.',
  };
  return { ...entry, estimate };
}

export function rankVigor(rollup?: VigorRollup, listing?: SubscriptionListing): VigorEntry[] | undefined {
  if (!rollup && !listing) return undefined;
  const entries = new Map((rollup?.subscriptions ?? []).map((entry) => [
    subscriptionKey(entry.driver, entry.subscription), entry,
  ]));
  const accounts = new Map<string, SubscriptionRecord>();
  for (const { driver, subscriptions } of listing?.drivers ?? []) {
    for (const account of subscriptions ?? []) {
      const key = subscriptionKey(driver, account.id);
      accounts.set(key, account);
      if (!entries.has(key)) {
        entries.set(key, {
          driver, subscription: account.id, label: account.label, family: account.family, result: null,
        });
      }
    }
  }
  return [...entries].map(([key, entry]) => {
    const account = accounts.get(key);
    return scoreEntry({ ...entry, activity: account?.activity, activityError: account?.activityError }, account);
  })
    .sort((left, right) => (displayedVigor(right) ?? -1) - (displayedVigor(left) ?? -1));
}

export function retainAccounts(next: SubscriptionListing, previous?: SubscriptionListing): SubscriptionListing {
  const earlier = new Map(previous?.drivers.map((entry) => [entry.driver, entry.subscriptions]));
  return {
    drivers: next.drivers.map((entry) => entry.error
      ? { ...entry, subscriptions: earlier.get(entry.driver) }
      : entry),
  };
}

export function retainVigor(next: VigorRollup, previous?: VigorRollup): VigorRollup {
  const received = new Set(next.subscriptions.map((row) => subscriptionKey(row.driver, row.subscription)));
  const retained = previous?.subscriptions.filter((row) =>
    Object.hasOwn(next.failures, row.driver) && !received.has(subscriptionKey(row.driver, row.subscription))) ?? [];
  return { ...next, subscriptions: [...next.subscriptions, ...retained] };
}
