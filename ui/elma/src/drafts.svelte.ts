/** One revision-fenced editor per Root/chat or Root/folder; backend Drafts are canonical. */
import { Refusal, type Bridge, type Fields } from './bridge';
import { parseWire, stringifyWire, sameRevision, validRevision, type Revision } from './wire-json';
import { Pastes } from './pastes.svelte';

export type DraftScope = {chat:string;folder?:never}|{folder:string;chat?:never};
export interface Draft {text:string;revision:Revision;updatedAt?:string;sentAs?:string;sentRequest?:Fields}
interface Saving {text:string;base:Revision|null;observation:number;version:number}
function decode(value:unknown):Draft|null {
 if(value===null)return null;
 if(!value||typeof value!=='object'||!('text' in value)||typeof value.text!=='string'||!('revision' in value)||!validRevision(value.revision))throw new Error('The backend sent an invalid Draft.');
 return value as Draft;
}
const body=(draft:Draft|null)=>draft?.text??'';
export class DraftEditor {
 readonly pastes:Pastes;
 text=$state('');ready=$state(false);dirty=$state(false);saving=$state(false);pendingSend=$state(false);problem=$state('');sendProblem=$state('');
 canonical=$state<Draft|null>(null);conflict=$state<{mine:string;theirs:string}|null>(null);recovery=$state<string|null>(null);storageProblem=$state('');
 private editBase:Revision|null=null;private recovered?:{text:string;baseRevision:Revision|null};
 private timer?:ReturnType<typeof setTimeout>;private retry?:ReturnType<typeof setTimeout>;
 private pending?:Promise<void>;private captured?:Saving;private observation=0;private version=0;private closed=false;
 private subscription:{close:()=>void;retry:()=>void};
 private readyWaiters=new Set<{resolve:()=>void;reject:(error:Error)=>void}>();
 constructor(private bridge:Bridge,readonly scope:DraftScope,private storageKey:string,onCanonical?:(editor:DraftEditor)=>void){
  this.pastes=new Pastes(bridge,this);
  try{const raw=sessionStorage.getItem(storageKey);if(raw){const value=parseWire(raw) as {text?:unknown;baseRevision?:unknown};if(typeof value?.text==='string'&&(value.baseRevision===null||validRevision(value.baseRevision)))this.recovered={text:value.text,baseRevision:value.baseRevision};else sessionStorage.removeItem(storageKey);}}
  catch{this.storageProblem='Unsaved-text recovery is unavailable in this window.';}
  this.subscription=bridge.subscribe('draft',scope,event=>{
   if(!['snapshot','draft'].includes(String(event.kind)))return;
   try{this.observe(decode(event.draft));onCanonical?.(this);if(this.ready){for(const waiter of this.readyWaiters)waiter.resolve();this.readyWaiters.clear();}}catch(e){this.problem=e instanceof Error?e.message:'The Draft could not be read.';this.rejectReady();}
  },error=>{this.problem='Draft not loaded: '+(error?.message??'The subscription ended.');this.rejectReady();});
 }
 private rejectReady(){for(const waiter of this.readyWaiters)waiter.reject(new Error(this.problem||'The Draft was closed.'));this.readyWaiters.clear();}
 waitReady(){if(this.ready)return Promise.resolve();if(this.problem||this.closed)return Promise.reject(new Error(this.problem||'The Draft was closed.'));return new Promise<void>((resolve,reject)=>this.readyWaiters.add({resolve,reject}));}
 get revision(){return this.canonical?.revision??null;}
 get status(){return !this.ready?'Loading Draft…':this.saving?'Saving Draft…':this.problem?'Draft not saved':this.dirty?'Draft not saved yet':'';}
 private cancel(){clearTimeout(this.timer);clearTimeout(this.retry);}
 private observe(next:Draft|null){
  if(this.closed)return;
  if(this.canonical&&next&&BigInt(next.revision)<BigInt(this.canonical.revision))return;
  this.observation++;
  if(!this.ready){this.canonical=next;this.text=body(next);this.editBase=this.revision;this.dirty=false;this.ready=true;this.problem='';if(this.recovered&&sameRevision(this.recovered.baseRevision,this.revision)&&this.recovered.text!==this.text)this.recovery=this.recovered.text;else this.recovered=undefined;this.persist();return;}
  const previous=this.canonical;
  this.canonical=next;
  if(this.recovery!==null&&this.recovered&&!sameRevision(this.recovered.baseRevision,this.revision)){this.recovery=null;this.recovered=undefined;}
  if(sameRevision(previous?.revision??null,next?.revision??null))return;
  const own=this.captured&&body(next)===this.captured.text;
  if(own)this.editBase=this.revision;
  const editedWhileSaving=!!this.captured&&this.version!==this.captured.version;
  if(!this.dirty||this.text===body(next)||own){
   if(!this.dirty&&!editedWhileSaving)this.text=body(next);
   this.dirty=this.text!==body(next);this.conflict=null;this.problem='';
   if(!this.dirty)this.cancel();
  }else{this.conflict={mine:this.text,theirs:body(next)};this.problem='';this.cancel();}
  this.persist();
 }
 input(text:string,edit?:{start:number;end:number}){
  if(!this.ready||this.closed||this.recovery!==null)return;
  if(!this.dirty)this.editBase=this.revision;
  this.pastes.change(this.text,text,edit);
  this.version++;this.text=text;this.dirty=text!==body(this.canonical)||!!this.captured&&text!==this.captured.text;
  if(this.conflict)this.conflict={mine:text,theirs:body(this.canonical)};
  clearTimeout(this.timer);
  this.persist();
  if(!this.dirty){this.cancel();this.problem='';return;}
  if(!this.conflict&&!this.problem)this.timer=setTimeout(()=>void this.flush(),350);
 }
 async flush():Promise<void>{
  clearTimeout(this.timer);
  if(this.pastes.pending)await this.pastes.wait();
  if(this.closed||!this.ready||!this.dirty||this.conflict)return;
  if(this.pending){await this.pending;if(this.dirty&&!this.problem&&!this.conflict)await this.flush();return;}
  clearTimeout(this.retry);
  const captured:Saving={text:this.text,base:this.revision,observation:this.observation,version:this.version};
  this.captured=captured;this.saving=true;
  this.pending=(async()=>{
   try{
    const result=await this.bridge.call<{revision?:Revision;removed?:boolean}>('draft.save',{...this.scope,text:captured.text,baseRevision:captured.base});
    if(this.closed)return;
    if(result.removed!==true&&!validRevision(result.revision))throw new Error('The backend sent an invalid Draft receipt.');
    // A publication can precede the reply. Neither it nor the reply may acknowledge later typing.
    if(result.removed===true){if(this.observation===captured.observation||this.canonical===null)this.canonical=null;}
    else if(this.observation===captured.observation||this.canonical&&BigInt(result.revision!)>=BigInt(this.canonical.revision))this.canonical={text:captured.text,revision:result.revision!};
    this.dirty=this.text!==body(this.canonical);
    if(body(this.canonical)===captured.text&&!this.conflict)this.editBase=this.revision;
    if(!this.dirty)this.conflict=null;
    this.problem='';
   }catch(e){
    if(this.closed)return;
    if(e instanceof Refusal&&e.detail.code==='draft_conflict'&&Object.hasOwn(e.detail,'draft')){
     try{this.observe(decode(e.detail.draft));if(this.dirty&&!this.conflict)this.conflict={mine:this.text,theirs:body(this.canonical)};}catch{this.failed('The backend sent an invalid Draft conflict.');}
    }else if(this.dirty)this.failed(e instanceof Error?e.message:'The database does not answer.');
   }finally{this.saving=false;this.captured=undefined;this.persist();}
  })();
  await this.pending;this.pending=undefined;
  if(!this.closed&&this.dirty&&!this.problem&&!this.conflict)this.timer=setTimeout(()=>void this.flush(),350);
 }
 private failed(message:string){
  this.problem='Draft not saved: '+message;
  if(this.dirty)this.retry=setTimeout(()=>void this.flush(),5000);
 }
 keepMine(){if(!this.conflict)return;this.conflict=null;this.problem='';this.editBase=this.revision;this.dirty=this.text!==body(this.canonical);this.persist();void this.flush();}
 takeTheirs(){this.cancel();this.pastes.cancel();this.text=body(this.canonical);this.editBase=this.revision;this.dirty=false;this.conflict=null;this.problem='';this.persist();}
 restore(){if(this.recovery===null)return;const text=this.recovery;this.recovery=null;this.recovered=undefined;this.input(text);}
 discardRecovery(){this.recovery=null;this.recovered=undefined;this.persist();}
 receiveDraft(value:unknown){this.observe(decode(value));}
 rereadAfterSend(){if(!this.dirty)this.ready=false;this.subscription.retry();}
 restoreMessage(text:string,base:Revision|null){this.cancel();this.pastes.cancel();this.text=text;this.editBase=base;this.recovery=null;this.recovered=undefined;this.dirty=text!==body(this.canonical);this.conflict=this.dirty?{mine:text,theirs:body(this.canonical)}:null;this.problem='';this.persist();}
 private persist(){
  try{if(this.recovered&&(!this.ready||this.recovery!==null))sessionStorage.setItem(this.storageKey,stringifyWire(this.recovered));else if(this.dirty)sessionStorage.setItem(this.storageKey,stringifyWire({text:this.text,baseRevision:this.editBase}));else sessionStorage.removeItem(this.storageKey);this.storageProblem='';}
  catch{this.storageProblem='Unsaved text is held in this page, but could not be kept for a reload.';}
 }
 close(){this.persist();this.closed=true;this.rejectReady();this.cancel();this.pastes.close();this.subscription.close();}
}

export class Drafts {
 private editors=new Map<string,DraftEditor>();private root='';private sends=new Set<Promise<unknown>>();current=$state<DraftEditor>();
 constructor(private bridge:Bridge,private onCanonical?:(root:string,editor:DraftEditor)=>void){}
 rootChanged(root:string){if(this.root&&root!==this.root){for(const editor of this.editors.values())editor.close();this.editors.clear();this.sends.clear();this.current=undefined;}this.root=root;}
 owner(root:string,scope:DraftScope){if(root!==this.root)throw new Error('The Draft belongs to a different Root.');const key=root+':'+JSON.stringify(scope);const editor=this.editors.get(key)??new DraftEditor(this.bridge,scope,'elma.unsaved.v1:'+key,value=>this.onCanonical?.(root,value));this.editors.set(key,editor);return editor;}
 select(root:string,scope:DraftScope){
  this.rootChanged(root);
  const next=this.owner(root,scope);
  const previous=this.current;this.current=next;
  if(next!==previous)void previous?.flush().then(()=>this.prune());this.prune();
  return next;
 }
 private prune(){for(const [key,editor]of this.editors)if(editor!==this.current&&editor.ready&&!editor.pendingSend&&!editor.dirty&&!editor.saving&&editor.recovery===null){editor.close();this.editors.delete(key);}}
 holdSend(completion:Promise<unknown>){this.sends.add(completion);const remove=()=>this.sends.delete(completion);void completion.then(remove,remove);}
 private async waitPending(except?:Promise<unknown>){
  while([...this.sends].some(p=>p!==except))await Promise.all([...this.sends].filter(p=>p!==except).map(p=>p.catch(()=>undefined)));
 }
 async settleCurrent(except?:Promise<unknown>){
  await this.waitPending(except);const editor=this.current;
  if(!editor?.ready)throw new Error('Wait for the current Draft to be read.');
  do{await editor.flush();}while(editor.dirty&&!editor.problem&&!editor.conflict&&editor.ready);
  if(editor!==this.current||editor.dirty||editor.conflict||editor.recovery!==null)throw new Error('Unsaved Draft text needs attention before continuing.');
 }
 async settle(){
  await this.waitPending();
  for(const editor of this.editors.values()){
   do{await editor.flush();}while(editor.dirty&&!editor.problem&&!editor.conflict&&editor.ready);
   if(editor.dirty||editor.conflict||editor.recovery!==null)throw new Error('Unsaved Draft text needs attention before reloading.');
  }
 }
 async beforeReload(){await this.settle();}
 close(){for(const editor of this.editors.values())editor.close();this.editors.clear();}
}
