/** Only BKD-2 conveniences; never saved message/answer/credential data. */
export interface Preferences {lastChat?:string;repositoryChats:Record<string,string>;recentRepositories:string[];recentChats:string[];theme:string;readingWidth:number;uiScale:number;contentScale:number}
const uuid=(value:unknown):value is string=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const themes=['ironbark','bloodwood','redwood','mahogany','cedar','evergreen','driftwood','amber','sandstone','oat','birch','paper'];
export function readPreferences(root:string):Preferences {
 const defaults:Preferences={repositoryChats:{},recentRepositories:[],recentChats:[],theme:'redwood',readingWidth:720,uiScale:1,contentScale:1};
 try{const text=localStorage.getItem('arbol-elma:'+root);if(!text||text.length>131072)return defaults;const data=JSON.parse(text);if(!data||typeof data!=='object')return defaults;
  if(uuid(data.lastChat))defaults.lastChat=data.lastChat;
  if(data.repositoryChats&&typeof data.repositoryChats==='object')for(const [key,value] of Object.entries(data.repositoryChats).slice(0,100))if(uuid(value))defaults.repositoryChats[key]=value;
  if(Array.isArray(data.recentRepositories))defaults.recentRepositories=data.recentRepositories.filter((v:unknown)=>typeof v==='string').slice(0,16);
  if(Array.isArray(data.recentChats))defaults.recentChats=data.recentChats.filter(uuid).slice(0,100);
  if(themes.includes(data.theme))defaults.theme=data.theme;
  if(typeof data.readingWidth==='number'&&Number.isFinite(data.readingWidth))defaults.readingWidth=Math.max(600,Math.min(1680,data.readingWidth));
  if(typeof data.uiScale==='number'&&Number.isFinite(data.uiScale))defaults.uiScale=Math.max(11.5/13.5,Math.min(23/13.5,data.uiScale));
  if(typeof data.contentScale==='number'&&Number.isFinite(data.contentScale))defaults.contentScale=Math.max(defaults.uiScale,Math.min(32/13.5,data.contentScale));
 }catch{/* A disabled/malformed convenience store cannot own the chat. */}return defaults;
}
export function savePreferences(root:string,value:Preferences){try{localStorage.setItem('arbol-elma:'+root,JSON.stringify(value));}catch{/* The live view remains usable with storage disabled. */}}
