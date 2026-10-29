// Mid-tier source from tests/ui/mutations.mjs; see MID_TIER.md.
// Shared helpers and refusal entry points remain at the original path.

// TEST-TIER-DISABLED-BEGIN tests/ui/mutations.mjs
// import assert from 'node:assert/strict';
// import {createServer} from '../../ui/elma/node_modules/vite/dist/node/index.js';
// import {chromium} from '../../ui/elma/node_modules/playwright/index.mjs';
// const server=await createServer({root:new URL('../../ui/elma',import.meta.url).pathname,configFile:new URL('../../ui/elma/vite.config.ts',import.meta.url).pathname,server:{host:'127.0.0.1',port:0}});await server.listen();
// const browser=await chromium.launch({headless:true}),page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
// try{
//  await page.addInitScript(()=>{window.posts=[];window.webkit={messageHandlers:{arbol:{postMessage:raw=>window.posts.push(raw)}}};});await page.goto(server.resolvedUrls.local[0]+'tests/drafts.html');await page.waitForFunction(()=>window.fixture);
//  await page.evaluate(()=>{
//   const {Bridge,Drafts,Mutations,parseWire,stringifyWire}=window.fixture;window.receive=value=>window.arbolBridge.receive(stringifyWire(value));window.reloads=[];window.results=[];window.failures=[];
//   window.bridge=new Bridge({build:'1',onstate:s=>{if(s!=='Connected')window.mutations?.offline();},onhello:r=>{window.drafts.rootChanged(r.root);window.mutations.hello(r.root);},beforeReload:()=>window.drafts.beforeReload(),reload:url=>window.reloads.push(url)});
//   window.drafts=new Drafts(window.bridge);window.mutations=new Mutations(window.bridge,done=>window.drafts.holdSend(done));window.hello=(root='r1',build='1')=>window.receive({type:'hello',bridge:1,root:{root,name:root,status:'working',current:true},build});window.calls=()=>window.posts.map(parseWire).filter(v=>v.type==='call');window.hello();
//   const params={chat:'11111111-1111-4111-8111-111111111111',title:'Exact title'};window.operation=window.mutations.start('chat.rename',params);window.operation.result.then(v=>window.results.push(v),e=>window.failures.push(e.detail));window.duplicate=window.mutations.start('chat.rename',params)===window.operation;
//  });assert(await page.evaluate(()=>window.duplicate));assert.equal(await page.evaluate(()=>window.calls().length),1);
//  await page.evaluate(()=>window.receive({type:'lost'}));await page.waitForFunction(()=>!window.operation.running);await page.evaluate(()=>window.hello('r1','2'));await page.waitForFunction(()=>window.calls().length===2);assert.equal(await page.evaluate(()=>window.reloads.length),0);
//  await page.evaluate(()=>{const c=window.calls().at(-1);window.receive({type:'reply',id:c.id,error:{code:'no_answer',message:'Uncertain receipt'}});});await page.waitForFunction(()=>window.calls().length===3);assert.equal(await page.evaluate(()=>new Set(window.calls().map(c=>JSON.stringify(c.params))).size),1);
//  await page.evaluate(()=>{const c=window.calls().at(-1);window.receive({type:'reply',id:c.id,result:{title:'Exact title'}});});await page.waitForFunction(()=>window.reloads.length===1);assert.deepEqual(await page.evaluate(()=>window.results),[{title:'Exact title'}]);
//  await page.evaluate(()=>{window.operation=window.mutations.start('chat.mark',{chat:'11111111-1111-4111-8111-111111111111',ongoing:false});window.operation.result.then(v=>window.results.push(v),e=>window.failures.push(e.detail));const c=window.calls().at(-1);window.receive({type:'reply',id:c.id,error:{code:'database_unavailable',message:'Private database is away'}});});await page.waitForFunction(()=>!window.operation.pending);assert.equal(await page.evaluate(()=>window.failures.at(-1).code),'database_unavailable');
//  await page.evaluate(()=>{window.operation=window.mutations.start('chat.rename',{chat:'11111111-1111-4111-8111-111111111111',title:'Old Root name'});window.operation.result.then(v=>window.results.push(v),e=>window.failures.push(e.detail));window.hello('r2');});await page.waitForFunction(()=>!window.operation.pending);assert.equal(await page.evaluate(()=>window.failures.at(-1).code),'context_changed');assert.equal(await page.evaluate(()=>window.mutations.forChat('11111111-1111-4111-8111-111111111111').length),0);
//  await page.evaluate(()=>{window.mutations.close();window.drafts.close();window.bridge.close();});assert.deepEqual(errors,[]);console.log('Metadata protocol: duplicate coalescing, exact idempotent lost/no_answer replay, action receipt gates actual Build reload, definite refusal and Root-change isolation passed');
// }finally{await browser.close();await server.close();}
// TEST-TIER-DISABLED-END tests/ui/mutations.mjs


throw new Error("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.");
