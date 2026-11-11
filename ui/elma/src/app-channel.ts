/** BKD-1 app channel. Browser development adapter never sends to backend.sock. */
import { Refusal, type Fields } from './bridge';
import type { WorkspaceRootChoice, WorkspaceRootSelector } from '../design-system/src/types';

type RootMethod = 'app.listRoots' | 'app.openRoot';
type AppMethod = 'app.pickFolder' | 'app.openLink' | 'app.takeOpen' | RootMethod;

function isRootChoice(value: unknown): value is WorkspaceRootChoice {
 if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
 const {root, name, status, unavailable} = value as Fields;
 return typeof root === 'string' && /^[a-z0-9]+$/.test(root)
  && typeof name === 'string' && name.length > 0
  && (status === 'working' || status === 'preparing' || status === 'failed')
  && (unavailable === undefined || typeof unavailable === 'string');
}

export class AppChannel {
 private next=0;private waiting=new Map<string,{resolve:(value:Fields)=>void;reject:(error:Refusal)=>void;timer:ReturnType<typeof setTimeout>}>();
 private openTaken=false;private listeners=new Set<()=>void>();
 private receiveBound=(text:string)=>this.receive(text);
 readonly rootSelector: WorkspaceRootSelector | undefined = window.webkit?.messageHandlers?.arbolApp ? {
  load: async () => {
   const {roots} = await this.callRoot('app.listRoots');
   if (!Array.isArray(roots) || !roots.every(isRootChoice) || new Set(roots.map(row => row.root)).size !== roots.length) {
    throw new Error('The App returned an invalid Root list.');
   }
   return roots;
  },
  open: async root => { await this.callRoot('app.openRoot', {root}); },
 } : undefined;
 constructor(){window.arbolApp={receive:this.receiveBound};}
 onopen(listener:()=>void){this.listeners.add(listener);return ()=>this.listeners.delete(listener);}
 private async callRoot(method: RootMethod, params: Fields = {}): Promise<Fields> {
  try { return await this.call(method, params); }
  catch (error) {
   if (error instanceof Refusal && error.detail.code === 'unknown_method') {
    throw new Error('Update the Arbol App to open another Root from this header.');
   }
   throw error;
  }
 }
 call(method:AppMethod,params:Fields={}):Promise<Fields>{
  if(method==='app.openLink'){
   try{const url=new URL(String(params.url));if(!['http:','https:'].includes(url.protocol))throw new Error();}
   catch{return Promise.reject(new Refusal({code:'invalid_input',message:'Only http and https links can be opened.'}));}
  }
  const native=window.webkit?.messageHandlers?.arbolApp;
  if(native){const id='a'+(++this.next);return new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>{this.waiting.delete(id);reject(new Refusal({code:'no_answer',message:'The app did not answer in time.'}));},30000);
   this.waiting.set(id,{resolve,reject,timer});try{native.postMessage(JSON.stringify({type:'call',id,method,params}));}catch{clearTimeout(timer);this.waiting.delete(id);reject(new Refusal({code:'disconnected',message:'The app is disconnected.'}));}
  });}
  // The relay's browser host answers locally. No app envelope reaches the Bridge.
  if(method==='app.openLink'){window.open(String(params.url),'_blank','noopener,noreferrer');return Promise.resolve({});}
  if(method==='app.pickFolder'){const value=window.prompt('Folder',typeof params.start==='string'?params.start:'');return Promise.resolve({folder:value?.trim()||null});}
  if(method==='app.listRoots'||method==='app.openRoot')return Promise.reject(new Refusal({code:'unknown_method',message:'Root selection requires the native App.'}));
  if(this.openTaken)return Promise.resolve({});this.openTaken=true;
  const chat=new URL(location.href).searchParams.get('open');return Promise.resolve(chat&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(chat)?{chat}:{});
 }
 private receive(text:string){
  let m:Fields;try{m=JSON.parse(text) as Fields;}catch{return;}
  if(!m||typeof m!=='object')return;
  if(m.type==='open'){for(const listener of this.listeners)listener();return;}
  if(m.type!=='reply'||typeof m.id!=='string')return;const p=this.waiting.get(m.id);if(!p)return;clearTimeout(p.timer);this.waiting.delete(m.id);
  if(m.error&&typeof m.error==='object')p.reject(new Refusal(m.error as {code:string;message:string}));else p.resolve((m.result??{}) as Fields);
 }
 close(){if(window.arbolApp?.receive===this.receiveBound)delete window.arbolApp;for(const p of this.waiting.values()){clearTimeout(p.timer);p.reject(new Refusal({code:'disconnected',message:'The app channel closed.'}));}this.waiting.clear();this.listeners.clear();}
}
