<script lang="ts">
 import { onMount } from 'svelte';
 import ElmaFrame from '../design-system/src/sections/ElmaFrame.svelte';
 import PinnedMessage from '../design-system/src/sections/PinnedMessage.svelte';
 import HistoryTree from '../design-system/src/sections/HistoryTree.svelte';
 import Modal from '../design-system/src/patterns/Modal.svelte';
 import ResponseReader from '../design-system/src/sections/ResponseReader.svelte';
 import Composer from '../design-system/src/sections/Composer.svelte';
 import { ElmaWindow } from './window.svelte';
 let view=$state<ElmaWindow>();
 let composerOpen=$state(false),reader=$state<{scrollToEdge:(edge:'top'|'bottom')=>void}>();
 onMount(()=>{const model=new ElmaWindow();view=model;return()=>model.close();});
 function keys(event:KeyboardEvent){if(!view||!event.metaKey||event.altKey)return;if(event.key.toLowerCase()==='p'){event.preventDefault();if(view.info)view.historyOpen=!view.historyOpen;}else if(!view.historyOpen&&(event.key==='['||event.code==='BracketLeft')){event.preventDefault();void view.older();}else if(!view.historyOpen&&(event.key===']'||event.code==='BracketRight')){event.preventDefault();view.newer();}}
</script>
<svelte:window onkeydown={keys}/>
<svelte:head><title>{view?`Elma Chat · ${view.root.name} - ${view.title}`:'Elma Chat'}</title></svelte:head>
{#if view}
 <ElmaFrame root={view.root} title={view.title} placeholder={view.placeholder} hasChat={!!view.info} total={view.info?.exchangeCount??0} turn={view.turn} working={view.working} ongoing={view.ongoing} inputTokens={view.usage.inputTokens} outputTokens={view.usage.outputTokens} repository={view.repository} route={view.route} repositories={view.repositories} routes={view.routes} accountProblems={view.accountProblems} onolder={()=>void view?.older()} onnewer={()=>view?.newer()} onhistory={()=>{if(view)view.historyOpen=true;}} fitted bind:theme={view.preferences.theme} bind:readingWidth={view.preferences.readingWidth} bind:uiScale={view.preferences.uiScale} bind:contentScale={view.preferences.contentScale} onpreferences={()=>view?.savePreferences()}>
  {#if view.connection!=='Connected'}<p class="connection" role="status">{view.connection}</p>{/if}
  {#if view.problem||view.pageProblem}<p class="problem" role="alert">{view.problem||view.pageProblem}</p>{/if}
  <section class="chat" aria-label="Chat">
   {#if view.exchange}<PinnedMessage text={view.prompt} index={view.turn} total={view.info?.exchangeCount??0} busy={view.pageBusy} onolder={()=>void view?.older()} onnewer={()=>view?.newer()} onhistory={()=>{if(view)view.historyOpen=true;}}/><ResponseReader bind:this={reader} identity={(view.info?.chat??'')+':'+view.exchange.exchange} snapshot={view.snapshotRevision} positions={view.readingPositions} response={{blocks:view.response,streaming:!view.complete,statusLabel:view.statusLabel,acceptedAt:view.exchange.acceptedAt,startedAt:view.startedAt,endedAt:view.exchange.endedAt,now:view.now,error:view.error,questions:view.questions,notes:view.responseNotes,openTools:view.openTools,onToolOpen:(id,open)=>{if(view)view.openTools[id]=open;},onloadTool:tool=>view!.loadTool(tool),onopenLink:url=>view!.openLink(url)}}/>
   {:else if view.restoring}<p class="empty" role="status">Restoring selected turn…</p>{/if}
   {#if view.drafts.current}{@const draft=view.drafts.current}<Composer firstSapling empty={!view.info} repository={view.repository} route={view.route} context={view.info?.chat??view.folder} value={draft.text} bind:expanded={composerOpen} readOnly={!draft.ready} status={draft.status} problem={draft.problem} conflict={draft.conflict} oninput={text=>draft.input(text)} onblur={()=>void draft.flush()} onKeepMine={()=>draft.keepMine()} onTakeTheirs={()=>draft.takeTheirs()} onTop={()=>reader?.scrollToEdge('top')} onBottom={()=>reader?.scrollToEdge('bottom')}/>{/if}
  </section>

 {#if view.historyOpen}<Modal title={`History · ${view.info?.exchangeCount??0} turns`} onclose={()=>{if(view)view.historyOpen=false;}} initialFocus="button[data-history-row]"><HistoryTree items={view.history} selected={view.selected??''} problem={view.pageProblem} more={view.more} busy={view.pageBusy} onselect={id=>view?.selectExchange(id)} onmore={()=>void view?.page()}/></Modal>{/if}
 </ElmaFrame>

{:else}<p role="status">Connecting…</p>{/if}
<style>
.connection,.problem{margin:0;padding:6px 16px;background:var(--inset);color:var(--warning);border-bottom:1px solid var(--border)}
.problem{color:var(--failure)}.chat{display:flex;flex-direction:column;min-height:0;flex:1;overflow:hidden}.empty{margin:auto;color:var(--muted)}
</style>
