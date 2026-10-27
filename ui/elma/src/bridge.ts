/** BKD-1: one connection, independent calls and replaceable subscriptions. No content logs. */
export type Fields = Record<string, unknown>;
export interface RootInfo {root:string;name:string;status:'preparing'|'working'|'failed';current:boolean;failed?:{at:string;reason:string}}
export interface BridgeError {code:string;message:string;source?:string;[key:string]:unknown}
export class Refusal extends Error { constructor(public detail:BridgeError){super(detail.message);this.name=detail.code;} }
interface Pending {resolve:(value:unknown)=>void;reject:(error:Refusal)=>void;timer:ReturnType<typeof setTimeout>}
interface Subscription {id:string;topic:string;params:Fields;seq:number;active:boolean;failure?:string;receive:(event:Fields)=>void;ended:(error?:BridgeError)=>void}
export interface BridgeOptions {
 build:string; onstate?:(state:string)=>void; onhello?:(root:RootInfo,build:string)=>void;
 beforeReload?:()=>Promise<void>; reload?:(url:string)=>void;
 /** Test seam for the exact production deadline, not a different protocol. */
 deadline?:(method:string)=>number;
}
const limit=16*1024*1024;
const error=(code:string,message:string)=>new Refusal({code,message});
export function deadline(method:string):number {return ['chat.send','exchange.sendAgain'].includes(method)?150000:['exchange.stop','chat.reimport'].includes(method)?120000:30000;}
export class Bridge {
 private serial=0;private online=false;private stopped=false;private versionOk=true;
 private pending=new Map<string,Pending>();private topics=new Set<Subscription>();
 private socket?:WebSocket;private reconnect?:ReturnType<typeof setTimeout>;private reloading=false;private backendBuild?:string;
 private reloads=new Set(new URL(location.href).searchParams.getAll('reloadedFor'));
 private receiveBound=(text:string)=>this.receive(text);
 private visibility=()=>{if(document.visibilityState==='visible'&&this.online)void this.check();};
 constructor(private options:BridgeOptions){
  window.arbolBridge={receive:this.receiveBound};document.addEventListener('visibilitychange',this.visibility);
  if(!window.webkit?.messageHandlers?.arbol)this.connect();
 }
 private id(){return 'w'+(++this.serial);}
 private state(value:string){this.options.onstate?.(value);}
 private connect(){
  if(this.stopped)return;
  const url=new URL('/bridge',location.href);url.protocol=location.protocol==='https:'?'wss:':'ws:';
  const ws=new WebSocket(url);this.socket=ws;
  ws.onmessage=e=>{if(typeof e.data==='string')this.receive(e.data);else ws.close();};
  ws.onclose=()=>{if(this.socket!==ws||this.stopped)return;this.lost();this.reconnect=setTimeout(()=>this.connect(),500);};
  ws.onerror=()=>ws.close();
 }
 private send(message:Fields){
  const text=JSON.stringify(message);if(new TextEncoder().encode(text+'\n').length>limit)throw error('invalid_input','The message is too large.');
  const native=window.webkit?.messageHandlers?.arbol;
  if(native)native.postMessage(text);else if(this.socket?.readyState===WebSocket.OPEN)this.socket.send(text);else throw error('disconnected','The backend is disconnected.');
 }
 call<T=unknown>(method:string,params:Fields={}):Promise<T>{
  if(!this.online||!this.versionOk)return Promise.reject(error('disconnected','The backend is disconnected.'));
  const id=this.id();return new Promise<T>((resolve,reject)=>{
   const timer=setTimeout(()=>{this.pending.delete(id);reject(error('no_answer','The backend did not answer in time.'));},this.options.deadline?.(method)??deadline(method));
   this.pending.set(id,{resolve:value=>resolve(value as T),reject,timer});
   try{this.send({type:'call',id,method,params});}catch(e){clearTimeout(timer);this.pending.delete(id);reject(e);}
  });
 }
 subscribe(topic:string,params:Fields,receive:(event:Fields)=>void,ended:(error?:BridgeError)=>void=()=>{}){
  // One logical subscription per topic/params. Never reuse a wire id.
  const key=JSON.stringify(Object.entries(params).sort(([a],[b])=>a.localeCompare(b)));
  for(const old of this.topics)if(old.topic===topic&&JSON.stringify(Object.entries(old.params).sort(([a],[b])=>a.localeCompare(b)))===key)this.remove(old);
  const sub:Subscription={id:'',topic,params,receive,ended,seq:0,active:false};this.topics.add(sub);if(this.online)this.start(sub);
  return {close:()=>this.remove(sub),retry:()=>{if(this.online)this.start(sub);}};
 }
 private remove(sub:Subscription){if(sub.active&&this.online){try{this.send({type:'unsubscribe',id:sub.id});}catch{/* disconnect already owns the state */}}this.topics.delete(sub);sub.active=false;}
 private start(sub:Subscription){
  if(sub.active){try{this.send({type:'unsubscribe',id:sub.id});}catch{return;}}
  sub.id=this.id();sub.seq=0;sub.active=true;sub.failure=undefined;this.send({type:'subscribe',id:sub.id,topic:sub.topic,params:sub.params});
 }
 async check(){
  try{const value=await this.call<{subscriptions:{id:string;seq:number}[]}>('subscriptions.check');const receipts=new Map(value.subscriptions.map(v=>[v.id,v.seq]));
   for(const sub of this.topics)if(sub.active&&receipts.get(sub.id)!==sub.seq)this.start(sub);
  }catch(e){this.state(e instanceof Refusal?e.message:'Subscriptions could not be checked.');}
 }
 receive(text:string){
  if(this.stopped||typeof text!=='string'||new TextEncoder().encode(text+'\n').length>limit)return;
  let m:Fields;try{const value:unknown=JSON.parse(text);if(!value||typeof value!=='object'||Array.isArray(value))return;m=value as Fields;}catch{return;}
  if(m.type==='lost'){this.lost();return;}
  if(m.type==='hello'){
   this.lost(false);if(m.bridge!==1){this.versionOk=false;this.state('This window cannot work with this Bridge version.');return;}
   if(!m.root||typeof m.root!=='object'||typeof m.build!=='string')return;
   this.versionOk=true;this.online=true;this.backendBuild=m.build;this.state('Connected');this.options.onhello?.(m.root as unknown as RootInfo,m.build);
   for(const sub of this.topics)this.start(sub);
   void this.reloadFor(m.build);return;
  }
  if(!this.online)return;
  if(m.type==='reply'&&typeof m.id==='string'){
   const p=this.pending.get(m.id);if(!p)return;clearTimeout(p.timer);this.pending.delete(m.id);
   if(m.error&&typeof m.error==='object')p.reject(new Refusal(m.error as BridgeError));else p.resolve(m.result);return;
  }
  const sub=[...this.topics].find(s=>s.active&&s.id===m.id);if(!sub)return;
  if(m.type==='ended'){sub.active=false;sub.failure=(m.error as BridgeError|undefined)?.code;sub.ended(m.error as BridgeError|undefined);return;}
  if(m.type!=='event'||!Number.isSafeInteger(m.seq)||!m.event||typeof m.event!=='object')return;
  if(m.seq!==sub.seq+1){this.start(sub);return;}sub.seq=m.seq as number;
  const event=m.event as Fields;sub.receive(event);
  if(sub.topic==='attention'&&event.kind==='closed'&&event.id==='database_unreachable')for(const failed of this.topics)if(!failed.active&&failed.failure==='database_unavailable')this.start(failed);
 }
 private async reloadFor(build:string){
  if(build===this.options.build||this.reloads.has(build)||this.reloading)return;
  this.reloading=true;
  try{await this.options.beforeReload?.();if(this.stopped||!this.online||this.backendBuild!==build)return;this.reloads.add(build);const url=new URL(location.href);url.searchParams.append('reloadedFor',build);(this.options.reload??(url=>location.replace(url)))(url.href);}
  catch{this.state('The page could not be reloaded; its unsaved text is kept.');}
  finally{this.reloading=false;if(this.online&&this.backendBuild&&this.backendBuild!==build)void this.reloadFor(this.backendBuild);}
 }
 private lost(notify=true){this.online=false;for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(error('disconnected','The backend is disconnected.'));}this.pending.clear();for(const sub of this.topics)sub.active=false;if(notify)this.state('Reconnecting…');}
 close(){this.stopped=true;clearTimeout(this.reconnect);document.removeEventListener('visibilitychange',this.visibility);if(window.arbolBridge?.receive===this.receiveBound)delete window.arbolBridge;this.lost(false);this.socket?.close();this.topics.clear();}
}
