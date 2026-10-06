import { check, equal, object, text } from '../check.js';
import type { Scenario } from './types.js';

export const c1: Scenario = {
  id: 'C1', title: 'Local Subscription records', scope: 'families, create, list, relabel and removal',
  covers: ['DRV-1.1 (families, create, list and relabel)', 'DRV-1.14 (list)', 'DRV-1.15', 'DRV-1.23 (create and update)'],
  async run(home) {
    const familyReply = await home.call(['subscriptions', 'families']);
    equal('Families exit status', familyReply.status, 0);
    const families: unknown = JSON.parse(familyReply.stdout);
    check('Families array', Array.isArray(families) && families.length > 0, 'a nonempty Family array', families);
    const listed = async (): Promise<Record<string, unknown>[]> => {
      const reply = await home.call(['subscriptions', 'list']);
      equal('List exit status', reply.status, 0);
      const parsed: unknown = JSON.parse(reply.stdout);
      check('Subscription array', Array.isArray(parsed), 'a Subscription array', parsed);
      return parsed.map(value => object('Subscription', value));
    };
    const initial = await listed();
    equal('One default Subscription per family', initial.length, families.length);
    for (const value of families) {
      const family = object('Family', value);
      const id = text('Family identifier', family.id);
      object('Family settings schema', family.settings);
      const builtin = initial.find(item => item.id === id);
      check('Default Subscription is named after its family', builtin !== undefined, id, initial);
      equal('Default family', builtin.family, id);
      equal('Default auth', builtin.auth, family.auth);
      equal('Default state', builtin.state, 'signed_out');
      object('Subscription settings', builtin.settings);
      const created = await home.json(['subscriptions', 'create', '--family', id, '--label', 'Another account']);
      equal('Create exit status', created.process.status, 0);
      equal('Automatic name', created.result.id, `${id}-2`);
      equal('New account family', created.result.family, id);
      equal('New account auth', created.result.auth, family.auth);
      equal('New account state', created.result.state, 'signed_out');
      equal('New account label', created.result.label, 'Another account');
      text('Creation date', created.result.createdAt);
      equal('Create is stored', (await listed()).find(item => item.id === created.result.id), created.result);
      const changed = await home.json(['subscriptions', 'update', `${id}-2`, '--label', 'Renamed account']);
      equal('Update exit status', changed.process.status, 0);
      equal('Relabel changes only label and update date', { ...changed.result, label: created.result.label, updatedAt: created.result.updatedAt }, created.result);
      equal('Update is stored', (await listed()).find(item => item.id === changed.result.id), changed.result);
      const unchanged = await home.json(['subscriptions', 'update', `${id}-2`]);
      equal('Omitted fields are preserved', unchanged.result, changed.result);
      const duplicate = await home.json(['subscriptions', 'create', '--family', id, '--label', 'Duplicate', '--id', `${id}-2`]);
      equal('Duplicate fails', duplicate.process.status, 1);
      equal('Duplicate typed error', object('Duplicate error', duplicate.result.error).code, 'in_use');
      const explicit = await home.json(['subscriptions', 'create', '--family', id, '--label', 'Named account', '--id', `${id}-work`]);
      equal('Explicit creation succeeds', explicit.process.status, 0);
      equal('Explicit identifier', explicit.result.id, `${id}-work`);
      const removed = await home.call(['subscriptions', 'remove', `${id}-work`]);
      equal('Removal exit status', removed.status, 0);
      equal('Removal returns no document', removed.stdout, '');
      equal('Removed account is absent', (await listed()).some(item => item.id === `${id}-work`), false);
    }
    equal('Local commands never start the vendor tool', await home.received(), []);
  },
};
