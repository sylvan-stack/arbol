/** Persist one exact request per unconfirmed Exchange. Receipts, never time, decide its outcome. */
import { Refusal,type Bridge,type Fields,type BridgeError } from './bridge';
import { parseWire,stringifyWire,validRevision } from './wire-json';
import type { DraftEditor,DraftScope } from './drafts.svelte';
import type { ElmaRoute } from '../design-system/src/sections/elma-types';
export interface SendIntent {version:1;root:string;scope:DraftScope;chat:string;exchange:string;method:'chat.send'|'exchange.sendAgain';params:Fields;number:number;existing:boolean;prompt?:string}
export interface Accepted {accepted:true;duplicate:boolean;chat:string;exchange:string;number:number}
const uuid=(value:unknown):value is string=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const object=(value:unknown):Fields=>value&&typeof value==='object'&&!Array.isArray(value)?value as Fields:{};
const folder=(value:unknown):value is string=>typeof value==='string'&&value.startsWith('/')&&!/[\0\r\n]/.test(value);
const route=(value:unknown):value is ElmaRoute=>['driver','subscription','model'].every(k=>typeof object(value)[k]==='string'&&(object(value)[k] as string).length>0);
const scopeKey=(root:string,scope:DraftScope)=>root+':'+JSON.stringify(scope);
function valid(value:unknown,root:string):value is SendIntent {
 const v=object(value),p=object(v.params),s=object(v.scope);
 if(v.version!==1||v.root!==root||!uuid(v.chat)||!uuid(v.exchange)||!Number.isSafeInteger(v.number)||Number(v.number)<1||typeof v.existing!=='boolean'||!route(p.route))return false;
 if(('chat' in s)===('folder' in s)||('chat' in s?!uuid(s.chat):!folder(s.folder)))return false;
 if(v.method==='chat.send'){const d=object(p.draft);return p.chat===v.chat&&p.exchange===v.exchange&&typeof p.message==='string'&&!!p.message.trim()&&!p.message.includes('\0')&&folder(p.workingFolder)&&validRevision(d.revision)&&('folder' in s?d.folder===s.folder&&p.workingFolder===s.folder:!('folder' in d)&&s.chat===v.chat);}
 return v.method==='exchange.sendAgain'&&uuid(p.exchange)&&p.newExchange===v.exchange&&p.exchange!==v.exchange&&s.chat===v.chat&&typeof v.prompt==='string';
}
export class SendOperation {
 status=$state('Sending…');pending=$state(true);outcome=$state<'pending'|'accepted'|'refused'>('pending');running=false;timer?:ReturnType<typeof setTimeout>;attempts=0;
 readonly done:Promise<void>;finish!:()=>void;
 constructor(readonly intent:SendIntent,public editor:DraftEditor){this.done=new Promise(resolve=>this.finish=resolve);}
 get message(){return typeof this.intent.params.message==='string'?this.intent.params.message:this.intent.prompt??'';}
}
interface Callbacks {provisional:(operation:SendOperation)=>void;accepted:(operation:SendOperation,result:Accepted)=>Promise<void>;refused:(operation:SendOperation,error:BridgeError)=>Promise<void>}
export class Sending {
 private operations=new Map<string,SendOperation>();private finished=new Set<string>();private revision=$state(0);private root='';private online=false;private closed=false;
 constructor(private bridge:Bridge,private owner:(root:string,scope:DraftScope)=>DraftEditor,private hold:(done:Promise<void>)=>void,private callbacks:Callbacks){}
 private storage(intent:SendIntent){return 'elma.send.v1:'+scopeKey(intent.root,intent.scope);}
 private pointer(root=this.root){return 'elma.activeSend.v1:'+root;}
 forEditor(root:string,editor:DraftEditor|undefined){this.revision;return editor?[...this.operations.values()].find(op=>op.pending&&scopeKey(op.intent.root,op.intent.scope)===scopeKey(root,editor.scope)):undefined;}
 forChat(chat:string){this.revision;return [...this.operations.values()].find(op=>op.pending&&op.intent.root===this.root&&op.intent.chat===chat);}
 select(root:string,editor:DraftEditor|undefined){const op=this.forEditor(root,editor);try{if(op)sessionStorage.setItem(this.pointer(root),op.intent.exchange);else sessionStorage.removeItem(this.pointer(root));}catch{/* Dispatch still requires its full recovery record. */}}
 start(intent:SendIntent,visible=true,recovery=false){
  if(!valid(intent,intent.root))throw new Error('The message could not be prepared safely.');
  const existing=this.operations.get(intent.root+':'+intent.exchange);if(existing)return existing;
  try{sessionStorage.setItem(this.storage(intent),stringifyWire(intent));}catch{if(!recovery)throw new Error('Not sent: this window could not keep the pending message for recovery.');}
  const op=new SendOperation(intent,this.owner(intent.root,intent.scope));op.editor.pendingSend=true;this.operations.set(intent.root+':'+intent.exchange,op);this.revision++;this.hold(op.done);
  if(visible){this.select(intent.root,op.editor);this.callbacks.provisional(op);}
  void this.run(op);return op;
 }
 hello(root:string){
  this.root=root;this.online=true;
  let active:string|null=null;
  try{active=sessionStorage.getItem(this.pointer(root));for(const storage of Object.keys(sessionStorage).filter(k=>k.startsWith('elma.send.v1:'+root+':'))){const raw=sessionStorage.getItem(storage);if(!raw)continue;let intent:unknown;try{intent=parseWire(raw);}catch{sessionStorage.removeItem(storage);continue;}if(valid(intent,root)&&this.storage(intent)===storage)this.start(intent,false,true);else sessionStorage.removeItem(storage);}}
  catch{/* Existing canonical sentAs marks can still recover the same request. */}
  for(const op of this.operations.values())if(op.pending&&op.intent.root===root){op.editor=this.owner(root,op.intent.scope);op.editor.pendingSend=true;this.hold(op.done);if(op.intent.exchange===active&&op.outcome==='pending')this.callbacks.provisional(op);}
  void Promise.resolve().then(()=>Promise.resolve()).then(()=>{for(const op of this.operations.values())if(op.pending&&op.intent.root===root)void this.run(op);});
 }
 marked(root:string,editor:DraftEditor,visible:boolean){
  const draft=editor.canonical,request=object(draft?.sentRequest);if(!draft?.sentAs||!uuid(draft.sentAs)||!uuid(request.chat)||!route(request.route)||!folder(request.workingFolder))return;
  if(this.forEditor(root,editor)||this.finished.has(root+':'+draft.sentAs))return;
  const scope=editor.scope;this.start({version:1,root,scope,chat:request.chat,exchange:draft.sentAs,method:'chat.send',params:{chat:request.chat,exchange:draft.sentAs,message:draft.text,route:request.route,workingFolder:request.workingFolder,draft:{revision:draft.revision,...('folder' in scope?{folder:scope.folder}:{})}},number:1,existing:'chat' in scope},visible,true);
 }
 offline(){this.online=false;}
 private async run(op:SendOperation){
  if(this.closed||!this.online||op.running||!op.pending||op.intent.root!==this.root)return;
  clearTimeout(op.timer);op.running=true;op.status=op.attempts?'Waiting for send receipt…':'Sending…';op.attempts++;
  try{
   const value=await this.bridge.call<Accepted>(op.intent.method,op.intent.params);
   if(value?.accepted!==true||typeof value.duplicate!=='boolean'||value.chat!==op.intent.chat||value.exchange!==op.intent.exchange||!Number.isSafeInteger(value.number)||value.number<1)throw new Refusal({code:'no_answer',message:'The backend did not return a valid send receipt.'});
   op.outcome='accepted';op.status='Sent; restoring chat…';if(op.intent.method==='chat.send')op.editor.rereadAfterSend();try{await this.callbacks.accepted(op,value);}finally{this.complete(op);}
  }catch(e){
   if(!op.pending||this.closed)return;
   const error=e instanceof Refusal?e.detail:{code:'no_answer',message:'The send receipt could not be read.'};
   if(['disconnected','no_answer'].includes(error.code)){op.status='Waiting for send receipt…';if(error.code==='no_answer')op.timer=setTimeout(()=>void this.run(op),op.attempts===1?0:1000);}
   else{op.outcome='refused';try{await this.callbacks.refused(op,error);}finally{this.complete(op);}}
  }finally{op.running=false;}
 }
 private complete(op:SendOperation){
  clearTimeout(op.timer);op.pending=false;op.editor.pendingSend=false;this.finished.add(op.intent.root+':'+op.intent.exchange);if(this.finished.size>1000)this.finished.delete(this.finished.values().next().value!);this.operations.delete(op.intent.root+':'+op.intent.exchange);this.revision++;
  try{sessionStorage.removeItem(this.storage(op.intent));if(sessionStorage.getItem(this.pointer(op.intent.root))===op.intent.exchange)sessionStorage.removeItem(this.pointer(op.intent.root));}catch{/* A known receipt remains known in memory. */}op.finish();
 }
 close(){this.closed=true;for(const op of this.operations.values())clearTimeout(op.timer);}
}
