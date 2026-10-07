import { check, equal, object } from '../check.js';
import type { Scenario } from './types.js';
import type { ScenarioHome } from '../harness.js';
import { stream, runRefusals } from './runs.js';

export async function checkSubscriptionRefusals(home: ScenarioHome, includeRuns = false): Promise<void> {
  const reply = await home.call(['subscriptions', 'list']);
  equal('List exit status', reply.status, 0);
  const subscriptions: unknown = JSON.parse(reply.stdout);
  check('Subscription array', Array.isArray(subscriptions) && subscriptions.length > 0, 'a nonempty Subscription array', subscriptions);
  for (const value of subscriptions) {
    const subscription = object('Subscription', value);
    check('Identifier', typeof subscription.id === 'string', 'an identifier', subscription.id);
    for (const command of ['models', 'check']) {
      const failure = await home.json(['subscriptions', command, subscription.id]);
      equal(`${command} exit status`, failure.process.status, 1);
      equal(`${command} error`, object('Error', failure.result.error).code, 'not_signed_in');
    }
    const usage = await home.json(['subscriptions', 'usage', subscription.id]);
    equal('Usage exit status', usage.process.status, 0);
    equal('Usage outcome', usage.result.outcome, 'needs_sign_in');
    equal('No numeric windows for unsigned usage', usage.result.windows, []);
    if (includeRuns) {
      const run = stream(await home.call(['run', '--subscription', String(subscription.id), 'answer']), 'failed');
      equal('Unsigned run one final', run.length, 1); equal('Unsigned run error', object('Error', run[0]!.error).code, 'not_signed_in');
    }
  }
  equal('The vendor tool is never started', await home.received(), []);
}
export const c40: Scenario = {
  id: 'C40', title: 'Subscription refusals before starting the tool',
  scope: 'unsigned models, check, usage and runs; folders, duplicate ID, models and effort',
  covers: ['DRV-1.11', 'DRV-2.2'],
  async run(home) { await checkSubscriptionRefusals(home, true); await runRefusals(home); },
};
