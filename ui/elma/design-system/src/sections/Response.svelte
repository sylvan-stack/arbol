<script lang="ts">
 import SafeMarkdown from '../components/SafeMarkdown.svelte';
 import ToolCall from './ToolCall.svelte';
 import { lifecycle,clock,pretty,askQuestions,answerLabels,type QuestionView,type ResponseBlock,type ToolView,type ToolDetails } from './elma-response';
 let {blocks=[] as ResponseBlock[],streaming=false,statusLabel,acceptedAt,startedAt,endedAt,now=Date.now(),error,questions=[],notes=[],showBeacon=false,onbeacon,onopenLink,onloadTool,oncopyAnswer,openTools,onToolOpen}: {blocks?:ResponseBlock[];streaming?:boolean;statusLabel?:string;acceptedAt?:string;startedAt?:string;endedAt?:string;now?:number;questions?:QuestionView[];error?:{code:string;message:string};notes?:string[];showBeacon?:boolean;onbeacon?:()=>void;onopenLink?:(url:string)=>Promise<unknown>;onloadTool?:(tool:ToolView)=>Promise<ToolDetails>;oncopyAnswer?:(text:string)=>Promise<void>;openTools?:Record<string,boolean>;onToolOpen?:(id:string,open:boolean)=>void}=$props();
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
 {#if error}<section class="failure"><p>Failed at: {clock(endedAt)}</p><p>Error: {error.message}</p><p>{error.code}: {error.message}</p></section>{/if}
 {#each notes as note}<p class="notice">{note}</p>{/each}
 {#each questions.filter(q=>q.open) as question (question.id)}<section class="question" aria-label="Agent question"><h3>{question.open?'Question from the agent':'Question closed'}</h3>{#each askQuestions(question.ask) as item (item.id)}<p>{item.question}</p><ul>{#each item.options as option}<li>{option.label}{option.description?' · '+option.description:''}</li>{/each}</ul>{:else}<p>{pretty(question.ask)}</p>{/each}{#if question.answer!==undefined}<h4>Your answer</h4><p>{answerLabels(question.answer)}</p>{/if}</section>{/each}
 <div class="status-row"><span class="exchange-status" role="status">{statusLabel??(streaming?'Responding…':'Completed')}</span>{#if !streaming}<button class="copy" disabled={!answer} onclick={()=>void copy()}>Copy answer</button>{/if}</div>
 {#if copied}<p class="notice" role="status">{copied}</p>{/if}
 {#if showBeacon&&!streaming}<button class="beacon" onclick={beacon}>↓ Answer</button>{/if}
</article>
<style>
.response{position:relative;width:100%;max-width:var(--elma-reading-width,720px);margin:0 auto;padding:20px 24px 32px;min-width:0;font:calc(13.5px * var(--elma-content-scale,var(--font-scale)))/1.6 var(--font-ui);overflow-wrap:anywhere}.lifecycle{display:flex;flex-direction:column;gap:3px;color:var(--muted);font:calc(11.5px * var(--font-scale))/1.5 var(--font-mono);margin-bottom:16px}.thinking{padding:10px 12px;margin:12px 0;color:var(--muted);background:var(--panel);border-left:2px solid var(--border)}.thinking h3{font:600 calc(11.5px * var(--font-scale))/1.5 var(--font-ui);margin:0 0 6px}.prose{margin:12px 0}.notice{color:var(--muted);font-size:.85em;margin:10px 0}.threshold{display:flex;align-items:center;gap:12px;color:var(--muted);font:calc(11.5px * var(--font-scale))/1.5 var(--font-ui);margin:24px 0 20px}.threshold:before,.threshold:after{content:'';height:1px;background:var(--border);flex:1}.status-row{display:flex;align-items:center;gap:12px;justify-content:flex-end;margin-top:16px}.exchange-status,.copy{font:calc(11.5px * var(--font-scale))/1.5 var(--font-ui);color:var(--muted)}.copy,.beacon{border:1px solid var(--border);background:var(--panel);border-radius:5px;padding:4px 8px;color:var(--link)}.beacon{position:sticky;bottom:12px;display:block;margin-left:auto;font:calc(11.5px * var(--font-scale))/1.5 var(--font-ui)}.failure{color:var(--failure);font-size:.9em}.children{border-left:2px solid var(--border);padding-left:12px;margin-top:12px}
.question{padding:12px;margin:16px 0;border:1px solid var(--border);border-radius:6px;background:var(--panel)}.question h3,.question h4{margin:0 0 8px;font-size:1em}.question p{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;margin:6px 0}
@media(max-width:600px){.response{padding:16px 12px}}
</style>
