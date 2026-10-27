import { Bridge, Refusal, describe, type BridgeError, type Fields, type RootInfo } from './bridge';
import { AppChannel } from './app-channel';
import { Drafts } from './drafts.svelte';
import { LiveExchange,savedBlocks } from './live';
import { readPreferences, savePreferences, type Preferences } from './preferences';
import type { ElmaExchange, ElmaRoute } from '../design-system/src/sections/elma-types';
import type { ResponseBlock,ToolView,ToolDetails } from '../design-system/src/sections/elma-response';
export interface ChatInfo {chat:string;title:string|null;firstMessage?:string;createdAt?:string;exchangeCount:number;usage:{inputTokens:number;outputTokens:number}}
export interface Repository {name:string;folder:string;route:ElmaRoute}
interface ChatSnapshot {kind:string;chat:ChatInfo;exchanges:ElmaExchange[];more:boolean;settings:{route?:ElmaRoute;workingFolder?:string};marks:{ongoing:boolean};draft:unknown}
export class ElmaWindow {
 private live=new Map<string,LiveExchange>();private revision=$state(0);snapshotRevision=$state(0);openTools=$state<Record<string,boolean>>({});readonly readingPositions=new Map<string,{top:number;following:boolean}>();restoring=$state(false);
 now=$state(Date.now());private clock=setInterval(()=>{this.now=Date.now();},1000);
 root=$state<RootInfo>({root:'',name:'…',status:'working',current:false});
 connection=$state('Connecting…');problem=$state('');info=$state<ChatInfo|null>(null);exchanges=$state<ElmaExchange[]>([]);
 selected=$state<string|null>(null);more=$state(false);pageBusy=$state(false);pageProblem=$state('');historyOpen=$state(false);settings=$state<ChatSnapshot['settings']>({});ongoing=$state(false);
 repositories=$state<Repository[]>([]);folder=$state('');defaultRoute=$state<ElmaRoute>({});routes=$state<{driver:string;subscription:string;unavailable?:string}[]>([]);
 accountProblems=$state<string[]>([]);
 preferences=$state<Preferences>(readPreferences(''));bridge:Bridge;app=new AppChannel();drafts:Drafts;
 private pageTicket=0;private generation=0;private chatSub?:{close:()=>void;retry:()=>void};private bootstrapGeneration=0;private closed=false;private cancelOpening?:()=>void;
 constructor(){this.bridge=new Bridge({build:__ARBOL_BUILD__,onstate:s=>this.connection=s,beforeReload:()=>this.drafts.beforeReload(),onhello:(root)=>{this.drafts?.rootChanged(root.root);this.root=root;this.preferences=readPreferences(root.root);void this.bootstrap();void this.loadAccounts();}});
  this.drafts=new Drafts(this.bridge);
  this.bridge.subscribe('root',{},event=>{if(event.root)this.root=event.root as unknown as RootInfo;},e=>this.failure(e));
 }
 get exchange(){if(this.restoring)return undefined;return this.exchanges.find(e=>e.exchange===this.selected)??this.exchanges.at(-1);}
 get title(){return this.info?.title||Array.from((this.info?.firstMessage??'').split('\n')[0]).slice(0,80).join('')||'New Chat';}
 get placeholder(){return !this.info?.title;}
 get route(){return this.settings.route??this.exchange?.route??this.defaultRoute;}
 get repository(){return this.repositories.find(r=>r.folder===(this.settings.workingFolder??this.exchange?.workingFolder??this.folder))?.name??(this.settings.workingFolder??this.exchange?.workingFolder??this.folder).split('/').filter(Boolean).at(-1)??'—';}
 get turn(){return this.info?this.info.exchangeCount-this.exchanges.filter(e=>e.number>(this.exchange?.number??Infinity)).length:0;}
 get working(){this.revision;return this.exchanges.some(e=>['open','accepting','running','stopping','ending','unsaved','gone'].includes(e.state));}
 savePreferences(){savePreferences(this.root.root,this.preferences);}
 private failure(error?:BridgeError){if(error)this.problem=describe(error);}
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
   this.selectDraft();this.problem='';
  }catch(e){this.problem=e instanceof Refusal?describe(e.detail):'The chat could not be read.';}
 }
 async openChat(chat:string):Promise<boolean>{
  this.cancelOpening?.();const generation=++this.generation;this.chatSub?.close();
  return new Promise<boolean>((resolve,reject)=>{
   let settled=false;this.cancelOpening=()=>{if(!settled){settled=true;resolve(false);}};
   this.chatSub=this.bridge.subscribe('chat',{chat},event=>{
    if(this.closed||generation!==this.generation)return;
    if(event.kind==='snapshot'){
     const snapshot=event as unknown as ChatSnapshot;this.pageTicket++;this.pageBusy=false;this.pageProblem='';
     if(!snapshot.chat||!snapshot.chat.createdAt&&snapshot.chat.exchangeCount===0){if(!settled){settled=true;resolve(false);}return;}
     const desired=this.info?.chat===snapshot.chat.chat?this.selected:null;for(const [exchange,live]of this.live)for(const block of live.blocks)if(block.kind==='tool'&&block.tool.position!==undefined&&this.openTools[block.tool.id])this.openTools[exchange+':'+block.tool.position]=true;
     this.restoring=false;this.live.clear();this.revision++;this.snapshotRevision++;
     this.info=snapshot.chat;this.exchanges=snapshot.exchanges;this.more=snapshot.more;this.settings=snapshot.settings;this.ongoing=snapshot.marks.ongoing;this.selected=this.exchanges.some(e=>e.exchange===this.selected)?this.selected:this.exchanges.at(-1)?.exchange??null;
     this.folder=this.settings.workingFolder??this.exchange?.workingFolder??this.folder;this.selectDraft();
     this.preferences.lastChat=chat;this.preferences.repositoryChats[this.repository]=chat;this.preferences.recentChats=[chat,...this.preferences.recentChats.filter(v=>v!==chat)].slice(0,100);this.savePreferences();
     if(desired&&!this.exchanges.some(e=>e.exchange===desired)&&this.more){this.restoring=true;void this.restoreSelection(desired,generation,this.snapshotRevision);}
     if(!settled){settled=true;resolve(true);}
    }else if(event.kind==='exchange'){const status=event.exchange as Fields;const row=this.exchanges.find(e=>e.exchange===status.exchange);if(row){this.projection(row).status(status);this.revision++;}}
    else if(event.kind==='lines'){const row=this.exchanges.find(e=>e.exchange===event.exchange);if(row&&Array.isArray(event.lines)){this.projection(row).apply(event.lines);this.revision++;}}
    else if(event.kind==='saved'){const row=event.exchange as unknown as ElmaExchange;const old=this.exchanges.find(e=>e.exchange===row.exchange);if(old){this.projection(old).reconcile(row);this.exchanges=this.exchanges.map(e=>e.exchange===row.exchange?row:e);this.revision++;}}
    else if(event.kind==='note'){const note=event.note as Fields;const row=this.exchanges.find(e=>e.exchange===note.exchange);if(row){row.note=note as unknown as ElmaExchange['note'];this.revision++;}}
    else if(event.kind==='title'&&this.info)this.info.title=event.title as string|null;
    else if(event.kind==='settings')this.settings=event.settings as ChatSnapshot['settings'];
    else if(event.kind==='marks')this.ongoing=!!(event.marks as {ongoing:boolean}).ongoing;
   },error=>{this.failure(error);if(!settled){settled=true;reject(new Refusal(error??{code:'ended',message:'The chat subscription ended.'}));}});
  });
 }
 private projection(row:ElmaExchange){let live=this.live.get(row.exchange);if(!live){live=new LiveExchange(row);this.live.set(row.exchange,live);}return live;}
 get currentLive(){this.revision;return this.exchange?this.live.get(this.exchange.exchange):undefined;}
 get response():ResponseBlock[]{const copy=(blocks:ResponseBlock[]):ResponseBlock[]=>blocks.map(b=>b.kind==='tool'?{...b,tool:{...b.tool,parallel:b.tool.parallel?{...b.tool.parallel}:undefined,children:b.tool.children?copy(b.tool.children):undefined}}:{...b});return this.currentLive?.blocks.length?copy(this.currentLive.blocks):this.exchange?savedBlocks(this.exchange):[];}
 get questions(){return this.currentLive?.questions.map(q=>({...q}))??[];}
 get usage(){this.revision;const total={inputTokens:this.info?.usage.inputTokens??0,outputTokens:this.info?.usage.outputTokens??0};for(const live of this.live.values()){const delta=live.usageDelta;total.inputTokens+=delta.inputTokens;total.outputTokens+=delta.outputTokens;}return{inputTokens:Math.max(0,total.inputTokens),outputTokens:Math.max(0,total.outputTokens)};}
 get complete(){return !!this.exchange&&['completed','failed','cancelled','interrupted'].includes(this.exchange.state);}
 get startedAt(){return this.currentLive?.startedAt??this.exchange?.runs.map(run=>run.started?.at).filter((value):value is string=>typeof value==='string'&&Number.isFinite(Date.parse(value))).sort((a,b)=>Date.parse(a)-Date.parse(b))[0];}
 get statusLabel(){return this.exchange?(this.currentLive??new LiveExchange(this.exchange)).label(this.exchange,this.now):'';}
 get error(){return this.exchange?.error??this.currentLive?.end?.error;}
 get responseNotes(){const state=this.currentLive?.state??this.exchange?.state;return [...(state==='unsaved'?['Not yet saved']:[]),...(state==='gone'||this.exchange?.state==='interrupted'?[this.exchange?.note?.kind==='ended_stuck'?'Ended because it was stuck. What had arrived is kept.':"Interrupted: the agent's process ended before the answer was finished. What had arrived is kept."]:[])];}
 async loadTool(tool:ToolView):Promise<ToolDetails>{const exchange=this.exchange?.exchange;if(!exchange||tool.position===undefined)throw new Error('not_found: The tool call is unavailable.');try{return await this.bridge.call<ToolDetails>('toolCall.get',{exchange,position:tool.position});}catch(e){throw new Error(e instanceof Refusal?describe(e.detail):'The tool details could not be read.');}}
 async openLink(url:string){try{return await this.app.call('app.openLink',{url});}catch(e){throw new Error(e instanceof Refusal?describe(e.detail):'The link could not be opened.');}}
 get prompt(){const item=this.exchange?.items.find(item=>item.kind==='message'&&item.role==='user');return item?.kind==='message'?item.text:'';}
 get history(){return this.exchanges.map((exchange,i)=>{const item=exchange.items.find(item=>item.kind==='message'&&item.role==='user');return{id:exchange.exchange,number:(this.info?.exchangeCount??0)-(this.exchanges.length-1-i),message:item?.kind==='message'?item.text:''};});}
 selectExchange(id:string){if(this.exchanges.some(e=>e.exchange===id)){this.selected=id;this.historyOpen=false;}}
 async older(){if(this.pageBusy)return;const chosen=this.exchange?.exchange;if(!chosen)return;let index=this.exchanges.findIndex(e=>e.exchange===chosen);if(index===0&&this.more){await this.page();if(this.selected!==chosen)return;index=this.exchanges.findIndex(e=>e.exchange===chosen);}if(index>0)this.selected=this.exchanges[index-1].exchange;}
 newer(){if(this.pageBusy)return;const index=this.exchanges.findIndex(e=>e.exchange===this.exchange?.exchange);if(index>=0&&index<this.exchanges.length-1)this.selected=this.exchanges[index+1].exchange;}
 private async restoreSelection(id:string,generation:number,snapshot:number){while(this.more&&!this.exchanges.some(e=>e.exchange===id)){await this.page();if(this.closed||generation!==this.generation||snapshot!==this.snapshotRevision)return;if(this.pageProblem||this.pageBusy)break;}if(generation===this.generation&&snapshot===this.snapshotRevision){this.restoring=false;this.selected=this.exchanges.some(e=>e.exchange===id)?id:this.exchanges.at(-1)?.exchange??null;}}
 async page(){
  if(this.pageBusy||!this.more||!this.info||!this.exchanges.length)return;
  const ticket=++this.pageTicket,generation=this.generation,chat=this.info.chat,beforeNumber=Math.min(...this.exchanges.map(e=>e.number));this.pageBusy=true;this.pageProblem='';
  try{const result=await this.bridge.call<{exchanges:ElmaExchange[];more:boolean}>('chat.exchanges',{chat,beforeNumber,limit:12});
   if(this.closed||generation!==this.generation||ticket!==this.pageTicket)return;
   const rows=new Map(this.exchanges.map(e=>[e.exchange,e]));for(const exchange of result.exchanges)rows.set(exchange.exchange,exchange);this.exchanges=[...rows.values()].sort((a,b)=>a.number-b.number);this.more=result.more;
  }catch(e){if(ticket===this.pageTicket&&e instanceof Refusal)this.pageProblem=describe(e.detail);}
  finally{if(ticket===this.pageTicket)this.pageBusy=false;}
 }
 private clear(){this.restoring=false;this.live.clear();this.revision++;this.pageTicket++;this.pageBusy=false;this.pageProblem='';this.historyOpen=false;this.cancelOpening?.();this.chatSub?.close();this.chatSub=undefined;this.generation++;this.info=null;this.exchanges=[];this.selected=null;this.settings={};this.ongoing=false;}
 private selectDraft(){if(this.root.root&&(this.info||this.folder))this.drafts.select(this.root.root,this.info?{chat:this.info.chat}:{folder:this.folder});}
 close(){clearInterval(this.clock);this.cancelOpening?.();this.closed=true;this.bootstrapGeneration++;this.chatSub?.close();this.drafts.close();this.bridge.close();this.app.close();}
}
