/** Read-only fields from the public accounts.list reply used by Seqoya Lab. */
export interface SubscriptionRecord {
  id: string;
  label: string;
  family: string;
  auth: string;
  state: string;
  problem?: { message: string };
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
  };
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
}
