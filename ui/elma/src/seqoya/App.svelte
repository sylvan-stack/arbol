<script lang="ts">
  import { onMount } from 'svelte';
  import SeqoyaLab from '../../design-system/src/pages/SeqoyaLab.svelte';
  import type { WorkspaceTrunkSelector } from '../../design-system/src/types';
  import { AppChannel } from '../app-channel';
  import { Bridge } from '../bridge';
  import { readSeqoyaAppearance, saveSeqoyaAppearance } from '../preferences';

  let trunk = $state<string>();
  let trunkSelector = $state<WorkspaceTrunkSelector>();
  let connectionStatus = $state('Connecting to Root…');
  let rootId = $state<string>();
  let appearance = $state(readSeqoyaAppearance());

  onMount(() => {
    const app = new AppChannel();
    let active = true;
    const bridge = new Bridge({
      onhello: (root) => {
        if (rootId !== root.root) {
          rootId = root.root;
          appearance = readSeqoyaAppearance(rootId);
        }
        void app.currentTrunk().then((current) => {
          if (active && trunk === undefined) trunk = current;
        }).catch(() => { /* The selector reports its own errors. */ });
      },
      onstate: (state) => { connectionStatus = state === 'Connected' ? '' : state; },
    });
    trunkSelector = app.trunkSelector((code) => { if (active) trunk = code; });
    return () => {
      active = false;
      bridge.close();
      app.close();
    };
  });
</script>

<SeqoyaLab fitted {trunk} {trunkSelector} {connectionStatus}
  appearanceReady={rootId !== undefined} bind:theme={appearance.theme} bind:uiScale={appearance.uiScale}
  onAppearanceChange={() => { if (rootId !== undefined) saveSeqoyaAppearance(rootId, appearance); }} />
