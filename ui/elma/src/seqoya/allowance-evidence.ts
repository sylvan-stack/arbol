import {
  formatSubscriptionCardTime, formatSubscriptionTime, subscriptionKey, type AllowanceView, type SubscriptionListing,
  type SubscriptionMetrics, type SubscriptionRecord, type SubscriptionWindow,
} from '../../design-system/src/sections/seqoya-subscriptions';
import type { VigorRollup } from '../../design-system/src/sections/seqoya-vigor';
import { deepSeekBalance } from './vigor-estimates';

interface QuotaReading {
  remainingPercent: number;
  resetsAt: string;
}

interface ManualReading {
  subscription: string;
  updatedAt: string;
  observedAt: string;
}

type EstimateBasis = 'claudeLocal' | 'kimiLocal' | 'kimiCalls' | 'piChatGPT' | 'zaiCredits';

interface WindowEstimate {
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

/** The optional bounded projection returned by the native app.readVigor channel. */
export interface UsageEvidence {
  windowEstimates?: WindowEstimate[];
  piChatGPT?: ManualReading & {
    plan: 'plus' | 'pro';
    allowed: boolean;
    capPercent: number;
    fiveHour?: QuotaReading;
    weekly?: QuotaReading;
  };
  mimo?: ManualReading & {
    resetsAt: string;
    plan?: 'lite' | 'standard' | 'pro' | 'max';
    totalCredits: string;
    remainingCredits: string;
  };
  codex?: {
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
const day = 86_400_000;
const integer = new Intl.NumberFormat();
// Xiaomi Token Plan rate for mimo-v2.6-pro. Checked 12 November 2026.
// https://mimo.mi.com/docs/en-US/quick-start/faq/token-plan/Usage%26Quota
const mimoCreditsPerOutputToken = 600;
const planNames = { lite: 'Lite', standard: 'Standard', pro: 'Pro', max: 'Max' };

function matches<T extends ManualReading>(reading: T | undefined, account: SubscriptionRecord, now: number): reading is T {
  return !!reading && reading.subscription === account.id && reading.updatedAt === account.updatedAt
    && Date.parse(reading.observedAt) <= now;
}

function windowReading(label: string, resetsAt: string | undefined, now: number, remainingPercent: number, windowMinutes?: number) {
  return { label, remainingPercent, resetsAt, windowMinutes, elapsed: !!resetsAt && Date.parse(resetsAt) <= now };
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
    quota = {
      source: 'Xiaomi Token Plan', plan: report.plan, observedAt: report.fetchedAt,
      credits: validCredits(report.extra?.planCredits) ? report.extra.planCredits : undefined,
      windows: [windowReading(directWindow.label, directWindow.resetsAt, now, 100 - directWindow.usedPercent, directWindow.windowMinutes)],
    };
  }
  if (manual && (!quota || quota.windows[0].elapsed
    && Date.parse(manual.resetsAt) > Date.parse(quota.windows[0].resetsAt ?? ''))) {
    const duration = radarWindow?.resetsAt && Date.parse(radarWindow.resetsAt) === Date.parse(manual.resetsAt)
      ? radarWindow.windowMinutes ?? undefined : undefined;
    const credits = { total: manual.totalCredits, remaining: manual.remainingCredits };
    if (validCredits(credits)) {
      quota = {
        source: 'Saved Xiaomi Token Plan reading', plan: manual.plan && planNames[manual.plan],
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
  if (!quota) return { issues: ['No MiMo quota reading. Refresh usage or open the Xiaomi console.'] };
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
    return { issues: ['Pi quota has no saved dashboard reading. Open ChatGPT Usage and check Connected App Limits for this sign-in.'] };
  }
  const windows = [
    ...(reading.fiveHour ? [windowReading('Shared five-hour quota', reading.fiveHour.resetsAt, now, reading.fiveHour.remainingPercent, 300)] : []),
    ...(reading.weekly ? [windowReading('Shared weekly quota', reading.weekly.resetsAt, now, reading.weekly.remainingPercent, 10_080)] : []),
  ];
  const issues = ['Absolute token capacity unavailable. ChatGPT Usage reports percentages for the shared plan.'];
  if (!reading.allowed) issues.push('Pi’s access to the shared plan was disabled at the reading.');
  else if (reading.capPercent < 100) issues.push('Pi’s remaining app-specific quota needs a separate consumption reading.');
  if (!windows.length) issues.push('Shared plan quota has no reading.');
  return { issues, quota: {
    source: 'ChatGPT dashboard snapshot', observedAt: reading.observedAt,
    plan: reading.plan === 'plus' ? 'ChatGPT Plus' : 'ChatGPT Pro',
    note: reading.allowed ? `Pi could use up to ${reading.capPercent}% of the shared plan at this reading.` : undefined,
    windows,
  } };
}

function codexCapacity(account: SubscriptionRecord, sample: UsageEvidence['codex'], now: number): AllowanceView {
  const usage = account.lastUsage;
  const checkedAt = 'checkedAt' in account && typeof account.checkedAt === 'string' ? account.checkedAt : undefined;
  const weekly = usage?.windows.find((window) => window.kind === 'weekly' && window.windowMinutes === 10_080);
  if (!sample || !usage || !weekly || sample.subscription !== account.id || sample.createdAt !== account.createdAt
    || !checkedAt || Date.parse(sample.checkedAt) !== Date.parse(checkedAt)
    || sample.plan !== usage.plan || Date.parse(sample.observedAt) > now || Date.parse(sample.observedAt) < now - 28 * day
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
  const calculation = `(${integer.format(sample.uncachedInputTokens)} × ${astraInput} + ${integer.format(sample.cachedInputTokens)} × ${astraCache} + ${integer.format(sample.outputTokens)} × ${astraOutput}) ÷ ${sample.points}% ÷ ${solOutput}.`;
  return { capacity: {
    model: 'GPT-6.1 Sol', total,
    remaining: reset > now && weekly.usedPercent != null ? total * (1 - weekly.usedPercent / 100) : undefined,
    source: `${priorWindow ? 'Previous-window calibration' : 'Weekly calibration'} ending ${formatSubscriptionTime(sample.observedAt)}. Uses local Astra tokens and assumes paid-credit weights approximate included usage. Other shared-plan activity can affect the estimate.`,
    calculation: weekly.usedPercent != null && reset > now
      ? `${calculation} Remaining = estimated total × (100% − ${weekly.usedPercent}%).` : calculation,
  } };
}

function allowance(
  driver: string, account: SubscriptionRecord, saved: Result | undefined, evidence: UsageEvidence | undefined, now: number,
): AllowanceView | undefined {
  if (account.state !== 'signed_in') return undefined;
  if (driver === 'mimo' && account.family === 'xiaomi') return mimoQuota(account, saved, evidence?.mimo, now);
  if (driver === 'pi' && account.family === 'chatgpt' && !account.lastUsage?.windows.length) {
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
    if (!account.lastUsage?.extra?.balances?.length) issues.push('No DeepSeek balance reading. Refresh usage to check the API key.');
    return issues.length ? { issues } : undefined;
  } else return undefined;
  if (!windows.some((window) => window.usedPercent != null)) issues.unshift('No quota percentage is available.');
  return { issues };
}

type Capacity = NonNullable<AllowanceView['capacity']>;

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

function windowCapacity(
  driver: string, account: SubscriptionRecord, label: string, evidence: UsageEvidence | undefined, now: number,
  resource?: string,
): Capacity | undefined {
  const checkedAt = 'checkedAt' in account && typeof account.checkedAt === 'string' ? Date.parse(account.checkedAt) : NaN;
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
    return reference && reference.driver === driver && reference.family === account.family && sample.subscription === account.id
      && checkedAt === Date.parse(sample.checkedAt) && sample.window === label && Date.parse(sample.observedAt) <= now
      && (sample.basis !== 'zaiCredits' || resource === 'credits');
  });
  if (samples?.length !== 1) return undefined;
  const [{ basis, amount, scale, observedAt, calibration }] = samples;
  const model = references[basis].model;
  const number = (value: number) => integer.format(Math.round(value));
  let total: number;
  let calculation: string;
  let source: string;
  if (basis === 'zaiCredits') {
    // Z.AI's Coding Plan formula uses a GLM-5.3 Standard output multiplier of 24.
    // https://docs.z.ai/devpack/overview.md#usage-instruction
    total = amount * 10_000 / 24;
    calculation = `${number(amount)} credits × 10,000 ÷ 24.`;
    source = 'Verified Coding Plan credit cap at the published GLM-5.3 Standard output rate.';
  } else {
    if (!scale) return undefined;
      total = amount / (scale / 100);
      calculation = `${number(amount)} observed output equivalents ÷ ${scale}% of the window.`;
      source = basis === 'kimiLocal' && calibration
        ? 'Local K3.1 Pro output between ' + formatSubscriptionCardTime(calibration.startedAt)
          + ' and ' + formatSubscriptionCardTime(calibration.endedAt) + '. Usage moved from '
          + calibration.startUsedPercent + '% to ' + calibration.endUsedPercent
          + '% before the same reset at ' + formatSubscriptionCardTime(calibration.endResetsAt)
          + '. Other shared-account activity can affect this reference estimate.'
        : basis === 'piChatGPT'
        ? 'Local Codex usage matched to the ChatGPT Plus window, using published Standard credit weights.'
        : 'Local output from the observed workload, scaled by the provider’s reported used share. Other account usage can affect the estimate.';
  }
  return { model, total, source: `${source} Sampled ${formatSubscriptionCardTime(observedAt)}. ${calculation}`, calculation };
}

function subscriptionMetrics(
  driver: string, account: SubscriptionRecord, view: AllowanceView | undefined, evidence: UsageEvidence | undefined, now: number,
): SubscriptionMetrics {
  const report = account.lastUsage;
  const rawWindows = report?.windows ?? [];
  const calibrated = driver === 'codex' && account.family === 'chatgpt'
    ? rawWindows.find((window) => window.kind === 'weekly' && window.windowMinutes === 10_080) : undefined;
  const kimi = driver === 'pi' && account.family === 'kimi-coding';
  const mimo = driver === 'mimo' && account.family === 'xiaomi';
  const passedBoundaries = new Set<number>();
  function project(reading: WindowReading, capacity?: Capacity) {
    const end = endTime(reading);
    if (end <= now) passedBoundaries.add(end);
    return asWindow(reading, now, capacity, rolloverFor(driver, account.family, reading.windowMinutes));
  }
  const windows = rawWindows.map((window) => {
    const used = window.usedPercent;
    // The monthly membership credits expire at the reported refresh boundary.
    // https://www.kimi.com/en/help/membership/membership-update-rules
    const terminal = window.resource === 'credits' && (
      kimi && window.label.startsWith('Monthly,') || mimo && window.label === 'Token Plan'
    );
    const pendingStart = rolloverFor(driver, account.family, window.windowMinutes) === 'startsOnUse'
      && used === 0 && !window.resetsAt;
    const capacity = window === calibrated ? view?.capacity
      : windowCapacity(driver, account, window.label, evidence, now, window.resource);
    return project({
      label: window.label, resetsAt: window.resetsAt, windowMinutes: window.windowMinutes,
      expiresAt: terminal ? window.resetsAt : undefined, terminal, pendingStart,
      observedAt: report?.fetchedAt, usedPercent: used, remainingPercent: used === undefined ? undefined : 100 - used,
    }, capacity);
  });

  const quota = view?.quota;
  if (quota) {
    for (const window of quota.windows) {
      const left = window.remainingPercent;
      const capacity = mimo ? view?.capacity : windowCapacity(driver, account, window.label, evidence, now);
      const row = project({
        label: window.label, resetsAt: window.resetsAt, windowMinutes: window.windowMinutes,
        expiresAt: mimo ? window.resetsAt : undefined, terminal: mimo,
        source: quota.source, observedAt: quota.observedAt,
        usedPercent: left === undefined ? undefined : 100 - left, remainingPercent: left,
      }, capacity);
      const matching = windows.findIndex((reported) => reported.label === row.label);
      if (matching < 0) windows.push(row);
      else windows[matching] = row;
    }
  }

  const balance = deepSeekBalance(account);
  if (balance && report) {
    windows.push(asWindow({
      label: 'API balance', resetsAt: null, observedAt: report.fetchedAt,
      outputTokensRemaining: balance.tokens, model: 'DeepSeek Flash',
      estimateBasis: `${balance.amount} ${balance.currency} at ${balance.rate} ${balance.currency} per million output tokens.`,
    }, now));
  }
  windows.sort((left, right) => (endTime(left) - endTime(right)) || 0);
  const issues = windows.length === 0 ? view?.issues ?? [] : [];
  if (account.state === 'signed_in' && account.family !== 'deepseek') {
    for (const window of windows) {
      if (window.next !== 'awaitingRenewal' && window.outputTokensRemaining === undefined) issues.push(`${window.label} needs a matching token estimate.`);
    }
  }
  const piReading = evidence?.piChatGPT;
  if (driver === 'pi' && account.family === 'chatgpt' && matches(piReading, account, now)) {
    if (!piReading.allowed) issues.push('Pi’s access to the shared plan was disabled at the reading.');
    else if (piReading.capPercent < 100) issues.push('Pi has a separate app cap. These figures describe the shared plan.');
  }
  return { windows, issues, passedBoundaries: [...passedBoundaries], limitResets: resetInventory(account, now) };
}

function endTime(window: SubscriptionWindow) {
  return Math.min(
    (window.resetsAt && Date.parse(window.resetsAt)) || Infinity,
    (window.expiresAt && Date.parse(window.expiresAt)) || Infinity,
  );
}

export function withAllowances(
  listing: SubscriptionListing | undefined, rollup: VigorRollup | undefined, evidence: UsageEvidence | undefined, now: number,
): SubscriptionListing | undefined {
  if (!listing) return undefined;
  const saved = new Map(rollup?.subscriptions.map((entry) => [subscriptionKey(entry.driver, entry.subscription), entry.result]));
  return { drivers: listing.drivers.map((driver) => ({
    ...driver, subscriptions: driver.subscriptions?.map((account) => {
      const view = allowance(driver.driver, account, saved.get(subscriptionKey(driver.driver, account.id)), evidence, now);
      return { ...account, allowance: view, metrics: subscriptionMetrics(driver.driver, account, view, evidence, now) };
    }),
  })) };
}
