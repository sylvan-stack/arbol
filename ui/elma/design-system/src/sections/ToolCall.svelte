<script lang="ts">
 import type { Snippet } from 'svelte';
 import { isShellTool,pretty,toolSummary,clock,duration,type ToolDetails } from './elma-response';
 let {name='Tool',label,input=undefined as unknown,result=undefined as unknown,error,state:status='Unknown',expanded=$bindable(false),startedAt,endedAt,now=Date.now(),truncated=false,cut=false,outputDelta='',parallel,load,onexpanded,children}: {name?:string;label?:string;input?:unknown;result?:unknown;error?:string;state?:string;expanded?:boolean;startedAt?:string;endedAt?:string;now?:number;truncated?:boolean;cut?:boolean;outputDelta?:string;parallel?:{running:number;total:number};load?:()=>Promise<ToolDetails>;onexpanded?:(open:boolean)=>void;children?:Snippet}=$props();
 let full=$state<ToolDetails>(),loading=$state(false),problem=$state('');
 async function details(){if(!cut||full||loading)return;if(!load){problem='Full details are unavailable.';return;}loading=true;problem='';try{full=await load();}catch(e){problem=e instanceof Error?e.message:'The tool details could not be read.';}finally{loading=false;}}
 function toggle(event:Event){expanded=(event.currentTarget as HTMLDetailsElement).open;onexpanded?.(expanded);if(expanded)void details();}
 const displayedInput = $derived(full ? full.input : input);
 const shellDetails = $derived.by(() => {
  if (!isShellTool(name)) return;
  if (typeof displayedInput === 'string' && (!cut || full)) return { command: displayedInput };
  if (!displayedInput || typeof displayedInput !== 'object' || Array.isArray(displayedInput)) return;
  const { command, ...metadata } = displayedInput as Record<string, unknown>;
  if (typeof command === 'string') return { command, metadata };
 });
 const mark=$derived(status==='Running'?'…':status==='Failed'?'!':status==='Interrupted'?'interrupted':status==='Complete'?'✓':status);
</script>
<details class="tool" open={expanded} ontoggle={toggle}>
 <summary>
  <span class="disclosure" aria-hidden="true">▸</span>
  <span class="name" title={name}>{name}</span>
  <span class="mark" title={status} class:failure={status==='Failed'}>
   <span aria-hidden="true">{mark}</span><span class="sr-only">{status}</span>
  </span>
  {#if status==='Running'&&startedAt&&now-Date.parse(startedAt)>=60000}<span class="time">{duration(startedAt,undefined,now)}</span>{/if}{#if parallel&&parallel.running>1}<span class="parallel">waiting on this call · {parallel.running} of {parallel.total} running</span>{/if}
  <span class="summary">{isShellTool(name) ? label || "Run shell command" : toolSummary(full?full.input:input)}</span>
 </summary>
 {#if expanded}<div class="detail"><dl><div><dt>Started</dt><dd>{clock(startedAt)}</dd></div><div><dt>Ended</dt><dd>{clock(endedAt)}</dd></div><div><dt>Duration</dt><dd>{status==='Running'?duration(startedAt,undefined,now):endedAt?duration(startedAt,endedAt,now):'Not recorded'}</dd></div></dl>
 <h4>{shellDetails ? "Command" : "Input"}</h4><!-- svelte-ignore a11y_no_noninteractive_tabindex (Scrollable tool data stays keyboard reachable.) --><pre tabindex="0" role="region" aria-label={name+(shellDetails ? ' command' : ' input')}>{shellDetails?.command ?? pretty(displayedInput)}</pre>
 {#if shellDetails?.metadata && Object.keys(shellDetails.metadata).length}
  <h4>Other input</h4><!-- svelte-ignore a11y_no_noninteractive_tabindex (Scrollable tool data stays keyboard reachable.) --><pre tabindex="0" role="region" aria-label={name+' other input'}>{pretty(shellDetails.metadata)}</pre>
 {/if}
 <h4>Output</h4><!-- svelte-ignore a11y_no_noninteractive_tabindex (Scrollable tool data stays keyboard reachable.) --><pre tabindex="0" role="region" aria-label={name+' output'}>{pretty(full?full.result:(outputDelta||result))}</pre>
 {#if full?.error??error}<p class="failure">{full?.error??error}</p>{/if}{#if truncated}<p class="note">The Driver cut this output.</p>{/if}{#if cut&&!full}<p class="note">{loading?'Loading full details…':'Preview; full details load when opened.'}</p>{/if}{#if problem}<p role="alert" class="failure">{problem}</p><button onclick={()=>void details()}>Try again</button>{/if}
 {#if children}{@render children()}{/if}</div>{/if}
</details>
<style>
.tool { min-width: 0; margin-block: 2px; font-size: .81em; color: var(--muted); }
summary {
 display: flex;
 align-items: baseline;
 gap: .5em;
 max-width: 100%;
 width: fit-content;
 padding: 2px 4px;
 cursor: pointer;
 list-style: none;
 border-radius: var(--radius-sm);
 font-family: var(--font-mono);
}
summary::-webkit-details-marker { display: none; }
summary:hover { background: var(--selected); }
.disclosure { display: inline-block; flex: none; transition: transform var(--motion-fast); }
details[open] .disclosure { transform: rotate(90deg); }
.name { flex: none; max-width: 35%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; text-decoration: underline; text-underline-offset: 2px; }
.summary { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mark { flex: none; }
.time,.parallel,.note{font-size:.85em;color:var(--muted)}.detail {
 margin: 4px 0 8px 1.4em;
 padding: 8px 12px;
 min-width: 0;
 background: var(--panel);
 border-left: 2px solid var(--border);
 border-radius: var(--radius-sm);
}dl{display:flex;flex-wrap:wrap;gap:8px 24px;font-size:.85em;color:var(--muted)}dl div{display:flex;gap:8px}dt{font-weight:600}dd{margin:0}pre{max-width:100%;max-height:50vh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;padding:12px;background:var(--inset);border:1px solid var(--border);border-radius:5px;font:calc(12px * var(--font-scale))/1.5 var(--font-mono)}h4{font:600 .9em var(--font-ui);margin:10px 0 4px}.failure{color:var(--failure)}button{border:1px solid var(--border);background:var(--inset);color:var(--text);padding:5px 10px;border-radius:5px}
.parallel{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:40%;flex-shrink:1}
</style>
