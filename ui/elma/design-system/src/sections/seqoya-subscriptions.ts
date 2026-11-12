interface ModelLabel {
  model?: string;
  performance: 'Top' | 'High' | 'Medium' | 'Low';
  cost: 'Expensive' | 'Moderate' | 'Cheap';
}

export type SubscriptionModelLabels = readonly [
  defaultModel: ModelLabel,
  ...additionalModels: (ModelLabel & { model: string })[],
];

/** Account data displayed by Seqoya Lab, including optional renderer annotations. */
export interface SubscriptionRecord {
  id: string;
  label: string;
  family: string;
  auth: string;
  state: string;
  modelLabels?: SubscriptionModelLabels;
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

const vendors = new Map([
  ['anthropic', 'Claude Code'],
  ['chatgpt', 'ChatGPT'],
  ['kimi-coding', 'Kimi Code'],
  ['zai', 'z.ai'],
  ['deepseek', 'DeepSeek'],
  ['xiaomi', 'MiMo'],
]);

export function subscriptionVendor(driver: string, family: string): string {
  return driver === 'codex' && family === 'chatgpt' ? 'Codex' : (vendors.get(family) ?? family);
}

const dateTime = new Intl.DateTimeFormat(undefined, {
  year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  timeZoneName: 'short',
});

export function formatSubscriptionTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Time unavailable' : dateTime.format(date);
}
