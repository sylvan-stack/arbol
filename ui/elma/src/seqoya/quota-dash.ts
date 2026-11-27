import type { QuotaDashChoice, QuotaDashChoices } from '../../design-system/src/sections/seqoya-vigor-priority';

const storageKey = 'arbol-seqoya:quota-dash';

function isChoice(value: unknown): value is QuotaDashChoice {
  if (!value || typeof value !== 'object') return false;
  const { windowEnd, marked } = value as Partial<QuotaDashChoice>;
  return typeof windowEnd === 'number' && Number.isSafeInteger(windowEnd) && windowEnd > 0
    && typeof marked === 'boolean';
}

export function readQuotaDashChoices(): QuotaDashChoices {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(storageKey) ?? '{}');
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      return Object.fromEntries(Object.entries(saved).filter(([, choice]) => isChoice(choice)));
    }
  } catch {
    return {};
  }
  return {};
}

export function saveQuotaDashChoice(key: string, choice: QuotaDashChoice): QuotaDashChoices {
  const choices = { ...readQuotaDashChoices(), [key]: choice };
  localStorage.setItem(storageKey, JSON.stringify(choices));
  return choices;
}
