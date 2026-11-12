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
  checkedAt?: string;
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
  pendingStart?: boolean;
  next?: 'projected' | 'awaitingRenewal';
}

export interface SubscriptionMetrics {
  issues?: string[];
  windows: SubscriptionWindow[];
  passedBoundaries?: number[];
  limitResets?: {
    count?: number;
    observedAt?: string;
    entries: { label: string; expiresAt?: string | 0; expired?: boolean }[];
  };
}

export type RenameSubscription = (
  driver: string, account: SubscriptionRecord, name: string,
) => Promise<void>;

export type AllowanceWindowType = '5h' | 'week' | 'month' | 'other';

export function allowanceWindowType(window: SubscriptionWindow): AllowanceWindowType {
  if (window.windowMinutes === 300) return '5h';
  if (window.windowMinutes === 10_080) return 'week';
  if (window.windowMinutes !== undefined && window.windowMinutes >= 28 * 1440 && window.windowMinutes <= 32 * 1440
    || window.label.startsWith('Monthly,') || window.label === 'Token Plan') return 'month';
  return 'other';
}

export function allowanceWindowLabel(window: SubscriptionWindow): string {
  return { '5h': '5 hours', week: '7 days', month: 'a month', other: 'other' }[allowanceWindowType(window)];
}

export function sortAllowanceWindows(windows: readonly SubscriptionWindow[]): SubscriptionWindow[] {
  const rank = { '5h': 0, week: 1, month: 2, other: 3 };
  return [...windows].sort((a, b) => rank[allowanceWindowType(a)] - rank[allowanceWindowType(b)]
    || (a.windowMinutes ?? Infinity) - (b.windowMinutes ?? Infinity) || a.label.localeCompare(b.label));
}

/** Preserve familiar headings for Driver defaults, and show edited account names. */
export function subscriptionName(driver: string, account: SubscriptionRecord): string {
  const defaults: Record<string, string> = {
    anthropic: 'Anthropic', chatgpt: 'ChatGPT', xiaomi: 'Xiaomi MiMo',
    zai: 'z.ai Coding Plan', 'kimi-coding': 'Kimi Code', deepseek: 'DeepSeek',
  };
  return account.label === defaults[account.family] || !account.label.trim()
    ? subscriptionVendor(driver, account.family) : account.label;
}

export type UsageDestination = 'chatgpt' | 'mimo';
export type OpenSubscriptionUsage = (destination: UsageDestination, driver: string, subscription: string) => void;

export function canRefreshSubscriptionUsage(driver: string, account: SubscriptionRecord): boolean {
  return account.state === 'signed_in' && (
    (driver === 'codex' && account.family === 'chatgpt')
    || (driver === 'mimo' && account.family === 'xiaomi')
    || (driver === 'pi' && ['kimi-coding', 'zai', 'deepseek'].includes(account.family))
  );
}

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
  usageLinkErrors?: Record<string, string | undefined>;
  evidenceError?: string;
  nameNotices?: Record<string, string | undefined>;
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

/** Local calendar days (rather than 24-hour offsets) keep Tomorrow correct across DST. */
export function formatSubscriptionTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Time unavailable';
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const time = new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(date);
  if (date.toDateString() === today.toDateString()) return time;
  if (date.toDateString() === tomorrow.toDateString()) return 'Tomorrow ' + time;
  const day = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }).format(date);
  return day + ', ' + time;
}

export function formatSubscriptionCardTime(value: string): string {
  return formatSubscriptionTime(value);
}
