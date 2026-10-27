<script lang="ts">
 import SafeMarkdown from '../components/SafeMarkdown.svelte';
 import ToolCall from './ToolCall.svelte';
 import AskUserQuestion from './AskUserQuestion.svelte';
 import { lifecycle,clock,failureCause,limitReset,type ExchangeError,type Answer,type QuestionView,type ResponseBlock,type ToolView,type ToolDetails } from './elma-response';
 let {blocks=[] as ResponseBlock[],streaming=false,statusLabel,acceptedAt,startedAt,endedAt,now=Date.now(),error,questions=[],notes=[],showBeacon=false,onbeacon,onopenLink,onloadTool,oncopyAnswer,openTools,onToolOpen,onanswer,onretry,oncontinue,failureBusy=false,signIn}: {blocks?:ResponseBlock[];streaming?:boolean;statusLabel?:string;acceptedAt?:string;startedAt?:string;endedAt?:string;now?:number;questions?:QuestionView[];error?:ExchangeError;notes?:string[];showBeacon?:boolean;onbeacon?:()=>void;onopenLink?:(url:string)=>Promise<unknown>;onloadTool?:(tool:ToolView)=>Promise<ToolDetails>;oncopyAnswer?:(text:string)=>Promise<void>;openTools?:Record<string,boolean>;onToolOpen?:(id:string,open:boolean)=>void;onanswer?:(question:QuestionView,answer:Answer)=>void;onretry?:()=>void;oncontinue?:()=>void;failureBusy?:boolean;signIn?:string}=$props();
 const reset=$derived(error?limitReset(error,endedAt):undefined);
 const lines=$derived(lifecycle(acceptedAt,startedAt,streaming?undefined:endedAt));
 const answer=$derived(blocks.filter(block=>block.kind==='text').map(block=>block.kind==='text'?block.text:'').join('\n\n'));
 const work=$derived(blocks.filter(block=>block.kind!=='text'));
 let copied=$state(''),threshold=$state<HTMLDivElement>();
 async function copy(){try{await(oncopyAnswer?.(answer)??navigator.clipboard.writeText(answer));copied='Answer copied';}catch{copied='The answer could not be copied.';}}
 function beacon(){if(onbeacon)onbeacon();else threshold?.scrollIntoView({block:'start'});}
</script>
{#snippet render(items:ResponseBlock[])}
 {#each items as block (block.id)}
  {#if block.kind==='thinking'}<section class="thinking" data-reading-stop aria-label="Thinking"><h3>{items.filter(b=>b.kind==='thinking').length>1?'Thinking '+(items.filter(b=>b.kind==='thinking').findIndex(b=>b.id===block.id)+1)+'/'+items.filter(b=>b.kind==='thinking').length:'Thinking'}</h3><SafeMarkdown text={block.text} {onopenLink}/></section>
  {:else if block.kind==='text'}<section class="prose" data-reading-stop><SafeMarkdown text={block.text} {onopenLink}/></section>
  {:else if block.kind==='notice'}<p class="notice" data-reading-stop>{block.text}</p>
  {:else if block.kind==='tool'}<section data-reading-stop><ToolCall name={block.tool.name} input={block.tool.input} result={block.tool.result} error={block.tool.error} state={block.tool.state} startedAt={block.tool.startedAt} endedAt={block.tool.endedAt} {now} cut={block.tool.cut} truncated={block.tool.truncated} outputDelta={block.tool.outputDelta} parallel={block.tool.parallel} expanded={openTools?.[block.tool.id]??false} onexpanded={open=>onToolOpen?.(block.tool.id,open)} load={onloadTool?()=>onloadTool!(block.tool):undefined}>
   {#if block.tool.children?.length}<section class="children" aria-label="Sub-agent activity">{@render render(block.tool.children)}</section>{/if}
  </ToolCall></section>{/if}
 {/each}
{/snippet}
<article class="response" aria-label="Assistant response">
 <div class="lifecycle">{#each lines as group}<p>{#each group as item,i}{i?' · ':''}{item.label} <time datetime={item.at}>{clock(item.at)}</time>{/each}</p>{/each}</div>
 {#if streaming}{@render render(blocks)}{:else}{@render render(work)}<div class="threshold" data-answer-threshold data-reading-stop bind:this={threshold}><span>Answer</span></div><section class="answer" aria-label="Answer"><SafeMarkdown text={answer} {onopenLink}/></section>{/if}
 {#if error}<section class="failure" aria-label="Exchange failure"><p>Failed at: {clock(endedAt)}</p><p>Error: {failureCause(error)}</p><p>{error.code}: {error.message}</p>{#if reset}<p>It resets at <time datetime={reset}>{clock(reset)}</time></p>{/if}{#if ['not_signed_in','credential_rejected'].includes(error.code)&&signIn}<p>Sign in with: <code>{signIn}</code></p>{/if}<p>⚠︎ {failureCause(error)}</p>{#if onretry||oncontinue}<div class="failure-actions">{#if onretry}<button disabled={failureBusy} onclick={onretry}>Retry</button>{/if}{#if oncontinue}<button disabled={failureBusy} onclick={oncontinue}>Continue from failure point</button>{/if}</div>{/if}</section>{/if}
 {#each notes as note}<p class="notice">{note}</p>{/each}
 {#each questions.filter(q=>q.open||q.answer!==undefined||q.recorded) as question (question.id)}<AskUserQuestion firstSapling {question} onanswer={onanswer?answer=>onanswer!(question,answer):undefined}/>{/each}
 <div class="status-row"><span class="exchange-status" role="status">{statusLabel??(streaming?'Responding…':'Completed')}</span>{#if !streaming}<button class="copy" disabled={!answer} onclick={()=>void copy()}>Copy answer</button>{/if}</div>
 {#if copied}<p class="notice" role="status">{copied}</p>{/if}
 {#if showBeacon&&!streaming}<button class="beacon" onclick={beacon}>↓ Answer</button>{/if}
</article>
<style>
.response{position:relative;width:100%;max-width:var(--elma-reading-width,720px);margin:0 auto;padding:20px 24px 32px;min-width:0;font:calc(13.5px * var(--elma-content-scale,var(--font-scale)))/1.6 var(--font-ui);overflow-wrap:anywhere}.lifecycle{display:flex;flex-direction:column;gap:3px;color:var(--muted);font:calc(11.5px * var(--font-scale))/1.5 var(--font-mono);margin-bottom:16px}.thinking{padding:10px 12px;margin:12px 0;color:var(--muted);background:var(--panel);border-left:2px solid var(--border)}.thinking h3{font:600 calc(11.5px * var(--font-scale))/1.5 var(--font-ui);margin:0 0 6px}.prose{margin:12px 0}.notice{color:var(--muted);font-size:.85em;margin:10px 0}.threshold{display:flex;align-items:center;gap:12px;color:var(--muted);font:calc(11.5px * var(--font-scale))/1.5 var(--font-ui);margin:24px 0 20px}.threshold:before,.threshold:after{content:'';height:1px;background:var(--border);flex:1}.status-row{display:flex;align-items:center;gap:12px;justify-content:flex-end;margin-top:16px}.exchange-status,.copy{font:calc(11.5px * var(--font-scale))/1.5 var(--font-ui);color:var(--muted)}.copy,.beacon{border:1px solid var(--border);background:var(--panel);border-radius:5px;padding:4px 8px;color:var(--link)}.beacon{position:sticky;bottom:12px;display:block;margin-left:auto;font:calc(11.5px * var(--font-scale))/1.5 var(--font-ui)}.failure-actions{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}.failure-actions button{border:1px solid var(--border);background:var(--panel);color:var(--link);border-radius:5px;padding:6px 10px;font:inherit}.failure-actions button:disabled{opacity:.6}.failure{color:var(--failure);font-size:.9em}.children{border-left:2px solid var(--border);padding-left:12px;margin-top:12px}
@media(max-width:600px){.response{padding:16px 12px}}
</style>
