import type { SubscriptionRecord, SubscriptionWindow } from '../../design-system/src/sections/seqoya-subscriptions';

type SavedEstimate = Pick<SubscriptionWindow, 'label' | 'windowMinutes' | 'model' | 'estimateBasis' | 'outputTokensPerHour'> & {
  savedEstimateAt: string;
  outputTokensUsed: number;
  outputTokensRemaining: number;
};

type SavedWindows = Record<string, SavedEstimate>;
export type AllowanceHistory = Record<string, SavedWindows>;
const storageKey = 'arbol-seqoya:allowance-history';

export function readAllowanceHistory(): AllowanceHistory {
  try {
    return JSON.parse(localStorage.getItem(storageKey) ?? '{}') ?? {};
  } catch {
    return {};
  }
}

export function saveAllowanceHistory(history: AllowanceHistory) {
  try {
    localStorage.setItem(storageKey, JSON.stringify(history));
  } catch {
    // The window still retains its last readings when persistent storage is unavailable.
  }
}

export function allowanceHistoryKey(driver: string, account: SubscriptionRecord) {
  const created = Date.parse(account.createdAt ?? '');
  if (account.state !== 'signed_in' || !Number.isFinite(created)) return undefined;
  // Older subscriptions use the epoch as a placeholder for their creation identity.
  const identity = created || Date.parse(account.checkedAt ?? '');
  return Number.isFinite(identity) ? JSON.stringify([driver, account.family, account.id, created, identity]) : undefined;
}

function tokenAmount(value: number | undefined): value is number {
  return value !== undefined && Number.isFinite(value) && value >= 0;
}

export function rememberEstimate(saved: SavedWindows, window: SubscriptionWindow) {
  if (window.calibrationDetail) return;
  const { label, windowMinutes, observedAt, model, estimateBasis, outputTokensUsed,
    outputTokensRemaining, outputTokensPerHour } = window;
  if (window.next || window.pendingStart || !observedAt || !tokenAmount(outputTokensUsed)
    || !tokenAmount(outputTokensRemaining)) return;
  const previous = saved[label];
  if (previous && (Date.parse(previous.savedEstimateAt) > Date.parse(observedAt)
    || previous.outputTokensPerHour !== undefined && outputTokensPerHour === undefined)) return;
  saved[label] = {
    label, windowMinutes, savedEstimateAt: observedAt, model, estimateBasis,
    outputTokensUsed, outputTokensRemaining, outputTokensPerHour,
  };
}

export function restoreEstimates(windows: SubscriptionWindow[], saved: SavedWindows, now: number) {
  const estimates = Object.values(saved).filter(estimate => estimate && typeof estimate.label === 'string'
    && Date.parse(estimate.savedEstimateAt) <= now && tokenAmount(estimate.outputTokensUsed)
    && tokenAmount(estimate.outputTokensRemaining));
  const reported = new Set(windows.map(window => window.label));
  const windowEstimates = new Map(estimates.map(estimate => [estimate.label, estimate]));
  return [
    ...windows.map(window => {
      if (window.calibrationDetail) return window;
      const estimate = windowEstimates.get(window.label);
      if (!estimate) return window;
      const missingRate = !window.pendingStart && window.outputTokensPerHour === undefined
        && estimate.outputTokensPerHour !== undefined;
      return window.next || window.outputTokensRemaining === undefined || missingRate
        ? { ...estimate, ...window, savedEstimateAt: estimate.savedEstimateAt, model: estimate.model,
            estimateBasis: estimate.estimateBasis, outputTokensUsed: estimate.outputTokensUsed,
            outputTokensRemaining: estimate.outputTokensRemaining, outputTokensPerHour: estimate.outputTokensPerHour }
        : window;
    }),
    ...estimates.filter(estimate => !reported.has(estimate.label)).map(estimate => ({
      ...estimate, next: 'awaitingRenewal' as const,
    })),
  ];
}
