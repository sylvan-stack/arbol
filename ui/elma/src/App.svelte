<script lang="ts">
  import { onMount } from 'svelte';
  import { Bridge } from './bridge';
  let state = $state('Connecting…');
  onMount(() => { const bridge = new Bridge({build:__ARBOL_BUILD__,onstate:s=>state=s}); return ()=>bridge.close(); });
</script>
<main><h1>Elma Chat</h1><p role="status">{state}</p></main>
