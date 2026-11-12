import {
  subscriptionKey, type SubscriptionListing, type SubscriptionModelLabels,
} from '../../design-system/src/sections/seqoya-subscriptions';

const modelLabelsByDriverAndFamily = new Map<string, SubscriptionModelLabels>([
  [subscriptionKey('claude', 'anthropic'), [
    { model: 'Opus 5.5', performance: 'Top', cost: 'Expensive' },
  ]],
  [subscriptionKey('codex', 'chatgpt'), [
    { model: 'GPT-6.1-Sol', performance: 'Top', cost: 'Expensive' },
    { model: 'GPT-6-Astra', performance: 'Top', cost: 'Expensive' },
  ]],
  [subscriptionKey('pi', 'kimi-coding'), [{ performance: 'High', cost: 'Moderate' }]],
  [subscriptionKey('pi', 'zai'), [{ performance: 'Medium', cost: 'Moderate' }]],
  [subscriptionKey('pi', 'deepseek'), [{ performance: 'Medium', cost: 'Cheap' }]],
  [subscriptionKey('mimo', 'xiaomi'), [{ performance: 'Low', cost: 'Cheap' }]],
]);

export function withModelLabels(listing: SubscriptionListing): SubscriptionListing {
  return {
    drivers: listing.drivers.map((entry) => ({
      ...entry,
      subscriptions: entry.subscriptions?.map((subscription) => {
        const modelLabels = modelLabelsByDriverAndFamily.get(subscriptionKey(entry.driver, subscription.family));
        return modelLabels ? { ...subscription, modelLabels } : subscription;
      }),
    })),
  };
}
