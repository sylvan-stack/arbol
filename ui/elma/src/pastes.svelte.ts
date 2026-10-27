/** File saves retain raw text until success, with edit-aware ranges and one queued send. */
import type { Bridge } from './bridge';
interface Editor {text:string;input:(text:string,edit?:{start:number;end:number})=>void}
interface Insertion {start:number;end:number;text:string;active:boolean}
export class Pastes {
 pending=$state(0);problem=$state('');queued=$state(false);
 private ranges=new Set<Insertion>();private jobs=new Set<Promise<void>>();private send?:()=>void;private closed=false;
 constructor(private bridge:Bridge,private editor:Editor){}
 get status(){return this.pending?'Saving pasted text…':'';}
 change(previous:string,next:string,edit?:{start:number;end:number}){
  let start=0;while(start<previous.length&&start<next.length&&previous[start]===next[start])start++;
  let tail=0;while(tail<previous.length-start&&tail<next.length-start&&previous[previous.length-1-tail]===next[next.length-1-tail])tail++;
  let end=previous.length-tail;const delta=next.length-previous.length;
  if(edit&&previous.slice(0,edit.start)===next.slice(0,edit.start)&&previous.slice(edit.end)===next.slice(edit.end+delta)){start=edit.start;end=edit.end;}
  for(const range of this.ranges){
   if(!range.active)continue;
   if(end<=range.start){range.start+=delta;range.end+=delta;}
   else if(start<range.end){range.active=false;this.queued=false;this.send=undefined;}
  }
 }
 paste(text:string,selection:{start:number;end:number}):boolean {
  if(this.closed||Array.from(text).length<10000)return false;
  this.problem='';
  const start=Math.max(0,Math.min(selection.start,this.editor.text.length)),end=Math.max(start,Math.min(selection.end,this.editor.text.length));
  this.editor.input(this.editor.text.slice(0,start)+text+this.editor.text.slice(end),{start,end});
  const range:Insertion={start,end:start+text.length,text,active:true};this.ranges.add(range);this.pending++;
  const job=this.save(range);this.jobs.add(job);
  void job.then(()=>{this.jobs.delete(job);this.pending--;if(!this.pending&&this.queued){const action=this.send;this.queued=false;this.send=undefined;action?.();}});
  return true;
 }
 private async save(range:Insertion){
  try{
   const reply=await this.bridge.call<{path:string}>('paste.save',{text:range.text});
   if(this.closed)return;
   if(typeof reply.path!=='string'||!reply.path.startsWith('/')||/[\0\r\n]/.test(reply.path))throw new Error('The backend sent an invalid paste path.');
   this.ranges.delete(range);
   if(!range.active){this.problem='Pasted text changed while saving. Your edits are kept; send again when ready.';return;}
   const count=Array.from(range.text).length.toLocaleString('en-US'),path=reply.path.replace(/</g,'%3C').replace(/>/g,'%3E');
   this.editor.input(this.editor.text.slice(0,range.start)+`[Pasted text (${count} characters)](<${path}>)`+this.editor.text.slice(range.end),{start:range.start,end:range.end});
  }catch(e){if(!this.closed)this.problem='Pasted text not saved: '+(e instanceof Error?e.message:'The file could not be saved.');this.queued=false;this.send=undefined;}
  finally{this.ranges.delete(range);}
 }
 requestSend(action:()=>void){if(!this.pending){action();return;}if(!this.queued){this.queued=true;this.send=action;}}
 async wait(){while(this.jobs.size)await Promise.all([...this.jobs]);}
 cancel(){for(const range of this.ranges)range.active=false;this.queued=false;this.send=undefined;}
 close(){this.closed=true;this.cancel();}
}
