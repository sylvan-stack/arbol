import { access, stat } from 'node:fs/promises';
import { constants } from 'node:fs';
import { delimiter, isAbsolute, resolve } from 'node:path';

export type Command = [string, ...string[]];

// Only command words: no shell, substitutions, redirects, pipes or globbing.
export function commandWords(input: string): Command {
  const words: string[] = [];
  let word = '', quote = '', started = false;
  for (let i = 0; i < input.length; i++) {
    const char = input[i]!;
    if (char === '\\' && quote !== "'") {
      const next = input[++i];
      if (next === undefined) throw new Error('The Driver command ends in a backslash.');
      word += next; started = true;
    } else if (quote) {
      if (char === quote) quote = '';
      else word += char;
    } else if (char === "'" || char === '"') {
      quote = char; started = true;
    } else if (/\s/.test(char)) {
      if (started) { words.push(word); word = ''; started = false; }
    } else {
      word += char; started = true;
    }
  }
  if (quote) throw new Error('The Driver command has an unclosed quote.');
  if (started) words.push(word);
  if (!words[0]) throw new Error('Give --driver a program to start.');
  return words as Command;
}

async function exists(path: string, executable = false): Promise<boolean> {
  try {
    if (executable) await access(path, constants.X_OK);
    const entry = await stat(path);
    return executable ? entry.isFile() : true;
  } catch { return false; }
}

export async function resolveCommand(input: string, cwd = process.cwd(), path = process.env.PATH ?? ''): Promise<Command> {
  const [program, ...args] = commandWords(input);
  const candidates = program.includes('/') ? [resolve(cwd, program)] : path.split(delimiter).map(folder => resolve(cwd, folder || '.', program));
  let found: string | undefined;
  for (const candidate of candidates) if (await exists(candidate, true)) { found = candidate; break; }
  if (!found) throw new Error(`Driver program was not found or is not executable: ${program}`);
  // The Driver works in its temporary home. Keep caller-relative fixed file arguments usable.
  const resolvedArgs: string[] = [];
  for (const arg of args) resolvedArgs.push(!isAbsolute(arg) && !arg.startsWith('-') && await exists(resolve(cwd, arg)) ? resolve(cwd, arg) : arg);
  return [found, ...resolvedArgs];
}

export const shellQuote = (value: string): string => "'" + value.replaceAll("'", "'\\''") + "'";
