<script lang="ts">
 import { onMount } from 'svelte';
 import ElmaFrame from '../design-system/src/sections/ElmaFrame.svelte';
 import PinnedMessage from '../design-system/src/sections/PinnedMessage.svelte';
 import HistoryTree from '../design-system/src/sections/HistoryTree.svelte';
 import Modal from '../design-system/src/patterns/Modal.svelte';
 import ConfirmAction from '../design-system/src/patterns/ConfirmAction.svelte';
 import ResponseReader from '../design-system/src/sections/ResponseReader.svelte';
 import Composer from '../design-system/src/sections/Composer.svelte';
 import { ElmaWindow } from './window.svelte';
 let view=$state<ElmaWindow>();
 let reader=$state<{scrollToEdge:(edge:'top'|'bottom')=>void}>();
 onMount(()=>{const model=new ElmaWindow();view=model;return()=>model.close();});
 function keys(event:KeyboardEvent){if(!view||event.defaultPrevented||document.querySelector('dialog[open]'))return;if(event.ctrlKey&&!event.metaKey&&!event.altKey&&!event.shiftKey){if(view.composerBusy){event.preventDefault();return;}if(/^[1-9]$/.test(event.key)){const row=view.routes[Number(event.key)-1];if(row&&!row.unavailable){event.preventDefault();void view.routing.choose(row.driver,row.subscription);}}else if(event.key.toLowerCase()==='m'){event.preventDefault();view.routing.nextModel();}else if(event.key==='Tab'){event.preventDefault();view.routing.nextEffort();}return;}if(!event.metaKey||event.altKey)return;if(!event.ctrlKey&&!event.shiftKey&&event.key==='Escape'){event.preventDefault();view.stopCurrent();return;}if(!event.ctrlKey&&!event.shiftKey&&/^[0-9]$/.test(event.key)){event.preventDefault();if(event.key==='0')void view.pickOther(true);else{const repo=view.repositories[Number(event.key)-1];if(repo)view.newChat(repo.folder);}return;}if(event.key.toLowerCase()==='p'){event.preventDefault();if(view.info)view.historyOpen=!view.historyOpen;}else if(!view.historyOpen&&(event.key==='['||event.code==='BracketLeft')){event.preventDefault();void view.older();}else if(!view.historyOpen&&(event.key===']'||event.code==='BracketRight')){event.preventDefault();view.newer();}}

</script>
<svelte:window onkeydown={keys}/>
<svelte:head><title>{view?`Elma Chat · ${view.root.name} - ${view.title}`:'Elma Chat'}</title></svelte:head>
{#if view}
 <ElmaFrame root={view.root} title={view.title} placeholder={view.placeholder} hasChat={!!view.info} total={view.info?.exchangeCount??0} turn={view.turn} working={view.working} ongoing={view.ongoing} inputTokens={view.usage.inputTokens} outputTokens={view.usage.outputTokens} repository={view.repository} route={view.route} repositories={view.repositories} routes={view.routes} onrepository={folder=>view?.chooseRepository(folder)} onother={()=>void view?.pickOther()} accountProblems={view.accountProblems} routeBusy={view.routing.busy} routeSaving={view.routing.saving} routeProblem={view.routing.problem} onretryRoute={view.routing.modelProblem&&view.routes.some(r=>r.driver===view!.route.driver&&r.subscription===view!.route.subscription&&!r.unavailable)?()=>void view?.routing.retryModels():undefined} onroute={!view.composerBusy?(driver,subscription)=>void view?.routing.choose(driver,subscription):undefined} onmodel={!view.composerBusy&&view.routing.models.length?()=>view?.routing.nextModel():undefined} oneffort={!view.composerBusy&&view.routing.efforts.length?()=>view?.routing.nextEffort():undefined} onolder={()=>void view?.older()} onnewer={()=>view?.newer()} onhistory={()=>{if(view)view.historyOpen=true;}} fitted bind:theme={view.preferences.theme} bind:readingWidth={view.preferences.readingWidth} bind:uiScale={view.preferences.uiScale} bind:contentScale={view.preferences.contentScale} onpreferences={()=>view?.savePreferences()}>
  {#if view.connection!=='Connected'}<p class="connection" role="status">{view.connection}</p>{/if}
  {#if view.problem||view.pageProblem}<p class="problem" role="alert">{view.problem||view.pageProblem}</p>{/if}
  {#if view.repositoryNotice}<p class="connection" role="status">{view.repositoryNotice}</p>{/if}
  <section class="chat" aria-label="Chat">
   {#if view.exchange}<PinnedMessage text={view.prompt} index={view.turn} total={view.info?.exchangeCount??0} busy={view.pageBusy} onolder={()=>void view?.older()} onnewer={()=>view?.newer()} onhistory={()=>{if(view)view.historyOpen=true;}}/><ResponseReader bind:this={reader} identity={(view.info?.chat??'')+':'+view.exchange.exchange} snapshot={view.snapshotRevision} positions={view.readingPositions} response={{blocks:view.response,streaming:!view.complete,statusLabel:view.statusLabel,acceptedAt:view.exchange.acceptedAt,startedAt:view.startedAt,endedAt:view.exchange.endedAt,now:view.now,error:view.error,questions:view.questions,notes:view.responseNotes,openTools:view.openTools,onToolOpen:(id,open)=>{if(view)view.openTools[id]=open;},onloadTool:tool=>view!.loadTool(tool),onopenLink:url=>view!.openLink(url)}}/>
   {:else if view.restoring}<p class="empty" role="status">Restoring selected turn…</p>{/if}
   {#if view.drafts.current}{@const draft=view.drafts.current}<Composer firstSapling empty={!view.info} repository={view.repository} route={view.route} context={view.info?.chat??view.folder} value={draft.text} bind:expanded={view.composerOpen} readOnly={!draft.ready||draft.recovery!==null} busy={view.composerBusy} onsend={()=>view?.requestSend()} status={view.composerStatus} problem={[draft.sendProblem,draft.pastes.problem,draft.problem,draft.storageProblem].filter(Boolean).join(" · ")} conflict={draft.conflict} recovery={draft.recovery} onRestore={()=>draft.restore()} onDiscardRecovery={()=>draft.discardRecovery()} oninput={(text,edit)=>draft.input(text,edit)} onpaste={(event,selection)=>{const text=event.clipboardData?.getData("text/plain")??"";if(draft.ready&&!view!.composerBusy&&draft.recovery===null&&draft.pastes.paste(text,selection))event.preventDefault();}} onblur={()=>void draft.flush()} onKeepMine={()=>draft.keepMine()} onTakeTheirs={()=>draft.takeTheirs()} onTop={()=>reader?.scrollToEdge('top')} onBottom={()=>reader?.scrollToEdge('bottom')}/>{/if}
  </section>

 {#if view.stopConfirmation}<ConfirmAction title="Stop current response?" description="Stop the current response, wait until its end is saved, and then send this Draft." action="Confirm" actionTone="primary" oncancel={()=>view?.cancelStop()} onconfirm={()=>void view?.confirmStopSend()}/>{/if}
 {#if view.repositoryChange}<ConfirmAction title="Change repository?" description="The agent still gets every message of this chat, but no longer remembers what it read and ran before" action="Change repository" actionTone="primary" oncancel={()=>{if(view)view.repositoryChange=null;}} onconfirm={()=>void view?.confirmRepository()}/>{/if}
 {#if view.historyOpen}<Modal title={`History · ${view.info?.exchangeCount??0} turns`} onclose={()=>{if(view)view.historyOpen=false;}} initialFocus="button[data-history-row]"><HistoryTree items={view.history} selected={view.selected??''} problem={view.pageProblem} more={view.more} busy={view.pageBusy} onselect={id=>view?.selectExchange(id)} onmore={()=>void view?.page()}/></Modal>{/if}
 </ElmaFrame>

{:else}<p role="status">Connecting…</p>{/if}
<style>
.connection,.problem{margin:0;padding:6px 16px;background:var(--inset);color:var(--warning);border-bottom:1px solid var(--border)}
.problem{color:var(--failure)}.chat{display:flex;flex-direction:column;min-height:0;flex:1;overflow:hidden}.empty{margin:auto;color:var(--muted)}
</style>
