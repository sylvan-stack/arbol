/** Persist one exact request per unconfirmed Exchange. Receipts, never time, decide its outcome. */
import { Refusal,type Bridge,type Fields,type BridgeError } from './bridge';
import { isTrunkCode } from './app-channel';
import { parseWire,stringifyWire,validRevision } from './wire-json';
import type { DraftEditor,DraftScope } from './drafts.svelte';
import type { ElmaRoute } from '../design-system/src/sections/elma-types';
export interface SendIntent {version:1;contextId:string;scope:DraftScope;chat:string;exchange:string;method:'chat.send'|'exchange.sendAgain';params:Fields;number:number;existing:boolean;prompt?:string;retryFolder?:string;purpose?:'continue'}
export interface Accepted {accepted:true;duplicate:boolean;chat:string;exchange:string;number:number;trunk:string;build:string}
const uuid=(value:unknown):value is string=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const object=(value:unknown):Fields=>value&&typeof value==='object'&&!Array.isArray(value)?value as Fields:{};
const folder=(value:unknown):value is string=>typeof value==='string'&&value.startsWith('/')&&!/[\0\r\n]/.test(value);
const route=(value:unknown):value is ElmaRoute=>['driver','subscription','model'].every(k=>typeof object(value)[k]==='string'&&(object(value)[k] as string).length>0);
const scopeKey=(contextId:string,scope:DraftScope)=>contextId+':'+JSON.stringify(scope);
function valid(value:unknown,contextId:string):value is SendIntent {
 const v=object(value),p=object(v.params),s=object(v.scope);
 if(v.version!==1||v.contextId!==contextId||!uuid(v.chat)||!uuid(v.exchange)||!Number.isSafeInteger(v.number)||Number(v.number)<1||typeof v.existing!=='boolean'||!route(p.route)||('trunk' in p&&!isTrunkCode(p.trunk)))return false;
 if(('chat' in s)===('folder' in s)||('chat' in s?!uuid(s.chat):!folder(s.folder)))return false;
 if(v.method==='chat.send'){const d=object(p.draft),selected=v.purpose==='continue'?v.existing===true&&p.message==='proceed'&&!('draft' in p)&&s.chat===v.chat:validRevision(d.revision)&&('folder' in s?d.folder===s.folder&&p.workingFolder===s.folder:!('folder' in d)&&s.chat===v.chat);return p.chat===v.chat&&p.exchange===v.exchange&&typeof p.message==='string'&&!!p.message.trim()&&!p.message.includes('\0')&&folder(p.workingFolder)&&selected;}
 return v.method==='exchange.sendAgain'&&uuid(p.exchange)&&p.newExchange===v.exchange&&p.exchange!==v.exchange&&s.chat===v.chat&&v.existing===true&&typeof v.prompt==='string'&&folder(v.retryFolder);
}
export class SendOperation {
 status=$state('Sending…');pending=$state(true);outcome=$state<'pending'|'accepted'|'refused'>('pending');running=false;timer?:ReturnType<typeof setTimeout>;attempts=0;
 readonly done:Promise<void>;finish!:()=>void;
 constructor(readonly intent:SendIntent,public editor:DraftEditor){this.done=new Promise(resolve=>this.finish=resolve);}
 get message(){return typeof this.intent.params.message==='string'?this.intent.params.message:this.intent.prompt??'';}
}
interface Callbacks {provisional:(operation:SendOperation)=>void;accepted:(operation:SendOperation,result:Accepted)=>Promise<void>;refused:(operation:SendOperation,error:BridgeError)=>Promise<void>}
export class Sending {
 private operations=new Map<string,SendOperation>();private finished=new Set<string>();private revision=$state(0);private contextId='';private online=false;private closed=false;
 constructor(private bridge:Bridge,private owner:(contextId:string,scope:DraftScope)=>DraftEditor,private hold:(done:Promise<void>)=>void,private callbacks:Callbacks){}
 private storage(intent:SendIntent){return 'elma.send.v1:'+scopeKey(intent.contextId,intent.scope);}
 private pointer(contextId=this.contextId){return 'elma.activeSend.v1:'+contextId;}
 forEditor(contextId:string,editor:DraftEditor|undefined){this.revision;return editor?[...this.operations.values()].find(op=>op.pending&&scopeKey(op.intent.contextId,op.intent.scope)===scopeKey(contextId,editor.scope)):undefined;}
 forChat(chat:string){this.revision;return [...this.operations.values()].find(op=>op.pending&&op.intent.contextId===this.contextId&&op.intent.chat===chat);}
 select(contextId:string,editor:DraftEditor|undefined){const op=this.forEditor(contextId,editor);try{if(op)sessionStorage.setItem(this.pointer(contextId),op.intent.exchange);else sessionStorage.removeItem(this.pointer(contextId));}catch{/* Dispatch still requires its full recovery record. */}}
 start(intent:SendIntent,visible=true,recovery=false){
  if(!valid(intent,intent.contextId))throw new Error('The message could not be prepared safely.');
  const existing=this.operations.get(intent.contextId+':'+intent.exchange);if(existing)return existing;
  try{sessionStorage.setItem(this.storage(intent),stringifyWire(intent));}catch{if(!recovery)throw new Error('Not sent: this window could not keep the pending message for recovery.');}
  const op=new SendOperation(intent,this.owner(intent.contextId,intent.scope));op.editor.pendingSend=true;this.operations.set(intent.contextId+':'+intent.exchange,op);this.revision++;this.hold(op.done);
  if(visible){this.select(intent.contextId,op.editor);this.callbacks.provisional(op);}
  void this.run(op);return op;
 }
 hello(contextId:string){
  this.contextId=contextId;this.online=true;
  let active:string|null=null;
  try{active=sessionStorage.getItem(this.pointer(contextId));for(const storage of Object.keys(sessionStorage).filter(k=>k.startsWith('elma.send.v1:'+contextId+':'))){const raw=sessionStorage.getItem(storage);if(!raw)continue;let intent:unknown;try{intent=parseWire(raw);}catch{sessionStorage.removeItem(storage);continue;}if(valid(intent,contextId)&&this.storage(intent)===storage)this.start(intent,false,true);else sessionStorage.removeItem(storage);}}
  catch{/* Existing canonical sentAs marks can still recover the same request. */}
  for(const op of this.operations.values())if(op.pending&&op.intent.contextId===contextId){op.editor=this.owner(contextId,op.intent.scope);op.editor.pendingSend=true;this.hold(op.done);if(op.intent.exchange===active&&op.outcome==='pending')this.callbacks.provisional(op);}
  void Promise.resolve().then(()=>Promise.resolve()).then(()=>{for(const op of this.operations.values())if(op.pending&&op.intent.contextId===contextId)void this.run(op);});
 }
 marked(contextId:string,editor:DraftEditor,visible:boolean){
  const draft=editor.canonical,request=object(draft?.sentRequest);if(!draft?.sentAs||!uuid(draft.sentAs)||!uuid(request.chat)||!route(request.route)||!folder(request.workingFolder)||('trunk' in request&&!isTrunkCode(request.trunk)))return;
  if(this.forEditor(contextId,editor)||this.finished.has(contextId+':'+draft.sentAs))return;
  const scope=editor.scope;this.start({version:1,contextId,scope,chat:request.chat,exchange:draft.sentAs,method:'chat.send',params:{chat:request.chat,exchange:draft.sentAs,message:draft.text,route:request.route,workingFolder:request.workingFolder,...(typeof request.trunk==='string'?{trunk:request.trunk}:{}),draft:{revision:draft.revision,...('folder' in scope?{folder:scope.folder}:{})}},number:1,existing:'chat' in scope},visible,true);
 }
 offline(){this.online=false;}
 private async run(op:SendOperation){
  if(this.closed||!this.online||op.running||!op.pending||op.intent.contextId!==this.contextId)return;
  clearTimeout(op.timer);
  if(typeof op.intent.params.trunk==='string'&&op.intent.params.trunk!=='trivial'&&!this.bridge.supportsTrunkSelection){
   op.status='Waiting for a backend that supports the selected Trunk…';return;
  }
  op.running=true;op.status=op.attempts?'Waiting for send receipt…':'Sending…';op.attempts++;
  try{
   const value=await this.bridge.call<Accepted>(op.intent.method,op.intent.params);
   if(value?.accepted!==true||typeof value.duplicate!=='boolean'||value.chat!==op.intent.chat||value.exchange!==op.intent.exchange||!Number.isSafeInteger(value.number)||value.number<1||!isTrunkCode(value.trunk)||typeof value.build!=='string'||!(/^(?:0|[1-9a-f][0-9a-f]*)$/).test(value.build)||!value.duplicate&&value.trunk!==(op.intent.params.trunk??'trivial'))throw new Refusal({code:'no_answer',message:'The backend did not return a valid send receipt.'});
   op.outcome='accepted';op.status='Sent; restoring chat…';if(op.intent.method==='chat.send'&&op.intent.purpose!=='continue')op.editor.rereadAfterSend();try{await this.callbacks.accepted(op,value);}finally{this.complete(op);}
  }catch(e){
   if(!op.pending||this.closed)return;
   const error=e instanceof Refusal?e.detail:{code:'no_answer',message:'The send receipt could not be read.'};
   if(['disconnected','no_answer'].includes(error.code)){op.status='Waiting for send receipt…';if(error.code==='no_answer')op.timer=setTimeout(()=>void this.run(op),op.attempts===1?0:1000);}
   else{op.outcome='refused';try{await this.callbacks.refused(op,error);}finally{this.complete(op);}}
  }finally{op.running=false;}
 }
 private complete(op:SendOperation){
  clearTimeout(op.timer);op.pending=false;op.editor.pendingSend=false;this.finished.add(op.intent.contextId+':'+op.intent.exchange);if(this.finished.size>1000)this.finished.delete(this.finished.values().next().value!);this.operations.delete(op.intent.contextId+':'+op.intent.exchange);this.revision++;
  try{sessionStorage.removeItem(this.storage(op.intent));if(sessionStorage.getItem(this.pointer(op.intent.contextId))===op.intent.exchange)sessionStorage.removeItem(this.pointer(op.intent.contextId));}catch{/* A known receipt remains known in memory. */}op.finish();
 }
 close(){this.closed=true;for(const op of this.operations.values())clearTimeout(op.timer);}
}
