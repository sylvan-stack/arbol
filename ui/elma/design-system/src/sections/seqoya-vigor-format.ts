const whole = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
const fractional = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function formatVigorNumber(value: number): string {
  return (Number.isInteger(value) ? whole : fractional).format(value);
}

export function formatVigorTokens(tokens: number): string {
  const millions = tokens >= 1_000_000;
  const value = tokens / (millions ? 1_000_000 : 1_000);
  if (value > 0 && value < 0.01) return '<' + fractional.format(0.01) + 'K';
  return formatVigorNumber(value) + (millions ? 'M' : 'K');
}
