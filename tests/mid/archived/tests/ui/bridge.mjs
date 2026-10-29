// Preserve the original fixture/resource base after the tier move.
const _originalTestURL = new URL("../../../../ui/bridge.mjs", import.meta.url).href;
import assert from 'node:assert/strict';
import { createServer } from '../../../../../ui/elma/node_modules/vite/dist/node/index.js';
import { chromium } from '../../../../../ui/elma/node_modules/playwright/index.mjs';
const server=await createServer({root:new URL('../../ui/elma',_originalTestURL).pathname,configFile:new URL('../../ui/elma/vite.config.ts',_originalTestURL).pathname,server:{host:'127.0.0.1',port:0}});await server.listen();
const browser=await chromium.launch({headless:true});const page=await browser.newPage();const failures=[];page.on('pageerror',e=>failures.push(e.message));
try {
 await page.addInitScript(()=>{window.sent=[];window.webkit={messageHandlers:{arbol:{postMessage:text=>window.sent.push(JSON.parse(text))}}};});
 await page.goto(server.resolvedUrls.local[0]+'tests/bridge.html');await page.waitForFunction(()=>window.fixture);
 const result=await page.evaluate(async()=>{
  const {Bridge,deadline}=window.fixture;const states=[],events=[],ends=[],reloads=[];let release;const gate=new Promise(r=>release=r);
  const bridge=new Bridge({build:'1',onstate:s=>states.push(s),deadline:()=>40,beforeReload:()=>gate,reload:url=>reloads.push(url)});
  const receive=x=>window.arbolBridge.receive(JSON.stringify(x));const hello=(build='1',version=1)=>receive({type:'hello',bridge:version,root:{root:'test',name:'Test Root',status:'working',current:true},build});
  const sub=bridge.subscribe('chat',{chat:'fictional'},e=>events.push(e),e=>ends.push(e));hello();const first=window.sent.at(-1).id;
  receive({type:'event',id:first,seq:1,event:{kind:'snapshot',value:1}});receive({type:'event',id:first,seq:3,event:{kind:'title',value:'missed'}});const second=window.sent.at(-1).id;
  receive({type:'event',id:first,seq:2,event:{kind:'title',value:'obsolete'}});receive({type:'event',id:second,seq:1,event:{kind:'snapshot',value:2}});
  const slow=bridge.call('root.get').catch(e=>e.name);await new Promise(r=>setTimeout(r,70));const timed=await slow;const late=window.sent.at(-1);receive({type:'reply',id:late.id,result:'too late'});
  const a=bridge.call('accounts.list');const aid=window.sent.at(-1).id;const b=bridge.call('root.get');const bid=window.sent.at(-1).id;receive({type:'reply',id:bid,result:{name:'Root'}});receive({type:'reply',id:aid,error:{code:'future_code',message:'Future message',source:'driver'}});const independent=await b;const unknown=await a.catch(e=>e.detail);
  const check=bridge.check();const checking=window.sent.at(-1);receive({type:'reply',id:checking.id,result:{subscriptions:[{id:second,seq:2}]}});await check;const third=window.sent.at(-1).id;
  const pending=bridge.call('root.get').catch(e=>e.name);receive({type:'lost'});const disconnected=await pending;const kept=events.length;hello();const fourth=window.sent.at(-1).id;
  receive({type:'event',id:third,seq:2,event:{kind:'old'}});receive({type:'event',id:fourth,seq:1,event:{kind:'snapshot',value:3}});
  const att=bridge.subscribe('attention',{},()=>{});const attId=window.sent.at(-1).id;receive({type:'event',id:attId,seq:1,event:{kind:'snapshot',items:[]}});receive({type:'ended',id:fourth,error:{code:'database_unavailable',message:'Database away'}});receive({type:'event',id:attId,seq:2,event:{kind:'closed',id:'database_unreachable'}});const fifth=window.sent.at(-1).id;
  hello('2');const blockedReload=reloads.length;release();await new Promise(r=>setTimeout(r,0));hello('2');await new Promise(r=>setTimeout(r,0));const after=reloads.length;
  hello('2',99);const count=window.sent.length;const incompatible=await bridge.call('root.get').catch(e=>e.name);const silent=window.sent.length===count;
  sub.close();att.close();bridge.close();return {events,states,timed,independent,unknown,disconnected,kept,ids:[first,second,third,fourth,fifth],blockedReload,after,reloads,incompatible,silent,deadlines:[deadline('root.get'),deadline('chat.send'),deadline('exchange.stop'),deadline('chat.reimport')]};
 });
 assert.deepEqual(result.events.map(x=>x.value),[1,2,3]);assert.equal(new Set(result.ids).size,5);assert.equal(result.timed,'no_answer');assert.equal(result.disconnected,'disconnected');assert.equal(result.kept,2);assert.deepEqual(result.independent,{name:'Root'});assert.equal(result.unknown.code,'future_code');assert.equal(result.unknown.message,'Future message');assert.equal(result.blockedReload,0);assert.equal(result.after,1);assert.match(result.reloads[0],/reloadedFor=2/);assert.equal(result.incompatible,'disconnected');assert.equal(result.silent,true);assert.deepEqual(result.deadlines,[30000,150000,120000,120000]);assert.deepEqual(failures,[]);
 const appResult=await page.evaluate(async()=>{
  const {AppChannel}=window.fixture;const sent=[],opened=[];window.webkit.messageHandlers.arbolApp={postMessage:text=>sent.push(JSON.parse(text))};
  const channel=new AppChannel();let notices=0;channel.onopen(()=>notices++);window.arbolApp.receive(JSON.stringify({type:'open'}));
  const taking=channel.call('app.takeOpen');const request=sent.at(-1);window.arbolApp.receive(JSON.stringify({type:'reply',id:request.id,result:{chat:'test'}}));const taken=await taking;
  const unsafe=await channel.call('app.openLink',{url:'javascript:alert(1)'}).catch(e=>e.name);channel.close();delete window.webkit.messageHandlers.arbolApp;
  const adapter=new AppChannel();const prior=window.open;window.open=(url)=>{opened.push(url);return null;};await adapter.call('app.openLink',{url:'https://example.com/fictional'});window.open=prior;
  const empty=await adapter.call('app.takeOpen');adapter.close();return {request,taken,unsafe,notices,opened,empty,backendApp:window.sent.some(m=>m.method?.startsWith('app.'))};
 });
 assert.equal(appResult.request.type,'call');assert.equal(appResult.request.method,'app.takeOpen');assert.deepEqual(appResult.taken,{chat:'test'});assert.equal(appResult.notices,1);assert.equal(appResult.unsafe,'invalid_input');assert.deepEqual(appResult.opened,['https://example.com/fictional']);assert.deepEqual(appResult.empty,{});assert.equal(appResult.backendApp,false);
 await page.goto(server.resolvedUrls.local[0]+'tests/bridge.html?open=11111111-1111-4111-8111-111111111111');await page.waitForFunction(()=>window.fixture);
 const opening=await page.evaluate(async()=>{const app=new window.fixture.AppChannel();const a=await app.call('app.takeOpen');const b=await app.call('app.takeOpen');app.close();return[a,b];});assert.deepEqual(opening,[{chat:'11111111-1111-4111-8111-111111111111'},{}]);
 const precision=await page.evaluate(async()=>{
  const {Bridge,parseWire,stringifyWire,validRevision,sameRevision}=window.fixture,posts=[];window.webkit.messageHandlers.arbol.postMessage=raw=>posts.push(raw);const bridge=new Bridge({build:'1'});window.arbolBridge.receive('{"type":"hello","bridge":1,"root":{"root":"test","name":"Test","status":"working","current":true},"build":"1"}');
  const read=bridge.call('draft.get',{folder:'/fictional/readonly'}),id=JSON.parse(posts.at(-1)).id;window.arbolBridge.receive('{"type":"reply","id":'+JSON.stringify(id)+',"result":{"text":"fictional","revision":9223372036854775806}}');const draft=await read;
  const save=bridge.call('draft.save',{folder:'/fictional/readonly',text:'fictional changed',baseRevision:draft.revision}),encoded=posts.at(-1),saving=JSON.parse(encoded).id;window.arbolBridge.receive('{"type":"reply","id":'+JSON.stringify(saving)+',"result":{"revision":9223372036854775807}}');const result=await save;
  const ordinary=parseWire('{"revision":7,"count":1.5,"text":"9223372036854775807"}'),quoted=parseWire('{"revision":"9223372036854775807"}'),marker=parseWire('{"revision":{"isLosslessNumber":true,"value":"9223372036854775807"}}');const prototype=parseWire('{"__proto__":{"polluted":true}}'),safePrototype=Object.hasOwn(prototype,'__proto__')&&({}).polluted===undefined;let duplicate=false;try{parseWire('{"revision":1,"revision":2}');}catch{duplicate=true;}bridge.close();return{received:String(draft.revision),receivedType:typeof draft.revision,encoded,result:String(result.revision),ordinary,quotedValid:validRevision(quoted.revision),marker:typeof marker.revision,same:sameRevision(7,7n),bad:validRevision(9223372036854775808n),pretty:stringifyWire({revision:result.revision},2),duplicate,safePrototype};
 });assert.equal(precision.received,'9223372036854775806');assert.equal(precision.receivedType,'bigint');assert(precision.encoded.includes('"baseRevision":9223372036854775806'));assert(!precision.encoded.includes('"baseRevision":"'));assert.equal(precision.result,'9223372036854775807');assert.deepEqual(precision.ordinary,{revision:7,count:1.5,text:'9223372036854775807'});assert.equal(precision.quotedValid,false);assert.equal(precision.marker,'object');assert.equal(precision.same,true);assert.equal(precision.bad,false);assert(precision.pretty.includes('9223372036854775807'));assert.equal(precision.duplicate,true);assert.equal(precision.safePrototype,true);
 console.log('bridge.frames/calls/deadlines/errors/gap/generation/check/lost/recovery/reload/version/exact-revision: passed in Chromium');
} finally {await browser.close();await server.close();}
