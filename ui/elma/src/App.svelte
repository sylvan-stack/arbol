<script lang="ts">
 import { onMount } from 'svelte';
 import ElmaFrame from '../design-system/src/sections/ElmaFrame.svelte';
 import { ElmaWindow } from './window.svelte';
 let view=$state<ElmaWindow>();
 onMount(()=>{const model=new ElmaWindow();view=model;return()=>model.close();});
</script>
<svelte:head><title>{view?`Elma Chat · ${view.root.name} - ${view.title}`:'Elma Chat'}</title></svelte:head>
{#if view}
 <ElmaFrame root={view.root} title={view.title} placeholder={view.placeholder} hasChat={!!view.info} total={view.info?.exchangeCount??0} turn={view.turn} working={view.working} ongoing={view.ongoing} inputTokens={view.info?.usage.inputTokens??0} outputTokens={view.info?.usage.outputTokens??0} repository={view.repository} route={view.route} repositories={view.repositories} routes={view.routes} accountProblems={view.accountProblems} fitted bind:theme={view.preferences.theme} bind:readingWidth={view.preferences.readingWidth} bind:uiScale={view.preferences.uiScale} bind:contentScale={view.preferences.contentScale} onpreferences={()=>view?.savePreferences()}>
  {#if view.connection!=='Connected'}<p class="connection" role="status">{view.connection}</p>{/if}
  {#if view.problem}<p class="problem" role="alert">{view.problem}</p>{/if}
  <section class="chat" aria-label="Chat">
   {#if view.exchange}<p class="prompt">{view.exchange.items.find(item=>item.kind==='message'&&item.role==='user')?.kind==='message'?view.exchange.items.filter(item=>item.kind==='message'&&item.role==='user').map(item=>item.kind==='message'?item.text:'').join('\n'):''}</p>
   {:else}<p class="empty">New Chat</p>{/if}
  </section>
 </ElmaFrame>
{:else}<p role="status">Connecting…</p>{/if}
<style>
.connection,.problem{margin:0;padding:6px 16px;background:var(--inset);color:var(--warning);border-bottom:1px solid var(--border)}
.problem{color:var(--failure)}.chat{display:flex;flex-direction:column;min-height:0;flex:1;overflow:hidden}.prompt{padding:16px;white-space:pre-wrap;overflow-wrap:anywhere;border-bottom:1px solid var(--border)}.empty{margin:auto;color:var(--muted)}
</style>
