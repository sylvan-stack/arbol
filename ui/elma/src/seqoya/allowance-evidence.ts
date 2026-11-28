import {
  formatSubscriptionCardTime, formatSubscriptionTime, subscriptionKey, type AllowanceView, type SubscriptionListing,
  type EstimatedTokenCost, type SubscriptionMetrics, type SubscriptionPrice, type SubscriptionRecord, type SubscriptionWindow,
} from '../../design-system/src/sections/seqoya-subscriptions';
import type { VigorRollup } from '../../design-system/src/sections/seqoya-vigor';
import { formatVigorNumber, formatVigorTokens } from '../../design-system/src/sections/seqoya-vigor-format';
import type { VigorEstimatedTokenCost } from '../../design-system/src/sections/seqoya-vigor-priority';
import { deepSeekBalance } from './vigor-estimates';
import { allowanceHistoryKey, rememberEstimate, restoreEstimates, type AllowanceHistory } from './allowance-history';

interface QuotaReading {
  remainingPercent: number;
  resetsAt: string;
  approximateReset?: boolean;
}

interface ManualReading {
  subscription: string;
  updatedAt: string;
  labelUpdatedAt?: string;
  browser?: boolean;
  observedAt: string;
}

type EstimateBasis = 'claudeLocal' | 'kimiLocal' | 'kimiCalls' | 'piChatGPT' | 'zaiCredits';

interface WindowEstimate {
  reference?: 'plan';
  createdAt?: string;
  plan?: 'pro' | 'max' | 'team' | 'enterprise';
  basis: EstimateBasis;
  subscription: string;
  checkedAt: string;
  window: string;
  observedAt: string;
  amount: number;
  scale?: number;
  calibration?: {
    startedAt: string; endedAt: string; startResetsAt: string; endResetsAt: string;
    startUsedPercent: number; endUsedPercent: number;
    model: 'Kimi Code K3.1 Pro'; outputTokens: number;
  };
}

interface MembershipPayment {
  subscription: string;
  createdAt: string;
  checkedAt: string;
  confirmedAt: string;
  validUntil: string;
  amount: number;
  months: number;
  currency: EstimatedTokenCost['currency'];
  weeklyCredits?: number;
}

interface CodexWeeklyCalibration {
  plan: string;
  resetsAt: number;
  observedAt: number;
  usedPercent: number;
  points: number;
  sample?: {
    startedAt: number;
    observedAt: number;
    points: number;
    outputTokens: number;
    inputTokens: number;
    cachedInputTokens: number;
  };
}

/** Bounded usage evidence returned by Seqoya's native app channel. */
export interface UsageEvidence {
  codexWeeklyCalibration?: CodexWeeklyCalibration[];
  windowEstimates?: WindowEstimate[];
  browserReports?: BrowserReport[];
  claudeDashboard?: {
    subscription: string;
    createdAt: string;
    checkedAt: string;
    observedAt: string;
    plan: 'pro' | 'max' | 'team' | 'enterprise';
    fiveHour?: QuotaReading;
    weekly?: QuotaReading;
    resetExpiries?: string[];
  };
  claudeMax5x?: { subscription: string; createdAt: string; confirmedAt: string };
  kimiBilling?: MembershipPayment;
  zaiBilling?: MembershipPayment;
  piChatGPT?: ManualReading & {
    plan: 'plus' | 'pro';
    allowed: boolean;
    capPercent: number;
    fiveHour?: QuotaReading;
    weekly?: QuotaReading;
  };
  piChatGPTCalibration?: UsageEvidence['piChatGPT'];
  mimo?: ManualReading & {
    resetsAt: string;
    plan?: 'lite' | 'standard' | 'pro' | 'max';
    totalCredits: string;
    remainingCredits: string;
  };
  codex?: {
    reference?: 'plan';
    subscription: string;
    createdAt: string;
    checkedAt: string;
    plan: 'plus' | 'pro';
    resetsAt: string;
    startedAt: string;
    observedAt: string;
    points: number;
    uncachedInputTokens: number;
    cachedInputTokens: number;
    outputTokens: number;
  };
}

type Quota = NonNullable<AllowanceView['quota']>;
type Credits = NonNullable<Quota['credits']>;
type Result = VigorRollup['subscriptions'][number]['result'];
type DriverReport = NonNullable<SubscriptionRecord['lastUsage']>;
type DriverWindow = DriverReport['windows'][number];
interface ApiBalanceReading {
  balance: string;
  observedAt: string;
  paymentAt?: string;
  startingBalance?: string;
  includesCarry?: boolean;
}
type BrowserWindow = DriverWindow & { creditsTotal?: number };
interface BrowserReport {
  driver: string;
  subscription: string;
  createdAt: string;
  checkedAt?: string | null;
  report: Omit<DriverReport, 'windows' | 'extra'> & {
    windows: BrowserWindow[];
    extra?: NonNullable<DriverReport['extra']> & {
      apiBalance?: ApiBalanceReading;
      connectedApp?: { allowed: boolean; capPercent: number };
    };
  };
  approximateWindows: string[];
}
const browserSource = 'Arbol Browser dashboard';
const day = 86_400_000;
const weekMinutes = 10_080;
const weeksPerMonth = 52 / 12;
// Monthly USD list prices checked 28 November 2026.
// https://claude.com/pricing?currency=USD
const claudeProPrice = { label: 'Claude Pro', usd: 20 };
const claudeMaxPrice = { label: 'Claude Max', usd: 100 };
const claudeMax5xPrice = { ...claudeMaxPrice, label: 'Claude Max 5×' };
const claudeMax5xMultiplier = 5;
// https://help.openai.com/en/articles/6950777-what-is-chatgpt-plus
// https://help.openai.com/en/articles/9793128-about-chatgpt-pro-tiers
const codexPlusPrice = { label: 'ChatGPT Plus', usd: 20 };
const codexPro200Price = { label: 'ChatGPT Pro 200', usd: 200 };
// https://zcode.z.ai/en · https://docs.z.ai/devpack/overview.md#usage-credit-allowance
const zaiMonthlyPlans = [
  { label: 'z.ai GLM Coding Lite', weeklyCredits: 10_000, usd: 18 },
  { label: 'z.ai GLM Coding Pro', weeklyCredits: 60_000, usd: 80 },
  { label: 'z.ai GLM Coding Max', weeklyCredits: 140_000, usd: 168 },
];
const integer = new Intl.NumberFormat();
// Xiaomi Token Plan rate for mimo-v2.6-pro. Checked 12 November 2026.
// https://mimo.mi.com/docs/en-US/quick-start/faq/token-plan/Usage%26Quota
const mimoCreditsPerOutputToken = 600;
const planNames = { lite: 'Lite', standard: 'Standard', pro: 'Pro', max: 'Max' };
// Published individual USD monthly list prices and matching credit grants, checked 21 November 2026.
// https://mimo.mi.com/docs/tokenplan/subscription
const mimoMonthlyPlans = new Map([
  ['lite', { credits: '4100000000', usd: 6 }],
  ['standard', { credits: '11000000000', usd: 16 }],
  ['pro', { credits: '38000000000', usd: 50 }],
  ['max', { credits: '82000000000', usd: 100 }],
]);

function sameCreation(expected: string | undefined, current: string | undefined): boolean {
  const created = Date.parse(expected ?? '');
  return Number.isFinite(created) && created === Date.parse(current ?? '');
}

function newerReading<T extends { observedAt: string }>(stored?: T, browser?: T): T | undefined {
  return browser && (!stored || Date.parse(browser.observedAt) > Date.parse(stored.observedAt)) ? browser : stored;
}

export function mergeUsageEvidence(stored?: UsageEvidence, browser?: UsageEvidence): UsageEvidence | undefined {
  return browser ? {
    ...stored,
    browserReports: browser.browserReports,
    claudeDashboard: newerReading(stored?.claudeDashboard, browser.claudeDashboard),
    piChatGPT: newerReading(stored?.piChatGPT, browser.piChatGPT),
    piChatGPTCalibration: stored?.piChatGPT,
    mimo: newerReading(stored?.mimo, browser.mimo),
  } : stored;
}

function recentObservation(observedAt: string, now: number): boolean {
  const observed = Date.parse(observedAt);
  return Number.isFinite(observed) && observed <= now && observed >= now - 28 * day;
}

function publicAccountPlan(account: SubscriptionRecord): string | undefined {
  if (!('account' in account) || !account.account || typeof account.account !== 'object') return undefined;
  const plan = (account.account as Record<string, unknown>).plan;
  return typeof plan === 'string' ? plan.trim().toLowerCase() : undefined;
}

function matches<T extends ManualReading>(reading: T | undefined, account: SubscriptionRecord, now: number): reading is T {
  return !!reading && reading.subscription === account.id && (reading.labelUpdatedAt ?? reading.updatedAt) === account.updatedAt
    && Date.parse(reading.observedAt) <= now;
}

function windowReading(label: string, resetsAt: string | undefined, now: number, remainingPercent: number, windowMinutes?: number) {
  return { label, remainingPercent, resetsAt, windowMinutes, elapsed: !!resetsAt && Date.parse(resetsAt) <= now };
}

function preferDashboard(
  dashboardReset: string, observedAt: string, report: DriverReport | undefined,
  driverWindow: DriverWindow | undefined, now: number,
): boolean {
  if (!report || driverWindow?.usedPercent == null) return true;
  const driverTime = Date.parse(report.fetchedAt);
  if (!Number.isFinite(driverTime) || driverTime > now) return true;
  const driverEnd = Date.parse(driverWindow.resetsAt ?? '');
  const driverCurrent = driverEnd > now || !driverWindow.resetsAt && driverWindow.usedPercent === 0;
  const dashboardCurrent = Date.parse(dashboardReset) > now;
  if (dashboardCurrent !== driverCurrent) return dashboardCurrent;
  return Date.parse(observedAt) > driverTime;
}

function validCredits(value?: Credits): value is Credits {
  return !!value && typeof value.total === 'string' && typeof value.remaining === 'string' && /^[0-9]{1,21}$/.test(value.total) && /^[0-9]{1,21}$/.test(value.remaining)
    && BigInt(value.total) > 0n && BigInt(value.remaining) <= BigInt(value.total);
}

function mimoQuota(account: SubscriptionRecord, saved: Result | undefined, reading: UsageEvidence['mimo'], now: number): AllowanceView {
  const report = account.lastUsage;
  const directWindow = report?.windows.find((window) => window.resource === 'credits' && window.usedPercent != null);
  const radarWindow = saved?.windows.find((window) => window.label === 'Token Plan' && !window.predicted && window.usedPercent != null);
  const manual = matches(reading, account, now) ? reading : undefined;
  let quota: Quota | undefined;
  if (report && directWindow?.usedPercent != null) {
    const credits = validCredits(report.extra?.planCredits) ? report.extra.planCredits : undefined;
    const left = credits ? 100 * Number(credits.remaining) / Number(credits.total) : 100 - directWindow.usedPercent;
    quota = {
      source: 'Xiaomi Token Plan', plan: report.plan, observedAt: report.fetchedAt, credits,
      windows: [windowReading(directWindow.label, directWindow.resetsAt, now, left, directWindow.windowMinutes)],
    };
  }
  if (manual && preferDashboard(manual.resetsAt, manual.observedAt, report, directWindow, now)) {
    const matchedDuration = radarWindow?.resetsAt && Date.parse(radarWindow.resetsAt) === Date.parse(manual.resetsAt)
      ? radarWindow.windowMinutes : undefined;
    const duration = matchedDuration ?? (manual.browser && manual.plan === 'pro' ? 43_200 : undefined);
    const credits = { total: manual.totalCredits, remaining: manual.remainingCredits };
    if (validCredits(credits)) {
      quota = {
        source: manual.browser ? browserSource : 'Saved Xiaomi Token Plan reading', plan: manual.plan && planNames[manual.plan],
        observedAt: manual.observedAt, credits,
        windows: [windowReading('Token Plan', manual.resetsAt, now, 100 * Number(credits.remaining) / Number(credits.total), duration)],
      };
    }
  }
  if (radarWindow?.usedPercent != null && (!quota || quota.windows[0].elapsed && radarWindow.resetsAt
    && Date.parse(radarWindow.resetsAt) > now)) {
    quota = {
      source: 'Saved Vigor quota reading',
      windows: [windowReading(radarWindow.label, radarWindow.resetsAt ?? undefined, now, 100 - radarWindow.usedPercent, radarWindow.windowMinutes ?? undefined)],
      note: saved?.stale ? 'The saved Vigor report is stale.' : undefined,
    };
  }
  if (!quota) return { issues: ['No MiMo quota reading. Refresh Subscriptions or open MiMo.'] };
  if (!quota.credits) return { quota, issues: ['Absolute MiMo capacity unavailable. The saved window has a usage percentage and needs a total credit count.'] };
  const { total, remaining } = quota.credits;
  const divisor = integer.format(mimoCreditsPerOutputToken);
  return {
    quota,
    capacity: {
      model: 'MiMo v2.6 Pro', source: 'Xiaomi’s published Token Plan output rate.',
      calculation: `${integer.format(BigInt(total))} total credits and ${integer.format(BigInt(remaining))} credits at reading ÷ ${divisor} credits per output token.`,
      total: Number(total) / mimoCreditsPerOutputToken,
      remaining: quota.windows[0].resetsAt && !quota.windows[0].elapsed
        ? Number(remaining) / mimoCreditsPerOutputToken : undefined,
    },
  };
}

function chatGPTQuota(account: SubscriptionRecord, reading: UsageEvidence['piChatGPT'], now: number): AllowanceView {
  if (!matches(reading, account, now)) {
    return { issues: ['Pi quota has no saved dashboard reading. Open in ChatGPT and check Connected App Limits for this sign-in.'] };
  }
  const report = account.lastUsage;
  const windows: Quota['windows'] = [];
  const sharedWindows = [
    { reading: reading.fiveHour, label: 'Shared five-hour quota', minutes: 300 },
    { reading: reading.weekly, label: 'Shared weekly quota', minutes: 10_080 },
  ];
  for (const { reading: captured, label, minutes } of sharedWindows) {
    const driverWindow = report?.windows.find((window) => window.windowMinutes === minutes);
    if (captured && preferDashboard(captured.resetsAt, reading.observedAt, report, driverWindow, now)) {
      windows.push({
        ...windowReading(label, captured.resetsAt, now, captured.remainingPercent, minutes),
        approximateReset: captured.approximateReset,
      });
    }
  }
  const issues = ['Absolute token capacity unavailable. ChatGPT Usage reports percentages for the shared plan.'];
  if (!reading.allowed) issues.push('Pi’s access to the shared plan was disabled at the reading.');
  else if (reading.capPercent < 100) issues.push('Pi’s remaining app-specific quota needs a separate consumption reading.');
  if (!windows.length && !report?.windows.length) issues.push('Shared plan quota has no reading.');
  return { issues, quota: {
    source: reading.browser ? browserSource : 'ChatGPT dashboard snapshot', observedAt: reading.observedAt,
    plan: reading.plan === 'plus' ? 'ChatGPT Plus' : 'ChatGPT Pro',
    note: reading.allowed ? `Pi could use up to ${reading.capPercent}% of the shared plan at this reading.` : undefined,
    windows,
  } };
}

function codexCapacity(account: SubscriptionRecord, sample: UsageEvidence['codex'], now: number): AllowanceView & { capacity?: Capacity } {
  const usage = account.lastUsage;
  const checkedAt = 'checkedAt' in account && typeof account.checkedAt === 'string' ? account.checkedAt : undefined;
  const weekly = usage?.windows.find((window) => window.kind === 'weekly' && window.windowMinutes === weekMinutes);
  if (!sample || !usage || !weekly || sample.subscription !== account.id || !sameCreation(sample.createdAt, account.createdAt)
    || (sample.reference !== 'plan' && (!checkedAt || Date.parse(sample.checkedAt) !== Date.parse(checkedAt)))
    || sample.plan !== usage.plan || !recentObservation(sample.observedAt, now)
    || !weekly.resetsAt || Date.parse(weekly.resetsAt) < Date.parse(sample.resetsAt) - 1_000) {
    return { issues: ['Absolute Codex capacity unavailable. The reported plan and weekly share need a matching recent token calibration.'] };
  }

  // Paid Standard rates are a reference weighting, not a published included subscription allowance.
  // https://learn.chatgpt.com/docs/pricing#token-rates
  const astraInput = 250, astraCache = 25, astraOutput = 1_250, solOutput = 250;
  const weightedTokens = sample.uncachedInputTokens * astraInput + sample.cachedInputTokens * astraCache
    + sample.outputTokens * astraOutput;
  const total = weightedTokens / (sample.points / 100) / solOutput;
  const reset = Date.parse(weekly.resetsAt);
  const priorWindow = Math.abs(reset - Date.parse(sample.resetsAt)) > 1_000;
  const describeCalibration = (tokens: (value: number) => string, percent: (value: number) => string) =>
    `(${tokens(sample.uncachedInputTokens)} × ${astraInput} + ${tokens(sample.cachedInputTokens)} × ${astraCache} + ${tokens(sample.outputTokens)} × ${astraOutput}) ÷ ${percent(sample.points)}% ÷ ${solOutput}.`;
  const calculation = describeCalibration(integer.format, String);
  const source = `${sample.reference === 'plan' ? `Plan reference (ChatGPT ${sample.plan === 'pro' ? 'Pro' : 'Plus'}). ` : ''}${priorWindow ? 'Previous-window calibration' : 'Weekly calibration'} ending ${formatSubscriptionTime(sample.observedAt)}. Uses local Astra tokens and assumes paid-credit weights approximate included usage. Other shared-plan activity can affect the estimate.`;
  return { capacity: {
    model: 'GPT-6.1 Sol', total,
    remaining: reset > now && weekly.usedPercent != null ? total * (1 - weekly.usedPercent / 100) : undefined,
    source, compactSource: `${source} ${describeCalibration(formatVigorTokens, formatVigorNumber)}`,
    calculation: weekly.usedPercent != null && reset > now
      ? `${calculation} Remaining = estimated total × (100% − ${weekly.usedPercent}%).` : calculation,
  } };
}

function continuousCodex(account: SubscriptionRecord, evidence: UsageEvidence | undefined, now: number) {
  const report = account.lastUsage;
  const weekly = report?.windows.find(window => window.kind === 'weekly' && window.windowMinutes === weekMinutes);
  const reset = Date.parse(weekly?.resetsAt ?? '');
  const created = Date.parse(account.createdAt ?? '');
  if (!weekly || reset <= now || !Number.isFinite(reset) || !Number.isFinite(created)
    || account.state !== 'signed_in' || !Array.isArray(evidence?.codexWeeklyCalibration)) return undefined;
  const matching = evidence.codexWeeklyCalibration.filter(row => row && row.plan === report?.plan
    && Math.abs(row.resetsAt * 1_000 - reset) <= 8_000 && row.observedAt * 1_000 >= created
    && row.observedAt * 1_000 <= now && row.observedAt * 1_000 < reset
    && row.usedPercent >= 0 && row.usedPercent <= 100 && row.points >= 0 && row.points <= 100);
  if (matching.length !== 1) return undefined;
  const [reading] = matching;
  const sample = reading.sample;
  if (!sample || !(sample.points >= 20 && sample.points <= 100)
    || !(sample.startedAt * 1_000 >= created && sample.startedAt < sample.observedAt && sample.observedAt <= reading.observedAt)
    || !Number.isSafeInteger(sample.outputTokens) || sample.outputTokens <= 0
    || !Number.isSafeInteger(sample.inputTokens) || !Number.isSafeInteger(sample.cachedInputTokens)
    || sample.cachedInputTokens < 0 || sample.cachedInputTokens > sample.inputTokens) {
    return { weekly, reading, detail: `Collecting GPT-6.2 Sol calibration · ${formatVigorNumber(reading.points)} of 20 percentage points.` };
  }
  const total = sample.outputTokens * 100 / sample.points;
  const lower = sample.outputTokens * 100 / Math.min(100, sample.points + 1);
  const upper = sample.outputTokens * 100 / (sample.points - 1);
  const operands = `${formatVigorTokens(sample.outputTokens)} output tokens ÷ ${formatVigorNumber(sample.points)}% of the weekly quota`;
  const observed = formatSubscriptionCardTime(new Date(sample.observedAt * 1_000).toISOString());
  const cache = sample.inputTokens > 0 ? ` · ${formatVigorNumber(sample.cachedInputTokens * 100 / sample.inputTokens)}% cached input` : '';
  const detail = `GPT-6.2 Sol calibration · ${operands} · rounding range ${formatVigorTokens(lower)}–${formatVigorTokens(upper)}${cache} · ${observed}.`;
  const capacity: Capacity = { model: 'GPT-6.2 Sol', total, source: detail, calculation: operands, compactSource: detail };
  return { weekly, reading, detail, capacity };
}

function allowance(
  driver: string, account: SubscriptionRecord, saved: Result | undefined, evidence: UsageEvidence | undefined, now: number,
): AllowanceView | undefined {
  if (account.state !== 'signed_in') return undefined;
  if (driver === 'mimo' && account.family === 'xiaomi') return mimoQuota(account, saved, evidence?.mimo, now);
  if (driver === 'pi' && account.family === 'chatgpt') {
    return chatGPTQuota(account, evidence?.piChatGPT, now);
  }
  const windows = account.lastUsage?.windows ?? [];
  const issues = windows.length > 0 && windows.some((window) => !window.resetsAt)
    ? ['One or more quota windows lack a reset time.'] : [];
  if (driver === 'codex' && account.family === 'chatgpt') {
    const capacity = codexCapacity(account, evidence?.codex, now);
    return { ...capacity, issues: [...capacity.issues ?? [], ...issues] };
  }
  if (driver === 'claude' && account.family === 'anthropic') {
    issues.push('Absolute Claude capacity unavailable. The plan reports usage shares without a published token cap.');
  } else if (driver === 'pi' && account.family === 'kimi-coding') {
    issues.push('Absolute Kimi capacity unavailable. Converting reported calls and shared credits requires a token conversion.');
  } else if (driver === 'pi' && account.family === 'zai') {
    issues.push('Absolute z.ai capacity unavailable. The Coding Plan reports quota shares without a token conversion.');
  } else if (driver === 'pi' && account.family === 'deepseek') {
    if (!account.lastUsage?.extra?.balances?.length) issues.push('No DeepSeek balance reading. Refresh Subscriptions to check the API key.');
    return issues.length ? { issues } : undefined;
  } else return undefined;
  if (!windows.some((window) => window.usedPercent != null)) issues.unshift('No quota percentage is available.');
  return { issues };
}

type Capacity = NonNullable<AllowanceView['capacity']> & { compactSource?: string };

function planTokenCost(billing: SubscriptionPrice, capacity: Capacity, window: string, weekly: boolean): VigorEstimatedTokenCost {
  const { label, amount, currency, months } = billing;
  const period = weekly ? 'weekly' : 'monthly';
  const monthlyAmount = amount / months;
  function describeBasis(tokens: string, format: (value: number) => string, units: string, source: string) {
    const denominator = weekly ? `${tokens} ${capacity.model} output-token equivalents × 52/12 weeks per month`
      : `${tokens} ${capacity.model} output-token equivalents per month`;
    const price = billing.source === 'list' ? `monthly list price of ${format(amount)} ${currency}`
      : `${format(amount)} ${currency} paid for ${months} ${months === 1 ? 'month' : 'months'} (${format(monthlyAmount)} ${currency} monthly equivalent)`;
    return `${label} ${price} ÷ (${denominator}) × ${units}. Assumes full use of the ${period} allowance. ${source}`;
  }
  return {
    window,
    windowsPerMonth: weekly ? weeksPerMonth : 1,
    perMillion: monthlyAmount / (capacity.total * (weekly ? weeksPerMonth : 1)) * 1_000_000,
    currency,
    basis: describeBasis(integer.format(Math.round(capacity.total)), String, '1 million', capacity.source),
    compactBasis: describeBasis(formatVigorTokens(capacity.total), formatVigorNumber, '1M', capacity.compactSource ?? capacity.source),
  };
}

function codexMonthlyPrice(report: DriverReport | undefined, browser: BrowserReport['report'] | undefined, now: number) {
  const browserPlan = browser && recentObservation(browser.fetchedAt, now) ? browser.plan : undefined;
  if (report?.plan === 'plus' && !browserPlan) return codexPlusPrice;
  if (report?.plan === 'pro' && browserPlan === 'pro-200') return codexPro200Price;
  return undefined;
}

function mimoMonthlyPrice(quota: Quota | undefined, minutes: number | undefined) {
  const plan = mimoMonthlyPlans.get(quota?.plan?.trim().toLowerCase() ?? '');
  if (!plan || quota?.credits?.total !== plan.credits
    || minutes === undefined || minutes < 28 * 1440 || minutes > 32 * 1440) return undefined;
  return { label: `Xiaomi Token Plan ${quota?.plan}`, usd: plan.usd };
}

function currentPayment(account: SubscriptionRecord, billing: MembershipPayment | undefined, now: number) {
  return billing?.subscription === account.id && sameCreation(billing.createdAt, account.createdAt)
    && Date.parse(billing.checkedAt) === Date.parse(account.checkedAt ?? '')
    && Date.parse(billing.confirmedAt) <= now && now < Date.parse(billing.validUntil) ? billing : undefined;
}

type WindowReading = Omit<SubscriptionWindow, 'remainingMinutes' | 'outputTokensPerHour'>;
type Rollover = 'startsOnUse' | 'weekly' | 'wait';

function asWindow(
  reading: WindowReading,
  now: number,
  capacity?: Capacity,
  rollover: Rollover = 'wait',
): SubscriptionWindow {
  let end = endTime(reading);
  if (end <= now) {
    const { label, windowMinutes, terminal } = reading;
    if (terminal || rollover === 'wait') return { label, windowMinutes, terminal, next: 'awaitingRenewal' };
    const period = (windowMinutes ?? 0) * 60_000;
    if (rollover === 'weekly' && period > 0) {
      end += period * (1 + Math.floor((now - end) / period));
    }
    reading = {
      label, windowMinutes, next: 'projected',
      approximateReset: rollover === 'weekly' ? reading.approximateReset : undefined,
      pendingStart: rollover === 'startsOnUse',
      resetsAt: rollover === 'weekly' ? new Date(end).toISOString() : undefined,
      usedPercent: 0, remainingPercent: 100,
    };
    end = endTime(reading);
  }
  const remainingMinutes = Number.isFinite(end) ? (end - now) / 60_000 : undefined;
  const used = reading.usedPercent;
  const left = reading.remainingPercent;
  const outputTokensUsed = capacity && used !== undefined ? capacity.total * used / 100 : reading.outputTokensUsed;
  const outputTokensRemaining = capacity && left !== undefined ? capacity.total * left / 100 : reading.outputTokensRemaining;
  return {
    ...reading, remainingMinutes, outputTokensUsed, outputTokensRemaining,
    outputTokensTotal: capacity?.total ?? reading.outputTokensTotal,
    model: capacity?.model ?? reading.model, estimateBasis: capacity?.source ?? reading.estimateBasis,
    outputTokensPerHour: outputTokensRemaining !== undefined && remainingMinutes !== undefined && remainingMinutes > 0
      ? outputTokensRemaining / remainingMinutes * 60 : undefined,
  };
}

function rolloverFor(driver: string, family: string, minutes?: number): Rollover {
  const chatgpt = (driver === 'codex' || driver === 'pi') && family === 'chatgpt';
  const claude = driver === 'claude' && family === 'anthropic';
  const zai = driver === 'pi' && family === 'zai';
  const kimi = driver === 'pi' && family === 'kimi-coding';
  if (minutes === 300 && (chatgpt || claude || zai || kimi)) return 'startsOnUse';
  if (minutes === 10_080 && (chatgpt || claude || zai)) return 'weekly';
  return 'wait';
}

function resetExpiry(value: unknown): string | undefined {
  if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0 && value <= 8_640_000_000_000) {
    return new Date(value * 1000).toISOString();
  }
  return undefined;
}

function resetInventory(account: SubscriptionRecord, now: number): SubscriptionMetrics['limitResets'] {
  const report = account.lastUsage;
  const raw = report?.extra?.rateLimitResetCredits;
  if (!report || !raw || typeof raw !== 'object') return undefined;
  const observedAt = report.fetchedAt;
  const count = 'availableCount' in raw && typeof raw.availableCount === 'number'
    && Number.isSafeInteger(raw.availableCount) && raw.availableCount >= 0 ? raw.availableCount : undefined;
  const entries: NonNullable<SubscriptionMetrics['limitResets']>['entries'] = [];
  const ids = new Set<string>();
  if ('credits' in raw && Array.isArray(raw.credits)) {
    for (const grant of raw.credits) {
      if (!grant || typeof grant !== 'object' || grant.status !== 'available') continue;
      if (typeof grant.id === 'string' && grant.id) {
        if (ids.has(grant.id)) continue;
        ids.add(grant.id);
      }
      const expiresAt = resetExpiry(grant.expiresAt);
      entries.push({
        label: typeof grant.title === 'string' && grant.title.trim() ? grant.title : 'Limit reset',
        expiresAt,
        expired: !!expiresAt && Date.parse(expiresAt) <= now,
      });
    }
  }
  const reconciled = count !== undefined && entries.length === count && ids.size === count;
  const expired = entries.filter((entry) => entry.expired).length;
  return { count: reconciled ? count - expired : count, entries, observedAt };
}

const references = {
  claudeLocal: { driver: 'claude', family: 'anthropic', model: 'Claude workload' },
  kimiLocal: { driver: 'pi', family: 'kimi-coding', model: 'Kimi Code K3.1 Pro' },
  kimiCalls: { driver: 'pi', family: 'kimi-coding', model: 'Kimi Code K3.1 Pro' },
  piChatGPT: { driver: 'pi', family: 'chatgpt', model: 'GPT-6.1 Sol' },
  zaiCredits: { driver: 'pi', family: 'zai', model: 'GLM-5.3' },
} satisfies Record<EstimateBasis, { driver: string; family: string; model: string }>;

function piPlusReference(sample: WindowEstimate, account: SubscriptionRecord, evidence: UsageEvidence | undefined, now: number) {
  const historical = evidence?.piChatGPTCalibration;
  const current = evidence?.piChatGPT;
  return sample.basis === 'piChatGPT' && historical?.subscription === account.id && historical.plan === 'plus'
    && current?.plan === 'plus' && matches(current, account, now)
    && Math.abs(Date.parse(historical.updatedAt) - Date.parse(sample.checkedAt)) <= 1_000
    && Date.parse(sample.observedAt) <= Date.parse(historical.observedAt) && recentObservation(sample.observedAt, now);
}

function zaiOutputTokens(credits: number) {
  return credits * 10_000 / 24;
}

function zaiCapacity(credits: number, source: string): Capacity {
  // https://docs.z.ai/devpack/overview.md#usage-instruction
  const calculation = `${integer.format(credits)} credits × 10,000 ÷ 24 at the published Standard output rate.`;
  return {
    model: 'GLM-5.3', total: zaiOutputTokens(credits), source: `${source} ${calculation}`, calculation,
    compactSource: `${source} ${integer.format(credits)} credits × 10K ÷ 24 at the published Standard output rate.`,
  };
}

function windowCapacity(
  driver: string, account: SubscriptionRecord, label: string, evidence: UsageEvidence | undefined, now: number,
  { resource, claudeMax5x = false, planOverride }: {
    resource?: string; claudeMax5x?: boolean; planOverride?: 'max';
  } = {},
): Capacity | undefined {
  const checkedAt = 'checkedAt' in account && typeof account.checkedAt === 'string' ? Date.parse(account.checkedAt) : NaN;
  const referencePlan = claudeMax5x ? 'pro' : planOverride ?? publicAccountPlan(account);
  const samples = evidence?.windowEstimates?.filter((sample) => {
    const reference = references[sample.basis];
    if (sample.basis === 'kimiCalls') return false; // Normalized quota units are not calls.
    if (sample.basis === 'kimiLocal' && sample.window === 'Five hours') {
      const calibration = sample.calibration;
      if (!calibration || calibration.model !== reference.model || calibration.outputTokens !== sample.amount
        || Math.abs(calibration.endUsedPercent - calibration.startUsedPercent - (sample.scale ?? 0)) > .001
        || (sample.scale ?? 0) < 5 || Date.parse(sample.observedAt) < now - 28 * day
        || Date.parse(calibration.startedAt) >= Date.parse(calibration.endedAt)
        || Date.parse(calibration.endedAt) !== Date.parse(sample.observedAt)
        || Date.parse(calibration.startResetsAt) !== Date.parse(calibration.endResetsAt)
        || Date.parse(calibration.startedAt) < Date.parse(calibration.endResetsAt) - 300 * 60_000
        || Date.parse(calibration.endedAt) >= Date.parse(calibration.endResetsAt)) return false;
    }
    const bindingMatches = sample.reference === 'plan'
      ? sample.basis === 'claudeLocal' && sameCreation(sample.createdAt, account.createdAt)
        && sample.plan !== undefined && sample.plan === referencePlan
        && recentObservation(sample.observedAt, now)
      : !claudeMax5x && !planOverride && (checkedAt === Date.parse(sample.checkedAt) || piPlusReference(sample, account, evidence, now));
    return reference && reference.driver === driver && reference.family === account.family && sample.subscription === account.id
      && bindingMatches && sample.window === label && Date.parse(sample.observedAt) <= now
      && (sample.basis !== 'zaiCredits' || resource === 'credits');
  });
  if (samples?.length !== 1) return undefined;
  const [{ basis, amount, scale, observedAt, calibration, reference, plan }] = samples;
  const model = references[basis].model;
  const number = (value: number) => integer.format(Math.round(value));
  if (basis === 'zaiCredits') {
    return zaiCapacity(amount, `Verified Coding Plan credit cap. Sampled ${formatSubscriptionCardTime(observedAt)}.`);
  }
  if (!scale) return undefined;
  const total = amount / (scale / 100) * (claudeMax5x ? claudeMax5xMultiplier : 1);
  const describeCalibration = (tokens: string, percent: string) => {
    const measured = `${tokens} observed output equivalents ÷ ${percent}% of the window`;
    return claudeMax5x ? `(${measured}) × ${claudeMax5xMultiplier}.` : `${measured}.`;
  };
  const calculation = describeCalibration(number(amount), String(scale));
  let source = 'Local output from the observed workload, scaled by the provider’s reported used share. Other account usage can affect the estimate.';
  if (basis === 'kimiLocal' && calibration) {
    source = 'Local K3.1 Pro output between ' + formatSubscriptionCardTime(calibration.startedAt)
      + ' and ' + formatSubscriptionCardTime(calibration.endedAt) + '. Usage moved from '
      + calibration.startUsedPercent + '% to ' + calibration.endUsedPercent
      + '% before the same reset at ' + formatSubscriptionCardTime(calibration.endResetsAt)
      + '. Other shared-account activity can affect this reference estimate.';
  } else if (basis === 'piChatGPT') {
    source = 'Local Codex usage matched to the ChatGPT Plus window, using published Standard credit weights.';
    if (piPlusReference(samples[0], account, evidence, now)) source = `Plan reference (ChatGPT Plus). ${source}`;
  }
  if (claudeMax5x) {
    source = `Claude Pro workload calibration scaled by Anthropic’s published Max 5× allowance. Assumes a similar workload. ${source}`;
  } else if (reference === 'plan') {
    source = `Plan reference (Claude ${plan}). ${source} Capacity assumes a similar workload on the same reported plan.`;
  }
  const provenance = `${source} Sampled ${formatSubscriptionCardTime(observedAt)}.`;
  return {
    model, total, source: `${provenance} ${calculation}`, calculation,
    compactSource: `${provenance} ${describeCalibration(formatVigorTokens(amount), formatVigorNumber(scale))}`,
  };
}

function matchingClaudeReading(
  driver: string, account: SubscriptionRecord, reading: UsageEvidence['claudeDashboard'], now: number,
): UsageEvidence['claudeDashboard'] {
  if (driver !== 'claude' || account.family !== 'anthropic' || account.state !== 'signed_in' || !reading) return undefined;
  return reading.subscription === account.id && sameCreation(reading.createdAt, account.createdAt)
    && Date.parse(reading.checkedAt) === Date.parse(account.checkedAt ?? '')
    && Date.parse(reading.observedAt) <= now
    ? reading : undefined;
}

function matchingBrowserReport(
  driver: string, account: SubscriptionRecord, evidence: UsageEvidence | undefined, now: number,
): BrowserReport | undefined {
  if (account.state !== 'signed_in' || account.family !== account.id) return undefined;
  return evidence?.browserReports?.find((entry) => entry.driver === driver && entry.subscription === account.id
    && sameCreation(entry.createdAt, account.createdAt)
    && (Date.parse(entry.createdAt) !== 0 || entry.checkedAt === account.checkedAt)
    && Date.parse(entry.report.fetchedAt) <= now);
}

function apiBalance(
  account: SubscriptionRecord, report: BrowserReport['report'] | undefined, now: number,
): Pick<SubscriptionMetrics, 'balance' | 'estimatedTokenCost'> | undefined {
  if (account.state !== 'signed_in') return undefined;
  const reading = report?.extra?.apiBalance;
  const cash = Number(reading?.balance);
  const observed = Date.parse(reading?.observedAt ?? '');
  const deepseek = account.family === 'deepseek';
  const fallback = deepseek ? deepSeekBalance(report?.extra?.balances?.length ? { ...account, lastUsage: report } : account) : undefined;
  if (!reading || !Number.isFinite(cash) || cash < 0 || !(observed <= now)) {
    if (!fallback) return undefined;
    const rateBasis = `DeepSeek Flash at ${fallback.rate} ${fallback.currency} per million output tokens.`;
    return {
      balance: {
        availableTokens: fallback.tokens,
        estimateBasis: `${rateBasis} Based on the current reported balance.`,
      },
      estimatedTokenCost: { perMillion: fallback.rate, currency: fallback.currency, basis: rateBasis },
    };
  }
  const model = deepseek ? 'DeepSeek Flash peak rate' : 'MiniMax-M3 Standard, up to 512k input';
  // https://api-docs.deepseek.com/quick_start/pricing/
  // https://platform.minimax.io/docs/pricing/overview?tab=api-enterprise
  const rate = 1.2;
  const rateBasis = `${model} at ${rate} USD per million output tokens.`;
  const equivalents = (dollars: number) => dollars / rate * 1_000_000;
  const paymentDate = reading.paymentAt?.match(/^20\d{2}-\d{2}-\d{2}(?= )/)?.[0];
  const starting = Number(reading.startingBalance);
  const used = paymentDate && Number.isFinite(starting) && starting > 0 && cash <= starting ? starting - cash : undefined;
  const basis = used === undefined ? 'The starting balance could not be established.'
    : reading.includesCarry ? `The ${starting} USD starting balance includes the payment and the previous cash reading.`
    : `The ${starting} USD starting balance is estimated from the last payment.`;
  return {
    balance: {
      paymentDate, availableTokens: equivalents(cash),
      usedTokens: used === undefined ? undefined : equivalents(used),
      usedPercent: used === undefined ? undefined : 100 * used / starting,
      estimateBasis: `${rateBasis} ${basis} Cash balance read ${formatSubscriptionCardTime(reading.observedAt)}.`,
    },
    estimatedTokenCost: { perMillion: rate, currency: 'USD', basis: rateBasis },
  };
}

function subscriptionMetrics(
  driver: string, account: SubscriptionRecord, view: AllowanceView | undefined, evidence: UsageEvidence | undefined,
  now: number, history?: AllowanceHistory,
): SubscriptionMetrics {
  const report = account.lastUsage;
  const driverWindows = report?.windows ?? [];
  const browser = matchingBrowserReport(driver, account, evidence, now);
  const browserReport = browser?.report;
  if (driver === 'pi' && (account.family === 'deepseek' || account.family === 'minimax')) {
    return { windows: [], ...apiBalance(account, browserReport, now) };
  }
  const rawWindows = new Map(driverWindows.map((window) => [window.label, { window, report, browser: false, approximate: false }]));
  if (browserReport) {
    for (const window of browserReport.windows) {
      const match = driverWindows.find((entry) => entry.label === window.label
        || ((window.windowMinutes === 300 || window.windowMinutes === 10_080) && entry.windowMinutes === window.windowMinutes));
      if (!match || (!match.resetsAt || !!window.resetsAt)
        && preferDashboard(window.resetsAt ?? '', browserReport.fetchedAt, report, match, now)) {
        const label = match?.label ?? (account.family === 'zai' && window.windowMinutes === 10_080 ? 'Weekly' : window.label);
        rawWindows.set(label, {
          window: { ...window, label }, report: browserReport, browser: true,
          approximate: browser?.approximateWindows.includes(window.label) ?? false,
        });
      }
    }
  }
  const piChatGPT = driver === 'pi' && account.family === 'chatgpt';
  const codex = driver === 'codex' && account.family === 'chatgpt';
  const continuous = codex ? continuousCodex(account, evidence, now) : undefined;
  if (continuous && report) {
    // Calibrate and display the same exact driver window. A recent browser countdown may be rounded.
    const observedAt = new Date(continuous.reading.observedAt * 1_000).toISOString();
    const useLog = Date.parse(observedAt) >= Date.parse(report.fetchedAt)
      || continuous.weekly.usedPercent == null;
    const window = useLog ? { ...continuous.weekly, usedPercent: continuous.reading.usedPercent } : continuous.weekly;
    rawWindows.set(window.label, { window, report: { ...report, fetchedAt: useLog ? observedAt : report.fetchedAt },
      browser: false, approximate: false });
  }
  const claude = driver === 'claude' && account.family === 'anthropic';
  const claudePlan = claude ? publicAccountPlan(account) : undefined;
  const claudeReading = matchingClaudeReading(driver, account, evidence?.claudeDashboard, now);
  const boundClaudePlan = claude && browserReport && recentObservation(browserReport.fetchedAt, now)
    ? browserReport.plan : undefined;
  const legacyClaudePlan = claudeReading && recentObservation(claudeReading.observedAt, now)
    && Date.parse(claudeReading.observedAt) >= Date.parse(claudeReading.checkedAt) ? claudeReading.plan : undefined;
  const verifiedClaudePlan = boundClaudePlan ?? legacyClaudePlan;
  const claudePlanChanged = verifiedClaudePlan !== undefined && verifiedClaudePlan !== claudePlan;
  const maxConfirmation = evidence?.claudeMax5x;
  const confirmedAt = Date.parse(maxConfirmation?.confirmedAt ?? '');
  const confirmedMax = claude && account.state === 'signed_in' && maxConfirmation?.subscription === account.id
    && sameCreation(maxConfirmation.createdAt, account.createdAt) && confirmedAt <= now;
  const dashboardMax = verifiedClaudePlan === 'max';
  const confirmedSincePlanCheck = Date.parse(account.checkedAt ?? '') <= confirmedAt
    && (!claudeReading || Date.parse(claudeReading.observedAt) <= confirmedAt)
    && (!boundClaudePlan || verifiedClaudePlan === 'max');
  const claudeMax5x = confirmedMax && (dashboardMax || confirmedSincePlanCheck);
  const dashboard = claudeReading?.plan === (claudeMax5x ? 'max' : claudePlan) ? claudeReading : undefined;
  function capacityForWindow(label: string, resource?: string) {
    const planOverride = claudeMax5x && claudePlan !== 'max' ? 'max' : undefined;
    const current = claudePlanChanged && !claudeMax5x
      ? undefined : windowCapacity(driver, account, label, evidence, now, { resource, planOverride });
    return current ?? (claudeMax5x ? windowCapacity(driver, account, label, evidence, now, { claudeMax5x: true }) : undefined);
  }
  const piReading = evidence?.piChatGPT;
  const boundPiReport = piChatGPT && browserReport && recentObservation(browserReport.fetchedAt, now)
    ? browserReport : undefined;
  const manualPi = piChatGPT && matches(piReading, account, now) && recentObservation(piReading.observedAt, now)
    ? piReading : undefined;
  const piPlan = boundPiReport?.plan ?? manualPi?.plan;
  const piAccess = boundPiReport?.extra?.connectedApp ?? manualPi;
  const piHasAllowance = piAccess?.allowed && piAccess.capPercent > 0;
  const weeklyPrice = codex ? codexMonthlyPrice(report, browserReport, now)
    : claudeMax5x ? claudeMax5xPrice
    : verifiedClaudePlan === 'max' ? claudeMaxPrice
    : verifiedClaudePlan === 'pro' ? claudeProPrice
    : piPlan === 'plus'
      ? { ...codexPlusPrice, label: 'ChatGPT Plus shared plan' } : undefined;
  const claudeWindows = new Map<string, { minutes: number; captured: QuotaReading }>();
  if (dashboard) {
    const candidates = [
      { label: 'Five hours', minutes: 300, captured: dashboard.fiveHour },
      { label: 'Seven days', minutes: weekMinutes, captured: dashboard.weekly },
    ];
    for (const { label, minutes, captured } of candidates) {
      if (captured && preferDashboard(captured.resetsAt, dashboard.observedAt, report,
        driverWindows.find((window) => window.label === label), now)) {
        claudeWindows.set(label, { minutes, captured });
      }
    }
  }
  const kimi = driver === 'pi' && account.family === 'kimi-coding';
  const zai = driver === 'pi' && account.family === 'zai';
  const mimo = driver === 'mimo' && account.family === 'xiaomi';
  const passedBoundaries = new Set<number>();
  const capacities = new Map<SubscriptionWindow, Capacity>();
  const historyKey = history && allowanceHistoryKey(driver, account);
  const saved = historyKey ? Object.assign(Object.create(null) as NonNullable<AllowanceHistory[string]>, history?.[historyKey]) : undefined;
  function project(reading: WindowReading, capacity?: Capacity) {
    const end = endTime(reading);
    if (end <= now) passedBoundaries.add(end);
    const window = asWindow(reading, now, capacity, rolloverFor(driver, account.family, reading.windowMinutes));
    if (capacity && Number.isFinite(capacity.total) && capacity.total > 0) capacities.set(window, capacity);
    const observed = Date.parse(reading.observedAt ?? '');
    if (saved && capacity && observed <= now && observed < end) {
      rememberEstimate(saved, asWindow(reading, observed, capacity));
    }
    return window;
  }
  const windows = [...rawWindows.values()].filter(({ window }) => !claudeWindows.has(window.label)
    && !(piChatGPT && view?.quota?.windows.some((entry) => entry.windowMinutes === window.windowMinutes))).map((entry) => {
    const { window } = entry;
    const used = window.usedPercent;
    // The monthly membership credits expire at the reported refresh boundary.
    // https://www.kimi.com/en/help/membership/membership-update-rules
    const terminal = window.resource === 'credits' && (
      kimi && window.label.startsWith('Monthly,') || mimo && window.label === 'Token Plan'
    );
    const pendingStart = rolloverFor(driver, account.family, window.windowMinutes) === 'startsOnUse'
      && used === 0 && !window.resetsAt;
    const observedCap = zai && browserReport
      && recentObservation(browserReport.fetchedAt, now) ? browserReport.windows.find(row => row.resource === 'credits'
        && row.windowMinutes === window.windowMinutes)?.creditsTotal : undefined;
    const calibration = continuous && window.label === continuous.weekly.label ? continuous : undefined;
    const capacity = codex && window.windowMinutes === weekMinutes ? (calibration ? calibration.capacity : view?.capacity)
      : typeof observedCap === 'number' && Number.isSafeInteger(observedCap) && observedCap > 0
        ? zaiCapacity(observedCap, 'Coding Plan credit cap from the confirmed z.ai dashboard.')
        : capacityForWindow(window.label, window.resource);
    return project({
      label: window.label, resetsAt: window.resetsAt, windowMinutes: window.windowMinutes,
      expiresAt: terminal ? window.resetsAt : undefined, terminal, pendingStart,
      source: entry.browser ? browserSource : calibration ? 'Codex local quota evidence' : undefined,
      calibrationDetail: calibration?.detail,
      approximateReset: entry.approximate,
      observedAt: entry.report?.fetchedAt, usedPercent: used, remainingPercent: used === undefined ? undefined : 100 - used,
    }, capacity);
  });

  if (dashboard) {
    for (const [label, { minutes, captured }] of claudeWindows) {
      windows.push(project({
        label, windowMinutes: minutes, resetsAt: captured.resetsAt, source: browserSource,
        approximateReset: captured.approximateReset,
        observedAt: dashboard.observedAt, remainingPercent: captured.remainingPercent, usedPercent: 100 - captured.remainingPercent,
      }, capacityForWindow(label)));
    }
  }
  const quota = view?.quota;
  if (quota) {
    for (const window of quota.windows) {
      const left = window.remainingPercent;
      const capacity = mimo ? view?.capacity : windowCapacity(driver, account, window.label, evidence, now);
      const row = project({
        label: window.label, resetsAt: window.resetsAt, windowMinutes: window.windowMinutes,
        approximateReset: window.approximateReset,
        expiresAt: mimo ? window.resetsAt : undefined, terminal: mimo,
        source: quota.source, observedAt: quota.observedAt,
        usedPercent: left === undefined ? undefined : 100 - left, remainingPercent: left,
      }, capacity);
      const matching = windows.findIndex((reported) => reported.label === row.label);
      if (matching < 0) windows.push(row);
      else windows[matching] = row;
    }
  }

  windows.sort((left, right) => (endTime(left) - endTime(right)) || 0);
  const pricingWindow = windows.find(window => window.next !== 'awaitingRenewal' && capacities.has(window) && (
    kimi ? window.label === 'Monthly, Kimi Code'
      : mimo ? window.label === quota?.windows[0]?.label : window.windowMinutes === weekMinutes
  ));
  const pricingCapacity = pricingWindow && capacities.get(pricingWindow);
  const zaiPlan = zai ? zaiMonthlyPlans.find(plan => zaiOutputTokens(plan.weeklyCredits) === pricingCapacity?.total) : undefined;
  const zaiPayment = zai ? currentPayment(account, evidence?.zaiBilling, now) : undefined;
  const payment = kimi ? currentPayment(account, evidence?.kimiBilling, now)
    : zaiPayment && (!pricingCapacity || zaiPayment.weeklyCredits === zaiPlan?.weeklyCredits) ? zaiPayment : undefined;
  const listPrice = mimo ? mimoMonthlyPrice(quota, quota?.windows[0]?.windowMinutes) : zai ? zaiPlan : weeklyPrice;
  const price: SubscriptionPrice | undefined = account.state !== 'signed_in' ? undefined
    : payment ? { label: kimi ? 'Kimi Code membership' : zaiPlan?.label ?? 'z.ai GLM Coding Plan',
        amount: payment.amount, currency: payment.currency, months: payment.months, source: 'payment' }
    : listPrice && { label: listPrice.label, amount: listPrice.usd, currency: 'USD', months: 1, source: 'list' };
  const rate = pricingWindow && pricingCapacity && price && (!piChatGPT || piHasAllowance)
    ? planTokenCost(price, pricingCapacity, pricingWindow.label, !mimo && !kimi) : undefined;
  const tokenCostUnavailableReason = rate || account.state !== 'signed_in' ? undefined
    : piAccess && !piHasAllowance ? 'Pi access disabled'
    : !pricingCapacity ? 'Token allowance uncalibrated'
    : zai || mimo ? 'Priced tier unverified' : kimi ? 'Membership price unknown' : 'Monthly price unknown';
  if (history && historyKey && saved && Object.keys(saved).length) history[historyKey] = saved;
  const displayWindows = saved ? restoreEstimates(windows, saved, now) : windows;
  const issues = displayWindows.length === 0 ? view?.issues ?? [] : [];
  if (piAccess) {
    if (!piAccess.allowed) issues.push('Pi’s access to the shared plan was disabled at the reading.');
    else if (piAccess.capPercent < 100) issues.push('Pi has a separate app cap. These figures describe the shared plan.');
  }
  let limitResets = resetInventory(account, now);
  if (browserReport?.extra?.rateLimitResetCredits && (!limitResets?.observedAt
    || Date.parse(browserReport.fetchedAt) > Date.parse(limitResets.observedAt))) {
    limitResets = resetInventory({ ...account, lastUsage: browserReport }, now);
  }
  if (dashboard?.resetExpiries && (!limitResets?.observedAt
      || Date.parse(dashboard.observedAt) > Date.parse(limitResets.observedAt))) {
    const entries = dashboard.resetExpiries.filter((expiresAt) => Date.parse(expiresAt) > now)
      .map((expiresAt) => ({ label: 'Full reset', expiresAt }));
    limitResets = { count: entries.length, entries, observedAt: dashboard.observedAt };
  }
  return { windows: displayWindows, price, estimatedTokenCost: rate, tokenCostUnavailableReason, issues, passedBoundaries: [...passedBoundaries], limitResets };
}

function endTime(window: SubscriptionWindow) {
  return Math.min(
    (window.resetsAt && Date.parse(window.resetsAt)) || Infinity,
    (window.expiresAt && Date.parse(window.expiresAt)) || Infinity,
  );
}

export function withAllowances(
  listing: SubscriptionListing | undefined, rollup: VigorRollup | undefined, evidence: UsageEvidence | undefined, now: number,
  browserIssues?: Record<string, string>, history?: AllowanceHistory,
): SubscriptionListing | undefined {
  if (!listing) return undefined;
  const signedInCodex = listing.drivers.filter(entry => entry.driver === 'codex')
    .flatMap(entry => entry.subscriptions ?? []).filter(account => account.family === 'chatgpt' && account.state === 'signed_in');
  // Each local reading carries the plan and weekly reset of the Subscription that paid for that response, but no
  // Subscription identity. Withhold calibration only from Subscriptions another signed-in one cannot be told apart from.
  const fingerprints = signedInCodex.map(account => {
    const weekly = account.lastUsage?.windows.find(window => window.kind === 'weekly' && window.windowMinutes === weekMinutes);
    return { account, plan: account.lastUsage?.plan, reset: Date.parse(weekly?.resetsAt ?? '') };
  });
  const ambiguous = new Set(fingerprints.filter(own => fingerprints.some(other => other.account !== own.account
    && other.plan === own.plan && Math.abs(other.reset - own.reset) <= 8_000)).map(entry => entry.account));
  const withoutCalibration = { ...evidence, codexWeeklyCalibration: undefined };
  const saved = new Map(rollup?.subscriptions.map((entry) => [subscriptionKey(entry.driver, entry.subscription), entry.result]));
  return { drivers: listing.drivers.map((driver) => ({
    ...driver, subscriptions: driver.subscriptions?.map((account) => {
      const key = subscriptionKey(driver.driver, account.id);
      const view = allowance(driver.driver, account, saved.get(key), evidence, now);
      const metrics = subscriptionMetrics(driver.driver, account, view,
        ambiguous.has(account) ? withoutCalibration : evidence, now, history);
      const browserIssue = browserIssues?.[key];
      if (browserIssue && account.state === 'signed_in') metrics.issues = [...(metrics.issues ?? []), browserIssue];
      return { ...account, allowance: view, metrics };
    }),
  })) };
}
