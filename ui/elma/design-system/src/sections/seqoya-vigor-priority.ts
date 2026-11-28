import {
  allowanceTokenTotal, allowanceWindowType, defaultSubscriptionUserScore, isSubscriptionUserScore, subscriptionKey,
  subscriptionName, subscriptionVendor, type EstimatedTokenCost, type SubscriptionListing,
  type SubscriptionRecord, type SubscriptionWindow,
} from './seqoya-subscriptions';
import type { VigorView } from './seqoya-vigor';

const hour = 60 * 60_000;
const weeklyHours = 7 * 24;
const week = weeklyHours * hour;

export const vigorFactors = [
  { key: 'dash', variable: 'D', coefficient: 'a₁', label: 'Quota Dash' },
  { key: 'time', variable: 'T', coefficient: 'a₂', label: 'Time urgency' },
  { key: 'tokens', variable: 'Q', coefficient: 'a₃', label: 'Available equivalents' },
  { key: 'loss', variable: 'L', coefficient: 'a₄', label: 'Potential quota loss' },
  { key: 'user', variable: 'U', coefficient: 'a₅', label: 'User score' },
] as const;

type Factor = (typeof vigorFactors)[number]['key'];
export type VigorCurrency = EstimatedTokenCost['currency'];
export type VigorEstimatedTokenCost = EstimatedTokenCost & { compactBasis?: string };
export const vigorCurrencies = ['USD', 'EUR', 'CNY'] as const satisfies readonly VigorCurrency[];

export const quotaDashRules = [
  { key: 'requiredPace', label: 'Weekly required pace', short: 'Required pace' },
  { key: 'potentialLoss', label: 'Potential weekly loss', short: 'Potential loss' },
  { key: 'projectedEtc', label: 'Projected monthly ETC', short: 'Monthly ETC' },
] as const;

type DashMetric = (typeof quotaDashRules)[number]['key'];
type DashThresholds = Partial<Record<DashMetric, number>>;
export type QuotaDashMatch = { kind: 'reset'; deadline: number } | { kind: DashMetric; value: number; threshold: number };

export interface MonthlyEtcForecast {
  start: number;
  end: number;
  charge: number;
  currency: VigorCurrency;
  used: number;
  expected: number;
  recordedAt: number;
}

export type MonthlyEtcForecasts = Record<string, MonthlyEtcForecast>;

export interface VigorSettings {
  weights: Record<Factor, number>;
  tokenScale: number;
  lossScale: number;
  lossCurrency: VigorCurrency;
  dashThresholds?: DashThresholds;
}

export const defaultVigorSettings: VigorSettings = {
  weights: { dash: 51, time: 20, tokens: 12, loss: 10, user: 7 },
  tokenScale: 400_000,
  lossScale: 6,
  lossCurrency: 'USD',
};

function nonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

export function isMonthlyEtcForecast(value: unknown): value is MonthlyEtcForecast {
  if (!value || typeof value !== 'object') return false;
  const { start, end, charge, currency, used, expected, recordedAt } = value as Partial<MonthlyEtcForecast>;
  return nonnegative(start) && nonnegative(end) && end > start && end <= 8.64e15
    && nonnegative(recordedAt) && start <= recordedAt && recordedAt < end
    && nonnegative(charge) && currency !== undefined && vigorCurrencies.includes(currency)
    && nonnegative(used) && nonnegative(expected) && Number.isFinite(used + expected);
}

export function isVigorSettings(value: unknown): value is VigorSettings {
  if (!value || typeof value !== 'object') return false;
  const { weights, tokenScale, lossScale, lossCurrency, dashThresholds } = value as Partial<VigorSettings>;
  if (!weights || typeof weights !== 'object' || !vigorFactors.every(({ key }) => nonnegative(weights[key]))) return false;
  if (dashThresholds !== undefined && (!dashThresholds || typeof dashThresholds !== 'object'
    || Array.isArray(dashThresholds)
    || !quotaDashRules.every(({ key }) => dashThresholds[key] === undefined || nonnegative(dashThresholds[key])))) return false;
  const total = vigorFactors.reduce((sum, { key }) => sum + weights[key], 0);
  return total > 0 && Number.isFinite(total)
    && nonnegative(tokenScale) && tokenScale > 0 && nonnegative(lossScale) && lossScale > 0
    && lossCurrency !== undefined && vigorCurrencies.includes(lossCurrency);
}

export type QuotaDashChoice = { windowEnd: number; marked: boolean };
export type QuotaDashChoices = Record<string, QuotaDashChoice>;

export interface VigorPriorityView extends VigorView {
  priority?: {
    listing?: SubscriptionListing;
    now: number;
    choices?: QuotaDashChoices;
    setChoice?: (key: string, choice: QuotaDashChoice) => void;
    settings?: VigorSettings;
    setSettings?: (settings: VigorSettings) => void;
    monthlyForecasts?: MonthlyEtcForecasts;
    setMonthlyForecast?: (key: string, forecast?: MonthlyEtcForecast) => void;
  };
}

type Loss = { amount: number; currency: VigorCurrency; perMillion: number; basis: string };

export interface VigorCalculation {
  dash: boolean;
  hoursLeft?: number;
  windowHours?: number;
  tokens?: number;
  loss?: Loss;
  userScore: number;
  terms: { factor?: number; weight: number; contribution: number }[];
  partial: boolean;
  sum: number;
  score: number;
  exhausted: boolean;
}

interface PriorityRow {
  key: string;
  name: string;
  windowEnd?: number;
  windowLabel?: string;
  totalTokens?: number;
  calibrationDetail?: string;
  weekly?: boolean;
  expires?: boolean;
  approximate?: boolean;
  status?: string;
  dash: boolean;
  reason?: string;
  matches?: QuotaDashMatch[];
  monthlyForecast?: MonthlyEtcForecast;
  projectedEtc?: number;
  userScore?: number;
  resetReady?: boolean;
  current?: VigorCalculation;
  next?: VigorCalculation;
}

function eligibleResetDeadlines(driver: string, account: SubscriptionRecord, now: number): number[] {
  const metrics = account.metrics;
  const inventory = metrics?.limitResets;
  if (inventory?.count === 0) return [];
  return inventory?.entries.flatMap(grant => {
    const coversWeek = driver === 'claude' && /^weekly reset$/i.test(grant.label)
      || driver === 'codex' && /^full reset$/i.test(grant.label)
        && /^ChatGPT (Plus|Pro)( |$)/.test(metrics?.price?.label ?? '');
    const expires = grant.expiresAt === 0 ? Infinity : Date.parse(grant.expiresAt ?? '');
    return coversWeek && !grant.expired && expires > now ? [expires] : [];
  }) ?? [];
}

function potentialLoss(tokens: number | undefined, rate: VigorEstimatedTokenCost | undefined): Loss | undefined {
  if (tokens === undefined || !rate || !nonnegative(rate.perMillion)) return undefined;
  const amount = tokens / 1_000_000 * rate.perMillion;
  return Number.isFinite(amount) ? { amount, currency: rate.currency, perMillion: rate.perMillion, basis: rate.compactBasis ?? rate.basis } : undefined;
}

function saturate(value: number, scale: number): number {
  return 1 / (1 + scale / value);
}

function calculate(
  settings: VigorSettings,
  dash: boolean,
  hoursLeft: number | undefined,
  windowHours: number | undefined,
  tokens: number | undefined,
  rate: VigorEstimatedTokenCost | undefined,
  userScore: number,
  exhausted = false,
): VigorCalculation {
  const loss = potentialLoss(tokens, rate);
  const factors: Record<Factor, number | undefined> = {
    dash: Number(dash),
    time: hoursLeft === undefined || windowHours === undefined ? undefined
      : 1 - Math.min(windowHours, Math.max(0, hoursLeft)) / windowHours,
    tokens: tokens === undefined ? undefined : saturate(tokens, settings.tokenScale),
    loss: loss && loss.currency === settings.lossCurrency ? saturate(loss.amount, settings.lossScale) : undefined,
    user: userScore,
  };
  const totalWeight = vigorFactors.reduce((sum, { key }) => sum + settings.weights[key], 0);
  const terms = vigorFactors.map(({ key }) => {
    const weight = settings.weights[key] / totalWeight;
    const factor = factors[key];
    return { factor, weight, contribution: weight * (factor ?? 0) };
  });
  const sum = terms.reduce((total, term) => total + term.contribution, 0);
  return { dash, hoursLeft, windowHours, tokens, loss, userScore, terms, sum, score: exhausted ? 0 : sum, exhausted,
    partial: terms.some(term => term.weight > 0 && term.factor === undefined) };
}

function projectedMonthlyEtc(forecast: MonthlyEtcForecast | undefined, now: number): number | undefined {
  if (!forecast || now < forecast.recordedAt || now >= forecast.end) return undefined;
  const total = forecast.used + forecast.expected;
  if (total === 0) return forecast.charge > 0 ? Infinity : undefined;
  const cost = forecast.charge / total * 1_000_000;
  return Number.isFinite(cost) ? cost : undefined;
}

function thresholdMatches(
  thresholds: DashThresholds | undefined,
  remainingShare: number | undefined,
  hoursLeft: number,
  potentialLoss: number | undefined,
  projectedEtc: number | undefined,
): QuotaDashMatch[] {
  if (!thresholds) return [];
  const values: Record<DashMetric, number | undefined> = {
    requiredPace: remainingShare === undefined ? undefined : remainingShare * weeklyHours / hoursLeft,
    potentialLoss,
    projectedEtc,
  };
  return quotaDashRules.flatMap(({ key }) => {
    const value = values[key];
    const threshold = thresholds[key];
    return value !== undefined && threshold !== undefined && value >= threshold ? [{ kind: key, value, threshold }] : [];
  });
}

function scheduledTime(value: string | number | null | undefined): number {
  const time = typeof value === 'string' ? Date.parse(value) : NaN;
  return Number.isFinite(time) ? time : Infinity;
}

function activeAllowance(windows: SubscriptionWindow[], now: number, pricedWindow?: string) {
  const active = windows.flatMap(window => {
    if (window.next || window.pendingStart) return [];
    const reset = scheduledTime(window.resetsAt);
    const expiry = scheduledTime(window.expiresAt);
    const end = Math.min(reset, expiry);
    if (!Number.isFinite(end) || end <= now) return [];
    return [{ window, end, expires: window.terminal === true || expiry <= reset, type: allowanceWindowType(window) }];
  });
  const priced = active.find(({ window }) => window.label === pricedWindow);
  if (priced?.type === 'week') return priced;
  return active.find(({ type }) => type === 'week') ?? priced
    ?? active.find(({ window }) => window.label === 'Monthly, Kimi Code' || window.label === 'Token Plan')
    ?? active.find(({ type }) => type === 'month') ?? active[0];
}

function priorityRow(
  driver: string, account: SubscriptionRecord, now: number, choices: QuotaDashChoices,
  settings: VigorSettings, forecasts: MonthlyEtcForecasts,
): PriorityRow {
  const key = JSON.stringify([driver, account.id, account.createdAt ?? null]);
  const name = subscriptionName(driver, account);
  const userScore = isSubscriptionUserScore(account.userScore) ? account.userScore : defaultSubscriptionUserScore;
  const monthlyForecast = forecasts[key];
  const projectedEtc = projectedMonthlyEtc(monthlyForecast, now);
  const base = { key, name, dash: false, userScore, monthlyForecast, projectedEtc };
  if (account.metrics?.balance || (driver === 'pi' && ['deepseek', 'minimax'].includes(account.family))) {
    return { ...base, status: 'Pay-as-you-go API scoring is postponed.' };
  }
  if (account.state !== 'signed_in') return { ...base, status: 'Subscription sign-in required.' };

  const price = account.metrics?.estimatedTokenCost;
  const selected = activeAllowance(account.metrics?.windows ?? [], now, price?.window);
  if (!selected) return base;

  const { window, end: windowEnd, expires, type } = selected;
  const weekly = type === 'week';
  const windowHours = nonnegative(window.windowMinutes) && window.windowMinutes > 0 ? window.windowMinutes / 60 : undefined;
  const rate = price?.window === window.label ? price : undefined;
  const choice = weekly && choices[key]?.windowEnd === windowEnd ? choices[key] : undefined;
  const deadlines = weekly ? eligibleResetDeadlines(driver, account, now) : [];
  const deadline = Math.min(...deadlines);
  const exhausted = window.outputTokensRemaining === 0 || window.remainingPercent === 0 || window.usedPercent === 100;
  const tokens = exhausted ? 0 : nonnegative(window.outputTokensRemaining) ? window.outputTokensRemaining : undefined;
  const hoursLeft = (windowEnd - now) / hour;
  const remainingShare = exhausted ? 0
    : nonnegative(window.remainingPercent) && window.remainingPercent <= 100 ? window.remainingPercent / 100
    : nonnegative(window.usedPercent) && window.usedPercent <= 100 ? 1 - window.usedPercent / 100
    : tokens !== undefined && nonnegative(window.outputTokensUsed) && Number.isFinite(tokens + window.outputTokensUsed)
      ? tokens / (tokens + window.outputTokensUsed) : undefined;
  const loss = potentialLoss(tokens, rate);
  const matches: QuotaDashMatch[] = deadline <= windowEnd + week / 2 ? [{ kind: 'reset', deadline }] : [];
  if (weekly && ((remainingShare ?? 0) > 0 || (tokens ?? 0) > 0)) {
    matches.push(...thresholdMatches(settings.dashThresholds, remainingShare, hoursLeft,
      loss?.currency === settings.lossCurrency ? loss.amount : undefined,
      monthlyForecast?.currency === settings.lossCurrency ? projectedEtc : undefined));
  }
  const dash = choice?.marked ?? (matches.length > 0);
  const reason = choice ? (choice.marked ? 'Marked manually for this weekly window.' : 'Dismissed for this weekly window.') : undefined;
  const resetReady = exhausted && dash && deadlines.length > 0;
  const current = calculate(settings, dash, hoursLeft, windowHours, tokens, rate, userScore, exhausted && !resetReady);

  let next: VigorCalculation | undefined;
  if (exhausted && !expires) {
    const full = nonnegative(window.outputTokensUsed) && window.outputTokensUsed > 0 ? window.outputTokensUsed : undefined;
    const nextDash = deadlines.some(expiry => expiry > windowEnd && expiry <= windowEnd + week * 1.5);
    next = calculate(settings, nextDash, windowHours, windowHours, full, rate, userScore);
  }
  return { ...base, windowEnd, windowLabel: window.label, totalTokens: allowanceTokenTotal(window),
    calibrationDetail: window.calibrationDetail,
    approximate: window.approximateReset, weekly, expires,
    dash, reason, matches, resetReady, current, next };
}

export function vigorPriorityRows(
  view: VigorPriorityView, choices: QuotaDashChoices, settings: VigorSettings, monthlyForecasts: MonthlyEtcForecasts,
): PriorityRow[] | undefined {
  const { listing, now } = view.priority ?? { now: Date.now() };
  if (!listing) return view.rollup?.subscriptions.map(entry => ({
    key: subscriptionKey(entry.driver, entry.subscription), name: entry.label || subscriptionVendor(entry.driver, entry.family), dash: false,
  }));
  return listing.drivers.flatMap(({ driver, subscriptions }) =>
    (subscriptions ?? []).map(account => priorityRow(driver, account, now, choices, settings, monthlyForecasts)))
    .sort((left, right) => (right.current?.score ?? -1) - (left.current?.score ?? -1) || left.name.localeCompare(right.name));
}
