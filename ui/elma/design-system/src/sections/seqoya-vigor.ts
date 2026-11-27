import {
  sortAllowanceWindows, type AllowanceView, type EstimatedTokenCost, type SubscriptionActivity,
  type SubscriptionMetrics, type SubscriptionRecord, type SubscriptionWindow,
} from './seqoya-subscriptions';

/** Displayed fields from the saved Radar rollup. */
export interface VigorRollup {
  moment: string;
  headline: {
    driver: string;
    subscription: string;
    label: string;
    vigor: number;
  } | null;
  subscriptions: {
    driver: string;
    subscription: string;
    family: string;
    label: string;
    result: {
      moment: string;
      vigor: number | null;
      exhausted: boolean;
      predicted: boolean;
      stale: { reportAgeMinutes: number } | null;
      unknown: string | null;
      nextChange: { at: string; vigor: number | null } | null;
      windows: {
        label: string;
        loss: number | null;
        weight?: number | null;
        contribution: number | null;
        usedPercent?: number | null;
        resetsAt?: string | null;
        windowMinutes?: number | null;
        reached?: boolean;
        predicted: boolean;
        reason: string | null;
      }[];
    } | null;
  }[];
  failures: Record<string, string>;
}

export type VigorEntry = VigorRollup['subscriptions'][number] & {
  plan?: VigorPlan;
  unavailable?: string;
  allowance?: AllowanceView;
  activity?: SubscriptionActivity;
  activityError?: string;
  estimate?: {
    score: number;
    reason: string;
    exhausted?: boolean;
    budget?: { amount: string; tokens: number; currency: string; rate: number; referenceTokens: number; ceiling: number };
  };
};

export function displayedVigor(entry: VigorEntry): number | null {
  if (entry.plan) return entry.plan.score ?? null;
  return entry.unavailable ? null : entry.estimate?.score ?? entry.result?.vigor ?? null;
}

type ResetGrant = NonNullable<SubscriptionMetrics['limitResets']>['entries'][number];

interface WindowProjection {
  window: SubscriptionWindow;
  remaining: number;
  full: number;
  hours: number;
  grants: { required: number; deadlineHours: number; redemptionHours: number }[];
  restarts: boolean;
  total: number;
  endHours: number;
  extraWindows: number;
  pace: number;
}

interface ScoreInputs {
  monthlyUsd: number;
  userScore: number;
  pace: number;
  baselinePace: number;
  tokenCostUsd: number;
  baselineTokenCostUsd: number;
}

export interface VigorPlan {
  metrics?: SubscriptionMetrics;
  performance?: NonNullable<SubscriptionRecord['modelLabels']>[0]['performance'];
  userScore?: number;
  apiBilling: boolean;
  windows: SubscriptionWindow[];
  projections: WindowProjection[];
  exhausted: boolean;
  pace?: number;
  adjustedTokenCost?: EstimatedTokenCost;
  pricingExtraWindows?: number;
  inputs?: ScoreInputs;
  comparison?: {
    highestMonthlyUsd: number;
    highestPace: number;
    lowestPositiveTokenCostUsd: number | undefined;
    monthlyCostCoefficient: number;
    factors: [preference: number, pace: number, tokenCost: number];
    scoreWithoutResets: number;
  };
  score?: number;
  reason?: string;
}

// ECB reference rates for 20 November 2026, expressed in USD per currency unit.
// https://www.ecb.europa.eu/stats/exchange/eurofxref/shared/pdf/2026/11/20261120.pdf
const usdRates = { USD: 1, EUR: 1.0990, CNY: 1.0990 / 7.3388 };

function resetCovers(driver: string, priceLabel: string | undefined, grant: ResetGrant, window: SubscriptionWindow): boolean {
  if (driver === 'codex' && /^full reset$/i.test(grant.label)) {
    if (priceLabel === 'ChatGPT Plus') return window.windowMinutes === 300 || window.windowMinutes === 10_080;
    if (priceLabel?.startsWith('ChatGPT Pro ')) return window.windowMinutes === 10_080;
  }
  if (driver === 'claude') {
    if (/^weekly reset$/i.test(grant.label)) return window.windowMinutes === 10_080;
    if (/^five-hour reset$/i.test(grant.label)) return window.windowMinutes === 300;
  }
  return false;
}

function projectWindow(driver: string, priceLabel: string | undefined, window: SubscriptionWindow,
  resets: SubscriptionMetrics['limitResets'], now: number): WindowProjection | undefined {
  const { outputTokensRemaining: remaining, outputTokensUsed: used, remainingMinutes } = window;
  if (remaining === undefined || used === undefined || remainingMinutes === undefined
    || window.outputTokensPerHour === undefined || !(remainingMinutes > 0)) return undefined;
  const full = remaining + used;
  if (!Number.isFinite(full) || !(full > 0) || remaining < 0 || used < 0) return undefined;
  const hours = remainingMinutes / 60;
  const baselinePace = remaining / hours;
  const restarts = driver === 'codex';
  const deadlines = (resets?.entries ?? []).flatMap((grant) => {
    if (grant.expired || !resetCovers(driver, priceLabel, grant, window)) return [];
    const expiryHours = grant.expiresAt === 0 ? Infinity : (Date.parse(grant.expiresAt ?? '') - now) / 3_600_000;
    return expiryHours > 0 ? [restarts ? expiryHours : Math.min(expiryHours, hours)] : [];
  }).sort((left, right) => left - right).slice(0, resets?.count ?? Infinity);
  if (!deadlines.length) return {
    window, remaining, full, hours, grants: [], restarts, total: remaining,
    endHours: hours, extraWindows: 0, pace: baselinePace,
  };

  const windowHours = (window.windowMinutes ?? 0) / 60;
  const total = remaining + deadlines.length * full;
  const target = restarts ? Math.max(baselinePace, full / windowHours) : total / hours;
  const pace = Math.max(target, ...deadlines.map((deadline, index) => (remaining + index * full) / deadline));
  let endHours = hours;
  let extraWindows = restarts ? 0 : deadlines.length;
  const grants = deadlines.map((deadlineHours, index) => {
    const required = remaining + index * full;
    const redemptionHours = required / pace;
    if (restarts) {
      extraWindows += Math.min(1, Math.max(0, (endHours - redemptionHours) / windowHours));
      endHours = redemptionHours + windowHours;
    }
    return { required, deadlineHours, redemptionHours };
  });
  return { window, remaining, full, hours, grants, restarts, total, endHours, extraWindows, pace };
}

export function calculateVigor(driver: string, account: SubscriptionRecord | undefined, now: number, reason?: string): VigorPlan {
  const metrics = account?.metrics;
  const windows = sortAllowanceWindows(metrics?.windows ?? []);
  const performance = account?.modelLabels?.[0]?.performance;
  const userScore = account?.userScore;
  const apiBilling = driver === 'pi' && (account?.family === 'deepseek' || account?.family === 'minimax')
    || !!metrics?.balance;
  const base = { metrics, performance, userScore, apiBilling, windows };
  if (apiBilling || reason || !account) return { ...base, projections: [], exhausted: false, reason };

  const active = windows.filter(window => window.next !== 'awaitingRenewal' && !window.pendingStart);
  const price = metrics?.price;
  const tokenCost = metrics?.estimatedTokenCost;
  const exhausted = active.some(window => window.remainingPercent === 0);
  const projections = active.flatMap((window) => {
    const projection = projectWindow(driver, price?.label, window, metrics?.limitResets, now);
    return projection ? [projection] : [];
  });
  const pace = projections.length ? Math.min(...projections.map(window => window.pace)) : undefined;
  const baselinePace = projections.length
    ? Math.min(...projections.map(({ remaining, hours }) => remaining / hours))
    : undefined;
  const pricing = projections.find(({ window }) => window.label === tokenCost?.window);
  const pricingExtraWindows = pricing?.extraWindows ?? 0;
  const adjustedTokenCost = tokenCost && {
    ...tokenCost, perMillion: tokenCost.perMillion / (1 + pricingExtraWindows / (tokenCost.windowsPerMonth ?? 1)),
  };
  const monthlyUsd = price && price.amount / price.months * usdRates[price.currency];
  const tokenCostUsd = adjustedTokenCost && adjustedTokenCost.perMillion * usdRates[adjustedTokenCost.currency];
  const baselineTokenCostUsd = tokenCost && tokenCost.perMillion * usdRates[tokenCost.currency];
  const plan = { ...base, projections, exhausted, pace, adjustedTokenCost, pricingExtraWindows };
  if (exhausted) return { ...plan, score: 0, reason: 'An active allowance is exhausted.' };
  if (pace === undefined || baselinePace === undefined) return { ...plan, reason: 'A timed allowance with a token estimate is needed.' };
  if (monthlyUsd === undefined || !Number.isFinite(monthlyUsd) || monthlyUsd < 0) {
    return { ...plan, reason: 'Subscription cost or billing period is unavailable.' };
  }
  if (tokenCostUsd === undefined || baselineTokenCostUsd === undefined || !Number.isFinite(baselineTokenCostUsd)
    || !Number.isFinite(tokenCostUsd) || tokenCostUsd < 0) {
    return { ...plan, reason: metrics?.tokenCostUnavailableReason ?? 'Estimated token cost is unavailable.' };
  }
  if (userScore === undefined || !(userScore >= 0 && userScore <= 1)) {
    return { ...plan, reason: 'User score is unavailable.' };
  }
  return { ...plan, inputs: { monthlyUsd, userScore, pace, baselinePace, tokenCostUsd, baselineTokenCostUsd } };
}

export function rankVigorEntries(entries: VigorEntry[]): VigorEntry[] {
  const inputs = entries.flatMap(entry => entry.plan?.inputs ? [entry.plan.inputs] : []);
  const highestMonthlyUsd = Math.max(0, ...inputs.map(input => input.monthlyUsd));
  const highestPace = Math.max(0, ...inputs.flatMap(input => [input.pace, input.baselinePace]));
  const positiveCosts = inputs.flatMap(input => [input.tokenCostUsd, input.baselineTokenCostUsd]).filter(cost => cost > 0);
  const lowestPositiveTokenCostUsd = positiveCosts.length ? Math.min(...positiveCosts) : undefined;

  return entries.map(entry => {
    const plan = entry.plan;
    const input = plan?.inputs;
    if (!plan || !input) return entry;
    const monthlyCostCoefficient = highestMonthlyUsd ? input.monthlyUsd / highestMonthlyUsd : 0;
    const paceFactor = (pace: number) => highestPace ? pace / highestPace : 0;
    const costFactor = (cost: number) => cost === 0 ? 1 : (lowestPositiveTokenCostUsd ?? cost) / cost;
    const combined = (pace: number, cost: number) =>
      monthlyCostCoefficient * (input.userScore + paceFactor(pace) + costFactor(cost)) / 3;
    const comparison: NonNullable<VigorPlan['comparison']> = {
      highestMonthlyUsd, highestPace, lowestPositiveTokenCostUsd, monthlyCostCoefficient,
      factors: [input.userScore, paceFactor(input.pace), costFactor(input.tokenCostUsd)],
      scoreWithoutResets: combined(input.baselinePace, input.baselineTokenCostUsd),
    };
    return { ...entry, plan: { ...plan, comparison, score: combined(input.pace, input.tokenCostUsd) } };
  }).sort((left, right) => (displayedVigor(right) ?? -1) - (displayedVigor(left) ?? -1));
}

export interface VigorView {
  rollup?: VigorRollup;
  entries?: VigorEntry[];
  accountIssues?: string[];
  loading?: boolean;
  error?: string;
}
