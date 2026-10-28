/** Public account/catalog choices; no credentials or inference. */
import { describe,Refusal,type Bridge,type BridgeError } from './bridge';
import type { ElmaRoute } from '../design-system/src/sections/elma-types';
export interface RouteRow {driver:string;subscription:string;unavailable?:string}
export interface Model {id:string;label:string;efforts?:string[];defaultEffort?:string;isDefault?:boolean}
const key=(route:ElmaRoute)=>route.driver&&route.subscription?route.driver+':'+route.subscription:'';
const effort=(model:Model|undefined)=>model?.defaultEffort??(model?.efforts?.includes('high')?'high':undefined);
export class Routing {
 rows=$state<RouteRow[]>([]);accountProblems=$state<string[]>([]);accountBusy=$state(false);models=$state<Model[]>([]);busy=$state(false);saving=$state(false);problem=$state('');modelProblem=$state(false);
 private accountRefresh?:{root:string;promise:Promise<void>};
 private accountFresh=false;
 private actual=$state<ElmaRoute>({});private chosen=$state<ElmaRoute|null>(null);
 private context='';private root='';private chat?:string;private defaults:ElmaRoute[]=[];private accountGeneration=0;private generation=0;private choice=0;private loaded=false;private closed=false;
 private catalogKey='';private catalogs=new Map<string,Promise<Model[]>>();private pending?:Promise<void>;
 constructor(private bridge:Bridge,private commit:(chat:string,route:ElmaRoute)=>Promise<unknown>){}
 get value(){return this.chosen??this.actual;}
 get efforts(){return this.models.find(m=>m.id===this.value.model)?.efforts??[];}
 get available(){const route=this.value;return !!route.model&&this.rows.some(r=>r.driver===route.driver&&r.subscription===route.subscription&&!r.unavailable);}
 select(context:string,chat:string|undefined,canonical:ElmaRoute|undefined,defaults:ElmaRoute[]){
  if(context!==this.context){this.context=context;this.generation++;this.choice++;this.chosen=null;this.actual=canonical??{};this.catalogKey='';this.models=[];this.problem='';this.modelProblem=false;this.busy=false;this.saving=false;}
  else if(canonical)this.actual=canonical;
  this.chat=chat;this.defaults=defaults;this.resolve();
 }
 private resolve(){
  if(!this.loaded||!this.context)return;
  if(!this.chat&&!this.chosen){const selected:ElmaRoute=this.defaults.find(candidate=>this.rows.some(r=>r.driver===candidate.driver&&r.subscription===candidate.subscription&&!r.unavailable))??this.rows.find(r=>!r.unavailable)??{};this.actual={...selected,...(key(selected)===key(this.actual)&&!selected.model&&this.actual.model?{model:this.actual.model,effort:this.actual.effort}:{})};}
  const current=key(this.value),row=this.rows.find(r=>key(r)===current);
  if(!row||row.unavailable){this.models=[];this.busy=false;this.catalogKey='';this.problem=row?.unavailable?`${row.driver} · ${row.subscription}: ${row.unavailable}`:'No signed-in Subscription is available.';return;}
  if(current!==this.catalogKey)void this.loadModels();
 }
 refresh(root=this.root):Promise<void>{if(this.accountRefresh?.root===root)return this.accountRefresh.promise;const promise=this.readAccounts(root);this.accountRefresh={root,promise};void promise.finally(()=>{if(this.accountRefresh?.promise===promise)this.accountRefresh=undefined;});return promise;}
 private async readAccounts(root:string){
  if(root!==this.root){this.root=root;this.loaded=false;this.rows=[];this.context='';this.generation++;this.chosen=null;this.actual={};this.models=[];this.busy=false;this.saving=false;}
  const generation=++this.accountGeneration;this.catalogs.clear();this.catalogKey='';this.accountBusy=true;this.accountFresh=false;
  try{const data=await this.bridge.call<{drivers:{driver:string;subscriptions?:{id:string;state:string}[];error?:BridgeError}[]}>('accounts.list');
   if(this.closed||generation!==this.accountGeneration)return;
   this.accountProblems=data.drivers.filter(d=>d.error).map(d=>d.driver+': '+describe(d.error!));
   this.rows=data.drivers.flatMap(driver=>(driver.subscriptions??[]).map(sub=>({driver:driver.driver,subscription:sub.id,...(sub.state==='signed_in'?{}:{unavailable:sub.state==='signed_out'?'logged out':sub.state==='signing_in'?'signing in':sub.state==='needs_attention'?'needs attention':sub.state})})));
   this.accountFresh=true;this.loaded=true;this.resolve();
  }catch(e){if(!this.closed&&generation===this.accountGeneration)this.accountProblems=['Subscriptions could not be read: '+(e instanceof Refusal?describe(e.detail):'The public account list is unavailable.')];}
  finally{if(generation===this.accountGeneration)this.accountBusy=false;}
 }
 private async loadModels(){
  const route={...this.value},selected=key(route),context=this.context,generation=++this.generation;
  this.catalogKey=selected;this.busy=true;this.models=[];this.problem='';this.modelProblem=false;
  let request=this.catalogs.get(selected);
  if(!request){request=this.bridge.call<{models:Model[]}>('accounts.models',{driver:route.driver,subscription:route.subscription}).then(v=>v.models);this.catalogs.set(selected,request);}
  try{const models=await request;if(this.closed||generation!==this.generation||context!==this.context||key(this.value)!==selected)return;
   if(!Array.isArray(models)||models.some(m=>typeof m.id!=='string'||typeof m.label!=='string'))throw new Error('The backend sent an invalid model catalog.');
   this.models=models;
   const current=this.value,model=current.model?models.find(m=>m.id===current.model):models.find(m=>m.isDefault),resolved={...current,...(!current.model&&model?{model:model.id}:{}),...(!current.effort&&effort(model)?{effort:effort(model)}:{})};
   if(this.chosen)this.chosen=resolved;else this.actual=resolved;
   if(!resolved.model)this.problem='No default model was reported. Choose a model with the model control (Ctrl M).';
  }catch(e){if(!this.closed&&generation===this.generation){this.modelProblem=true;this.problem=e instanceof Refusal?describe(e.detail):e instanceof Error?e.message:'Models could not be read.';}}
  finally{if(generation===this.generation)this.busy=false;}
 }
 async choose(driver:string,subscription:string){
  const choice=++this.choice,context=this.context,root=this.root;await this.refresh(root);if(this.closed||choice!==this.choice||context!==this.context||root!==this.root||!this.accountFresh)return;
  const row=this.rows.find(r=>r.driver===driver&&r.subscription===subscription);if(!row||row.unavailable)return;
  this.chosen={driver,subscription};await this.loadModels();
  if(choice===this.choice&&context===this.context&&this.available)await this.save();
 }
 nextModel(){if(this.busy||!this.models.length)return;const index=this.models.findIndex(m=>m.id===this.value.model),model=this.models[(index+1)%this.models.length];this.choice++;this.chosen={...this.value,model:model.id,effort:effort(model)};void this.save();}
 nextEffort(){if(this.busy||!this.efforts.length)return;const index=this.efforts.indexOf(this.value.effort??'');this.choice++;this.chosen={...this.value,effort:this.efforts[(index+1)%this.efforts.length]};void this.save();}
 private async save(){
  this.problem='';if(!this.chat)return;
  const route={...this.value},chat=this.chat,context=this.context,choice=this.choice;this.saving=true;
  const operation=this.commit(chat,route);this.pending=operation.then(()=>undefined,()=>undefined);
  try{await operation;if(context===this.context&&choice===this.choice){this.actual=route;this.chosen=null;}}
  catch(e){if(context===this.context&&choice===this.choice){this.chosen=null;this.generation++;this.busy=false;this.modelProblem=false;this.problem='Route not saved: '+(e instanceof Refusal?describe(e.detail):e instanceof Error?e.message:'The backend did not save the choice.');this.catalogKey=key(this.actual);const models=await this.catalogs.get(this.catalogKey)?.catch(()=>[])??[];if(context===this.context&&choice===this.choice)this.models=models;}}
  finally{if(context===this.context&&choice===this.choice)this.saving=false;}
 }
 async retryModels(){this.catalogs.delete(key(this.value));await this.loadModels();}
 preview(route:ElmaRoute){this.choice++;this.chosen={...route};this.resolve();}
 async settle(){await this.pending;if(this.saving)await this.settle();}
 close(){this.closed=true;this.accountGeneration++;this.generation++;}
}
