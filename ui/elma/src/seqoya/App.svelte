<script lang="ts">
  import { onMount } from 'svelte';
  import SeqoyaLab from '../../design-system/src/pages/SeqoyaLab.svelte';
  import {
    subscriptionKey, type SubscriptionActivity, type SubscriptionListing, type SubscriptionView,
  } from '../../design-system/src/sections/seqoya-subscriptions';
  import type { VigorRollup, VigorView } from '../../design-system/src/sections/seqoya-vigor';
  import type { WorkspaceTrunkSelector } from '../../design-system/src/types';
  import { AppChannel } from '../app-channel';
  import { Bridge, Refusal } from '../bridge';
  import { readSeqoyaAppearance, saveSeqoyaAppearance } from '../preferences';
  import { withModelLabels } from './subscription-model-labels';
  import { rankVigor, retainAccounts, retainVigor } from './vigor-estimates';

  let trunk = $state<string>();
  let trunkSelector = $state<WorkspaceTrunkSelector>();
  let connectionStatus = $state('Connecting to Root…');
  let rootId = $state<string>();
  let appearance = $state(readSeqoyaAppearance());
  let subscriptions = $state<SubscriptionView>({ connected: false });
  let vigor = $state<VigorView>({});
  let vigorAccounts = $state<SubscriptionListing>();
  const vigorView = $derived<VigorView>({
    ...vigor,
    entries: rankVigor(vigor.rollup, vigorAccounts),
    accountIssues: [
      ...(subscriptions.error ? [subscriptions.error] : []),
      ...(subscriptions.listing?.drivers.flatMap(({ driver, error }) =>
        error ? [driver + ' accounts · ' + error.message] : []) ?? []),
    ],
  });
  let activeTab = 'Subscriptions';
  let readSubscriptions: (() => Promise<void>) | undefined;
  let readVigor: (() => Promise<void>) | undefined;
  let readUsage: ((driver: string, subscription: string) => Promise<void>) | undefined;
  let openConsole: (() => Promise<void>) | undefined;

  function refreshSubscriptions() {
    void readSubscriptions?.();
  }

  function refreshVigor() {
    refreshSubscriptions();
    void readVigor?.();
  }

  function refreshUsage(driver: string, subscription: string) {
    void readUsage?.(driver, subscription);
  }

  function openMiMo() {
    void openConsole?.();
  }

  function changeTab(tab: string) {
    activeTab = tab;
    if (tab === 'Subscriptions') refreshSubscriptions();
    else if (tab === 'Vigor') refreshVigor();
  }

  onMount(() => {
    const app = new AppChannel();
    let active = true;
    let connection = 0;
    let listRequest: Promise<void> | undefined;
    const isCurrent = (requestedOn: number) => active && requestedOn === connection;
    const bridge = new Bridge({
      onhello: (root) => {
        connection++;
        listRequest = undefined;
        subscriptions = {
          connected: true,
          listing: rootId === root.root ? subscriptions.listing : undefined,
        };
        if (rootId !== root.root) {
          vigorAccounts = undefined;
          rootId = root.root;
          appearance = readSeqoyaAppearance(rootId);
        }
        if (activeTab === 'Subscriptions' || activeTab === 'Vigor') refreshSubscriptions();
        void app.currentTrunk().then((current) => {
          if (active && trunk === undefined) trunk = current;
        }).catch(() => { /* The selector reports its own errors. */ });
      },
      onstate: (state) => {
        connectionStatus = state === 'Connected' ? '' : state;
        if (state === 'Reconnecting…' || state === 'This window cannot work with this Bridge version.') {
          connection++;
          listRequest = undefined;
          subscriptions = { connected: false, listing: subscriptions.listing };
        }
      },
    });

    async function withActivity(listing: SubscriptionListing): Promise<SubscriptionListing> {
      const drivers = await Promise.all(listing.drivers.map(async (entry) => {
        if (entry.driver !== 'mimo' || !entry.subscriptions) return entry;
        const accounts = await Promise.all(entry.subscriptions.map(async (subscription) => {
          if (subscription.family !== 'xiaomi') return subscription;
          try {
            const activity = await bridge.call<SubscriptionActivity>('accounts.activity', {
              driver: entry.driver, subscription: subscription.id,
            });
            return { ...subscription, activity };
          } catch (error) {
            return {
              ...subscription,
              activityError: error instanceof Refusal && error.detail.code === 'unknown_method'
                ? 'This Root’s backend needs an update to show MiMo activity.'
                : 'Could not read MiMo activity for this Root.',
            };
          }
        }));
        return { ...entry, subscriptions: accounts };
      }));
      return { drivers };
    }

    async function loadListing(requestedOn: number) {
      subscriptions = { ...subscriptions, loading: true, error: undefined };
      try {
        const listing = await bridge.call<SubscriptionListing>('accounts.list');
        if (!isCurrent(requestedOn)) return;
        if (!Array.isArray(listing?.drivers)) throw new Error('Invalid account list.');
        vigorAccounts = retainAccounts(listing, vigorAccounts);
        subscriptions = { ...subscriptions, loading: false, listing };
        const withMiMo = await withActivity(withModelLabels(listing));
        if (isCurrent(requestedOn)) subscriptions = { ...subscriptions, listing: withMiMo };
      } catch (error) {
        if (!isCurrent(requestedOn)) return;
        subscriptions = {
          ...subscriptions,
          loading: false,
          error: error instanceof Refusal
            ? error.detail.code === 'unknown_method'
              ? 'This Root’s backend needs an update to list subscriptions.'
              : error.message
            : 'The backend did not return a readable account list.',
        };
      }
    }

    async function reloadList() {
      if (!active || !subscriptions.connected) return;
      if (listRequest) return listRequest;
      const request = loadListing(connection);
      listRequest = request;
      try {
        await request;
      } finally {
        if (listRequest === request) listRequest = undefined;
      }
    }
    readSubscriptions = reloadList;

    readVigor = async () => {
      if (!active || vigor.loading) return;
      vigor = { ...vigor, loading: true, error: undefined };
      try {
        const reply = await app.call('app.readVigor');
        if (!active) return;
        if (typeof reply.moment !== 'string' || !Array.isArray(reply.subscriptions)
          || !reply.failures || typeof reply.failures !== 'object' || Array.isArray(reply.failures)
          || (reply.headline !== null && (!reply.headline || typeof reply.headline !== 'object'))) {
          throw new Error('Invalid Vigor rollup.');
        }
        vigor = { rollup: retainVigor(reply as unknown as VigorRollup, vigor.rollup) };
      } catch (error) {
        if (!active) return;
        vigor = {
          ...vigor,
          loading: false,
          error: error instanceof Refusal
            ? error.detail.code === 'unknown_method'
              ? 'Open Seqoya Lab in the updated Arbol App to read Vigor.'
              : error.message
            : 'The App did not return a readable Vigor rollup.',
        };
      }
    };

    readUsage = async (driver, subscription) => {
      const account = subscriptions.listing?.drivers.find((entry) => entry.driver === driver)
        ?.subscriptions?.find((row) => row.id === subscription);
      const key = subscriptionKey(driver, subscription);
      if (!active || !subscriptions.connected || subscriptions.usageRequests?.[key]?.pending
        || account?.state !== 'signed_in' || !['zai', 'deepseek'].includes(account.family)) return;
      const requestedOn = connection;
      subscriptions = {
        ...subscriptions, usageRequests: { ...subscriptions.usageRequests, [key]: { pending: true } },
      };
      let problem: string | undefined;
      try {
        const result = await bridge.call<{ outcome: string; message?: string }>('accounts.usage', {
          driver, subscription,
        });
        if (result?.outcome !== 'ok') problem = result?.message || 'The provider did not return a usage report.';
      } catch (error) {
        problem = error instanceof Refusal ? error.message : 'Could not refresh usage.';
      }
      if (!isCurrent(requestedOn)) return;
      // A listing begun before the provider replied may still contain the previous report.
      await listRequest;
      if (!isCurrent(requestedOn)) return;
      await reloadList();
      if (!isCurrent(requestedOn)) return;
      const requests = { ...subscriptions.usageRequests };
      if (problem) requests[key] = { error: problem };
      else delete requests[key];
      subscriptions = { ...subscriptions, usageRequests: requests };
    };

    openConsole = async () => {
      subscriptions = { ...subscriptions, consoleError: undefined };
      try {
        await app.call('app.openLink', { url: 'https://platform.xiaomimimo.com/console/balance' });
      } catch (error) {
        if (active) subscriptions = {
          ...subscriptions,
          consoleError: error instanceof Refusal ? error.message : 'Could not open the MiMo console.',
        };
      }
    };
    trunkSelector = app.trunkSelector((code) => { if (active) trunk = code; });
    return () => {
      active = false;
      readSubscriptions = undefined;
      readVigor = undefined;
      readUsage = undefined;
      openConsole = undefined;
      bridge.close();
      app.close();
    };
  });
</script>

<SeqoyaLab fitted {trunk} {trunkSelector} {connectionStatus}
  {subscriptions} vigor={vigorView} onTabChange={changeTab}
  onRefreshSubscriptions={refreshSubscriptions} onRefreshVigor={refreshVigor}
  onRefreshUsage={refreshUsage} onOpenMiMo={openMiMo}
  appearanceReady={rootId !== undefined} bind:theme={appearance.theme} bind:uiScale={appearance.uiScale}
  onAppearanceChange={() => { if (rootId !== undefined) saveSeqoyaAppearance(rootId, appearance); }} />
