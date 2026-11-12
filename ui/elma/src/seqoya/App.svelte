<script lang="ts">
  import { onMount } from 'svelte';
  import SeqoyaLab from '../../design-system/src/pages/SeqoyaLab.svelte';
  import {
    canRefreshSubscriptionUsage, subscriptionKey, type SubscriptionActivity, type SubscriptionListing, type SubscriptionView, type UsageDestination,
  } from '../../design-system/src/sections/seqoya-subscriptions';
  import type { VigorRollup, VigorView } from '../../design-system/src/sections/seqoya-vigor';
  import type { WorkspaceTrunkSelector } from '../../design-system/src/types';
  import { AppChannel } from '../app-channel';
  import { Bridge, Refusal } from '../bridge';
  import { readSeqoyaAppearance, saveSeqoyaAppearance } from '../preferences';
  import { withAllowances, type UsageEvidence } from './allowance-evidence';
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
  let evidence = $state<UsageEvidence>();
  let evidenceError = $state<string>();
  let now = $state(Date.now());
  const subscriptionView = $derived<SubscriptionView>({
    ...subscriptions, listing: withAllowances(subscriptions.listing, vigor.rollup, evidence, now),
    evidenceError: evidenceError ?? vigor.error,
  });
  const vigorView = $derived<VigorView>({
    ...vigor,
    entries: rankVigor(vigor.rollup, withAllowances(vigorAccounts, vigor.rollup, evidence, now)),
    accountIssues: [
      ...(subscriptions.error ? [subscriptions.error] : []),
      ...(evidenceError ? [evidenceError] : []),
      ...(subscriptions.listing?.drivers.flatMap(({ driver, error }) =>
        error ? [driver + ' accounts · ' + error.message] : []) ?? []),
    ],
  });
  let activeTab = 'Subscriptions';
  let readSubscriptions: (() => Promise<void>) | undefined;
  let readVigor: (() => Promise<void>) | undefined;
  let readUsage: ((driver: string, subscription: string) => Promise<void>) | undefined;
  let openUsagePage: ((destination: UsageDestination, driver: string, subscription: string) => Promise<void>) | undefined;

  function refreshSubscriptions() {
    void readSubscriptions?.();
    void readVigor?.();
  }

  function refreshUsage(driver: string, subscription: string) {
    void readUsage?.(driver, subscription);
  }

  function openUsage(destination: UsageDestination, driver: string, subscription: string) {
    void openUsagePage?.(destination, driver, subscription);
  }

  function changeTab(tab: string) {
    activeTab = tab;
    if (tab === 'Subscriptions' || tab === 'Vigor') refreshSubscriptions();
  }

  onMount(() => {
    const app = new AppChannel();
    const attemptedBoundaries = new Map<string, Set<number>>();
    const expiryClock = setInterval(() => { now = Date.now(); refreshPassedWindows(); }, 30_000);
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
          attemptedBoundaries.clear();
          vigorAccounts = undefined;
          vigor = {};
          evidence = undefined;
          evidenceError = undefined;
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
        if ((entry.driver !== 'mimo' && entry.driver !== 'pi') || !entry.subscriptions) return entry;
        const accounts = await Promise.all(entry.subscriptions.map(async (subscription) => {
          const hasActivity = (entry.driver === 'mimo' && subscription.family === 'xiaomi')
            || (entry.driver === 'pi' && subscription.family === 'chatgpt');
          if (!hasActivity) return subscription;
          try {
            const activity = await bridge.call<SubscriptionActivity>('accounts.activity', {
              driver: entry.driver, subscription: subscription.id,
            });
            return { ...subscription, activity };
          } catch (error) {
            return {
              ...subscription,
              activityError: error instanceof Refusal && error.detail.code === 'unknown_method'
                ? 'This Root’s backend needs an update to show account activity.'
                : 'Could not read account activity for this Root.',
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
        const withLocalActivity = await withActivity(withModelLabels(listing));
        if (isCurrent(requestedOn)) {
          vigorAccounts = retainAccounts(withLocalActivity, vigorAccounts);
          subscriptions = { ...subscriptions, listing: withLocalActivity };
          queueMicrotask(refreshPassedWindows);
        }
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
      if (!active || vigor.loading || !rootId) return;
      const requestedRoot = rootId;
      vigor = { ...vigor, loading: true, error: undefined };
      try {
        const reply = await app.call('app.readVigor');
        if (!active || rootId !== requestedRoot) return;
        if (typeof reply.moment !== 'string' || !Array.isArray(reply.subscriptions)
          || !reply.failures || typeof reply.failures !== 'object' || Array.isArray(reply.failures)
          || (reply.headline !== null && (!reply.headline || typeof reply.headline !== 'object'))) {
          throw new Error('Invalid Vigor rollup.');
        }
        evidence = reply.usageEvidence as UsageEvidence | undefined;
        evidenceError = typeof reply.usageEvidenceError === 'string' ? reply.usageEvidenceError : undefined;
        now = Date.now();
        vigor = { rollup: retainVigor(reply as unknown as VigorRollup, vigor.rollup) };
        refreshPassedWindows();
      } catch (error) {
        if (!active || rootId !== requestedRoot) return;
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

    function refreshPassedWindows() {
      if (!active || !subscriptions.connected || activeTab !== 'Subscriptions' || !readUsage) return;
      for (const { driver, subscriptions: accounts } of subscriptionView.listing?.drivers ?? []) {
        for (const account of accounts ?? []) {
          if (!canRefreshSubscriptionUsage(driver, account)) continue;
          const key = subscriptionKey(driver, account.id);
          if (subscriptions.usageRequests?.[key]?.pending) continue;
          const boundaries = account.metrics?.passedBoundaries;
          if (!boundaries?.length) continue;
          const binding = JSON.stringify([key, account.createdAt, account.family]);
          const attempted = attemptedBoundaries.get(binding) ?? new Set<number>();
          if (!boundaries.some((boundary) => !attempted.has(boundary))) continue;
          for (const boundary of boundaries) attempted.add(boundary);
          attemptedBoundaries.set(binding, attempted);
          void readUsage(driver, account.id);
        }
      }
    }

    readUsage = async (driver, subscription) => {
      const account = subscriptions.listing?.drivers.find((entry) => entry.driver === driver)
        ?.subscriptions?.find((row) => row.id === subscription);
      const key = subscriptionKey(driver, subscription);
      if (!active || !subscriptions.connected || subscriptions.usageRequests?.[key]?.pending
        || !account || !canRefreshSubscriptionUsage(driver, account)) return;
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
      const current = subscriptions.listing?.drivers.find((entry) => entry.driver === driver)
        ?.subscriptions?.find((row) => row.id === subscription);
      const requests = { ...subscriptions.usageRequests };
      if (problem && current?.family === account.family && current?.createdAt === account.createdAt) requests[key] = { error: problem };
      else delete requests[key];
      subscriptions = { ...subscriptions, usageRequests: requests };
    };

    openUsagePage = async (destination, driver, subscription) => {
      const key = subscriptionKey(driver, subscription);
      const requestedOn = connection;
      subscriptions = {
        ...subscriptions, usageLinkErrors: { ...subscriptions.usageLinkErrors, [key]: undefined },
      };
      try {
        if (destination === 'chatgpt') await app.call('app.openSubscriptionUsage', { driver, subscription });
        else await app.call('app.openLink', { url: 'https://platform.xiaomimimo.com/console/balance' });
      } catch (error) {
        if (isCurrent(requestedOn)) subscriptions = {
          ...subscriptions,
          usageLinkErrors: {
            ...subscriptions.usageLinkErrors,
            [key]: error instanceof Refusal ? error.message : 'Could not open vendor usage.',
          },
        };
      }
    };

    return () => {
      active = false;
      readSubscriptions = undefined;
      readVigor = undefined;
      readUsage = undefined;
      openUsagePage = undefined;
      clearInterval(expiryClock);
      bridge.close();
      app.close();
    };
  });
</script>

<SeqoyaLab fitted {trunk} {trunkSelector} {connectionStatus}
  subscriptions={subscriptionView} vigor={vigorView} onTabChange={changeTab}
  onRefreshSubscriptions={refreshSubscriptions} onRefreshVigor={refreshSubscriptions}
  onRefreshUsage={refreshUsage} onOpenUsage={openUsage}
  appearanceReady={rootId !== undefined} bind:theme={appearance.theme} bind:uiScale={appearance.uiScale}
  onAppearanceChange={() => { if (rootId !== undefined) saveSeqoyaAppearance(rootId, appearance); }} />
