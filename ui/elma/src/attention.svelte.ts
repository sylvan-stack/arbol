/** Every stable ID remains visible until its own closed event or a replacing snapshot. */
import {describe,type Bridge,type Fields} from './bridge';
export interface AttentionItem {id:string;kind:string;severity:string;message:string;since?:string}
export class Attention {
 items=$state<AttentionItem[]>([]);problem=$state('');private root='';private sub:{close:()=>void;retry:()=>void};
 constructor(bridge:Bridge){this.sub=bridge.subscribe('attention',{},event=>this.receive(event),error=>this.problem=error?describe(error):'Attention could not be read.');}
 hello(root:string){if(this.root!==root){this.items=[];this.problem='';}this.root=root;}
 private valid(value:unknown):value is AttentionItem{return !!value&&typeof value==='object'&&['id','kind','severity','message'].every(key=>typeof(value as Fields)[key]==='string');}
 private receive(event:Fields){
  if(event.kind==='snapshot'&&Array.isArray(event.items)&&event.items.every(value=>this.valid(value)))this.items=[...new Map(event.items.map(item=>[item.id,item])).values()];
  else if(event.kind==='opened'&&this.valid(event.item)){const opened=event.item;this.items=[...this.items.filter(item=>item.id!==opened.id),opened];}
  else if(event.kind==='closed'&&typeof event.id==='string')this.items=this.items.filter(item=>item.id!==event.id);
  else{this.problem='The backend sent an invalid attention notice.';return;}
  this.problem='';
 }
 close(){this.sub.close();}
}
