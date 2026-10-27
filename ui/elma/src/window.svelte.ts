import { Bridge, Refusal, describe, type BridgeError, type Fields, type RootInfo } from './bridge';
import { AppChannel } from './app-channel';
import { Drafts,type DraftEditor } from './drafts.svelte';
import { Sending,type SendIntent,type SendOperation,type Accepted } from './sending.svelte';
import type { Revision } from './wire-json';
import { Routing } from './routes.svelte';
import { LiveExchange,savedBlocks } from './live';
import {signInCommand} from '../design-system/src/sections/elma-response';
import { readPreferences, savePreferences, type Preferences } from './preferences';
import type { ElmaExchange, ElmaRoute } from '../design-system/src/sections/elma-types';
import type { ResponseBlock,ToolView,ToolDetails,QuestionView,Answer } from '../design-system/src/sections/elma-response';
export interface ChatInfo {chat:string;title:string|null;firstMessage?:string;createdAt?:string;exchangeCount:number;usage:{inputTokens:number;outputTokens:number}}
export interface Repository {name:string;folder:string;route:ElmaRoute}
interface PendingMessage {intent:SendIntent;editor:DraftEditor;generation:number;exchange:string}
interface ChatSnapshot {kind:string;chat:ChatInfo;exchanges:ElmaExchange[];more:boolean;settings:{route?:ElmaRoute;workingFolder?:string};marks:{ongoing:boolean};draft:unknown}
export class ElmaWindow {
 private live=new Map<string,LiveExchange>();private revision=$state(0);snapshotRevision=$state(0);openTools=$state<Record<string,boolean>>({});readonly readingPositions=new Map<string,{top:number;following:boolean}>();restoring=$state(false);
 now=$state(Date.now());private clock=setInterval(()=>{this.now=Date.now();},1000);
 root=$state<RootInfo>({root:'',name:'…',status:'working',current:false});
 connection=$state('Connecting…');problem=$state('');info=$state<ChatInfo|null>(null);exchanges=$state<ElmaExchange[]>([]);
 selected=$state<string|null>(null);more=$state(false);pageBusy=$state(false);pageProblem=$state('');historyOpen=$state(false);settings=$state<ChatSnapshot['settings']>({});ongoing=$state(false);
 repositories=$state<Repository[]>([]);folder=$state('');defaultRoute=$state<ElmaRoute>({});private workspaceRoute:ElmaRoute={};routing:Routing;private settingsQueues=new Map<string,Promise<unknown>>();
 preferences=$state<Preferences>(readPreferences(''));bridge:Bridge;app=new AppChannel();drafts:Drafts;
 composerOpen=$state(false);sendWait=$state('');stopping=$state<string[]>([]);sending:Sending;stopConfirmation=$state<PendingMessage|null>(null);private stopQueue?:PendingMessage&{finish:()=>void};private previousSelection=new Map<string,string|null>();private replacements=new Map<string,ElmaExchange>();private stopCalls=new Map<string,Promise<void>>();private answerSerial=0;private answerStates=$state<Record<string,{token:number;pending:boolean;problem:string;after:number}>>({});
 repositoryNotice=$state('');repositoryChange=$state<{root:string;chat:string;folder:string;generation:number}|null>(null);
 private pageTicket=0;private generation=0;private settingsObservation=0;private chatSub?:{close:()=>void;retry:()=>void};private bootstrapGeneration=0;private closed=false;private cancelOpening?:()=>void;
 constructor(){this.bridge=new Bridge({build:__ARBOL_BUILD__,onstate:s=>{this.connection=s;if(s==='Reconnecting…'||s==='Connecting…'||s.includes('Bridge version'))this.sending?.offline();},beforeReload:()=>this.drafts.beforeReload(),onhello:(root)=>{if(this.root.root&&this.root.root!==root.root){this.clear();this.folder='';this.stopping=[];this.stopCalls.clear();}this.drafts?.rootChanged(root.root);this.root=root;this.sending?.hello(root.root);this.preferences=readPreferences(root.root);void this.bootstrap();void this.loadAccounts();const rootId=root.root;setTimeout(()=>{if(this.root.root===rootId)for(const id of this.stopping)void this.stopExchange(id,true);},0);}});
  this.drafts=new Drafts(this.bridge,(root,editor)=>this.sending?.marked(root,editor,this.drafts.current===editor));this.sending=new Sending(this.bridge,(root,scope)=>this.drafts.owner(root,scope),done=>this.drafts.holdSend(done),{provisional:op=>this.provisional(op),accepted:(op,result)=>this.accepted(op,result),refused:(op,error)=>this.refused(op,error)});this.routing=new Routing(this.bridge,(chat,route)=>this.saveSettings(chat,{route}));
  this.bridge.subscribe('root',{},event=>{if(event.root)this.root=event.root as unknown as RootInfo;},e=>this.failure(e));
  this.bridge.subscribe('attention',{},()=>{});
 }
 get exchange(){if(this.restoring)return undefined;return this.exchanges.find(e=>e.exchange===this.selected)??this.exchanges.at(-1);}
 get title(){return this.info?.title||Array.from((this.info?.firstMessage??'').split('\n')[0]).slice(0,80).join('')||'New Chat';}
 get placeholder(){return !this.info?.title;}
 get route(){return this.routing.value;}
 get routes(){return this.routing.rows;}
 get accountProblems(){return this.routing.accountProblems;}
 get repository(){return this.repositories.find(r=>r.folder===(this.settings.workingFolder??this.exchange?.workingFolder??this.folder))?.name??(this.settings.workingFolder??this.exchange?.workingFolder??this.folder).split('/').filter(Boolean).at(-1)??'—';}
 get turn(){return this.info?this.info.exchangeCount-this.exchanges.filter(e=>e.number>(this.exchange?.number??Infinity)).length:0;}
 get working(){this.revision;return this.exchanges.some(e=>['open','accepting','running','stopping','ending','unsaved','gone'].includes(e.state));}
 savePreferences(){savePreferences(this.root.root,this.preferences);}
 private failure(error?:BridgeError){if(error)this.problem=describe(error);}
 private async loadAccounts(){await this.routing.refresh(this.root.root);}
 private selectRoute(){if(this.root.root&&(this.info||this.folder))this.routing.select(this.root.root+':'+(this.info?.chat??this.folder),this.info?.chat,this.info?(this.settings.route??this.exchange?.route):undefined,[this.repositories.find(r=>r.folder===this.folder)?.route??{},this.workspaceRoute]);}
 private async saveSettings(chat:string,change:{route?:ElmaRoute;workingFolder?:string},valid?:()=>boolean){
  const root=this.root.root,key=root+':'+chat,previous=this.settingsQueues.get(key)??Promise.resolve();
  let observed=-1;
  const operation=previous.catch(()=>undefined).then(()=>{if(root!==this.root.root)throw new Refusal({code:'disconnected',message:'The Root changed before its settings could be saved.'});if(valid&&!valid())throw new Refusal({code:'changed',message:'The chat changed or is working. Choose the repository again after its turn finishes.'});observed=this.settingsObservation;return this.bridge.call('chat.settings',{chat,...change});});this.settingsQueues.set(key,operation);
  try{await operation;if(this.root.root===root&&this.info?.chat===chat&&observed===this.settingsObservation)this.settings={...this.settings,...change};}
  finally{if(this.settingsQueues.get(key)===operation)this.settingsQueues.delete(key);}
 }
 private async bootstrap(){
  const generation=++this.bootstrapGeneration;
  try{
   const request=await this.app.call('app.takeOpen');const workspace=await this.bridge.call<{repositories:Repository[];route:ElmaRoute}>('workspace.get');
   if(this.closed||generation!==this.bootstrapGeneration)return;
   this.workspaceRoute=workspace.route;this.repositories=[...workspace.repositories];const recent=this.preferences.recentRepositories;
   this.repositories=[...this.repositories.slice(0,1),...this.repositories.slice(1).sort((a,b)=>{const ai=recent.indexOf(a.name),bi=recent.indexOf(b.name);return(ai<0?Infinity:ai)-(bi<0?Infinity:bi);})];
   this.folder=this.folder||this.repositories[0]?.folder||'';this.defaultRoute=this.repositories.find(r=>r.folder===this.folder)?.route??workspace.route;
   // A live view is reread by its retained subscription on hello, not replaced by convenience state.
   if(this.info&&!request.chat){this.selectRoute();return;}
   const first=this.repositories[0];const candidates=[request.chat,this.preferences.lastChat,first&&this.preferences.repositoryChats[first.name]].filter((v):v is string=>typeof v==='string');
   let opened=false;for(const chat of [...new Set(candidates)]){if(generation!==this.bootstrapGeneration)return;if(await this.openChat(chat)){opened=true;break;}}if(generation!==this.bootstrapGeneration)return;
   if(!opened){this.clear();if(typeof request.folder==='string')this.folder=request.folder;}
   this.selectDraft();this.selectRoute();this.problem='';
  }catch(e){this.problem=e instanceof Refusal?describe(e.detail):'The chat could not be read.';}
 }
 async openChat(chat:string,canonicalDraft=false):Promise<boolean>{
  this.cancelOpening?.();const generation=++this.generation;this.chatSub?.close();
  return new Promise<boolean>((resolve,reject)=>{
   let settled=false;this.cancelOpening=()=>{if(!settled){settled=true;resolve(false);}};
   this.chatSub=this.bridge.subscribe('chat',{chat},event=>{
    if(this.closed||generation!==this.generation)return;
    if(event.kind==='snapshot'){
     let snapshot=event as unknown as ChatSnapshot;const pending=this.sending.forChat(chat);if(pending?.outcome==='pending'&&snapshot.chat.createdAt&&!snapshot.exchanges.some(row=>row.exchange===pending.intent.exchange)){const row=this.provisionalRow(pending,Math.max(pending.intent.number,snapshot.chat.exchangeCount+1));snapshot={...snapshot,chat:{...snapshot.chat,exchangeCount:row.number},exchanges:[...snapshot.exchanges,row]};}this.pageTicket++;this.pageBusy=false;this.pageProblem='';
     if(!snapshot.chat||!snapshot.chat.createdAt&&snapshot.chat.exchangeCount===0){if(!settled){settled=true;resolve(false);}return;}
     const desired=this.info?.chat===snapshot.chat.chat?this.selected:null;for(const [exchange,live]of this.live)for(const block of live.blocks)if(block.kind==='tool'&&block.tool.position!==undefined&&this.openTools[block.tool.id])this.openTools[exchange+':'+block.tool.position]=true;
     this.restoring=false;this.live.clear();this.revision++;this.snapshotRevision++;
     this.info=snapshot.chat;this.exchanges=snapshot.exchanges;this.more=snapshot.more;this.settings=snapshot.settings;this.settingsObservation++;this.ongoing=snapshot.marks.ongoing;this.selected=this.exchanges.some(e=>e.exchange===this.selected)?this.selected:this.exchanges.at(-1)?.exchange??null;
     this.folder=this.settings.workingFolder??this.exchange?.workingFolder??this.folder;this.selectDraft(canonicalDraft);this.selectRoute();this.afterChatState();
     this.preferences.lastChat=chat;this.preferences.repositoryChats[this.repository]=chat;this.preferences.recentChats=[chat,...this.preferences.recentChats.filter(v=>v!==chat)].slice(0,100);this.savePreferences();
     if(desired&&!this.exchanges.some(e=>e.exchange===desired)&&this.more){this.restoring=true;void this.restoreSelection(desired,generation,this.snapshotRevision);}
     if(!settled){settled=true;resolve(true);}
    }else if(event.kind==='exchange'){const status=event.exchange as Fields;const row=this.exchanges.find(e=>e.exchange===status.exchange);if(row){this.projection(row).status(status);this.revision++;}}
    else if(event.kind==='lines'){const row=this.exchanges.find(e=>e.exchange===event.exchange);if(row&&Array.isArray(event.lines)){this.projection(row).apply(event.lines);this.settleAnswerReceipts(row);this.revision++;}}
    else if(event.kind==='saved'){const row=event.exchange as unknown as ElmaExchange;const old=this.exchanges.find(e=>e.exchange===row.exchange);if(old){this.projection(old).reconcile(row);this.exchanges=this.exchanges.map(e=>e.exchange===row.exchange?row:e);this.revision++;this.afterChatState();}}
    else if(event.kind==='note'){const note=event.note as Fields;const row=this.exchanges.find(e=>e.exchange===note.exchange);if(row){row.note=note as unknown as ElmaExchange['note'];this.revision++;}}
    else if(event.kind==='title'&&this.info)this.info.title=event.title as string|null;
    else if(event.kind==='settings'){this.settings=event.settings as ChatSnapshot['settings'];this.settingsObservation++;this.selectRoute();}
    else if(event.kind==='marks')this.ongoing=!!(event.marks as {ongoing:boolean}).ongoing;
   },error=>{this.failure(error);if(!settled){settled=true;reject(new Refusal(error??{code:'ended',message:'The chat subscription ended.'}));}});
  });
 }
 private projection(row:ElmaExchange){let live=this.live.get(row.exchange);if(!live){live=new LiveExchange(row);this.live.set(row.exchange,live);}return live;}
 get currentLive(){this.revision;return this.exchange?this.live.get(this.exchange.exchange):undefined;}
 get response():ResponseBlock[]{const copy=(blocks:ResponseBlock[]):ResponseBlock[]=>blocks.map(b=>b.kind==='tool'?{...b,tool:{...b.tool,parallel:b.tool.parallel?{...b.tool.parallel}:undefined,children:b.tool.children?copy(b.tool.children):undefined}}:{...b});return this.currentLive?.blocks.length?copy(this.currentLive.blocks):this.exchange?savedBlocks(this.exchange):[];}
 get questions(){const row=this.exchange;if(!row)return[];const saved:QuestionView[]=row.items.flatMap(item=>item.kind==='tool'&&item.ask!==undefined?[{id:'saved:'+item.position,ask:item.ask,answer:item.answer,open:false,recorded:true}]:[]);return(!this.complete&&this.currentLive?.questions.length?this.currentLive.questions:saved).map(q=>{const state=this.answerStates[this.answerKey(row.exchange,q.id)];return{...q,pending:state?.pending??false,problem:q.problem||state?.problem};});}
 get usage(){this.revision;const total={inputTokens:this.info?.usage.inputTokens??0,outputTokens:this.info?.usage.outputTokens??0};for(const live of this.live.values()){const delta=live.usageDelta;total.inputTokens+=delta.inputTokens;total.outputTokens+=delta.outputTokens;}return{inputTokens:Math.max(0,total.inputTokens),outputTokens:Math.max(0,total.outputTokens)};}
 get complete(){return !!this.exchange&&['completed','failed','cancelled','interrupted'].includes(this.exchange.state);}
 get startedAt(){return this.currentLive?.startedAt??this.exchange?.runs.map(run=>run.started?.at).filter((value):value is string=>typeof value==='string'&&Number.isFinite(Date.parse(value))).sort((a,b)=>Date.parse(a)-Date.parse(b))[0];}
 get statusLabel(){if(this.exchange&&this.stopping.includes(this.exchange.exchange)&&!this.complete)return 'Stopping…';return this.exchange?(this.currentLive??new LiveExchange(this.exchange)).label(this.exchange,this.now):'';}
 get endedAt(){return this.exchange?.endedAt??this.currentLive?.end?.at;}
 get failureActions(){return this.exchange?.state==='failed'&&this.exchange.exchange===this.exchanges.at(-1)?.exchange&&!this.moreAfterSelected;}
 private get moreAfterSelected(){return !!this.info&&this.exchange?.number!==this.info.exchangeCount;}
 get failureBusy(){return this.composerBusy||!!this.sendWait||this.working||!this.routing.available||this.routing.busy;}
 get signIn(){return signInCommand(this.exchange?.route.driver,this.exchange?.route.subscription);}
 get error(){return this.exchange?.error??this.currentLive?.end?.error;}
 get responseNotes(){const state=this.currentLive?.state??this.exchange?.state;return [...(this.complete&&this.exchange?.state==='cancelled'?['⏹ Stopped']:[]),...(state==='unsaved'?['Not yet saved']:[]),...(state==='gone'||this.exchange?.state==='interrupted'?[this.exchange?.note?.kind==='ended_stuck'?'Ended because it was stuck. What had arrived is kept.':"Interrupted: the agent's process ended before the answer was finished. What had arrived is kept."]:[])];}
 async loadTool(tool:ToolView):Promise<ToolDetails>{const exchange=this.exchange?.exchange;if(!exchange||tool.position===undefined)throw new Error('not_found: The tool call is unavailable.');try{return await this.bridge.call<ToolDetails>('toolCall.get',{exchange,position:tool.position});}catch(e){throw new Error(e instanceof Refusal?describe(e.detail):'The tool details could not be read.');}}
 async openLink(url:string){try{return await this.app.call('app.openLink',{url});}catch(e){throw new Error(e instanceof Refusal?describe(e.detail):'The link could not be opened.');}}
 get prompt(){const item=this.exchange?.items.find(item=>item.kind==='message'&&item.role==='user');return item?.kind==='message'?item.text:'';}
 private answerKey(exchange:string,id:string){return JSON.stringify([this.root.root,exchange,id]);}
 private settleAnswerReceipts(row:ElmaExchange){for(const q of this.live.get(row.exchange)?.questions??[]){const key=this.answerKey(row.exchange,q.id),state=this.answerStates[key];if(state&&(!q.open||Math.max(q.answerPosition??0,q.refusalPosition??0)>state.after))delete this.answerStates[key];}}
 async answer(question:QuestionView,answer:Answer){const row=this.exchange;if(!row||!question.open||!question.askId||this.complete)return;const key=this.answerKey(row.exchange,question.id);if(this.answerStates[key]?.pending)return;const token=++this.answerSerial;this.answerStates[key]={token,pending:true,problem:'',after:Math.max(question.answerPosition??0,question.refusalPosition??0)};const original=this.live.get(row.exchange)?.questions.find(q=>q.id===question.id);if(original)original.problem=undefined;
  try{await this.bridge.call('exchange.answer',{exchange:row.exchange,askId:question.askId,answer});}
  catch(e){if(this.answerStates[key]?.token===token)this.answerStates[key]={...this.answerStates[key],pending:false,problem:e instanceof Refusal?describe(e.detail):'The answer could not be sent.'};}
 }
 get composerBusy(){return !!this.drafts.current?.pendingSend||!!(this.info&&this.sending.forChat(this.info.chat));}
 get composerStatus(){return(this.info?this.sending.forChat(this.info.chat)?.status:undefined)||this.sendWait||this.drafts.current?.pastes.status||this.drafts.current?.status||'';}
 async recoverFailure(continueFrom=false){
  const row=this.exchange,editor=this.drafts.current,chat=this.info?.chat,root=this.root.root,generation=this.generation;
  if(!row||!chat||!editor?.ready||!this.failureActions||this.failureBusy)return;
  editor.pendingSend=true;editor.sendProblem='';this.sendWait='Preparing failure recovery…';let transferred=false,finish!:()=>void;const preparing=new Promise<void>(resolve=>finish=resolve);this.drafts.holdSend(preparing);
  try{await this.routing.settle();if(this.routing.problem.startsWith('Route not saved:'))throw new Error(this.routing.problem);if(this.routing.busy||!this.routing.available)throw new Error('Choose a signed-in Subscription and model before sending.');await editor.flush();
   if(this.closed||root!==this.root.root||generation!==this.generation||chat!==this.info?.chat||editor!==this.drafts.current||row.exchange!==this.exchange?.exchange||!this.failureActions||this.working)throw new Error('The failed response changed before recovery could start.');
   if(editor.dirty||editor.conflict||editor.recovery!==null)throw new Error('Save or resolve the Draft before continuing.');
   const exchange=crypto.randomUUID(),common={version:1 as const,root,scope:{chat},chat,exchange,existing:true};
   const intent:SendIntent=continueFrom?{...common,method:'chat.send',purpose:'continue',params:{chat,exchange,message:'proceed',route:{...this.route},workingFolder:this.settings.workingFolder??this.folder},number:(this.info?.exchangeCount??0)+1}:{...common,method:'exchange.sendAgain',params:{exchange:row.exchange,newExchange:exchange,route:{...this.route}},prompt:this.prompt,retryFolder:row.workingFolder,number:row.number};
   this.sending.start(intent);transferred=true;
  }catch(e){editor.sendProblem='Not sent: '+(e instanceof Refusal?describe(e.detail):e instanceof Error?e.message:'Recovery could not start.');this.composerOpen=true;}
  finally{this.sendWait='';if(!transferred)editor.pendingSend=false;finish();}
 }
 requestSend(){const editor=this.drafts.current;if(!editor?.ready||editor.pendingSend||this.composerBusy||!editor.text.trim())return;const generation=this.generation;editor.sendProblem='';editor.pastes.requestSend(()=>void this.prepareSend(editor,generation));}
 private async prepareSend(editor:DraftEditor,generation:number){
  if(this.closed||generation!==this.generation||editor!==this.drafts.current){editor.sendProblem='Not sent: the composition changed while pasted text was saved.';return;}
  const root=this.root.root;editor.pendingSend=true;this.sendWait='Saving Draft before sending…';let transferred=false;
  try{await this.routing.settle();if(this.routing.problem.startsWith('Route not saved:'))throw new Error(this.routing.problem);if(this.routing.busy||!this.routing.available)throw new Error('Choose a signed-in Subscription and model before sending.');await editor.flush();
   if(this.closed||root!==this.root.root||generation!==this.generation||editor!==this.drafts.current)throw new Error('The composition changed before the message was sent.');
   if(!editor.ready||editor.dirty||editor.conflict||editor.recovery!==null||editor.revision===null)throw new Error('Save or resolve the Draft before sending.');
   const chat=this.info?.chat??crypto.randomUUID(),exchange=crypto.randomUUID(),workingFolder=this.settings.workingFolder??this.exchange?.workingFolder??this.folder;
   const intent:SendIntent={version:1,root,scope:editor.scope,chat,exchange,method:'chat.send',params:{chat,exchange,message:editor.text,route:{...this.route},workingFolder,draft:{revision:editor.revision,...('folder' in editor.scope?{folder:editor.scope.folder}:{})}},number:(this.info?.exchangeCount??0)+1,existing:!!this.info};
   const working=this.exchanges.find(row=>!['completed','failed','cancelled','interrupted'].includes(row.state));
   if(working){this.stopConfirmation={intent,editor,generation,exchange:working.exchange};this.sendWait='';transferred=true;return;}
   this.sending.start(intent);this.sendWait='';transferred=true;
  }catch(e){const message=e instanceof Error?e.message:'The message could not be sent.';editor.sendProblem=message.startsWith('Not sent:')?message:'Not sent: '+message;this.composerOpen=true;}
  finally{if(!transferred){editor.pendingSend=false;this.sendWait='';}}
 }
 private provisionalRow(op:SendOperation,number=op.intent.number):ElmaExchange{return{exchange:op.intent.exchange,number,state:'accepting',route:op.intent.params.route as ElmaRoute,workingFolder:op.intent.retryFolder??(typeof op.intent.params.workingFolder==='string'?op.intent.params.workingFolder:this.folder),acceptedAt:'',items:[{position:0,kind:'message',role:'user',text:op.message}],runs:[]};}
 private provisional(op:SendOperation){
  if(op.intent.root!==this.root.root)return;const same=this.info?.chat===op.intent.chat;
  this.previousSelection.set(op.intent.exchange,this.previousSelection.get(op.intent.exchange)??this.selected);
  if(!same){this.live.clear();this.info={chat:op.intent.chat,title:null,firstMessage:op.intent.existing?'':op.message,exchangeCount:op.intent.number,usage:{inputTokens:0,outputTokens:0}};this.exchanges=[];this.settings={route:op.intent.params.route as ElmaRoute,workingFolder:typeof op.intent.params.workingFolder==='string'?op.intent.params.workingFolder:undefined};}
  const present=this.exchanges.some(row=>row.exchange===op.intent.exchange);if(!present){const old=this.exchanges.find(row=>row.exchange===op.intent.params.exchange);if(op.intent.method==='exchange.sendAgain'&&old){this.replacements.set(op.intent.exchange,old);this.exchanges=this.exchanges.map(row=>row===old?this.provisionalRow(op):row);}else this.exchanges=[...this.exchanges,this.provisionalRow(op)];}if(!same||!present)this.selected=op.intent.exchange;
  if(this.info)this.info.exchangeCount=Math.max(this.info.exchangeCount,op.intent.number);this.folder=this.settings.workingFolder??this.folder;this.drafts.select(this.root.root,op.intent.scope);this.sending.select(this.root.root,this.drafts.current);this.selectRoute();this.composerOpen=false;
 }
 private async accepted(op:SendOperation,result:Accepted){
  if(this.root.root!==op.intent.root)return;const visible=this.info?.chat===op.intent.chat;
  if(visible){const row=this.exchanges.find(row=>row.exchange===op.intent.exchange);if(row)row.number=result.number;let opened=false;try{opened=await this.openChat(op.intent.chat,true);if(!opened)this.problem='The message was sent, but the chat is not available yet.';}catch(e){this.problem='The message was sent, but the chat could not be restored: '+(e instanceof Refusal?describe(e.detail):'read failed');}if(!opened&&this.root.root===op.intent.root&&this.info?.chat===op.intent.chat){this.drafts.select(this.root.root,{chat:op.intent.chat});this.sending.select(this.root.root,this.drafts.current);}}
  this.previousSelection.delete(op.intent.exchange);this.replacements.delete(op.intent.exchange);
 }
 private async refused(op:SendOperation,error:BridgeError){
  if(this.root.root!==op.intent.root)return;
  if(error.code==='draft_conflict'&&Object.hasOwn(error,'draft')){try{op.editor.receiveDraft(error.draft);}catch{/* The retained message still needs its canonical subscription. */}}
  if(op.intent.method==='chat.send'&&op.intent.purpose!=='continue')op.editor.restoreMessage(op.message,(op.intent.params.draft as {revision:Revision}).revision);
  op.editor.sendProblem=error.code==='chat_busy'?'Another message of this chat is running':'Not sent: '+describe(error);
  if(this.info?.chat===op.intent.chat){if(!op.intent.existing){this.clear();this.folder=(op.intent.scope as {folder:string}).folder;this.selectDraft();this.selectRoute();this.routing.preview(op.intent.params.route as ElmaRoute);}
   else{const original=this.replacements.get(op.intent.exchange);this.exchanges=original?this.exchanges.map(row=>row.exchange===op.intent.exchange?original:row):this.exchanges.filter(row=>row.exchange!==op.intent.exchange);if(this.selected===op.intent.exchange)this.selected=this.previousSelection.get(op.intent.exchange)??this.exchanges.at(-1)?.exchange??null;try{await this.openChat(op.intent.chat,true);}catch{/* The retained Draft and refusal remain visible. */}}
   this.composerOpen=true;
  }this.previousSelection.delete(op.intent.exchange);this.replacements.delete(op.intent.exchange);
 }
 cancelStop(){const pending=this.stopConfirmation;this.stopConfirmation=null;if(pending)pending.editor.pendingSend=false;this.sendWait='';this.composerOpen=true;}
 async confirmStopSend(){const pending=this.stopConfirmation;this.stopConfirmation=null;if(!pending)return;if(pending.generation!==this.generation||pending.intent.root!==this.root.root||pending.intent.chat!==this.info?.chat){pending.editor.pendingSend=false;return;}
  let finish!:()=>void;const done=new Promise<void>(resolve=>finish=resolve);this.stopQueue={...pending,finish};this.drafts.holdSend(done);this.sendWait='Waiting for the current response to be saved…';this.composerOpen=false;this.afterChatState();if(this.stopQueue)await this.stopExchange(pending.exchange);
 }
 private cancelQueued(){const pending=this.stopConfirmation;this.stopConfirmation=null;if(pending){pending.editor.pendingSend=false;pending.editor.sendProblem='The queued message is kept in its Draft.';}if(this.stopQueue){this.stopQueue.editor.pendingSend=false;this.stopQueue.editor.sendProblem='The queued message is kept in its Draft.';this.stopQueue.finish();this.stopQueue=undefined;}this.sendWait='';}
 private afterChatState(){this.stopping=this.stopping.filter(id=>!this.exchanges.some(row=>row.exchange===id&&['completed','failed','cancelled','interrupted'].includes(row.state)));const queued=this.stopQueue;if(!queued)return;const row=this.exchanges.find(row=>row.exchange===queued.exchange);if(!row||!['completed','failed','cancelled','interrupted'].includes(row.state))return;this.stopQueue=undefined;this.sendWait='';queued.editor.pendingSend=false;try{this.sending.start(queued.intent);}catch(e){queued.editor.sendProblem=e instanceof Error?e.message:'Not sent';this.composerOpen=true;}queued.finish();}
 stopCurrent(){const row=[...this.exchanges].reverse().find(value=>!['completed','failed','cancelled','interrupted'].includes(value.state));if(row)void this.stopExchange(row.exchange);}
 async stopExchange(exchange:string,retry=false):Promise<void>{
  const root=this.root.root,previous=this.stopCalls.get(exchange);if(previous){await previous;if(retry&&root===this.root.root&&this.stopping.includes(exchange)){if(this.stopCalls.get(exchange)===previous)this.stopCalls.delete(exchange);await this.stopExchange(exchange,true);}return;}
  if(this.stopping.includes(exchange)&&!retry)return;if(!this.stopping.includes(exchange))this.stopping=[...this.stopping,exchange];
  const operation=(async()=>{try{await this.bridge.call('exchange.stop',{exchange});if(root===this.root.root)this.afterChatState();}catch(e){if(root!==this.root.root)return;if(e instanceof Refusal&&['disconnected','no_answer'].includes(e.detail.code))return;this.stopping=this.stopping.filter(id=>id!==exchange);this.problem='Could not stop: '+(e instanceof Refusal?describe(e.detail):'The request failed.');if(this.stopQueue?.exchange===exchange)this.cancelQueued();}})();this.stopCalls.set(exchange,operation);try{await operation;}finally{if(this.stopCalls.get(exchange)===operation)this.stopCalls.delete(exchange);}
 }

 private rememberRepository(folder:string){const repo=this.repositories.find(r=>r.folder===folder);if(!repo)return;this.preferences.recentRepositories=[repo.name,...this.preferences.recentRepositories.filter(name=>name!==repo.name)].slice(0,16);const recent=this.preferences.recentRepositories;this.repositories=[...this.repositories.slice(0,1),...this.repositories.slice(1).sort((a,b)=>{const ai=recent.indexOf(a.name),bi=recent.indexOf(b.name);return(ai<0?Infinity:ai)-(bi<0?Infinity:bi);})];this.savePreferences();}
 newChat(folder:string){
  if(!folder.startsWith('/')||/[\0\r\n]/.test(folder)){this.problem='Choose an absolute folder path.';return;}
  this.clear();this.folder=folder;this.problem='';this.repositoryNotice='';this.rememberRepository(folder);this.selectDraft();this.selectRoute();
 }
 chooseRepository(folder:string){
  if(!folder.startsWith('/')||/[\0\r\n]/.test(folder)){this.problem='Choose an absolute folder path.';return;}
  if(!this.info){this.newChat(folder);return;}
  if(this.working){this.problem='Wait for the current turn to finish before changing Repo';return;}
  if(folder===(this.settings.workingFolder??this.exchange?.workingFolder??this.folder))return;
  this.repositoryChange={root:this.root.root,chat:this.info.chat,folder,generation:this.generation};
  if(!this.info.exchangeCount)void this.confirmRepository();
 }
 async confirmRepository(){
  const intent=this.repositoryChange;this.repositoryChange=null;if(!intent)return;
  const current=()=>intent.root===this.root.root&&intent.chat===this.info?.chat&&intent.generation===this.generation;
  if(!current())return;if(this.working){this.problem='Wait for the current turn to finish before changing Repo';return;}
  try{await this.saveSettings(intent.chat,{workingFolder:intent.folder},()=>current()&&!this.working);if(!current())return;this.folder=this.settings.workingFolder??intent.folder;this.rememberRepository(this.folder);this.selectRoute();this.repositoryNotice='Repo changed to '+this.repository;this.problem='';}
  catch(e){if(current())this.problem=e instanceof Refusal?describe(e.detail):'The repository could not be changed.';}
 }
 async pickOther(asNew=false){const generation=this.generation,root=this.root.root;try{const result=await this.app.call('app.pickFolder',{start:this.settings.workingFolder??this.folder});if(this.closed||generation!==this.generation||root!==this.root.root||typeof result.folder!=='string')return;if(asNew)this.newChat(result.folder);else this.chooseRepository(result.folder);}catch(e){if(generation===this.generation)this.problem=e instanceof Refusal?describe(e.detail):'The folder could not be picked.';}}
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
 private clear(){this.answerStates={};this.cancelQueued();this.repositoryChange=null;this.repositoryNotice='';this.restoring=false;this.live.clear();this.revision++;this.pageTicket++;this.pageBusy=false;this.pageProblem='';this.historyOpen=false;this.cancelOpening?.();this.chatSub?.close();this.chatSub=undefined;this.generation++;this.info=null;this.exchanges=[];this.selected=null;this.settings={};this.ongoing=false;}
 private selectDraft(canonical=false){if(this.root.root&&(this.info||this.folder)){const pending=this.info?this.sending.forChat(this.info.chat):undefined;this.drafts.select(this.root.root,pending&&!canonical?pending.intent.scope:this.info?{chat:this.info.chat}:{folder:this.folder});this.sending.select(this.root.root,this.drafts.current);}}

 close(){clearInterval(this.clock);this.cancelOpening?.();this.closed=true;this.bootstrapGeneration++;this.chatSub?.close();this.cancelQueued();this.sending.close();this.drafts.close();this.routing.close();this.bridge.close();this.app.close();}
}
