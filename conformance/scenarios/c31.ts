import { check, equal, object, text } from '../check.js';
import { inspectInfo, versionOrder, versionRecords } from './info.js';
import type { Scenario } from './types.js';

export const c31: Scenario = {
  id: 'C31', title: 'Missing and old vendor tools', scope: 'missing and old',
  covers: ['DRV-0.6', 'DRV-4.14'],
  async run(home) {
    for (const part of ['missing', 'old']) {
      await home.part(part, part === 'missing');
      const reply = await home.json(['info']);
      equal(`${part}: info exit status`, reply.process.status, 0);
      const { tool, name } = inspectInfo(reply.result);
      equal(`${part}: tool support`, tool.supported, false);
      const needed = text('Needed tool version', tool.oldestSupported);
      if (part === 'missing') {
        equal('Missing tool path is absent', tool.path, undefined);
        equal('Missing tool version is absent', tool.version, undefined);
      } else {
        equal('Old tool path', tool.path, home.toolPath);
        const found = text('Old tool version', tool.version);
        check('Old version is below the support boundary', versionOrder(found, needed) < 0, `a version below ${needed}`, found);
      }
      const failure = await home.json(['run', 'Answer with the single word: ready']);
      equal(`${part}: refused operation exit status`, failure.process.status, 1);
      const error = object(`${part}: typed error`, failure.result.error);
      equal(`${part}: error code`, error.code, part === 'missing' ? 'tool_missing' : 'tool_unsupported');
      equal(`${part}: retryable`, error.retryable, false);
      const detail = object(`${part}: error detail`, error.detail);
      equal(`${part}: needed version in error`, detail.neededVersion, needed);
      if (part === 'old') equal('Found version in error', detail.toolVersion, tool.version);
      const message = text(`${part}: error message`, error.message);
      for (const word of [name, needed, ...(part === 'old' ? [tool.version as string] : [])]) {
        check(`${part}: error names tool and versions`, message.includes(word), `a message containing ${word}`, message);
      }
      if (part === 'missing') equal('Missing tool was never started', await home.received(), []);
      else {
        await versionRecords(home, 'old');
        for (const record of await home.received()) equal('Old version matches the stand-in', tool.version, record.toolVersion);
      }
    }
  },
};
