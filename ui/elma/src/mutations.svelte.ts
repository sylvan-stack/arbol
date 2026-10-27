/** Idempotent chat metadata calls retain their exact parameters until a definite receipt. */
import {Refusal,type Bridge,type Fields} from './bridge';

export type MetadataMethod='chat.rename'|'chat.mark';
export class MetadataOperation {
 pending=$state(true);
 status=$state('Saving…');
 running=false;
 attempts=0;
 timer?:ReturnType<typeof setTimeout>;
 readonly result:Promise<Fields>;
 readonly done:Promise<void>;
 resolve!:(value:Fields)=>void;
 reject!:(error:Refusal)=>void;
 finish!:()=>void;
 constructor(readonly root:string,readonly method:MetadataMethod,readonly params:Fields){
  this.result=new Promise((resolve,reject)=>{this.resolve=resolve;this.reject=reject;});
  this.done=new Promise(resolve=>this.finish=resolve);
 }
}

export class Mutations {
 private root='';
 private online=false;
 private closed=false;
 private helloSerial=0;
 private operations=new Map<string,MetadataOperation>();
 private revision=$state(0);
 constructor(private bridge:Bridge,private hold:(done:Promise<void>)=>void){}
 private key(root:string,method:MetadataMethod,chat:unknown){return JSON.stringify([root,method,chat]);}
 forChat(chat:string){this.revision;return [...this.operations.values()].filter(op=>op.root===this.root&&op.params.chat===chat);}
 start(method:MetadataMethod,params:Fields){
  if(this.closed||!this.root)throw new Error('The chat is not connected to a Root.');
  const key=this.key(this.root,method,params.chat),existing=this.operations.get(key);
  if(existing){if(JSON.stringify(existing.params)!==JSON.stringify(params))throw new Error('Wait for the previous action to finish.');return existing;}
  const op=new MetadataOperation(this.root,method,{...params});
  this.operations.set(key,op);this.revision++;this.hold(op.done);void this.run(op);return op;
 }
 hello(root:string){
  if(this.root&&root!==this.root)for(const op of [...this.operations.values()])this.complete(op,new Refusal({code:'context_changed',message:'The Root changed before the action’s outcome was known.'}));
  this.root=root;this.online=true;this.helloSerial++;
  void Promise.resolve().then(()=>{for(const op of this.operations.values())void this.run(op);});
 }
 offline(){this.online=false;}
 private async run(op:MetadataOperation){
  if(this.closed||!this.online||!op.pending||op.running||op.root!==this.root)return;
  clearTimeout(op.timer);op.running=true;op.status=op.attempts?'Waiting for the action receipt…':'Saving…';op.attempts++;
  const hello=this.helloSerial;
  try{
   const value=await this.bridge.call<Fields>(op.method,op.params);
   if(!op.pending||this.closed)return;
   if(!value||typeof value!=='object'||Array.isArray(value)||(op.method==='chat.rename'?value.title!==null&&typeof value.title!=='string':typeof value.ongoing!=='boolean'))throw new Refusal({code:'no_answer',message:'The backend did not return a valid action receipt.'});
   this.complete(op,undefined,value);
  }catch(error){
   if(!op.pending||this.closed)return;
   const refusal=error instanceof Refusal?error:new Refusal({code:'no_answer',message:'The action receipt could not be read.'});
   if(['disconnected','no_answer'].includes(refusal.detail.code)){
    op.status='Waiting for the action receipt…';
    if(refusal.detail.code==='no_answer')op.timer=setTimeout(()=>void this.run(op),op.attempts===1?0:1000);
   }else this.complete(op,refusal);
  }finally{
   op.running=false;
   if(op.pending&&this.online&&hello!==this.helloSerial)void this.run(op);
  }
 }
 private complete(op:MetadataOperation,error?:Refusal,value:Fields={}){
  if(!op.pending)return;clearTimeout(op.timer);op.pending=false;
  this.operations.delete(this.key(op.root,op.method,op.params.chat));this.revision++;
  if(error)op.reject(error);else op.resolve(value);op.finish();
 }
 close(){this.closed=true;for(const op of [...this.operations.values()])this.complete(op,new Refusal({code:'disconnected',message:'The window closed before the action finished.'}));}
}
