import { isDeepStrictEqual } from 'node:util';

export class Mismatch extends Error {
  constructor(message: string, readonly expected: unknown, readonly actual: unknown) {
    super(message);
  }
}

export function equal(message: string, actual: unknown, expected: unknown): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Mismatch(message, expected, actual);
}

export function check(message: string, condition: boolean, expected: string, actual: unknown): asserts condition {
  if (!condition) throw new Mismatch(message, expected, actual);
}

export function object(message: string, value: unknown): Record<string, unknown> {
  check(message, value !== null && typeof value === 'object' && !Array.isArray(value), 'a JSON object', value);
  return value as Record<string, unknown>;
}

export function text(message: string, value: unknown): string {
  check(message, typeof value === 'string' && value.length > 0, 'a nonempty string', value);
  return value;
}
