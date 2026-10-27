import { Bridge, Refusal, type BridgeError, type Fields, type RootInfo } from './bridge';
import { AppChannel } from './app-channel';
import { readPreferences, savePreferences, type Preferences } from './preferences';
import type { ElmaExchange, ElmaRoute } from '../design-system/src/sections/elma-types';
export interface ChatInfo {chat:string;title:string|null;firstMessage?:string;createdAt?:string;exchangeCount:number;usage:{inputTokens:number;outputTokens:number}}
export interface Repository {name:string;folder:string;route:ElmaRoute}
interface ChatSnapshot {kind:string;chat:ChatInfo;exchanges:ElmaExchange[];more:boolean;settings:{route?:ElmaRoute;workingFolder?:string};marks:{ongoing:boolean};draft:unknown}
export class ElmaWindow {
 root=$state<RootInfo>({root:'',name:'…',status:'working',current:false});
 connection=$state('Connecting…');problem=$state('');info=$state<ChatInfo|null>(null);exchanges=$state<ElmaExchange[]>([]);
 selected=$state<string|null>(null);more=$state(false);settings=$state<ChatSnapshot['settings']>({});ongoing=$state(false);
 repositories=$state<Repository[]>([]);folder=$state('');defaultRoute=$state<ElmaRoute>({});routes=$state<{driver:string;subscription:string;unavailable?:string}[]>([]);
 accountProblems=$state<string[]>([]);
 preferences=$state<Preferences>(readPreferences(''));bridge:Bridge;app=new AppChannel();
 private generation=0;private chatSub?:{close:()=>void;retry:()=>void};private bootstrapGeneration=0;private closed=false;private cancelOpening?:()=>void;
 constructor(){this.bridge=new Bridge({build:__ARBOL_BUILD__,onstate:s=>this.connection=s,onhello:(root)=>{this.root=root;this.preferences=readPreferences(root.root);void this.bootstrap();void this.loadAccounts();}});
  this.bridge.subscribe('root',{},event=>{if(event.root)this.root=event.root as unknown as RootInfo;},e=>this.failure(e));
 }
 get exchange(){return this.exchanges.find(e=>e.exchange===this.selected)??this.exchanges.at(-1);}
 get title(){return this.info?.title||Array.from((this.info?.firstMessage??'').split('\n')[0]).slice(0,80).join('')||'New Chat';}
 get placeholder(){return !this.info?.title;}
 get route(){return this.settings.route??this.exchange?.route??this.defaultRoute;}
 get repository(){return this.repositories.find(r=>r.folder===(this.settings.workingFolder??this.exchange?.workingFolder??this.folder))?.name??(this.settings.workingFolder??this.exchange?.workingFolder??this.folder).split('/').filter(Boolean).at(-1)??'—';}
 get turn(){return this.info?this.info.exchangeCount-this.exchanges.filter(e=>e.number>(this.exchange?.number??Infinity)).length:0;}
 get working(){return this.exchanges.some(e=>['open','accepting','running','stopping','ending','unsaved','gone'].includes(e.state));}
 savePreferences(){savePreferences(this.root.root,this.preferences);}
 private failure(error?:BridgeError){if(error)this.problem=(error.code==='unknown_method'?'This needs a newer Build. ':error.code+': ')+error.message;}
 private async loadAccounts(){
  try{const data=await this.bridge.call<{drivers:{driver:string;subscriptions?:{id:string;state:string}[];error?:BridgeError}[]}>('accounts.list');
   if(this.closed)return;
   this.accountProblems=data.drivers.filter(d=>d.error).map(d=>d.driver+': '+d.error!.code+': '+d.error!.message);
   this.routes=data.drivers.flatMap(driver=>(driver.subscriptions??[]).map(sub=>({driver:driver.driver,subscription:sub.id,...(sub.state==='signed_in'?{}:{unavailable:sub.state==='signed_out'?'logged out':sub.state==='signing_in'?'signing in':sub.state==='needs_attention'?'needs attention':sub.state})})));
  }catch(e){if(e instanceof Refusal&&e.detail.code!=='disconnected')this.failure(e.detail);}
 }
 private async bootstrap(){
  const generation=++this.bootstrapGeneration;
  try{
   const request=await this.app.call('app.takeOpen');const workspace=await this.bridge.call<{repositories:Repository[];route:ElmaRoute}>('workspace.get');
   if(this.closed||generation!==this.bootstrapGeneration)return;
   this.repositories=[...workspace.repositories];const recent=this.preferences.recentRepositories;
   this.repositories=[...this.repositories.slice(0,1),...this.repositories.slice(1).sort((a,b)=>{const ai=recent.indexOf(a.name),bi=recent.indexOf(b.name);return(ai<0?Infinity:ai)-(bi<0?Infinity:bi);})];
   this.folder=this.folder||this.repositories[0]?.folder||'';this.defaultRoute=this.repositories.find(r=>r.folder===this.folder)?.route??workspace.route;
   // A live view is reread by its retained subscription on hello, not replaced by convenience state.
   if(this.info&&!request.chat)return;
   const first=this.repositories[0];const candidates=[request.chat,this.preferences.lastChat,first&&this.preferences.repositoryChats[first.name]].filter((v):v is string=>typeof v==='string');
   let opened=false;for(const chat of [...new Set(candidates)]){if(generation!==this.bootstrapGeneration)return;if(await this.openChat(chat)){opened=true;break;}}if(generation!==this.bootstrapGeneration)return;
   if(!opened){this.clear();if(typeof request.folder==='string')this.folder=request.folder;}
   this.problem='';
  }catch(e){this.problem=e instanceof Refusal?e.detail.code+': '+e.message:'The chat could not be read.';}
 }
 async openChat(chat:string):Promise<boolean>{
  this.cancelOpening?.();const generation=++this.generation;this.chatSub?.close();
  return new Promise<boolean>((resolve,reject)=>{
   let settled=false;this.cancelOpening=()=>{if(!settled){settled=true;resolve(false);}};
   this.chatSub=this.bridge.subscribe('chat',{chat},event=>{
    if(this.closed||generation!==this.generation)return;
    if(event.kind==='snapshot'){
     const snapshot=event as unknown as ChatSnapshot;
     if(!snapshot.chat||!snapshot.chat.createdAt&&snapshot.chat.exchangeCount===0){if(!settled){settled=true;resolve(false);}return;}
     this.info=snapshot.chat;this.exchanges=snapshot.exchanges;this.more=snapshot.more;this.settings=snapshot.settings;this.ongoing=snapshot.marks.ongoing;this.selected=this.exchanges.some(e=>e.exchange===this.selected)?this.selected:this.exchanges.at(-1)?.exchange??null;
     this.folder=this.settings.workingFolder??this.exchange?.workingFolder??this.folder;
     this.preferences.lastChat=chat;this.preferences.repositoryChats[this.repository]=chat;this.preferences.recentChats=[chat,...this.preferences.recentChats.filter(v=>v!==chat)].slice(0,100);this.savePreferences();
     if(!settled){settled=true;resolve(true);}
    }else if(event.kind==='title'&&this.info)this.info.title=event.title as string|null;
    else if(event.kind==='settings')this.settings=event.settings as ChatSnapshot['settings'];
    else if(event.kind==='marks')this.ongoing=!!(event.marks as {ongoing:boolean}).ongoing;
   },error=>{this.failure(error);if(!settled){settled=true;reject(new Refusal(error??{code:'ended',message:'The chat subscription ended.'}));}});
  });
 }
 private clear(){this.cancelOpening?.();this.chatSub?.close();this.chatSub=undefined;this.generation++;this.info=null;this.exchanges=[];this.selected=null;this.settings={};this.ongoing=false;}
 close(){this.cancelOpening?.();this.closed=true;this.bootstrapGeneration++;this.chatSub?.close();this.bridge.close();this.app.close();}
}
