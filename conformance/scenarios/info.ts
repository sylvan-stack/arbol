import { check, equal, object, text } from '../check.js';
import type { ScenarioHome } from '../harness.js';

export function inspectInfo(value: unknown): { info: Record<string, unknown>; tool: Record<string, unknown>; name: string } {
  const info = object('info result', value);
  const name = text('info Driver name', info.driver);
  check('Supported Driver identity', ['claude', 'codex'].includes(name), 'claude or codex', name);
  const tool = object('info tool', info.tool);
  equal('Vendor tool name', tool.name, name);
  text('Oldest supported tool version', tool.oldestSupported);
  return { info, tool, name };
}

export function versionOrder(found: string, needed: string): number {
  for (const version of [found, needed]) check('Tool version format', /^\d+\.\d+\.\d+$/.test(version), 'a three-part tool version', version);
  const left = found.split('.').map(BigInt);
  const right = needed.split('.').map(BigInt);
  for (let i = 0; i < 3; i++) if (left[i] !== right[i]) return left[i]! < right[i]! ? -1 : 1;
  return 0;
}

export async function versionRecords(home: ScenarioHome, part: string): Promise<void> {
  const records = await home.received();
  check('Stand-in was used', records.length > 0, 'at least one stand-in version probe', records);
  for (const record of records) {
    equal('Stand-in scenario', record.scenario, home.id);
    equal('Stand-in part', record.part, part);
    equal('Only version probes reached the tool', record.arguments, ['--version']);
    check('Version probe working folder', home.contains(record.workingDirectory), 'a folder in the scenario home', record.workingDirectory);
  }
}
