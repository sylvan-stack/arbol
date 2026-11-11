<script lang="ts">
  import { onMount } from 'svelte';
  import SeqoyaLab from '../../design-system/src/pages/SeqoyaLab.svelte';
  import type { SubscriptionListing, SubscriptionView } from '../../design-system/src/sections/seqoya-subscriptions';
  import type { WorkspaceTrunkSelector } from '../../design-system/src/types';
  import { AppChannel } from '../app-channel';
  import { Bridge, Refusal } from '../bridge';
  import { readSeqoyaAppearance, saveSeqoyaAppearance } from '../preferences';

  let trunk = $state<string>();
  let trunkSelector = $state<WorkspaceTrunkSelector>();
  let connectionStatus = $state('Connecting to Root…');
  let rootId = $state<string>();
  let appearance = $state(readSeqoyaAppearance());
  let subscriptions = $state<SubscriptionView>({ connected: false });
  let subscriptionsOpen = false;
  let readSubscriptions: (() => void) | undefined;

  function refreshSubscriptions() {
    readSubscriptions?.();
  }

  function changePage(page: string) {
    subscriptionsOpen = page === 'Subscriptions';
    if (subscriptionsOpen) refreshSubscriptions();
  }

  onMount(() => {
    const app = new AppChannel();
    let active = true;
    let connection = 0;
    const bridge = new Bridge({
      onhello: (root) => {
        connection++;
        subscriptions = {
          connected: true,
          listing: rootId === root.root ? subscriptions.listing : undefined,
        };
        if (rootId !== root.root) {
          rootId = root.root;
          appearance = readSeqoyaAppearance(rootId);
        }
        if (subscriptionsOpen) refreshSubscriptions();
        void app.currentTrunk().then((current) => {
          if (active && trunk === undefined) trunk = current;
        }).catch(() => { /* The selector reports its own errors. */ });
      },
      onstate: (state) => {
        connectionStatus = state === 'Connected' ? '' : state;
        if (state === 'Reconnecting…' || state === 'This window cannot work with this Bridge version.') {
          connection++;
          subscriptions = { connected: false, listing: subscriptions.listing };
        }
      },
    });
    readSubscriptions = async () => {
      if (!active || !subscriptions.connected || subscriptions.loading) return;
      const requestedOn = connection;
      subscriptions = { ...subscriptions, loading: true, error: undefined };
      try {
        const listing = await bridge.call<SubscriptionListing>('accounts.list');
        if (!active || requestedOn !== connection) return;
        if (!Array.isArray(listing?.drivers)) throw new Error('Invalid account list.');
        subscriptions = { connected: true, listing };
      } catch (error) {
        if (!active || requestedOn !== connection) return;
        subscriptions = {
          connected: true,
          listing: subscriptions.listing,
          error: error instanceof Refusal
            ? error.detail.code === 'unknown_method'
              ? 'This Root’s backend needs an update to list subscriptions.'
              : error.message
            : 'The backend did not return a readable account list.',
        };
      }
    };
    trunkSelector = app.trunkSelector((code) => { if (active) trunk = code; });
    return () => {
      active = false;
      readSubscriptions = undefined;
      bridge.close();
      app.close();
    };
  });
</script>

<SeqoyaLab fitted {trunk} {trunkSelector} {connectionStatus}
  {subscriptions} onPageChange={changePage} onRefreshSubscriptions={refreshSubscriptions}
  appearanceReady={rootId !== undefined} bind:theme={appearance.theme} bind:uiScale={appearance.uiScale}
  onAppearanceChange={() => { if (rootId !== undefined) saveSeqoyaAppearance(rootId, appearance); }} />
