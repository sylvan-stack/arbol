import {
  defaultVigorSettings, isMonthlyEtcForecast, isVigorSettings,
  type MonthlyEtcForecast, type MonthlyEtcForecasts, type VigorSettings,
} from '../../design-system/src/sections/seqoya-vigor-priority';

const storageKey = 'arbol-seqoya:vigor-settings';

export function readVigorSettings(): VigorSettings {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(storageKey) ?? 'null');
    if (isVigorSettings(saved)) return saved;
  } catch {
    // Use the defaults if local storage is unavailable or its contents are invalid.
  }
  return defaultVigorSettings;
}

export function saveVigorSettings(settings: VigorSettings): VigorSettings {
  if (!isVigorSettings(settings)) throw new Error('Invalid Vigor settings.');
  localStorage.setItem(storageKey, JSON.stringify(settings));
  return settings;
}

const monthlyEtcKey = 'arbol-seqoya:monthly-etc';

export function readMonthlyEtcForecasts(): MonthlyEtcForecasts {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(monthlyEtcKey) ?? '{}');
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      return Object.fromEntries(Object.entries(saved).filter(([, forecast]) => isMonthlyEtcForecast(forecast)));
    }
  } catch {
    // Start without forecasts when local storage is unavailable or invalid.
  }
  return {};
}

export function saveMonthlyEtcForecast(key: string, forecast?: MonthlyEtcForecast): MonthlyEtcForecasts {
  const forecasts = readMonthlyEtcForecasts();
  if (forecast === undefined) delete forecasts[key];
  else {
    if (!isMonthlyEtcForecast(forecast)) throw new Error('Invalid monthly ETC forecast.');
    forecasts[key] = forecast;
  }
  localStorage.setItem(monthlyEtcKey, JSON.stringify(forecasts));
  return forecasts;
}
