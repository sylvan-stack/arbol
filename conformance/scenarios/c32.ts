import { join } from 'node:path';
import { check, equal, text } from '../check.js';
import { inspectInfo, versionOrder, versionRecords } from './info.js';
import type { Scenario } from './types.js';

export const c32: Scenario = {
  id: 'C32', title: 'Driver info', scope: 'info only; other command checks pending',
  covers: ['DRV-0.1 (info)', 'DRV-0.11 (info)', 'DRV-0.12 (info)', 'DRV-0.13 (info)', 'DRV-0.15 (info)'],
  async run(home) {
    await home.part('info');
    let identity: unknown;
    for (const override of [false, true]) {
      const state = override ? join(home.home, 'explicit-state') : undefined;
      const reply = await home.json(override ? ['--state-dir', state!, 'info'] : ['info']);
      equal('info exit status', reply.process.status, 0);
      const { info, tool, name } = inspectInfo(reply.result);
      equal('Contract version', info.contract, 1);
      const version = text('Package version', info.version);
      check('Package version format', /^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$/.test(version), 'a semantic package version', version);
      const build = text('Build number', info.build);
      check('Build number format', /^(?:0|[1-9a-f][0-9a-f]*)$/.test(build), 'a hexadecimal Build number, or 0 for a source checkout', build);
      equal('State directory', info.stateDirectory, state ?? join(home.home, 'Library', 'Application Support', 'Arbol', 'drivers', name));
      equal('Settings filename', info.settingsFile, join(home.home, '.arbol', `arbol-${name}-driver.json`));
      equal('Supported tool path', tool.path, home.toolPath);
      equal('Supported tool version', tool.supported, true);
      const found = text('Reported tool version', tool.version);
      const needed = text('Oldest supported tool version', tool.oldestSupported);
      check('Supported version meets the support boundary', versionOrder(found, needed) >= 0, `a version at least ${needed}`, found);
      const current = { driver: name, version, build, contract: info.contract };
      if (identity === undefined) identity = current;
      else equal('Identity is stable with a state override', current, identity);
      await versionRecords(home, 'info');
      for (const record of await home.received()) equal('Reported version matches the stand-in', tool.version, record.toolVersion);
    }
  },
};
