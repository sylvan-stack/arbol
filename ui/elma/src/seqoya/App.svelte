<script lang="ts">
  import { onMount } from 'svelte';
  import SeqoyaLab from '../../design-system/src/pages/SeqoyaLab.svelte';
  import type { WorkspaceRootSelector } from '../../design-system/src/types';
  import { AppChannel } from '../app-channel';
  import { Bridge, type RootInfo } from '../bridge';

  let root = $state<RootInfo>();
  let rootSelector = $state<WorkspaceRootSelector>();
  let connectionStatus = $state('Connecting to Root…');

  onMount(() => {
    const app = new AppChannel();
    const bridge = new Bridge({
      onhello: (identity) => { root = identity; },
      onstate: (state) => { connectionStatus = state === 'Connected' ? '' : state; },
    });
    rootSelector = app.rootSelector;
    return () => {
      bridge.close();
      app.close();
    };
  });
</script>

<SeqoyaLab fitted {root} {rootSelector} {connectionStatus} />
