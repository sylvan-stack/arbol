/** One revision-fenced editor per Root/chat or Root/folder; backend Drafts are canonical. */
import { Refusal, type Bridge, type Fields } from './bridge';
import { sameRevision, validRevision, type Revision } from './wire-json';

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
 text=$state('');ready=$state(false);dirty=$state(false);saving=$state(false);problem=$state('');
 canonical=$state<Draft|null>(null);conflict=$state<{mine:string;theirs:string}|null>(null);
 private timer?:ReturnType<typeof setTimeout>;private retry?:ReturnType<typeof setTimeout>;
 private pending?:Promise<void>;private captured?:Saving;private observation=0;private version=0;private closed=false;
 private subscription:{close:()=>void;retry:()=>void};
 constructor(private bridge:Bridge,readonly scope:DraftScope){
  this.subscription=bridge.subscribe('draft',scope,event=>{
   if(!['snapshot','draft'].includes(String(event.kind)))return;
   try{this.observe(decode(event.draft));}catch(e){this.problem=e instanceof Error?e.message:'The Draft could not be read.';}
  },error=>{this.problem='Draft not loaded: '+(error?.message??'The subscription ended.');});
 }
 get revision(){return this.canonical?.revision??null;}
 get status(){return !this.ready?'Loading Draft…':this.saving?'Saving Draft…':this.problem?'Draft not saved':this.dirty?'Draft not saved yet':'';}
 private cancel(){clearTimeout(this.timer);clearTimeout(this.retry);}
 private observe(next:Draft|null){
  if(this.closed)return;
  if(this.canonical&&next&&BigInt(next.revision)<BigInt(this.canonical.revision))return;
  this.observation++;
  if(!this.ready){this.canonical=next;this.text=body(next);this.dirty=false;this.ready=true;this.problem='';return;}
  const previous=this.canonical;
  this.canonical=next;
  if(sameRevision(previous?.revision??null,next?.revision??null))return;
  const own=this.captured&&body(next)===this.captured.text;
  const editedWhileSaving=!!this.captured&&this.version!==this.captured.version;
  if(!this.dirty||this.text===body(next)||own){
   if(!this.dirty&&!editedWhileSaving)this.text=body(next);
   this.dirty=this.text!==body(next);this.conflict=null;this.problem='';
   if(!this.dirty)this.cancel();
  }else{this.conflict={mine:this.text,theirs:body(next)};this.problem='';this.cancel();}
 }
 input(text:string){
  if(!this.ready||this.closed)return;
  this.version++;this.text=text;this.dirty=text!==body(this.canonical)||!!this.captured&&text!==this.captured.text;
  if(this.conflict)this.conflict={mine:text,theirs:body(this.canonical)};
  clearTimeout(this.timer);
  if(!this.dirty){this.cancel();this.problem='';return;}
  if(!this.conflict&&!this.problem)this.timer=setTimeout(()=>void this.flush(),350);
 }
 async flush():Promise<void>{
  clearTimeout(this.timer);
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
    if(!this.dirty)this.conflict=null;
    this.problem='';
   }catch(e){
    if(this.closed)return;
    if(e instanceof Refusal&&e.detail.code==='draft_conflict'&&Object.hasOwn(e.detail,'draft')){
     try{this.observe(decode(e.detail.draft));if(this.dirty&&!this.conflict)this.conflict={mine:this.text,theirs:body(this.canonical)};}catch{this.failed('The backend sent an invalid Draft conflict.');}
    }else if(this.dirty)this.failed(e instanceof Error?e.message:'The database does not answer.');
   }finally{this.saving=false;this.captured=undefined;}
  })();
  await this.pending;this.pending=undefined;
  if(!this.closed&&this.dirty&&!this.problem&&!this.conflict)this.timer=setTimeout(()=>void this.flush(),350);
 }
 private failed(message:string){
  this.problem='Draft not saved: '+message;
  if(this.dirty)this.retry=setTimeout(()=>void this.flush(),5000);
 }
 keepMine(){if(!this.conflict)return;this.conflict=null;this.problem='';this.dirty=this.text!==body(this.canonical);void this.flush();}
 takeTheirs(){this.cancel();this.text=body(this.canonical);this.dirty=false;this.conflict=null;this.problem='';}
 close(){this.closed=true;this.cancel();this.subscription.close();}
}

export class Drafts {
 private editors=new Map<string,DraftEditor>();current=$state<DraftEditor>();
 constructor(private bridge:Bridge){}
 select(root:string,scope:DraftScope){
  const key=root+':'+JSON.stringify(scope);
  const next=this.editors.get(key)??new DraftEditor(this.bridge,scope);this.editors.set(key,next);
  if(next!==this.current)void this.current?.flush();this.current=next;
  return next;
 }
 close(){for(const editor of this.editors.values())editor.close();this.editors.clear();}
}
