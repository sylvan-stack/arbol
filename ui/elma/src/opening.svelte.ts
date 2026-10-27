/** Native routing targets are retained; the app channel never enters the backend Bridge. */
import {Refusal,describe,type Fields} from './bridge';
import type {AppChannel} from './app-channel';
export type OpenTarget={chat:string;folder?:never}|{folder:string;chat?:never};
function target(value:Fields):OpenTarget|null{
 if(typeof value.chat==='string'&&value.folder===undefined&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value.chat))return{chat:value.chat};
 if(typeof value.folder==='string'&&value.chat===undefined&&value.folder.startsWith('/')&&!/[\0\r\n]/.test(value.folder))return{folder:value.folder};
 if(Object.keys(value).length)throw new Error('The app returned an invalid open request.');return null;
}
export class Opening {
 pending=$state<OpenTarget|null>(null);busy=$state(false);problem=$state('');storageProblem=$state('');
 private root='';private epoch=0;private wanted=true;private enabled=false;private closed=false;private running?:Promise<boolean>;private unlisten:()=>void;
 constructor(private app:AppChannel,private gate:(done:Promise<void>)=>Promise<void>,private open:(target:OpenTarget)=>Promise<boolean>,private hold:(done:Promise<void>)=>void){this.unlisten=app.onopen(()=>{this.wanted=true;if(this.enabled)void this.start();});}
 private key(root=this.root){return 'elma.open.v1:'+root;}
 hello(root:string){if(root!==this.root){this.epoch++;this.root=root;this.pending=null;this.problem='';this.storageProblem='';try{const raw=sessionStorage.getItem(this.key());if(raw)this.pending=target(JSON.parse(raw));}catch{this.storageProblem='The open request cannot be retained across a page reload.';}}this.enabled=false;this.wanted=true;}
 private retain(root:string,value:OpenTarget|null){try{if(value)sessionStorage.setItem(this.key(root),JSON.stringify(value));else sessionStorage.removeItem(this.key(root));if(root===this.root)this.storageProblem='';}catch{if(root===this.root)this.storageProblem='The open request cannot be retained across a page reload.';}}
 async start():Promise<boolean>{
  if(this.closed)return false;this.enabled=true;const epoch=this.epoch;
  while(this.running){const running=this.running,result=await running;if(this.closed||epoch!==this.epoch)return false;if(this.running===running)this.running=undefined;if(!this.wanted&&!this.pending)return result;}
  if(this.closed||epoch!==this.epoch)return false;
  const running=this.process(epoch);this.running=running;try{return await running;}finally{if(this.running===running)this.running=undefined;}
 }
 private async process(epoch:number){
  const root=this.root;let opened=false,finish!:()=>void;const done=new Promise<void>(resolve=>finish=resolve);this.hold(done);this.busy=true;this.problem='';
  try{
   while(!this.closed&&epoch===this.epoch&&(this.pending||this.wanted)){
    await this.gate(done);if(this.closed||epoch!==this.epoch)return opened;
    if(!this.pending){this.wanted=false;const value=target(await this.app.call('app.takeOpen'));if(value)this.retain(root,value);if(this.closed||epoch!==this.epoch)return opened;if(!value)continue;this.pending=value;}
    // Text or the visible composition can change while the host answers.
    await this.gate(done);if(this.closed||epoch!==this.epoch)return opened;
    const captured=this.pending;if(!captured)continue;if(!await this.open(captured))throw new Error('The requested chat is not available. Retry opening it.');
    if(this.closed||epoch!==this.epoch)return opened;if(this.pending===captured){this.pending=null;this.retain(root,null);}opened=true;
   }
  }catch(error){if(!this.closed&&epoch===this.epoch)this.problem=error instanceof Refusal?describe(error.detail):error instanceof Error?error.message:'The open request could not be completed.';}
  finally{finish();if(epoch===this.epoch)this.busy=false;}
  return opened;
 }
 dismiss(){if(this.busy)return;this.pending=null;this.retain(this.root,null);this.problem='';if(this.wanted)void this.start();}
 beforeReload(){if(this.pending&&this.storageProblem)throw new Error(this.storageProblem);}
 close(){this.closed=true;this.epoch++;this.unlisten();}
}
