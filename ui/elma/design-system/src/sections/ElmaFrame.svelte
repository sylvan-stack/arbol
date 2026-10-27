<script lang="ts">
  import type { Snippet } from 'svelte';
  import WorkspaceShell from '../patterns/WorkspaceShell.svelte';
  import WorkspaceGlyph from '../components/WorkspaceGlyph.svelte';
  import { THEMES } from '../themes';
  import type { ElmaRoute } from './elma-types';
  let {
    root = {name:'Fixture Root',status:'working',failed:undefined as {reason:string}|undefined}, title='New Chat', placeholder=false,
    turn=0, total=0, hasChat=false, working=false, ongoing=false, inputTokens=0, outputTokens=0,
    repository='sylvan-stack', route={} as ElmaRoute, repositories=[] as {name:string;folder:string}[],
    routes=[] as {driver:string;subscription:string;unavailable?:string}[], accountProblems=[] as string[], fitted=false,routeBusy=false,routeSaving=false,routeProblem='',onretryRoute,
    readingWidth=$bindable(720), uiScale=$bindable(0), contentScale=$bindable(0), theme=$bindable(''),
    onpreferences=()=>{}, onolder, onnewer, onhistory, onrepository, onroute, onmodel, oneffort, onother, onquick, onongoing, children,
  }: {
    root?:{name:string;status:string;failed?:{reason:string}};title?:string;placeholder?:boolean;turn?:number;total?:number;hasChat?:boolean;working?:boolean;ongoing?:boolean;
    inputTokens?:number;outputTokens?:number;repository?:string;route?:ElmaRoute;repositories?:{name:string;folder:string}[];routes?:{driver:string;subscription:string;unavailable?:string}[];
    accountProblems?:string[];fitted?:boolean;routeBusy?:boolean;routeSaving?:boolean;routeProblem?:string;onretryRoute?:()=>void;readingWidth?:number;uiScale?:number;contentScale?:number;theme?:string;onpreferences?:()=>void;
    onolder?:()=>void;onnewer?:()=>void;onhistory?:()=>void;onrepository?:(folder:string)=>void;onroute?:(driver:string,subscription:string)=>void;onmodel?:()=>void;oneffort?:()=>void;onother?:()=>void;onquick?:()=>void;onongoing?:()=>void;children?:Snippet;
  }=$props();
  let repoOpen=$state(true), intelligenceOpen=$state(true), priorEmpty=true;
  $effect(()=>{const empty=total===0;if(empty!==priorEmpty){repoOpen=empty;intelligenceOpen=empty;priorEmpty=empty;}});
  const rounded=(n:number)=>Math.round(n*100)/100;
  function font(increase:boolean){let ui=uiScale||1,content=contentScale||ui;const maxUI=23/13.5,maxContent=32/13.5,min=11.5/13.5;
    if(increase){if(ui<maxUI){ui=Math.min(maxUI,rounded(ui+.1));content=ui;}else content=Math.min(maxContent,rounded(content+.1));}
    else if(content>ui)content=Math.max(ui,rounded(content-.1));else {ui=Math.max(min,rounded(ui-.1));content=ui;}
    uiScale=ui;contentScale=content;onpreferences();
  }
</script>

<div class="elma-frame" data-theme={theme||undefined} style:--font-scale={uiScale||undefined} style:--elma-content-scale={contentScale||undefined} style:--elma-reading-width={readingWidth+'px'}>
<WorkspaceShell workspace="Elma" {fitted} elma>
  {#snippet headerContent()}
    <span class:working class="mark"><WorkspaceGlyph workspace="Elma" size={21}/></span>
    <h1 class:placeholder>Elma Chat · {root.name} - {title}</h1>
    {#if root.status!=='working'}<span class="root-state">{root.status}{root.failed ? ': '+root.failed.reason : ''}</span>{/if}
    <div class="preferences">
      <label class="width">Reading width <select aria-label="Reading width" bind:value={readingWidth} onchange={onpreferences}>{#each Array.from({length:10},(_,i)=>600+i*120) as width}<option value={width}>{width} px</option>{/each}</select></label>
      <button aria-label="Decrease text size" disabled={(uiScale||1)<=11.5/13.5&&(contentScale||1)<=(uiScale||1)} onclick={()=>font(false)}>A−</button>
      <button aria-label="Increase text size" disabled={(contentScale||1)>=32/13.5} onclick={()=>font(true)}>A+</button>
      <select aria-label="Theme" bind:value={theme} onchange={onpreferences}>{#if !theme}<option value="">Current theme</option>{/if}{#each THEMES as item}<option value={item.id}>{item.name}</option>{/each}</select>
    </div>
  {/snippet}
  {#snippet navigation()}
    <div class="nav-title" class:placeholder>{title}</div>
    {#if total}<p class="turn-count">Turn {turn} of {total}</p>{/if}
    {#if hasChat}<div class="cockpit"><button disabled={!onongoing} onclick={onongoing}>{ongoing?'○ Ongoing':'○ Not ongoing'}</button><span>∑ {(inputTokens+outputTokens).toLocaleString()} ↑{inputTokens.toLocaleString()} ↓{outputTokens.toLocaleString()}</span></div>{/if}
    <button class="group" aria-expanded={repoOpen} onclick={()=>repoOpen=!repoOpen}><span>Repositories</span><span aria-hidden="true">{repoOpen?'−':'+'}</span></button>
    {#if repoOpen}{#each repositories.slice(0,9) as repo,i}<button class="nav-row" disabled={!onrepository} onclick={()=>onrepository?.(repo.folder)}><span>{repo.name}</span><kbd>⌘{i+1}</kbd></button>{/each}<button class="nav-row" disabled={!onother} onclick={onother}><span>Other…</span><kbd>⌘0</kbd></button>{/if}
    <div class="history-heading">History{total?' · '+total+' turns':''}</div>
    {#if total>1}<button class="nav-row" disabled={!onolder||turn<=1} onclick={onolder}><span>Older turn</span><kbd>⌘[</kbd></button><button class="nav-row" disabled={!onnewer||turn>=total} onclick={onnewer}><span>Newer turn</span><kbd>⌘]</kbd></button><button class="nav-row" disabled={!onhistory} onclick={onhistory}><span>Jump to turn…</span><kbd>⌘P</kbd></button>{/if}
    {#if hasChat}<button class="nav-row" disabled={!onquick} onclick={onquick}><span>Quick actions…</span><kbd>⇧⏎</kbd></button>{/if}
    <button class="group" aria-expanded={intelligenceOpen} onclick={()=>intelligenceOpen=!intelligenceOpen}><span>Intelligence</span><span aria-hidden="true">{intelligenceOpen?'−':'+'}</span></button>
    {#if intelligenceOpen}{#each accountProblems as problem}<p class="account-problem">{problem}</p>{/each}{#if routeBusy||routeSaving}<p class="account-problem" role="status">{routeBusy?'Loading models…':'Saving route…'}</p>{/if}{#if routeProblem}<p class="account-problem" role="status">{routeProblem}</p>{#if onretryRoute}<button class="nav-row" onclick={onretryRoute}>Retry models</button>{/if}{/if}<button class="nav-row" disabled={!onmodel||routeBusy} onclick={onmodel}><span>Model: {route.model||'—'}</span><kbd>⌃M</kbd></button><button class="nav-row" disabled={!oneffort||routeBusy} onclick={oneffort}><span>Thinking: {route.effort||'—'}</span><kbd>⌃⇥</kbd></button>{#each routes as row,i}<button class="nav-row" disabled={!!row.unavailable||!onroute} onclick={()=>onroute?.(row.driver,row.subscription)} title={row.unavailable}><span>{row.driver} · {row.subscription}{row.unavailable?' · '+row.unavailable:''}</span>{#if i<9}<kbd>⌃{i+1}</kbd>{/if}</button>{/each}{/if}
  {/snippet}
  {#snippet status()}<span class="status-text">{repository} – {route.driver||'—'} · {route.subscription||'—'} – {route.model||'—'}::{route.effort||'—'}</span>{/snippet}
  {#if children}{@render children()}{:else}<div class="empty">New Chat</div>{/if}
</WorkspaceShell>
</div>

<style>
.elma-frame{min-width:0;color:var(--text);font:calc(13.5px * var(--font-scale))/1.5 var(--font-ui)}
h1{min-width:0;flex:1;font:600 calc(13.5px * var(--font-scale))/1.4 var(--font-ui);overflow-wrap:anywhere}
.placeholder{font-weight:400;color:var(--muted)}.mark{display:flex;color:var(--accent);flex-shrink:0}.working{animation:breathe 1.6s ease-in-out infinite}@keyframes breathe{50%{opacity:.4;transform:rotate(-12deg)}}
.preferences{display:flex;gap:4px;align-items:center;flex-wrap:wrap;font-size:calc(11.5px * var(--font-scale))}.preferences button,.preferences select{min-height:28px;background:var(--inset);color:var(--text);border:1px solid var(--border);border-radius:5px;padding:2px 5px}.width{font-size:0}.width select{font-size:calc(11.5px * var(--font-scale))}.root-state{color:var(--warning);overflow-wrap:anywhere}
.account-problem{color:var(--warning);font-size:calc(11.5px * var(--font-scale));overflow-wrap:anywhere}.nav-title{font-weight:600;overflow-wrap:anywhere}.turn-count,.cockpit,.history-heading{color:var(--muted);font-size:calc(11.5px * var(--font-scale))}.cockpit{display:flex;flex-direction:column;gap:4px;margin:12px 0}.cockpit button{border:1px solid var(--border);border-radius:20px;background:var(--inset);color:var(--text);padding:4px 8px;align-self:start}.group,.nav-row{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;text-align:left;min-height:30px;background:transparent;border:0;color:var(--text);padding:4px 0}.group{font-size:calc(11.5px * var(--font-scale));color:var(--muted);font-weight:700;margin-top:12px;text-transform:uppercase}.nav-row span{overflow-wrap:anywhere;min-width:0}.nav-row kbd{white-space:nowrap;flex-shrink:0;color:var(--muted)}.history-heading{border-top:1px solid var(--border);padding-top:12px;margin-top:12px;text-transform:uppercase}.status-text{overflow-wrap:anywhere;white-space:normal}.empty{margin:auto;padding:32px;color:var(--muted)}
@media(prefers-reduced-motion:reduce){.working{animation:none}}
@media(max-width:800px){.preferences{margin-left:auto}.preferences .width{display:none}.mark{display:none}}
</style>
