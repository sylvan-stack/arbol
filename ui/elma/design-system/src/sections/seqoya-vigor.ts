import type { AllowanceView, SubscriptionActivity } from './seqoya-subscriptions';

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
  return entry.unavailable ? null : entry.estimate?.score ?? entry.result?.vigor ?? null;
}

export interface VigorView {
  rollup?: VigorRollup;
  entries?: VigorEntry[];
  accountIssues?: string[];
  loading?: boolean;
  error?: string;
}
