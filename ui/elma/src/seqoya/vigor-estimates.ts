import {
  subscriptionKey, type SubscriptionListing, type SubscriptionRecord,
} from '../../design-system/src/sections/seqoya-subscriptions';
import {
  calculateVigor, rankVigorEntries, type VigorEntry, type VigorRollup,
} from '../../design-system/src/sections/seqoya-vigor';

const tokensPerRate = 1_000_000;
// Peak output price per million tokens for deepseek-flash, checked 2026-11-12.
// https://api-docs.deepseek.com/quick_start/pricing/
// https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
const deepSeekRates = { USD: 1.2, CNY: 8 };
const inactiveStates = new Map([
  ['signed_out', 'Signed out.'],
  ['needs_attention', 'This account needs attention before it can be used.'],
  ['signing_in', 'Sign-in is still in progress.'],
]);

export function deepSeekBalance(account: SubscriptionRecord) {
  const usage = account.lastUsage;
  if (account.family !== 'deepseek' || account.auth !== 'key' && account.auth !== 'api_key'
    || usage?.windows.some((window) => window.resetsAt)) return undefined;

  let largest: { amount: string; currency: 'USD' | 'CNY'; tokens: number; rate: number } | undefined;
  for (const { currency, amount } of usage?.extra?.balances ?? []) {
    const rate = deepSeekRates[currency];
    const balance = Number(amount);
    if (!rate || !Number.isFinite(balance)) continue;
    const tokens = Math.max(0, balance) / rate * tokensPerRate;
    if (!largest || tokens > largest.tokens) largest = { amount, currency, tokens, rate };
  }
  return largest;
}

export function rankVigor(rollup: VigorRollup | undefined, listing: SubscriptionListing | undefined, now: number): VigorEntry[] | undefined {
  if (!rollup && !listing) return undefined;
  const saved = new Map((rollup?.subscriptions ?? []).map(entry => [
    subscriptionKey(entry.driver, entry.subscription), entry.result,
  ]));
  if (!listing) return rollup?.subscriptions.map(entry => ({
    ...entry, plan: calculateVigor(entry.driver, undefined, now, 'Waiting for subscription metrics.'),
  }));
  const entries = listing.drivers.flatMap(({ driver, subscriptions }) => (subscriptions ?? []).map(account => {
    const { id: subscription, label, family, activity, activityError, allowance } = account;
    const inactive = inactiveStates.get(account.state);
    const unavailable = inactive && (account.problem?.message || inactive);
    const reason = account.state === 'signed_in' ? undefined : unavailable ?? 'Sign-in status is unavailable.';
    return {
      driver, subscription, label, family, activity, activityError, allowance, unavailable,
      result: saved.get(subscriptionKey(driver, subscription)) ?? null,
      plan: calculateVigor(driver, account, now, reason),
    };
  }));
  return rankVigorEntries(entries);
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
