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
        contribution: number | null;
        predicted: boolean;
        reason: string | null;
      }[];
    } | null;
  }[];
  failures: Record<string, string>;
}

export interface VigorView {
  rollup?: VigorRollup;
  loading?: boolean;
  error?: string;
}
