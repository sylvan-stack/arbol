<script lang="ts">
  import { onMount } from 'svelte';
  import SeqoyaLab from '../../design-system/src/pages/SeqoyaLab.svelte';
  import {
    canRefreshSubscriptionUsage, subscriptionKey, type RenameSubscription, type SubscriptionActivity, type SubscriptionListing, type SubscriptionRecord, type SubscriptionView, type UsageDestination,
  } from '../../design-system/src/sections/seqoya-subscriptions';
  import type { VigorRollup, VigorView } from '../../design-system/src/sections/seqoya-vigor';
  import { AppChannel } from '../app-channel';
  import { Bridge, Refusal } from '../bridge';
  import { readSeqoyaAppearance, saveSeqoyaAppearance } from '../preferences';
  import { withAllowances, type UsageEvidence } from './allowance-evidence';
  import { withModelLabels } from './subscription-model-labels';
  import { rankVigor, retainAccounts, retainVigor } from './vigor-estimates';

  let connectionStatus = $state('Connecting to Arbol…');
  let ready = $state(false);
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
  let renameSubscription: RenameSubscription | undefined;
  let activeTab = 'Subscriptions';
  let readSubscriptions: (() => Promise<void>) | undefined;
  let readVigor: (() => Promise<void>) | undefined;
  let readUsage: ((driver: string, subscription: string, startWindow?: boolean) => Promise<void>) | undefined;
  let retryWindowStarts: ((key?: string) => void) | undefined;
  let openUsagePage: ((destination: UsageDestination, driver: string, subscription: string) => Promise<void>) | undefined;

  function refreshSubscriptions(retryStarts = false) {
    if (retryStarts) retryWindowStarts?.();
    void readSubscriptions?.();
    void readVigor?.();
  }

  function refreshUsage(driver: string, subscription: string) {
    retryWindowStarts?.(subscriptionKey(driver, subscription));
    void readUsage?.(driver, subscription);
  }

  function openUsage(destination: UsageDestination, driver: string, subscription: string) {
    void openUsagePage?.(destination, driver, subscription);
  }

  const renameName: RenameSubscription = async (driver, account, name) => {
    if (!renameSubscription) throw new Error('Subscription editing requires the native App.');
    await renameSubscription(driver, account, name);
  };

  function changeTab(tab: string) {
    activeTab = tab;
    if (tab === 'Subscriptions' || tab === 'Vigor') refreshSubscriptions();
  }

  onMount(() => {
    const app = new AppChannel();
    const attemptedBoundaries = new Map<string, Set<number>>();
    const attemptedStarts = new Map<string, string>();
    retryWindowStarts = (key) => { if (key) attemptedStarts.delete(key); else attemptedStarts.clear(); };
    const expiryClock = setInterval(() => { now = Date.now(); refreshWindows(); }, 30_000);
    let active = true;
    let connection = 0;
    let evidenceRevision = 0;
    let listRequest: Promise<void> | undefined;
    const isCurrent = (requestedOn: number) => active && requestedOn === connection;
    const bridge = new Bridge({
      onhello: () => {
        connection++;
        listRequest = undefined;
        subscriptions = { connected: true, listing: subscriptions.listing };
        vigor = { ...vigor, loading: false };
        if (!ready) {
          attemptedBoundaries.clear();
          ready = true;
          appearance = readSeqoyaAppearance('installation');
        }
        if (activeTab === 'Subscriptions' || activeTab === 'Vigor') refreshSubscriptions();
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
    // Bridge projects validated installation snapshots and events through onstate.
    bridge.subscribe('installation', {}, () => {}, (error) => {
      connectionStatus = error?.message ?? 'Installation status updates ended.';
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
                ? 'The backend needs an update to show account activity.'
                : 'Could not read account activity for this installation.',
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
          queueMicrotask(refreshWindows);
        }
      } catch (error) {
        if (!isCurrent(requestedOn)) return;
        subscriptions = {
          ...subscriptions,
          loading: false,
          error: error instanceof Refusal
            ? error.detail.code === 'unknown_method'
              ? 'The backend needs an update to list subscriptions.'
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
      if (!active || vigor.loading || !subscriptions.connected) return;
      const requestedOn = connection;
      const requestedEvidenceRevision = evidenceRevision;
      vigor = { ...vigor, loading: true, error: undefined };
      try {
        const reply = await app.call('app.readVigor');
        if (!isCurrent(requestedOn)) return;
        if (typeof reply.moment !== 'string' || !Array.isArray(reply.subscriptions)
          || !reply.failures || typeof reply.failures !== 'object' || Array.isArray(reply.failures)
          || (reply.headline !== null && (!reply.headline || typeof reply.headline !== 'object'))) {
          throw new Error('Invalid Vigor rollup.');
        }
        if (requestedEvidenceRevision === evidenceRevision) {
          evidence = reply.usageEvidence as UsageEvidence | undefined;
          evidenceError = typeof reply.usageEvidenceError === 'string' ? reply.usageEvidenceError : undefined;
        }
        now = Date.now();
        vigor = { rollup: retainVigor(reply as unknown as VigorRollup, vigor.rollup) };
        refreshWindows();
      } catch (error) {
        if (!isCurrent(requestedOn)) return;
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
      if (!active || !subscriptions.connected || !['Subscriptions', 'Vigor'].includes(activeTab) || !readUsage) return;
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

    function canStartWindow(driver: string, account: SubscriptionRecord) {
      return account.state === 'signed_in' && !!account.createdAt && (
        driver === 'claude' && account.family === 'anthropic'
        || driver === 'codex' && account.family === 'chatgpt'
        || driver === 'pi' && ['chatgpt', 'kimi-coding', 'zai'].includes(account.family)
      );
    }

    function refreshWindows() {
      refreshPassedWindows();
      if (!active || !subscriptions.connected || !['Subscriptions', 'Vigor'].includes(activeTab) || !readUsage) return;
      for (const { driver, subscriptions: accounts } of subscriptionView.listing?.drivers ?? []) {
        for (const account of accounts ?? []) {
          if (!canStartWindow(driver, account)) continue;
          const key = subscriptionKey(driver, account.id);
          const windows = account.metrics?.windows ?? [];
          if (!windows.some(window => window.pendingStart)) {
            if (windows.some(window => window.windowMinutes === 300 && window.remainingMinutes !== undefined)) {
              attemptedStarts.delete(key);
            }
            continue;
          }
          const binding = JSON.stringify([account.createdAt, account.family]);
          if (subscriptions.usageRequests?.[key]?.pending || attemptedStarts.get(key) === binding) continue;
          // Claim before dispatch. A still-pending report must not recursively retry.
          attemptedStarts.set(key, binding);
          void readUsage(driver, account.id, true);
        }
      }
    }

    readUsage = async (driver, subscription, startWindow = false) => {
      const account = subscriptions.listing?.drivers.find((entry) => entry.driver === driver)
        ?.subscriptions?.find((row) => row.id === subscription);
      const key = subscriptionKey(driver, subscription);
      if (!active || !subscriptions.connected || subscriptions.usageRequests?.[key]?.pending
        || !account || !(startWindow ? canStartWindow(driver, account) : canRefreshSubscriptionUsage(driver, account))) return;
      const requestedOn = connection;
      const sameAccount = () => isCurrent(requestedOn) && subscriptions.listing?.drivers
        .find(entry => entry.driver === driver)?.subscriptions?.some(row => row.id === subscription
          && row.createdAt === account.createdAt && row.family === account.family && row.state === 'signed_in');
      subscriptions = {
        ...subscriptions, usageRequests: { ...subscriptions.usageRequests, [key]: { pending: true } },
      };
      const pending = subscriptions.usageRequests?.[key];
      let problem: string | undefined;
      if (startWindow) {
        try {
          const result = await bridge.call<{ outcome: string }>('accounts.startWindow', {
            driver, subscription, createdAt: account.createdAt,
          });
          if (!['started', 'skipped'].includes(result?.outcome)) problem = 'The provider did not confirm the window start.';
        } catch (error) {
          problem = error instanceof Refusal ? error.message : 'Could not start this allowance window.';
        }
        if (!sameAccount()) {
          if (subscriptions.usageRequests?.[key] === pending) {
            const requests = { ...subscriptions.usageRequests };
            delete requests[key];
            subscriptions = { ...subscriptions, usageRequests: requests };
          }
          return;
        }
      }
      try {
        const result = await bridge.call<{ outcome: string; message?: string }>('accounts.usage', {
          driver, subscription,
        });
        if (result?.outcome !== 'ok') problem ??= result?.message || 'The provider did not return a usage report.';
      } catch (error) {
        problem ??= error instanceof Refusal ? error.message : 'Could not refresh usage.';
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
      queueMicrotask(refreshWindows);
    };

    renameSubscription = async (driver, account, label) => {
      if (!active || !subscriptions.connected || !account.createdAt) throw new Error('Reconnect and refresh this subscription before editing.');
      const requestedOn = connection;
      const current = subscriptions.listing?.drivers.find(entry => entry.driver === driver)?.subscriptions?.find(row => row.id === account.id);
      if (!current || current.createdAt !== account.createdAt || current.checkedAt !== account.checkedAt || current.label !== account.label) {
        throw new Error('This subscription changed while you were editing. Refresh before saving.');
      }
      const reply = await app.call('app.renameSubscription', {
        driver, subscription: account.id, label, expectedLabel: account.label,
        createdAt: account.createdAt, checkedAt: account.checkedAt ?? null,
      });
      if (!isCurrent(requestedOn)) throw new Error('The save finished after the connection changed. Refresh to see the saved name.');
      if (reply.label !== label || typeof reply.updatedAt !== 'string') throw new Error('The App did not confirm this name. Refresh before trying again.');
      evidenceRevision++;
      evidence = reply.usageEvidence as UsageEvidence | undefined;
      evidenceError = typeof reply.usageEvidenceError === 'string' ? reply.usageEvidenceError : undefined;
      const key = subscriptionKey(driver, account.id);
      subscriptions = {
        ...subscriptions,
        nameNotices: { ...subscriptions.nameNotices, [key]: typeof reply.warning === 'string' ? reply.warning : undefined },
        listing: subscriptions.listing && { drivers: subscriptions.listing.drivers.map(entry => entry.driver !== driver ? entry : ({
          ...entry, subscriptions: entry.subscriptions?.map(row => row.id === account.id && row.createdAt === account.createdAt
            ? { ...row, label, updatedAt: reply.updatedAt as string } : row),
        })) },
      };
      await listRequest;
      if (isCurrent(requestedOn)) await reloadList();
    };

    openUsagePage = async (destination, driver, subscription) => {
      const key = subscriptionKey(driver, subscription);
      const requestedOn = connection;
      const account = subscriptions.listing?.drivers.find((entry) => entry.driver === driver)
        ?.subscriptions?.find((row) => row.id === subscription);
      if (!account) return;
      subscriptions = {
        ...subscriptions, usageLinkErrors: { ...subscriptions.usageLinkErrors, [key]: undefined },
      };
      try {
        if (destination === 'chatgpt') await app.call('app.openSubscriptionUsage', { driver, subscription });
        else await app.call('app.openLink', { url: 'https://platform.xiaomimimo.com/console/balance' });
      } catch (error) {
        const current = subscriptions.listing?.drivers.find((entry) => entry.driver === driver)
          ?.subscriptions?.find((row) => row.id === subscription);
        if (isCurrent(requestedOn) && current?.createdAt === account?.createdAt && current?.family === account?.family) subscriptions = {
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
      retryWindowStarts = undefined;
      openUsagePage = undefined;
      renameSubscription = undefined;
      clearInterval(expiryClock);
      bridge.close();
      app.close();
    };
  });
</script>

<SeqoyaLab fitted {connectionStatus}
  subscriptions={subscriptionView} vigor={vigorView} onTabChange={changeTab}
  onRefreshSubscriptions={() => refreshSubscriptions(true)} onRefreshVigor={() => refreshSubscriptions(true)}
  onRefreshUsage={refreshUsage} onOpenUsage={openUsage} onRenameSubscription={renameName}
  appearanceReady={ready} bind:theme={appearance.theme} bind:uiScale={appearance.uiScale}
  onAppearanceChange={() => { if (ready) saveSeqoyaAppearance('installation', appearance); }} />
