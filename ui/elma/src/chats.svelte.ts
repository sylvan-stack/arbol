/** Bounded canonical summaries. Local preferences contain UUID ordering only. */
import {describe,type Bridge,type Fields} from './bridge';
import type {ElmaRoute} from '../design-system/src/sections/elma-types';
export interface ChatSummary {chat:string;title:string|null;firstMessage?:string;activityAt?:string;last?:{exchange:string;number:number;state:string};hasDraft:boolean;workingFolder?:string;route?:ElmaRoute;ongoing:boolean;migration?:{fromRoot:string;fromChat:string;stale:boolean};archived?:true}
export const chatTitle=(row:Pick<ChatSummary,'title'|'firstMessage'>)=>row.title||Array.from((row.firstMessage??'').split('\n')[0]).slice(0,80).join('')||'Untitled chat';
const activity=(row:ChatSummary)=>Number.isFinite(Date.parse(row.activityAt??''))?Date.parse(row.activityAt!):0;
const newest=(a:ChatSummary,b:ChatSummary)=>activity(b)-activity(a)||b.chat.localeCompare(a.chat);
export class Chats {
 rows=$state<ChatSummary[]>([]);ready=$state(false);problem=$state('');private root='';private closed=false;private refreshing=false;private sub:{close:()=>void;retry:()=>void};
 constructor(bridge:Bridge){this.sub=bridge.subscribe('chats',{},event=>this.receive(event),error=>{this.ready=false;this.problem=error?describe(error):'The latest chats could not be read.';});}
 hello(root:string){if(this.root!==root){this.rows=[];this.ready=false;this.problem='';}this.root=root;}
 private receive(event:Fields){
  if(!['snapshot','changed'].includes(String(event.kind))||!Array.isArray(event.chats)){this.problem='The backend sent an invalid chat list.';return;}
  const rows=event.chats as ChatSummary[];
  if(rows.some(row=>!row||typeof row.chat!=='string'||!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(row.chat)||row.title!==null&&typeof row.title!=='string')){this.problem='The backend sent an invalid chat summary.';return;}
  const map=new Map((event.kind==='snapshot'?[]:this.rows).map(row=>[row.chat,row]));for(const row of rows)if(row.archived)map.delete(row.chat);else map.set(row.chat,row);
  this.rows=[...map.values()].sort(newest).slice(0,100);this.ready=true;this.problem='';
  // A fresh bounded snapshot backfills an archived row without racing an old page reply.
  if(event.kind==='changed'&&rows.some(row=>row.archived)&&!this.refreshing){this.refreshing=true;void Promise.resolve().then(()=>{this.refreshing=false;if(!this.closed)this.sub.retry();});}
 }
 ordered(current:string|undefined,recent:string[]){const ranks=new Map(recent.map((chat,i)=>[chat,i]));return this.rows.filter(row=>row.chat!==current&&!row.archived).sort((a,b)=>(ranks.get(a.chat)??Infinity)-(ranks.get(b.chat)??Infinity)||newest(a,b));}
 retry(){this.problem='';this.sub.retry();}
 close(){this.closed=true;this.sub.close();}
}
export function chatDetail(row:ChatSummary,repositories:{name:string;folder:string}[],now:number){
 const folder=row.workingFolder,repo=repositories.find(repo=>repo.folder===folder)?.name??folder?.split('/').filter(Boolean).at(-1)??'Repository unrecorded';
 const route=row.route?[[row.route.driver,row.route.subscription,row.route.model].filter(Boolean).join(' · '),row.route.effort].filter(Boolean).join(' / '):'Route unrecorded';
 const seconds=row.activityAt&&Number.isFinite(Date.parse(row.activityAt))?Math.max(0,Math.floor((now-Date.parse(row.activityAt))/1000)):undefined;
 const ago=(count:number,unit:string)=>count+' '+unit+(count===1?'':'s')+' ago';
 const age=seconds===undefined?'Activity time unrecorded':seconds<60?'just now':seconds<3600?ago(Math.floor(seconds/60),'minute'):seconds<86400?ago(Math.floor(seconds/3600),'hour'):ago(Math.floor(seconds/86400),'day');
 return[repo,route,row.last?.state??'No exchanges',age,row.ongoing?'Ongoing':'',row.hasDraft?'Draft':''].filter(Boolean).join(' · ');
}
