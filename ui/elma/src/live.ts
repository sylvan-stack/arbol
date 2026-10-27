/** A snapshot owns the lifetime of this file projection. No wall-clock timeout ends it. */
import type { ElmaExchange } from '../design-system/src/sections/elma-types';
import { clock, duration, type ResponseBlock, type ToolView, type QuestionView } from '../design-system/src/sections/elma-response';
type ObjectValue=Record<string,unknown>;
const object=(v:unknown):ObjectValue=>v!==null&&typeof v==='object'&&!Array.isArray(v)?v as ObjectValue:{};
const text=(v:unknown)=>typeof v==='string'?v:'';
const tokens=(v:unknown)=>{const u=object(v);return{inputTokens:typeof u.inputTokens==='number'&&u.inputTokens>=0?u.inputTokens:0,outputTokens:typeof u.outputTokens==='number'&&u.outputTokens>=0?u.outputTokens:0};};
export function savedUsage(row:ElmaExchange){return row.runs.reduce((sum,run)=>{const u=tokens(run.usage);return{inputTokens:sum.inputTokens+u.inputTokens,outputTokens:sum.outputTokens+u.outputTokens};},{inputTokens:0,outputTokens:0});}
export function savedBlocks(row:ElmaExchange):ResponseBlock[]{return row.items.flatMap((item):ResponseBlock[]=>item.kind==='message'?(item.role==='assistant'?[{id:'message:'+item.position,kind:'text',text:item.text}]:[]):[{id:'tool:'+item.position,kind:'tool',tool:{id:row.exchange+':'+item.position,name:item.name,input:item.input,result:item.result,error:item.error,state:item.interrupted?'Interrupted':item.ok?'Complete':'Failed',truncated:item.truncated,cut:item.cut,position:item.position}}]);}
export class LiveExchange {
 blocks:ResponseBlock[]=[];questions:QuestionView[]=[];seen=new Set<number>();
 state='accepting';waitingFor='';since?:string;startedAt?:string;activity='';end?:{state:string;at?:string;error?:{code:string;message:string}};saved=false;
 private pending=new Map<string,ResponseBlock>();private tools=new Map<string,ToolView>();private usage=new Map<string,ReturnType<typeof tokens>>();private totalOverride?:ReturnType<typeof tokens>;
 readonly baseline:ReturnType<typeof tokens>;
 constructor(row:ElmaExchange){this.state=row.state;this.saved=['completed','failed','cancelled','interrupted'].includes(row.state);this.baseline=savedUsage(row);}
 status(value:ObjectValue){if(this.saved)return;if(typeof value.state==='string')this.state=value.state;this.waitingFor=text(value.waitingFor);this.since=text(value.since)||undefined;const end=object(value.end);if(typeof end.state==='string')this.setEnd(end);}
 private setEnd(end:ObjectValue){const error=object(end.error);if(['completed','failed','cancelled','interrupted'].includes(text(end.state)))for(const q of this.questions)q.open=false;this.end={state:text(end.state),at:text(end.at)||undefined,...(typeof error.code==='string'&&typeof error.message==='string'?{error:{code:error.code,message:error.message}}:{})};}
 private target(run:string,parent:string):ResponseBlock[]{if(!parent)return this.blocks;const tool=this.tools.get(run+'\0'+parent);if(!tool)return [];return tool.children??=([]);}
 apply(lines:unknown[]){if(this.saved)return;for(const raw of lines){const line=object(raw),n=line.n;if(!Number.isSafeInteger(n)||Number(n)<1||this.seen.has(Number(n)))continue;this.seen.add(Number(n));
  if(line.tooLarge===true){this.blocks.push({id:'oversize:'+n,kind:'notice',text:`An event was too large to display (${typeof line.bytes==='number'?line.bytes:'unknown'} bytes).`});continue;}
  if(line.end){this.setEnd(object(line.end));continue;}
  if(line.answer){const answer=object(line.answer);const q=this.questions.find(q=>q.open&&q.askId===answer.askId);if(q){q.answer=answer.answer;q.answerPosition=Number(n);q.problem=undefined;}continue;}
  const e=object(line.event??line.smallRun),run=text(e.runId),parent=text(e.parentCallId),kind=text(e.type);if(!run)continue;
  if((kind==='usage'||kind==='finished')&&!parent){if(e.usage!==undefined)this.usage.set(run,tokens(e.usage));if(line.smallRun)continue;}
  const target=this.target(run,parent),actor=run+'\0'+parent,id=String(n);
  if(kind==='started'&&!parent){this.startedAt??=text(e.at)||undefined;this.activity='';}
  else if(['text_delta','text','thinking_delta','thinking'].includes(kind)&&typeof e.text==='string'){
   const blockKind=kind.startsWith('thinking')?'thinking':'text',key=actor+'\0'+blockKind;let block=this.pending.get(key);
   if(!block){block={id:'live:'+id,kind:blockKind,text:''};target.push(block);this.pending.set(key,block);}
   if(block.kind!=='tool')block.text=kind.endsWith('_delta')?block.text+e.text:e.text;
   if(!kind.endsWith('_delta'))this.pending.delete(key);if(!parent)this.activity=blockKind;
  }else if(kind==='tool_started'&&typeof e.callId==='string'){
   const tool:ToolView={id:run+':'+e.callId,name:text(e.name)||'Tool',input:e.input,state:'Running',startedAt:text(e.at)||undefined};
   const siblings=[...this.tools.values()].filter(t=>t.state==='Running'&&target.some(b=>b.kind==='tool'&&b.tool===t));
   const total=siblings.length+1;if(total>1){for(const t of siblings)t.parallel={running:total,total};tool.parallel={running:total,total};}
   this.tools.set(run+'\0'+e.callId,tool);target.push({id:'live:'+id,kind:'tool',tool});if(!parent)this.activity='';
  }else if((kind==='tool_output_delta'||kind==='tool_finished')&&typeof e.callId==='string'){
   const tool=this.tools.get(run+'\0'+e.callId);if(!tool)continue;
   if(kind==='tool_output_delta')tool.outputDelta=(tool.outputDelta??'')+text(e.text);
   else{tool.state=e.interrupted?'Interrupted':e.ok===true?'Complete':'Failed';tool.result=e.result;tool.error=typeof e.error==='string'?e.error:undefined;tool.truncated=e.truncated===true;tool.endedAt=text(e.at)||undefined;tool.position=Number(n);
    const running=target.filter(b=>b.kind==='tool'&&b.tool.state==='Running').length;for(const b of target)if(b.kind==='tool'&&b.tool.parallel)b.tool.parallel={...b.tool.parallel,running};}
  }else if(kind==='ask_opened'&&typeof e.askId==='string'&&!this.questions.some(q=>q.id===run+':'+e.askId))this.questions.push({id:run+':'+e.askId,askId:e.askId,ask:e.ask,at:text(e.at)||undefined,open:true});
  else if(kind==='ask_closed'){const q=this.questions.find(q=>q.id===run+':'+e.askId);if(q)q.open=false;}
  else if(kind==='notice'&&typeof e.message==='string')target.push({id:'live:'+id,kind:'notice',text:e.message});
  else if(kind==='control_refused'){const error=object(e.error),message='The answer was not taken: '+(text(error.message)||text(e.message)||'The Driver refused it.');const q=this.questions.find(q=>q.id===run+':'+e.askId);if(q){q.problem=message;q.refusalPosition=Number(n);}else target.push({id:'live:'+id,kind:'notice',text:message});}
 }}
 reconcile(row:ElmaExchange){const retained=this.blocks.filter(b=>b.kind==='thinking'||b.kind==='notice');const tools=[...this.tools.values()];this.blocks=[...retained,...savedBlocks(row).map(b=>{if(b.kind!=='tool')return b;const observed=tools.find(t=>t.position===b.tool.position);return{...b,tool:{...b.tool,id:observed?.id??b.tool.id,startedAt:observed?.startedAt,endedAt:observed?.endedAt}};})];this.state=row.state;this.saved=true;this.questions=[];this.totalOverride=savedUsage(row);}
 get totals(){if(this.totalOverride)return this.totalOverride;if(!this.usage.size)return this.baseline;return[...this.usage.values()].reduce((sum,u)=>({inputTokens:sum.inputTokens+u.inputTokens,outputTokens:sum.outputTokens+u.outputTokens}),{inputTokens:0,outputTokens:0});}
 get usageDelta(){const total=this.totals;return{inputTokens:total.inputTokens-this.baseline.inputTokens,outputTokens:total.outputTokens-this.baseline.outputTokens};}
 label(row:ElmaExchange,now:number){
  const ended=this.saved||['completed','failed','cancelled','interrupted'].includes(row.state),state=ended?row.state:this.state;
  if(state==='failed'||this.end?.state==='failed')return 'Failed';if(state==='stopping')return 'Stopping…';
  if(state==='gone')return 'Interrupted';
  if(!ended){const q=this.questions.find(q=>q.open);if(q||this.waitingFor==='answer')return 'Waiting for your answer since '+clock(this.waitingFor==='answer'?this.since??q?.at:q?.at);
   if(!this.startedAt&&!row.runs.some(r=>r.kind==='agent'&&r.started))return 'Starting agent…';
   const tools=[...this.tools.values()].filter(t=>t.state==='Running');if(this.waitingFor==='tool'||tools.length)return 'Waiting for tools… '+duration(this.waitingFor==='tool'?this.since??tools[0]?.startedAt:tools[0]?.startedAt,undefined,now);
   if(this.activity==='thinking')return 'Thinking…';if(this.activity==='text')return 'Responding…';return `${row.route.driver??'Driver'} · ${row.route.subscription??'Subscription'} is working…`;
  }
  return state==='completed'?'Completed':state==='cancelled'?'Canceled':row.note?.kind==='ended_stuck'?'Ended because it was stuck':'Interrupted';
 }
}
