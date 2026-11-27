import {
  defaultSubscriptionUserScore, isSubscriptionUserScore, subscriptionKey, type SubscriptionListing,
} from '../../design-system/src/sections/seqoya-subscriptions';

const storageKey = 'arbol-seqoya:user-scores';
type UserScores = Record<string, number>;

export function readUserScores(): UserScores {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(storageKey) ?? '{}');
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      return Object.fromEntries(Object.entries(saved).filter(([, score]) => isSubscriptionUserScore(score)));
    }
  } catch {
    // Existing scores are optional when local storage is unavailable.
  }
  return {};
}

export function saveUserScore(driver: string, subscription: string, score: number): UserScores {
  if (!isSubscriptionUserScore(score)) throw new Error('Enter a number from 0 to 1.');
  const scores = { ...readUserScores(), [subscriptionKey(driver, subscription)]: score };
  localStorage.setItem(storageKey, JSON.stringify(scores));
  return scores;
}

export function withUserScores(listing: SubscriptionListing | undefined, scores: UserScores): SubscriptionListing | undefined {
  if (!listing) return undefined;
  return { drivers: listing.drivers.map(entry => ({
    ...entry,
    subscriptions: entry.subscriptions?.map(account => ({
      ...account,
      userScore: scores[subscriptionKey(entry.driver, account.id)] ?? defaultSubscriptionUserScore,
    })),
  })) };
}
