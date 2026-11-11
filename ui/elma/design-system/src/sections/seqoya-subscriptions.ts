/** Read-only fields from the public accounts.list reply used by Seqoya Lab. */
export interface SubscriptionRecord {
  id: string;
  label: string;
  family: string;
  auth: string;
  state: string;
  problem?: { message: string };
  activity?: SubscriptionActivity;
  activityError?: string;
  lastUsage?: {
    fetchedAt: string;
    plan?: string;
    windows: {
      label: string;
      resource?: 'tokens' | 'credits' | 'calls';
      usedPercent?: number;
      resetsAt?: string;
      limitReached?: boolean;
    }[];
    extra?: {
      balances?: { currency: 'USD' | 'CNY'; amount: string }[];
      apiAvailable?: boolean;
    };
  };
}

export interface SubscriptionActivity {
  runCount: number;
  inputTokens?: string;
  outputTokens?: string;
  lastRunAt?: string;
}

export interface SubscriptionListing {
  drivers: {
    driver: string;
    subscriptions?: SubscriptionRecord[];
    error?: { message: string };
  }[];
}

export interface SubscriptionView {
  connected: boolean;
  loading?: boolean;
  listing?: SubscriptionListing;
  error?: string;
  usageRequests?: Record<string, { pending?: boolean; error?: string }>;
  consoleError?: string;
}

export function subscriptionKey(driver: string, subscription: string): string {
  return JSON.stringify([driver, subscription]);
}
