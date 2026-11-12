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
  createdAt?: string;
  updatedAt?: string;
  allowance?: AllowanceView;
  metrics?: SubscriptionMetrics;
  modelLabels?: SubscriptionModelLabels;
  problem?: { message: string };
  activity?: SubscriptionActivity;
  activityError?: string;
  lastUsage?: {
    fetchedAt: string;
    plan?: string;
    windows: {
      label: string;
      kind?: 'session' | 'weekly' | 'other';
      windowMinutes?: number;
      resource?: 'tokens' | 'credits' | 'calls';
      usedPercent?: number;
      resetsAt?: string;
      limitReached?: boolean;
    }[];
    extra?: {
      balances?: { currency: 'USD' | 'CNY'; amount: string }[];
      apiAvailable?: boolean;
      planCredits?: { total: string; remaining: string };
      rateLimitResetCredits?: unknown;
    };
  };
}

export interface SubscriptionWindow {
  label: string;
  windowMinutes?: number;
  resetsAt?: string | null;
  expiresAt?: string | 0;
  remainingMinutes?: number;
  usedPercent?: number;
  remainingPercent?: number;
  outputTokensUsed?: number;
  outputTokensRemaining?: number;
  outputTokensPerHour?: number;
  model?: string;
  estimateBasis?: string;
  source?: string;
  observedAt?: string;
  terminal?: boolean;
  ended?: boolean;
}

export interface SubscriptionMetrics {
  windows: SubscriptionWindow[];
  limitResets?: {
    count?: number;
    observedAt?: string;
    entries: { label: string; expiresAt?: string | 0; expired?: boolean }[];
  };
}

export type UsageDestination = 'chatgpt' | 'mimo';

export interface AllowanceView {
  quota?: {
    source: string;
    plan?: string;
    observedAt?: string;
    note?: string;
    credits?: { total: string; remaining: string };
    windows: { label: string; remainingPercent?: number; resetsAt?: string; windowMinutes?: number; elapsed?: boolean }[];
  };
  capacity?: {
    model: string;
    total: number;
    remaining?: number;
    source: string;
    calculation: string;
  };
  issues?: string[];
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
  usageLinkErrors?: Partial<Record<UsageDestination, string>>;
  evidenceError?: string;
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
